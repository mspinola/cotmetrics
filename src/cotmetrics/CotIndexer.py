import copy
import json
import os
import threading
from functools import lru_cache

import pandas as pd
import yaml

import cotmetrics as metrics
import cotmetrics.categories as categories
import cotmetrics.constants as const
import cotmetrics.models as models
import cotmetrics.symbol_code_map as symbol_code_map
import cotmetrics.utils as utils
from cotmetrics.database import cotDatabase

# Instrument roles decouple data collection from what the dashboard plots.
#   deploy  — in the book, plotted (default)
#   watch   — plotted, not in the book
#   heldout — collected + indexed but NOT plotted or selected
VALID_ROLES = frozenset({"deploy", "watch", "heldout"})
PLOTTED_ROLES = frozenset({"deploy", "watch"})


def resolve_role(asset: dict, asset_class: str, role_config: dict) -> str:
    """A per-instrument ``Role`` wins, else the class-level default in ``role_config``,
    else ``role_config['default']`` (falling back to 'deploy'). Raises on an unknown
    role so a typo can't silently make a market plot-or-not."""
    role = (asset.get("Role") or role_config.get(asset_class)
            or role_config.get("default", "deploy"))
    if role not in VALID_ROLES:
        raise ValueError(
            f"invalid Role {role!r} for {asset.get('Symbol')} in '{asset_class}'; "
            f"expected one of {sorted(VALID_ROLES)}")
    return role


class Instrument:
    def __init__(self, asset_class_, name_, symbol_, code_, custom_lookback_,
                 role_="deploy"):
        self.asset_class = asset_class_
        self.name = name_
        self.symbol = symbol_
        self.code = code_
        self.custom_lookback = custom_lookback_
        self.role = role_
        self.df = pd.DataFrame()

    def append(self, df):
        if self.df.empty:
            self.df = df
        else:
            self.df = pd.concat([self.df, df])

    def sort_by_date(self, col, ascending=True):
        self.df = self.df.sort_values(by=col, ascending=ascending)

    def __str__(self):
        return f"{self.name} {self.symbol} {self.code} {self.custom_lookback}"


class _IndexState:
    """The three collections a rebuild replaces, grouped so they swap as one.

    They are load-bearing together: `supported_instruments` is iterated to index into
    `instruments`, and `asset_class_map` names the assets a page asks for. Rebinding
    them one at a time would let a reader pair a new asset_class_map with an old
    instruments dict. One reference, one rebind, no straddle.
    """

    __slots__ = ("instruments", "supported_instruments", "asset_class_map")

    def __init__(self):
        self.instruments = dict()
        self.supported_instruments = set()
        self.asset_class_map = dict()


class CotIndexer:
    def __init__(self, real_test_data_dir=None, params_dir=None):
        import cotmetrics.config as config
        self._config = config

        self.real_test_data_dir = real_test_data_dir if real_test_data_dir else os.path.join(config.data_dir(), 'real_test_data')
        self.params_dir = params_dir if params_dir else config.params_path()

        self.last_known_db_time = cotDatabase.latest_update_timestamp()
        # Serializes refresh_if_stale across Dash worker threads, so concurrent pollers
        # produce one rebuild rather than several. It does NOT guard readers: they never
        # take it, and never block, because a refresh publishes by rebinding _state.
        self._refresh_lock = threading.RLock()

        # Reached through the properties below rather than assigned directly, so a
        # refresh can build a replacement off to the side and publish it in one bind.
        self._state = _IndexState()
        self.role_config = {}
        self.lookbacks = []
        self.years = []

        self.load_years()
        self.load_roles()
        self.load_instruments()
        self.load_lookbacks()
        self.load_price_config()

        if self.try_load_from_cache():
            utils.cot_logger.info("CotIndexer: Loaded instruments from Parquet cache!")
        else:
            utils.cot_logger.warning("CotIndexer: Cache missing or stale. Running full indexing and calculation rebuild...")
            self.populate_instruments()
            self.calculate_weekly_data()
            self.export_cot_data_to_csv()
            self.export_weekly_summary_results_to_csv()
            self.export_real_test_data_to_csv()
        # The daily options fetch is NOT run here — constructing/importing the
        # indexer must not trigger live network I/O. The app calls
        # core.indexer.boot_options_update() explicitly at startup instead.

    # Read-only views onto the current state. Every existing `self.instruments[...]`
    # call site keeps working unchanged, including the ones that mutate the dict in
    # place during a build. What they can no longer do is rebind the collection out
    # from under a reader, which is the whole point.
    @property
    def instruments(self):
        return self._state.instruments

    @property
    def supported_instruments(self):
        return self._state.supported_instruments

    @property
    def asset_class_map(self):
        return self._state.asset_class_map

    def load_years(self):
        with open(self.params_dir, 'r') as yf:
            yaml_data = yaml.safe_load(yf)
            for year in yaml_data["years"]:
                self.years.append(year)

    def load_roles(self):
        """Load the optional `roles:` block (per-class defaults + global `default`)."""
        with open(self.params_dir, 'r') as yf:
            yaml_data = yaml.safe_load(yf)
            self.role_config = yaml_data.get("roles", {}) or {}

    def load_instruments(self):
        with open(self.params_dir, 'r') as yf:
            yaml_data = yaml.safe_load(yf)
            for asset_class_dict in yaml_data["AssetClasses"]:
                for asset_class, assets in asset_class_dict.items():
                    self.asset_class_map[asset_class] = set()
                    for asset in assets:
                        code = symbol_code_map.cot_root_code_map[asset["Symbol"]]
                        if not code == "":
                            self.instruments[code] = Instrument(
                                asset_class, asset["Name"], asset["Symbol"], code,
                                asset["CustomLookbackWeeks"],
                                resolve_role(asset, asset_class, self.role_config))
                            self.supported_instruments.add(code)
                            self.asset_class_map[asset_class].add(
                                asset["Name"])

    # ── role-filtered views (the dashboard renders only PLOTTED_ROLES; the full
    #    `instruments`/`asset_class_map` stay intact for data + strategy scoring) ──
    def plotted_instruments(self):
        """code -> Instrument for markets that should render (deploy/watch)."""
        return {c: i for c, i in self.instruments.items() if i.role in PLOTTED_ROLES}

    def plotted_asset_class_map(self):
        """asset_class -> {names}, restricted to plotted instruments; a class whose
        every member is heldout drops out entirely."""
        out = {}
        for i in self.instruments.values():
            if i.role in PLOTTED_ROLES:
                out.setdefault(i.asset_class, set()).add(i.name)
        return out

    def instruments_with_role(self, *roles):
        """code -> Instrument filtered to the given role(s)."""
        rs = set(roles)
        return {c: i for c, i in self.instruments.items() if i.role in rs}

    def load_lookbacks(self):
        with open(self.params_dir, 'r') as yf:
            yaml_data = yaml.safe_load(yf)
            for lb in yaml_data["lookbacks"]:
                self.lookbacks.append([lb[0], int(lb[1])])

    def load_price_config(self):
        """Loads price_type and flow_caps from params.yaml."""
        with open(self.params_dir, 'r') as yf:
            yaml_data = yaml.safe_load(yf)
            self.price_type = yaml_data.get("price_type", "close")
            self.flow_caps = yaml_data.get("flow_caps", {})

    def _load_raw_cot(self, columns=None) -> pd.DataFrame:
        """Raw weekly COT (Legacy schema, Report_Date as a column) from the cotdata
        store, one per-code table per supported instrument, concatenated."""
        import cotdata
        frames = []
        for code in self.supported_instruments:
            cdf = cotdata.get_cot(code)
            if cdf is not None and not cdf.empty:
                frames.append(cdf.reset_index())  # Report_Date index → column
        if frames:
            df = pd.concat(frames, ignore_index=True)
            return df[columns] if columns else df
        return pd.DataFrame()

    @staticmethod
    def _cache_schema_marker_path() -> str:
        """Sidecar recording the cotdata schema_version and the cotmetrics
        METRICS_CACHE_VERSION the caches were built under. A sidecar (not a df
        column) so it never leaks into metrics/ML features."""
        return os.path.join(const.CACHE_DIR, "_cotdata_schema.json")

    @classmethod
    def _read_cache_marker(cls) -> dict:
        try:
            with open(cls._cache_schema_marker_path()) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @classmethod
    def _read_cache_schema(cls) -> int:
        try:
            return int(cls._read_cache_marker().get("schema_version", 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _read_cache_metrics_version(cls) -> int:
        try:
            return int(cls._read_cache_marker().get("metrics_version", 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _stamp_cache_schema(cls) -> None:
        """Record the cotdata schema_version and our METRICS_CACHE_VERSION next to
        the parquet caches, so both an upstream store move and an internal
        metrics-logic change bust the caches."""
        marker = {"metrics_version": int(const.METRICS_CACHE_VERSION)}
        try:
            import cotdata
            marker["schema_version"] = int(cotdata.schema_version())
        except Exception as e:
            # Preserve any previously recorded store schema rather than zeroing it
            # (which would force a rebuild on every boot without cotdata).
            prev = cls._read_cache_schema()
            if prev:
                marker["schema_version"] = prev
            utils.cot_logger.warning(f"_stamp_cache_schema: cotdata schema unavailable: {e}")
        try:
            os.makedirs(const.CACHE_DIR, exist_ok=True)
            with open(cls._cache_schema_marker_path(), "w") as f:
                json.dump(marker, f)
        except Exception as e:  # never let cache bookkeeping break a build
            utils.cot_logger.warning(f"_stamp_cache_schema: could not write marker: {e}")

    def try_load_from_cache(self) -> bool:
        """
        Attempts to load instruments from the local Parquet cache files.
        """
        if not self.years:
            utils.cot_logger.warning("try_load_from_cache: self.years is empty")
            return False

        # Bust all caches when our own derived-metrics logic changed (e.g. the
        # Spearman fallback going 0.0 -> NaN). Like the store-schema case below
        # this is a value-only change the per-symbol column-presence guards can't
        # see, but it originates here rather than upstream — so it gets its own
        # counter that is checked even when cotdata is unavailable.
        cached_metrics_version = self._read_cache_metrics_version()
        if cached_metrics_version < int(const.METRICS_CACHE_VERSION):
            utils.cot_logger.info(
                f"try_load_from_cache: cache metrics version {cached_metrics_version} "
                f"< cotmetrics METRICS_CACHE_VERSION {const.METRICS_CACHE_VERSION} "
                f"— rebuilding all caches.")
            return False

        # Bust all caches when the cotdata store schema moved (e.g. reconstructed
        # volume promoted). The per-symbol guards below key on column *presence*,
        # so they can't see a value-only change like front→reconstructed volume;
        # the schema marker can.
        try:
            import cotdata
            store_schema = int(cotdata.schema_version())
            if self._read_cache_schema() < store_schema:
                utils.cot_logger.info(
                    f"try_load_from_cache: cache schema {self._read_cache_schema()} "
                    f"< cotdata schema {store_schema} — rebuilding all caches.")
                return False
        except Exception as e:
            utils.cot_logger.warning(f"try_load_from_cache: schema check skipped: {e}")

        self.years[-1]

        try:
            df_latest = self._load_raw_cot(columns=[const.REPORT_DATE_XLS, const.CONTRACT_CODE_XLS])

            if df_latest.empty:
                utils.cot_logger.warning("try_load_from_cache: df_latest is empty")
                return False

            df_latest['std_code'] = df_latest[const.CONTRACT_CODE_XLS].apply(utils.standardize_contract_code)
            df_latest['parsed_date'] = pd.to_datetime(df_latest[const.REPORT_DATE_XLS]).dt.tz_localize(None)

            # Map standardized code to its max report date in latest data
            raw_dates_by_code = df_latest.groupby('std_code')['parsed_date'].max().to_dict()
            # Also get the overall max report date
            fallback_max_date = df_latest['parsed_date'].max()
        except Exception as e:
            print(f"\n\nError reading latest raw date: {e}\n\n")
            utils.cot_logger.error(f"Error reading latest raw date: {e}")
            return False

        temp_instruments = {}
        for instrument_code in self.supported_instruments:
            instrument = self.instruments[instrument_code]
            cache_path = os.path.join(const.CACHE_DIR, f"{instrument.symbol}.parquet")
            if not os.path.exists(cache_path):
                utils.cot_logger.warning(f"try_load_from_cache: cache file missing -> {cache_path}")
                return False
            try:
                cached_df = pd.read_parquet(cache_path)
                if cached_df.empty or const.REPORT_DATE_XLS not in cached_df.columns:
                    utils.cot_logger.warning(f"try_load_from_cache: cache invalid or empty -> {cache_path}")
                    return False

                # Ensure it has calculated metrics in it (e.g. COMM_CUSTOM_IDX)
                # If it doesn't, it is a partial/price-only cache and needs recalculation
                if const.COMM_CUSTOM_IDX not in cached_df.columns:
                    utils.cot_logger.warning(f"try_load_from_cache: missing metrics in -> {cache_path}")
                    return False

                # Force a rebuild of caches predating the week-over-week index deltas.
                # get_symbols_data reads them unconditionally, so a stale cache would
                # KeyError at load rather than degrade.
                # Both bases: the normalized twin landed later, so a cache built in
                # between carries the raw family and not the normalized one.
                if (const.COMM_CUSTOM_WOW not in cached_df.columns
                        or const.COMM_CUSTOM_WOW_NORM not in cached_df.columns):
                    utils.cot_logger.warning(f"try_load_from_cache: missing WoW metrics in -> {cache_path}")
                    return False

                # Force a rebuild of caches predating the true-MM (disaggregated) and
                # TFF-LEV merges. Only commodities carry MM data and only financials
                # carry LEV, so a column's absence on the other kind of market is fine.
                #
                # Test the RAW merged positions, not the derived concentration columns.
                # The derived MM_*/LEV_* columns are produced by append_trading_signals
                # at read time and never written to this parquet, so a guard keyed on
                # MM_LONG_PSIZE_IDX can never be satisfied: it fails, triggers a full
                # rebuild, and the rebuilt cache still lacks the column, so the next
                # request rebuilds again. What _attach_disagg_mm actually persists is
                # MM_LONG_POS_XLS, and its absence is what "predates the merge" looks
                # like on disk.
                if (self.is_commodity_code(instrument_code)
                        and const.MM_LONG_POS_XLS not in cached_df.columns):
                    utils.cot_logger.warning(f"try_load_from_cache: missing true-MM positions in -> {cache_path}")
                    return False
                if (self.has_tff_code(instrument_code)
                        and const.LEV_LONG_POS_XLS not in cached_df.columns):
                    utils.cot_logger.warning(f"try_load_from_cache: missing TFF-LEV positions in -> {cache_path}")
                    return False

                # Get the latest date in the excel file for this specific instrument, falling back to overall max date
                std_inst_code = utils.standardize_contract_code(instrument_code)
                latest_raw_date = raw_dates_by_code.get(std_inst_code, fallback_max_date)

                latest_cached_date = pd.to_datetime(cached_df[const.REPORT_DATE_XLS]).max().tz_localize(None)
                if latest_raw_date > latest_cached_date:
                    print(f"Cache stale for {instrument.symbol}: raw date {latest_raw_date.date()} > cached date {latest_cached_date.date()}")
                    utils.cot_logger.info(f"Cache stale for {instrument.symbol}: raw date {latest_raw_date.date()} > cached date {latest_cached_date.date()}")
                    return False

                temp_instruments[instrument_code] = cached_df
            except Exception as e:
                print(f"\n\nError reading cache for {instrument.symbol}: {e}")
                utils.cot_logger.error(f"Error reading cache for {instrument.symbol}: {e}")
                return False

        # If all cache files are valid and up-to-date, populate instruments and skip full pipeline
        for instrument_code, cached_df in temp_instruments.items():
            self.instruments[instrument_code].df = cached_df

        return True

    def populate_instruments(self):
        df = self._load_raw_cot()
        if df.empty:
            msg = "No COT data in the cotdata store. Run `cotdata-update --cot-all` to populate it."
            utils.cot_logger.error(msg)
            raise FileNotFoundError(msg)

        utils.cot_logger.info(f"Loaded {len(df)} raw COT rows for {len(self.supported_instruments)} instruments...")

        for instrument in self.supported_instruments:
            self.instruments[instrument].append(
                df.loc[df[const.CONTRACT_CODE_XLS] == instrument])

        for instrument in self.supported_instruments:
            # Sort by date and add a row count index
            self.instruments[instrument].sort_by_date(
                const.REPORT_DATE_XLS, ascending=True)
            self.instruments[instrument].df = self.instruments[instrument].df.drop_duplicates(subset=[const.REPORT_DATE_XLS], keep='last')
            self.instruments[instrument].df.index = range(
                0, len(self.instruments[instrument].df))
            self._attach_disagg_mm(instrument)
            self._attach_tff_lev(instrument)

    def _has_report_code(self, code, attr, dir_fn):
        """Cached membership test: does `code` have a per-code file in a store subdir?
        Zero network — one dir listing, cached under `attr`.

        Store filenames are `{SYMBOL}_{code}.parquet` ("GC_088691"), so a bare stem
        never equals a bare code. Until the code half was added to this set the test
        matched nothing, and since both callers are cache-staleness guards, neither
        guard could fire.
        """
        if getattr(self, attr, None) is None:
            try:
                codes = set()
                for p in dir_fn().glob("*.parquet"):
                    stem = p.stem
                    codes.add(stem)
                    if "_" in stem:
                        codes.add(stem.rsplit("_", 1)[1])
                setattr(self, attr, codes)
            except Exception:
                setattr(self, attr, set())
        s = str(code).strip()
        st = getattr(self, attr)
        return s in st or s.zfill(6) in st

    def is_commodity_code(self, code):
        """True if the code has a disaggregated report (physical commodity; financials
        are covered by the separate TFF report and have none)."""
        import cotdata.config as _cfg
        return self._has_report_code(code, "_disagg_code_set", _cfg.cot_disagg_dir)

    def has_tff_code(self, code):
        """True if the code has a TFF (Traders in Financial Futures) report — i.e. a
        financial future carrying the Leveraged-Funds (LEV) speculative group."""
        import cotdata.config as _cfg
        return self._has_report_code(code, "_tff_code_set", _cfg.cot_tff_dir)

    def _attach_disagg_mm(self, instrument_code):
        """Left-join TRUE Money-Manager positions from the disaggregated store onto an
        instrument's legacy frame, keyed on report date. Commodities gain MM_*_POS_XLS;
        financials (no disaggregated report) are left untouched — the concentration code
        downstream guards on column presence, so those simply get no MM signal."""
        import cotdata
        inst = self.instruments[instrument_code]
        try:
            dg = cotdata.get_cot(instrument_code, report="disagg")
        except Exception as e:
            utils.cot_logger.warning(f"_attach_disagg_mm: disagg load failed for {instrument_code}: {e}")
            return
        if dg is None or dg.empty or const.MM_LONG_POS_XLS not in dg.columns:
            return
        # Attach only the MM-specific columns. Traders_Tot_All is NOT re-merged —
        # base already carries the legacy total (what signals.py reads), and
        # re-merging it caused duplicate-column collisions.
        cols = [const.MM_LONG_POS_XLS, const.MM_SHORT_POS_XLS,
                const.MM_LONG_TRADERS_XLS, const.MM_SHORT_TRADERS_XLS]
        cols = [c for c in cols if c in dg.columns]
        mm = dg.reset_index()[[const.REPORT_DATE_XLS] + cols].copy()
        mm[const.REPORT_DATE_XLS] = pd.to_datetime(mm[const.REPORT_DATE_XLS]).dt.tz_localize(None)
        # Trader counts arrive as whitespace-padded strings ("     48") — coerce to numeric.
        for tc in (const.MM_LONG_TRADERS_XLS, const.MM_SHORT_TRADERS_XLS):
            if tc in mm.columns:
                mm[tc] = pd.to_numeric(mm[tc].astype(str).str.strip(), errors="coerce")
        base = inst.df.copy()
        base[const.REPORT_DATE_XLS] = pd.to_datetime(base[const.REPORT_DATE_XLS]).dt.tz_localize(None)
        # Idempotent: drop any prior attach of these columns so a repeat
        # populate_instruments() can't duplicate them (no suffix collisions).
        base = base.drop(columns=[c for c in cols if c in base.columns], errors="ignore")
        merged = base.merge(mm, on=const.REPORT_DATE_XLS, how="left")
        merged.index = range(len(merged))
        inst.df = merged

    def _attach_tff_lev(self, instrument_code):
        """Left-join TFF Leveraged-Funds positions + trader counts onto a financial
        instrument's frame, keyed on report date. Mirror of _attach_disagg_mm for the
        disjoint financial universe; commodities have no TFF report and are untouched."""
        import cotdata
        inst = self.instruments[instrument_code]
        try:
            tf = cotdata.get_cot(instrument_code, report="tff")
        except Exception as e:
            utils.cot_logger.warning(f"_attach_tff_lev: tff load failed for {instrument_code}: {e}")
            return
        if tf is None or tf.empty or const.LEV_LONG_POS_XLS not in tf.columns:
            return
        # Attach only the Lev-specific columns; Traders_Tot_All stays base's legacy
        # value (not re-merged) to avoid duplicate-column collisions.
        cols = [const.LEV_LONG_POS_XLS, const.LEV_SHORT_POS_XLS,
                const.LEV_LONG_TRADERS_XLS, const.LEV_SHORT_TRADERS_XLS]
        cols = [c for c in cols if c in tf.columns]
        lev = tf.reset_index()[[const.REPORT_DATE_XLS] + cols].copy()
        lev[const.REPORT_DATE_XLS] = pd.to_datetime(lev[const.REPORT_DATE_XLS]).dt.tz_localize(None)
        for tc in (const.LEV_LONG_TRADERS_XLS, const.LEV_SHORT_TRADERS_XLS):
            if tc in lev.columns:
                lev[tc] = pd.to_numeric(lev[tc].astype(str).str.strip(), errors="coerce")
        base = inst.df.copy()
        base[const.REPORT_DATE_XLS] = pd.to_datetime(base[const.REPORT_DATE_XLS]).dt.tz_localize(None)
        # Idempotent: drop any prior tff attach so a repeat populate can't duplicate.
        base = base.drop(columns=[c for c in cols if c in base.columns], errors="ignore")
        merged = base.merge(lev, on=const.REPORT_DATE_XLS, how="left")
        merged.index = range(len(merged))
        inst.df = merged

    @staticmethod
    def process_lookback(lookback, symbol, df):
        idx_col_header_name = const.get_lookback_header_str(lookback) + const.IDX
        COMM_IDX = const.COMM + idx_col_header_name
        LRG_IDX = const.LARGE + idx_col_header_name
        SML_IDX = const.SMALL + idx_col_header_name

        idx_norm_col_header_name = const.get_lookback_header_str(lookback) + const.IDX + const.NORMALIZED
        COMM_NORM_IDX = const.COMM + idx_norm_col_header_name
        LRG_NORM_IDX = const.LARGE + idx_norm_col_header_name
        SML_NORM_IDX = const.SMALL + idx_norm_col_header_name

        WILLCO = const.WILLCO + const.get_lookback_header_str(lookback)

        LIQUIDITY_STRAIN = const.LIQUIDITY_STRAIN + const.ZSCORE + const.get_lookback_header_str(lookback)
        PRICE_HEDGING_DIV = const.PRICE_HEDGING_DIV + const.ZSCORE + const.get_lookback_header_str(lookback)

        lb_weeks = lookback[1]
        for idx in range(len(df)):
            if lb_weeks < 0 or idx < lb_weeks:
                df.at[idx, COMM_IDX] = None
                df.at[idx, LRG_IDX] = None
                df.at[idx, SML_IDX] = None
                df.at[idx, COMM_NORM_IDX] = None
                df.at[idx, LRG_NORM_IDX] = None
                df.at[idx, SML_NORM_IDX] = None
                df.at[idx, WILLCO] = None
            else:
                lb_idx = idx - lb_weeks
                df.at[idx, COMM_IDX] = metrics.calculate_cot_index(df[const.COMM_NET], lb_idx, idx)
                df.at[idx, LRG_IDX] = metrics.calculate_cot_index(df[const.LARGE_NET], lb_idx, idx)
                df.at[idx, SML_IDX] = metrics.calculate_cot_index(df[const.SMALL_NET], lb_idx, idx)
                df.at[idx, COMM_NORM_IDX] = metrics.calculate_cot_index(df[const.COMM_NET_NORM], lb_idx, idx)
                df.at[idx, LRG_NORM_IDX] = metrics.calculate_cot_index(df[const.LARGE_NET_NORM], lb_idx, idx)
                df.at[idx, SML_NORM_IDX] = metrics.calculate_cot_index(df[const.SMALL_NET_NORM], lb_idx, idx)
                df.at[idx, WILLCO] = metrics.calculate_willco(df[const.COMM_PCT_OI], lb_idx, idx)

        # Calculate Liquidity Strain Ratio and the Price Hedging Divergence over the entire series directly
        df[LIQUIDITY_STRAIN] = metrics.calculate_liquidity_strain_ratio_index(df[const.COMM_NET], df[const.LARGE_NET], lb_weeks)
        if const.CLOSING_PRICE in df.columns:
            df[PRICE_HEDGING_DIV] = metrics.calculate_price_hedging_divergence(df, const.CLOSING_PRICE, const.COMM_NET, velocity_window=3, macro_window=lb_weeks)
        else:
            df[PRICE_HEDGING_DIV] = 0.0

        three_year_lb_weeks = 52 * 3
        for idx in range(len(df)):
            if three_year_lb_weeks < 0 or idx < three_year_lb_weeks:
                df.at[idx, const.COMM_3Y_IDX] = None
                df.at[idx, const.COMM_3Y_IDX_NORM] = None
            else:
                lb_idx = idx - three_year_lb_weeks
                df.at[idx, const.COMM_3Y_IDX] = metrics.calculate_cot_index(df[const.COMM_NET], lb_idx, idx)
                df.at[idx, const.COMM_3Y_IDX_NORM] = metrics.calculate_cot_index(df[const.COMM_NET_NORM], lb_idx, idx)

        lrg_sentiment_lb_weeks = 15
        for idx in range(len(df)):
            if lrg_sentiment_lb_weeks < 0 or idx < lrg_sentiment_lb_weeks:
                df.at[idx, const.LW_LRG_SENTIMENT] = None
            else:
                lb_idx = idx - lrg_sentiment_lb_weeks
                df.at[idx, const.LW_LRG_SENTIMENT] = metrics.calculate_cot_index(df[const.LARGE_NET], lb_idx, idx)

        OI_ZSCORE = const.OPEN_INTEREST + const.get_lookback_header_str(lookback) + const.ZSCORE
        if const.OPEN_INTEREST_XLS in df.columns:
            oi_series = df[const.OPEN_INTEREST_XLS]
        elif const.OPEN_INTEREST in df.columns:
            oi_series = df[const.OPEN_INTEREST]
        else:
            oi_series = pd.Series(1e-9, index=df.index)
        df[OI_ZSCORE] = metrics.calculate_z_score(oi_series, lb_weeks)

        # Z-Score
        zscore_col_header_name = const.get_lookback_header_str(lookback) + const.ZSCORE
        COMM_ZS = const.COMM + zscore_col_header_name
        LRG_ZS = const.LARGE + zscore_col_header_name
        SML_ZS = const.SMALL + zscore_col_header_name
        df[COMM_ZS] = metrics.calculate_z_score(df[const.COMM_NET], lb_weeks)
        df[LRG_ZS] = metrics.calculate_z_score(df[const.LARGE_NET], lb_weeks)
        df[SML_ZS] = metrics.calculate_z_score(df[const.SMALL_NET], lb_weeks)

        zscore_norm_col_header_name = zscore_col_header_name + const.NORMALIZED
        COMM_ZS_NORM = const.COMM + zscore_norm_col_header_name
        LRG_ZS_NORM = const.LARGE + zscore_norm_col_header_name
        SML_ZS_NORM = const.SMALL + zscore_norm_col_header_name
        df[COMM_ZS_NORM] = metrics.calculate_z_score(df[const.COMM_NET_NORM], lb_weeks)
        df[LRG_ZS_NORM] = metrics.calculate_z_score(df[const.LARGE_NET_NORM], lb_weeks)
        df[SML_ZS_NORM] = metrics.calculate_z_score(df[const.SMALL_NET_NORM], lb_weeks)

        # Spearman Correlation
        spearman_header_name = const.get_lookback_header_str(lookback) + const.SPEARMAN
        COMM_SPR = const.COMM + spearman_header_name
        LRG_SPR = const.LARGE + spearman_header_name
        SML_SPR = const.SMALL + spearman_header_name
        spearman_norm_header_name = spearman_header_name + const.NORMALIZED
        COMM_NORM_SPR = const.COMM + spearman_norm_header_name
        LRG_NORM_SPR = const.LARGE + spearman_norm_header_name
        SML_NORM_SPR = const.SMALL + spearman_norm_header_name
        if const.CLOSING_PRICE in df.columns:
            df[COMM_SPR] = metrics.calculate_spearman_correlation_vectorized(df, const.CLOSING_PRICE, const.COMM_NET, lb_weeks)
            df[LRG_SPR] = metrics.calculate_spearman_correlation_vectorized(df, const.CLOSING_PRICE, const.LARGE_NET, lb_weeks)
            df[SML_SPR] = metrics.calculate_spearman_correlation_vectorized(df, const.CLOSING_PRICE, const.SMALL_NET, lb_weeks)
            df[COMM_NORM_SPR] = metrics.calculate_spearman_correlation_vectorized(df, const.CLOSING_PRICE, const.COMM_NET_NORM, lb_weeks)
            df[LRG_NORM_SPR] = metrics.calculate_spearman_correlation_vectorized(df, const.CLOSING_PRICE, const.LARGE_NET_NORM, lb_weeks)
            df[SML_NORM_SPR] = metrics.calculate_spearman_correlation_vectorized(df, const.CLOSING_PRICE, const.SMALL_NET_NORM, lb_weeks)
        else:
            df[COMM_SPR] = 0
            df[LRG_SPR] = 0
            df[SML_SPR] = 0

        # Momentum Index
        momentum_idx_header_name = const.get_lookback_header_str(lookback) + const.MOMENTUM
        idx_col_name = const.get_lookback_header_str(lookback) + const.IDX
        idx_norm_col_name = idx_col_name + const.NORMALIZED
        COMM_MOVE = const.COMM + momentum_idx_header_name
        LRG_MOVE = const.LARGE + momentum_idx_header_name
        SML_MOVE = const.SMALL + momentum_idx_header_name
        df[COMM_MOVE] = metrics.calculate_momentum_index(df[const.COMM + idx_col_name])
        df[LRG_MOVE] = metrics.calculate_momentum_index(df[const.LARGE + idx_col_name])
        df[SML_MOVE] = metrics.calculate_momentum_index(df[const.SMALL + idx_col_name])

        # Week-over-week twins of the same three. Separate from the MOMENTUM_PERIOD
        # family rather than replacing it: the 6-week change reads as a trend, this
        # reads as "what moved at this release".
        #
        # Both bases, built in one loop so they cannot drift apart. The normalized twin
        # is what lets a movers list follow the app's positioning model: without it,
        # ranking would have to stay on raw contracts while the setup badges came from
        # the normalized basis, which is the mixed rule models.py exists to prevent.
        wow_header = const.get_lookback_header_str(lookback) + const.WOW_MOVE
        wow_norm_header = wow_header + const.NORMALIZED
        for group in (const.COMM, const.LARGE, const.SMALL):
            df[group + wow_header] = metrics.calculate_momentum_index(
                df[group + idx_col_name], periods=const.WOW_PERIOD
            )
            df[group + wow_norm_header] = metrics.calculate_momentum_index(
                df[group + idx_norm_col_name], periods=const.WOW_PERIOD
            )

        momentum_norm_idx_header_name = momentum_idx_header_name + const.NORMALIZED
        COMM_MOVE_NORM = const.COMM + momentum_norm_idx_header_name
        LRG_MOVE_NORM = const.LARGE + momentum_norm_idx_header_name
        SML_MOVE_NORM = const.SMALL + momentum_norm_idx_header_name
        df[COMM_MOVE_NORM] = metrics.calculate_momentum_index(df[const.COMM + idx_norm_col_name])
        df[LRG_MOVE_NORM] = metrics.calculate_momentum_index(df[const.LARGE + idx_norm_col_name])
        df[SML_MOVE_NORM] = metrics.calculate_momentum_index(df[const.SMALL + idx_norm_col_name])

        # Return a defragmented dataframe
        return df.copy()

    def retrieve_report_date_closing_prices(self, instrument, years, force_refresh=False, price_data=None):
        os.makedirs(const.CACHE_DIR, exist_ok=True)

        df = instrument.df
        symbol = instrument.symbol
        # Yahoo Finance ticker format for futures contracts
        ticker = f"{symbol}=F"

        # Check if cache exists
        cache_path = os.path.join(const.CACHE_DIR, f"{symbol}.parquet")
        fallback_df = None
        if os.path.exists(cache_path):
            try:
                fallback_df = pd.read_parquet(cache_path)
            except Exception as e:
                print(f"\n\nError reading cache fallback for {symbol}: {e}\n\n")

        # Check if cache is fresh and up-to-date
        if fallback_df is not None and not force_refresh:
            # Schema guard: if this instrument now carries disaggregated MM positions
            # (merged in populate_instruments) but the cache predates the true-MM
            # concentration columns, the cache is stale regardless of its date.
            # Same correction as the guard in try_load_from_cache: compare like with
            # like. MM_LONG_PSIZE_IDX is derived at read time and never written here,
            # so testing for it marked every commodity cache stale on every boot and
            # re-read the bars from the store each time.
            mm_merged = const.MM_LONG_POS_XLS in instrument.df.columns
            cache_has_mm = const.MM_LONG_POS_XLS in fallback_df.columns
            lev_merged = const.LEV_LONG_POS_XLS in instrument.df.columns
            cache_has_lev = const.LEV_LONG_POS_XLS in fallback_df.columns
            schema_stale = (mm_merged and not cache_has_mm) or (lev_merged and not cache_has_lev)
            if const.REPORT_DATE_XLS in fallback_df.columns and not df.empty and not schema_stale:
                latest_raw_date = pd.to_datetime(df[const.REPORT_DATE_XLS]).max().tz_localize(None)
                latest_cached_date = pd.to_datetime(fallback_df[const.REPORT_DATE_XLS]).max().tz_localize(None)
                if latest_raw_date <= latest_cached_date:
                    print(f"Using cache for {symbol} (up to date: {latest_cached_date.date()})")
                    # Make sure instrument.df also gets the cached price columns
                    for col in [const.OPEN_PRICE, const.HIGH_PRICE, const.LOW_PRICE, const.CLOSING_PRICE]:
                        if col in fallback_df.columns:
                            instrument.df[col] = fallback_df[col]
                    return fallback_df

        # The per-instrument cache above missed, so read the bars from the cotdata store.
        # This is a local parquet read, not a fetch: cotdata.get_prices never goes to the
        # network. Say so, because a message about downloading sends anyone debugging a
        # slow or failing boot looking for a network problem that cannot exist.
        if price_data is None:
            print(f"Reading {symbol} prices from the cotdata store...")
            try:
                import cotdata
                start_date = f"{years[0]}-01-01"
                price_data = cotdata.get_prices(symbol, adjustment='backadj', start=start_date)
            except Exception as e:
                print(f"Error reading prices for {symbol} from the store: {e}")
                utils.cot_logger.error(f"Error reading prices for {symbol} from the store: {e}")
                price_data = pd.DataFrame()

        try:
            if price_data is not None and not price_data.empty:
                # Clean the price data (safely handle multi-index if multiple tokens are returned)
                if isinstance(price_data.columns, pd.MultiIndex):
                    price_df = price_data.loc[:, ([
                                                   'Open', 'High', 'Low', 'Close'], ticker)].copy()
                    price_df.columns = price_df.columns.droplevel(1)
                else:
                    price_df = price_data[[
                        'Open', 'High', 'Low', 'Close']].copy()

                # Convert price index to datetime and force nanosecond resolution
                price_df.index = pd.to_datetime(price_df.index).tz_localize(
                    None).astype('datetime64[ns]')

                # Aggregate daily data into true weekly bars ending on Tuesdays (COT Report Day)
                weekly_price_df = price_df.resample('W-TUE').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last'
                })

                # OHLC Repair
                weekly_price_df['Open'] = weekly_price_df['Open'].fillna(weekly_price_df['Close'])
                weekly_price_df['High'] = weekly_price_df['High'].fillna(weekly_price_df['Close'])
                weekly_price_df['Low'] = weekly_price_df['Low'].fillna(weekly_price_df['Close'])
                weekly_price_df = weekly_price_df.dropna(subset=['Close'])

                # Ensure COT dates match resolution
                df[const.REPORT_DATE_XLS] = pd.to_datetime(
                    df[const.REPORT_DATE_XLS]).dt.tz_localize(None).astype('datetime64[ns]')

                weekly_price_df = weekly_price_df.rename(columns={
                    'Open': const.OPEN_PRICE,
                    'High': const.HIGH_PRICE,
                    'Low': const.LOW_PRICE,
                    'Close': const.CLOSING_PRICE
                })

                # Clamp live candle
                actual_latest_date = price_df.index.max()
                if not weekly_price_df.empty and weekly_price_df.index[-1] > actual_latest_date:
                    idx = weekly_price_df.index.tolist()
                    idx[-1] = actual_latest_date
                    weekly_price_df.index = pd.DatetimeIndex(idx, name=weekly_price_df.index.name)

                # Merge weekly prices into COT data
                df_sorted = df.sort_values(const.REPORT_DATE_XLS)

                # Drop price columns if they already exist to prevent _x/_y suffix collisions
                price_cols = [const.OPEN_PRICE, const.HIGH_PRICE, const.LOW_PRICE, const.CLOSING_PRICE]
                df_sorted = df_sorted.drop(columns=[c for c in price_cols if c in df_sorted.columns])

                merged = pd.merge_asof(
                    df_sorted,
                    weekly_price_df.sort_index(),
                    left_on=const.REPORT_DATE_XLS,
                    right_index=True,
                    direction='backward'
                )
                merged = merged.sort_index()

                # Add the 4 new columns to the instrument's dataframe
                instrument.df[const.OPEN_PRICE] = merged[const.OPEN_PRICE]
                instrument.df[const.HIGH_PRICE] = merged[const.HIGH_PRICE]
                instrument.df[const.LOW_PRICE] = merged[const.LOW_PRICE]
                instrument.df[const.CLOSING_PRICE] = merged[const.CLOSING_PRICE]

                utils.cot_logger.info(f"Integrated Weekly OHLC prices for {symbol}")
                # Save to local cache
                instrument.df.to_parquet(cache_path)
                self._stamp_cache_schema()
                return instrument.df

            else:
                raise ValueError("Empty price data")

        except Exception as e:
            print(f"Error processing price for {symbol}: {e}")
            utils.cot_logger.error(f"Error processing price for {symbol}: {e}")

            if fallback_df is not None and const.CLOSING_PRICE in fallback_df.columns:
                print(f"Falling back to existing cached prices for {symbol}.")
                # Merge new COT data with existing cached prices
                for col in [const.OPEN_PRICE, const.HIGH_PRICE, const.LOW_PRICE, const.CLOSING_PRICE]:
                    if col in instrument.df.columns:
                        instrument.df = instrument.df.drop(columns=[col])

                prices_only = fallback_df[[const.REPORT_DATE_XLS, const.OPEN_PRICE, const.HIGH_PRICE, const.LOW_PRICE, const.CLOSING_PRICE]].drop_duplicates(subset=[const.REPORT_DATE_XLS])
                merged = pd.merge(instrument.df, prices_only, on=const.REPORT_DATE_XLS, how='left')

                for col in [const.OPEN_PRICE, const.HIGH_PRICE, const.LOW_PRICE, const.CLOSING_PRICE]:
                    merged[col] = merged[col].fillna(0)

                instrument.df = merged
                return instrument.df
            else:
                df[const.OPEN_PRICE] = 0
                df[const.HIGH_PRICE] = 0
                df[const.LOW_PRICE] = 0
                df[const.CLOSING_PRICE] = 0
                # Save to local cache if no fallback exists
                instrument.df.to_parquet(cache_path)
                self._stamp_cache_schema()
                return instrument.df

    def calculate_weekly_data(self, force_refresh=False):
        # Prices come from the cotdata store, one instrument at a time. There used to be
        # a batch backfill here (Databento), which needed a pre-pass to decide which
        # instruments to fetch and a map to hand the results back. Both outlived it: the
        # pre-pass read every cached parquet to build a list nothing consumed, and the
        # map was always empty, so price_data was always None. Removed -- the per-symbol
        # freshness check in retrieve_report_date_closing_prices is the real one.
        for instrument in self.supported_instruments:
            inst_obj = self.instruments[instrument]

            # Retrieve report date closing prices first (from cache or the store).
            # This avoids discarding calculated columns if the cache is older than the code changes
            df = self.retrieve_report_date_closing_prices(
                inst_obj,
                self.years,
                force_refresh=force_refresh,
            )
            df[const.PRICE_CHANGE] = (df[const.CLOSING_PRICE].pct_change() * 100).fillna(0).round(1)

            # 2. Add/calculate all weekly data on the retrieved DataFrame
            # Add new columns for net positions
            df[const.COMM_NET] = df[const.COMM_LONG_POS_XLS] - df[const.COMM_SHORT_POS_XLS]
            df[const.LARGE_NET] = df[const.LARGE_LONG_POS_XLS] - df[const.LARGE_SHORT_POS_XLS]
            df[const.SMALL_NET] = df[const.SMALL_LONG_POS_XLS] - df[const.SMALL_SHORT_POS_XLS]
            df[const.COMM_NET_CHANGE_PCT] = (df[const.COMM_NET].pct_change() * 100).fillna(0).round(1)

            # Calculate the COT-MACD metrics
            macd_line, signal_line, macd_hist = metrics.calculate_cot_macd(df[const.COMM_NET])
            df[const.COMM_MACD_LINE] = macd_line
            df[const.COMM_MACD_SIGNAL] = signal_line
            df[const.COMM_MACD_HIST] = macd_hist

            # Generate Algorithmic Crossover Signals
            # A bullish cross happens when the histogram flips from negative to positive
            df[const.COMM_MACD_BULL_CROSS] = (df[const.COMM_MACD_HIST] > 0) & (df[const.COMM_MACD_HIST].shift(1) <= 0)
            df[const.COMM_MACD_BEAR_CROSS] = (df[const.COMM_MACD_HIST] < 0) & (df[const.COMM_MACD_HIST].shift(1) >= 0)

            # Check for sign change in Net Positions
            df[const.COMM_FLIP] = (df[const.COMM_NET] * df[const.COMM_NET].shift(1)) < 0
            df[const.LARGE_FLIP] = (df[const.LARGE_NET] * df[const.LARGE_NET].shift(1)) < 0
            df[const.SMALL_FLIP] = (df[const.SMALL_NET] * df[const.SMALL_NET].shift(1)) < 0

            # Add new columns for net positions normalized by open interest
            df[const.COMM_NET_NORM] = df[const.COMM_NET] / (df[const.OPEN_INTEREST_XLS] + 1e-9)
            df[const.LARGE_NET_NORM] = df[const.LARGE_NET] / (df[const.OPEN_INTEREST_XLS] + 1e-9)
            df[const.SMALL_NET_NORM] = df[const.SMALL_NET] / (df[const.OPEN_INTEREST_XLS] + 1e-9)
            df[const.COMM_NET_CHANGE_NORM] = (df[const.COMM_NET_NORM].pct_change() * 100).fillna(0).round(1)

            # Add new columns for position as percent of open interest
            # Adding epsilon (1e-9) to denominator prevents division by zero
            df[const.COMM_PCT_OI] = round((df[const.COMM_NET] / (df[const.OPEN_INTEREST_XLS] + 1e-9)) * 100, 2)
            df[const.LARGE_PCT_OI] = round((df[const.LARGE_NET] / (df[const.OPEN_INTEREST_XLS] + 1e-9)) * 100, 2)
            df[const.SMALL_PCT_OI] = round((df[const.SMALL_NET] / (df[const.OPEN_INTEREST_XLS] + 1e-9)) * 100, 2)

            df = CotIndexer.process_lookback(["Custom", self.instruments[instrument].custom_lookback], self.instruments[instrument].symbol, df)
            for lookback in self.lookbacks:
                df = CotIndexer.process_lookback(lookback, self.instruments[instrument].symbol, df)

            # Return a defragmented dataframe
            self.instruments[instrument].df = df.copy()

            # Save the final calculated DataFrame to Parquet cache
            cache_path = os.path.join(const.CACHE_DIR, f"{self.instruments[instrument].symbol}.parquet")
            self.instruments[instrument].df.to_parquet(cache_path)



    def collect_symbol_summary_results(self, instrument):
        df = self.instruments[instrument].df

        # Construct summary dataframe with only relevant columns for the summary csv
        summary_df = pd.DataFrame()
        summary_df[const.DATE] = df[const.REPORT_DATE_XLS]
        summary_df[const.SYMBOL] = self.instruments[instrument].symbol
        summary_df[const.OPEN_INTEREST] = df[const.OPEN_INTEREST_XLS]
        summary_df[const.COMM_NET] = df[const.COMM_NET]
        summary_df[const.LARGE_NET] = df[const.LARGE_NET]
        summary_df[const.SMALL_NET] = df[const.SMALL_NET]
        summary_df[const.CLOSING_PRICE] = df[const.CLOSING_PRICE]

        # Grab index values
        index_cols = [col for col in df.columns if const.IDX in col]
        for col in index_cols:
            summary_df[col] = df[col]

        # Grab z-score values
        index_cols = [col for col in df.columns if const.ZSCORE in col]
        for col in index_cols:
            summary_df[col] = df[col]

        # Grab Spearman values
        index_cols = [col for col in df.columns if const.SPEARMAN in col]
        for col in index_cols:
            summary_df[col] = df[col]

        # Grab WILLCO values
        index_cols = [col for col in df.columns if const.WILLCO in col]
        for col in index_cols:
            summary_df[col] = df[col]

        return summary_df

    def collect_symbol_detailed_results(self, instrument):
        # Construct detailed dataframe with all columns
        df = self.instruments[instrument].df
        detailed_df = df.copy()
        return detailed_df

    def export_cot_data_to_csv(self):
        working_dir = os.getcwd()
        csv_data_detailed = 'data/csv_data/detailed'
        csv_data_summary = 'data/csv_data/summary'
        os.makedirs(csv_data_detailed, exist_ok=True)
        os.makedirs(csv_data_summary, exist_ok=True)

        for instrument in self.supported_instruments:
            df = self.instruments[instrument].df
            symbol = self.instruments[instrument].symbol

            data_file_name = f'{symbol}.csv'
            detailed_csv_path = os.path.join(
                working_dir, csv_data_detailed, "detailed_" + data_file_name)
            summary_csv_path = os.path.join(
                working_dir, csv_data_summary, "summary_" + data_file_name)

            # Write everything to the detailed csv
            df.to_csv(detailed_csv_path, sep=",", index=True, header=True)

            # Construct summary dataframe with only relevant columns for the summary csv
            summary_df = self.collect_symbol_summary_results(instrument)
            summary_df.to_csv(summary_csv_path, sep=",",
                              index=False, header=True)

    def export_weekly_summary_results_to_csv(self):
        working_dir = os.getcwd()
        csv_data = 'data/csv_data'
        os.makedirs(csv_data, exist_ok=True)
        summary_csv_path = os.path.join(
            working_dir, csv_data, "positioning_summary.csv")

        cols = [const.DATE, const.SYMBOL, const.NAME, const.LOOKBACK,
                const.COMM_CUSTOM_IDX, const.LARGE_CUSTOM_IDX, const.SMALL_CUSTOM_IDX,
                const.COMM_26_IDX, const.LARGE_26_IDX, const.SMALL_26_IDX,
                const.COMM_52_IDX, const.LARGE_52_IDX, const.SMALL_52_IDX,
                const.COMM_CUSTOM_ZSCORE, const.LARGE_CUSTOM_ZSCORE, const.SMALL_CUSTOM_ZSCORE,
                const.COMM_26_ZSCORE, const.LARGE_26_ZSCORE, const.SMALL_26_ZSCORE,
                const.COMM_52_ZSCORE, const.LARGE_52_ZSCORE, const.SMALL_52_ZSCORE,
                const.COMM_CUSTOM_CORR, const.LARGE_CUSTOM_CORR, const.SMALL_CUSTOM_CORR,
                const.COMM_26_CORR, const.LARGE_26_CORR, const.SMALL_26_CORR,
                const.COMM_52_CORR, const.LARGE_52_CORR, const.SMALL_52_CORR,
                ]
        positioning_df = pd.DataFrame(columns=cols)

        for asset in self.asset_class_map:
            instruments = self.get_assets_for_asset_class(asset)
            for instrument_name in instruments:
                instrument = self.get_instrument_from_name(instrument_name)
                df = instrument.df

                new_df = pd.DataFrame(
                    [[df.iloc[-1][const.REPORT_DATE_XLS].date(), instrument.symbol, instrument.name, instrument.custom_lookback,
                      df.iloc[-1][const.COMM_CUSTOM_IDX], df.iloc[-1][const.LARGE_CUSTOM_IDX], df.iloc[-1][const.SMALL_CUSTOM_IDX],
                      df.iloc[-1][const.COMM_26_IDX], df.iloc[-1][const.LARGE_26_IDX], df.iloc[-1][const.SMALL_26_IDX],
                      df.iloc[-1][const.COMM_52_IDX], df.iloc[-1][const.LARGE_52_IDX], df.iloc[-1][const.SMALL_52_IDX],

                      df.iloc[-1][const.COMM_CUSTOM_ZSCORE], df.iloc[-1][const.LARGE_26_ZSCORE], df.iloc[-1][const.SMALL_CUSTOM_ZSCORE],
                      df.iloc[-1][const.COMM_26_ZSCORE], df.iloc[-1][const.LARGE_26_ZSCORE], df.iloc[-1][const.SMALL_26_ZSCORE],
                      df.iloc[-1][const.COMM_52_ZSCORE], df.iloc[-1][const.LARGE_52_ZSCORE], df.iloc[-1][const.SMALL_52_ZSCORE],

                      df.iloc[-1][const.COMM_CUSTOM_CORR], df.iloc[-1][const.LARGE_CUSTOM_CORR], df.iloc[-1][const.SMALL_CUSTOM_CORR],
                      df.iloc[-1][const.COMM_26_CORR], df.iloc[-1][const.LARGE_26_CORR], df.iloc[-1][const.SMALL_26_CORR],
                      df.iloc[-1][const.COMM_52_CORR], df.iloc[-1][const.LARGE_52_CORR], df.iloc[-1][const.SMALL_52_CORR],
                      ]], columns=positioning_df.columns)
                if positioning_df.empty:
                    positioning_df = new_df
                else:
                    positioning_df = pd.concat([positioning_df, new_df])

        positioning_df.to_csv(summary_csv_path, sep=",",
                              index=False, header=True)

    def export_real_test_data_to_csv(self):
        # Event List format: https://mhptrading.com/docs/topics/idh-topic490.htm
        # The first row of the file must contain column names from the following list:
        # •Symbol – the symbol for which the event occurred
        # •Date – the date of the event
        # •Time – the time of the event (optional)
        # •Type – any numeric code > 0 --
        #         Here type 1 is Commercials Index, 2 is Large Specs Index, and 3 is Small Specs Index
        #              type 4 is Commercials Net Position, 5 is Large Specs Net Position, and 6 is Small Specs Net Position
        # •Value – any numeric value (e.g. dividend amount, or EPS, or index constituency flags)
        working_dir = os.getcwd()
        real_test_data_dir = self.real_test_data_dir
        os.makedirs(real_test_data_dir, exist_ok=True)

        for instrument in self.supported_instruments:
            symbol = self.instruments[instrument].symbol
            lb = self.instruments[instrument].custom_lookback
            data_file_name = f'{symbol}.csv'
            real_test_csv_path = os.path.join(
                working_dir, real_test_data_dir, "RT_event_list_lb_" + str(lb) + "_" + data_file_name)
            real_test_df = self.create_real_test_event_asset_list(instrument)
            real_test_df.to_csv(real_test_csv_path, sep=",",
                                index=True, header=True)

    def create_real_test_event_asset_list(self, instrument):
        df = self.instruments[instrument].df
        #
        # Indexes
        #
        # Add commercials
        commercial_idx_df = pd.DataFrame()
        commercial_idx_df[const.DATE] = df[const.REPORT_DATE_XLS].apply(
            lambda x: x.date())
        commercial_idx_df[const.SYMBOL] = [
            self.instruments[instrument].symbol] * len(df[const.REPORT_DATE_XLS])
        commercial_idx_df["Type"] = 1  # Commercials index
        commercial_idx_df["Value"] = df[const.COMM_CUSTOM_IDX]
        commercial_idx_df = commercial_idx_df[commercial_idx_df["Value"] != -1]

        # Add large specs
        large_specs_idx_df = pd.DataFrame()
        large_specs_idx_df[const.DATE] = df[const.REPORT_DATE_XLS].apply(
            lambda x: x.date())
        large_specs_idx_df[const.SYMBOL] = [
            self.instruments[instrument].symbol] * len(df[const.REPORT_DATE_XLS])
        large_specs_idx_df["Type"] = 2  # Large specs index
        large_specs_idx_df["Value"] = df[const.LARGE_CUSTOM_IDX]
        large_specs_idx_df = large_specs_idx_df[large_specs_idx_df["Value"] != -1]

        # Add small specs
        small_specs_idx_df = pd.DataFrame()
        small_specs_idx_df[const.DATE] = df[const.REPORT_DATE_XLS].apply(
            lambda x: x.date())
        small_specs_idx_df[const.SYMBOL] = [
            self.instruments[instrument].symbol] * len(df[const.REPORT_DATE_XLS])
        small_specs_idx_df["Type"] = 3  # Small specs index
        small_specs_idx_df["Value"] = df[const.SMALL_CUSTOM_IDX]
        small_specs_idx_df = small_specs_idx_df[small_specs_idx_df["Value"] != -1]

        #
        # Net Positions
        #
        # Add commercials
        commercial_pos_df = pd.DataFrame()
        commercial_pos_df[const.DATE] = df[const.REPORT_DATE_XLS].apply(
            lambda x: x.date())
        commercial_pos_df[const.SYMBOL] = [
            self.instruments[instrument].symbol + "_B"] * len(df[const.REPORT_DATE_XLS])
        commercial_pos_df["Type"] = 4  # Commercials net position
        commercial_pos_df["Value"] = df[const.COMM_NET]
        commercial_pos_df = commercial_pos_df[commercial_pos_df["Value"] != -1]

        # Add large specs
        large_specs_pos_df = pd.DataFrame()
        large_specs_pos_df[const.DATE] = df[const.REPORT_DATE_XLS].apply(
            lambda x: x.date())
        large_specs_pos_df[const.SYMBOL] = [
            self.instruments[instrument].symbol + "_B"] * len(df[const.REPORT_DATE_XLS])
        large_specs_pos_df["Type"] = 5  # Large specs net position
        large_specs_pos_df["Value"] = df[const.LARGE_NET]
        large_specs_pos_df = large_specs_pos_df[large_specs_pos_df["Value"] != -1]

        # Add small specs
        small_specs_pos_df = pd.DataFrame()
        small_specs_pos_df[const.DATE] = df[const.REPORT_DATE_XLS].apply(
            lambda x: x.date())
        small_specs_pos_df[const.SYMBOL] = [
            self.instruments[instrument].symbol + "_B"] * len(df[const.REPORT_DATE_XLS])
        small_specs_pos_df["Type"] = 6  # Small specs net position
        small_specs_pos_df["Value"] = df[const.SMALL_NET]
        small_specs_pos_df = small_specs_pos_df[small_specs_pos_df["Value"] != -1]

        # Concatenate into one dataframe
        result_df = commercial_idx_df
        result_df = pd.concat([result_df, commercial_idx_df])
        result_df = pd.concat([result_df, large_specs_idx_df])
        result_df = pd.concat([result_df, large_specs_pos_df])
        result_df = pd.concat([result_df, small_specs_idx_df])
        result_df = pd.concat([result_df, small_specs_pos_df])

        return result_df

    def get_asset_classes(self, sort=True, exclude_financial=False, include_heldout=False):
        # Default excludes role:heldout markets so neither the dashboard nor a
        # config's asset_classes universe (resolve_universe) picks them up — they are
        # collected + indexed but out of selection. Pass include_heldout=True for the
        # full set. A class whose every member is heldout drops out entirely.
        src = self.asset_class_map if include_heldout else self.plotted_asset_class_map()
        if exclude_financial:
            classes = [asset for asset in src if metrics.is_commodity(asset)]
        else:
            classes = list(src)
        if sort:
            classes.sort()
        return classes

    def get_default_asset_class(self, exclude_financial=False):
        if not (len(self.asset_class_map)) == 0:
            if exclude_financial:
                for asset in self.asset_class_map:
                    if metrics.is_commodity(asset):
                        return asset
            else:
                if 'Equities' in self.asset_class_map:
                    return 'Equities'
                else:
                    for asset in self.asset_class_map:
                        return asset
        return ""

    def get_assets_for_asset_class(self, asset_class, sort=True, include_heldout=False):
        # Default excludes role:heldout members (see get_asset_classes) — this is the
        # method resolve_universe expands a config's asset_classes through, so held-out
        # markets must NOT leak into the deployed/plotted universe. Access them by
        # explicit symbol (get_instrument_from_symbol) or include_heldout=True.
        src = self.asset_class_map if include_heldout else self.plotted_asset_class_map()
        result = list(src.get(asset_class, set()))
        if sort:
            result.sort()
        return result

    def get_instrument_names(self):
        result = []
        for code in self.instruments:
            result.append(self.instruments[code].symbol)
        return result

    def get_instrument_symbol_from_name(self, name):
        for code in self.instruments:
            if self.instruments[code].name == name:
                return self.instruments[code].symbol
        return None

    def get_instrument_from_code(self, code):
        if code in self.instruments:
            return self.instruments[code]
        return None

    def get_instrument_code_from_name(self, name):
        for code in self.instruments:
            if self.instruments[code].name == name:
                return code
        return None

    def get_instrument_from_name(self, name):
        for inst_code in self.instruments:
            if self.instruments[inst_code].name == name:
                return self.instruments[inst_code]
        return None

    def get_instrument_from_symbol(self, symbol):
        for inst_code in self.instruments:
            if self.instruments[inst_code].symbol == symbol:
                return self.instruments[inst_code]
        return None

    def is_equity(self, name):
        if "quit" in self.get_instrument_from_name(name).asset_class:
            return True
        return False

    def refresh_if_stale(self):
        """Rebuild the in-memory index if the producer has written a newer COT week.

        Returns True if a rebuild happened, False if the store had not moved.

        The freshness signal is ``status.json`` in the cotdata store, read uncached
        through ``cotDatabase.latest_update_timestamp``. That file is rewritten once,
        atomically (tmp file + os.replace), at the very end of a producer run and
        after every report kind has landed, precisely so consumers can poll it. So a
        poll can see the old week or the new one, never a half-written store.

        This logic used to live inline at the top of get_symbols_data, where it could
        not do its job: it was guarded by that method's own lru_cache, so on a cache
        HIT the body never ran and the check never fired. The cache holds 256 entries
        against 252 live keys (42 instruments x 2 bases x 3 lookbacks), so the board
        goes warm within minutes of boot and from then on essentially every call is a
        hit. In practice the check only fired when someone happened to request a
        combination nobody had requested since startup. Observed 2026-08-07: the store
        took the 2026-08-04 week at 16:09 local, the navbar badge (which reads the same
        status.json, uncached, on a 5-minute interval) showed it immediately, and every
        page kept serving 2026-07-28 until 20:52 when a cold key finally missed. Call
        this from a poller instead. The call left in get_symbols_data now only covers
        the cold-start case.

        Rebuilding takes ~2 minutes on the full universe, and the navbar interval fires
        once per open browser tab, so concurrent callers are ordinary rather than
        exotic. The lock makes the second caller wait for the first rather than start a
        duplicate rebuild, and the re-check under it means it then returns immediately.

        The new state is built off to the side and published in a single rebind, so a
        request served during those two minutes sees the previous week whole rather
        than a half-updated universe. See _build_state.
        """
        if cotDatabase.latest_update_timestamp() == self.last_known_db_time:
            return False

        with self._refresh_lock:
            current_db_time = cotDatabase.latest_update_timestamp()
            if current_db_time == self.last_known_db_time:
                return False

            utils.cot_logger.warning(f"New database data detected ({current_db_time}). Rebuilding index.")
            new_state = self._build_state()

            # Publish. One rebind of one reference, so a reader either sees the whole
            # old week or the whole new one.
            self._state = new_state

            # Only now drop the memoized frames, which are the old week's. Clearing
            # BEFORE the build (as this used to) would have refilled them from the old
            # state during the two minutes the build was running, so the stale entries
            # came straight back and outlived the swap.
            self.get_symbols_data.__func__.cache_clear()
            self.get_asset_class_z_score_heat.__func__.cache_clear()
            self.get_asset_class_index_heat.__func__.cache_clear()
            self.get_positioning_table_by_asset_class.__func__.cache_clear()
            self.get_category_data.__func__.cache_clear()

            # Adopt the stamp only after a build that actually succeeded. Setting it
            # first (as this used to, to stop the in-place rebuild recursing) meant a
            # build that raised would have claimed data it never loaded, and no later
            # poll would retry. Recursion is no longer the risk it guards against: the
            # build runs against a separate object, not self.
            self.last_known_db_time = current_db_time
            utils.cot_logger.info("Updated instruments and recalculated metrics with latest database data.")
            return True

    def _build_state(self):
        """Build a complete replacement _IndexState without touching the live one.

        populate_instruments and calculate_weekly_data are written against `self`, and
        they mutate Instrument.df in place. Run them on this object and every page
        rendered during the ~2 minute rebuild reads frames mid-mutation. So they are run
        against a shallow copy that has been given its own empty state: same config,
        same params, same already-loaded years/lookbacks/roles, but its own instruments.

        Shallow is what makes this cheap and also what makes it correct. The builder
        shares the immutable-in-practice config by reference and only ever writes
        through `_state`, which is the one attribute reassigned to a fresh object.
        load_years and load_roles are deliberately NOT re-run: they append to shared
        lists, so a second pass would double their contents.

        A fresh CotIndexer() would be the obvious alternative and is wrong here, because
        __init__ tries try_load_from_cache first and that check tests for column presence
        rather than freshness. It would happily load the very parquet cache this rebuild
        exists to replace.
        """
        builder = copy.copy(self)
        builder._state = _IndexState()
        builder.load_instruments()
        builder.populate_instruments()
        builder.calculate_weekly_data()
        return builder._state

    # Sized to hold the whole board rather than a round number: 42 instruments x 2 bases
    # x 3 lookbacks = 252 distinct keys. At the previous 128 a single flip of the Home
    # page's lookback or model selector evicted frames the *previous* selection was still
    # using, so toggling back and forth rebuilt frames that had just been computed.
    #
    # The ceiling this buys is real memory, not a free win. Each frame is a fresh copy
    # built column by column (432 x 242, ~2.9MB deep), so a fully populated cache is
    # ~730MB resident. Raising this further without re-measuring that number is how the
    # server box runs out of RAM.
    @lru_cache(maxsize=256)
    def get_symbols_data(self, name, lookback, basis=const.BASIS_RAW):
        """Weekly frame for one instrument, with the generic alias columns the UI and
        the ML dataset consume.

        `basis` selects which net-position series the level metrics are built from:
        BASIS_RAW (net contracts) or BASIS_OI_NORM (net / open interest). Both families
        are precomputed by process_lookback, so this only picks which one lands on the
        aliases. Every alias moves together, otherwise the signal engine would mix a
        normalized index with a raw z-score inside one condition set.
        """
        if basis not in const.BASIS_CHOICES:
            raise ValueError(f"unknown basis {basis!r}, expected one of {const.BASIS_CHOICES}")
        normalized = basis == const.BASIS_OI_NORM
        lookback = " " + lookback

        # Cold-start path only. This call cannot be relied on to notice new data,
        # because it sits inside this method's own lru_cache: see refresh_if_stale.
        self.refresh_if_stale()

        instrument = self.get_instrument_from_name(name)
        if instrument is not None:
            idx_col_header_name = lookback + const.IDX
            COMM_IDX = const.COMM + idx_col_header_name
            LRG_IDX = const.LARGE + idx_col_header_name
            SML_IDX = const.SMALL + idx_col_header_name

            norm_idx_col_header_name = idx_col_header_name + const.NORMALIZED
            COMM_NORM_IDX = const.COMM + norm_idx_col_header_name
            LRG_NORM_IDX = const.LARGE + norm_idx_col_header_name
            SML_NORM_IDX = const.SMALL + norm_idx_col_header_name

            zscore_col_header_name = lookback + const.ZSCORE
            COMM_ZS = const.COMM + zscore_col_header_name
            LRG_ZS = const.LARGE + zscore_col_header_name
            SML_ZS = const.SMALL + zscore_col_header_name

            zscore_norm_col_header_name = zscore_col_header_name + const.NORMALIZED
            COMM_ZS_NORM = const.COMM + zscore_norm_col_header_name
            LRG_ZS_NORM = const.LARGE + zscore_norm_col_header_name
            SML_ZS_NORM = const.SMALL + zscore_norm_col_header_name

            spearman_col_header_name = lookback + const.SPEARMAN
            COMM_SPR = const.COMM + spearman_col_header_name
            LRG_SPR = const.LARGE + spearman_col_header_name
            SML_SPR = const.SMALL + spearman_col_header_name

            norm_spearman_col_header_name = spearman_col_header_name + const.NORMALIZED
            COMM_NORM_SPR = const.COMM + norm_spearman_col_header_name
            LRG_NORM_SPR = const.LARGE + norm_spearman_col_header_name
            SML_NORM_SPR = const.SMALL + norm_spearman_col_header_name

            momentum_idx_header_name = lookback + const.MOMENTUM
            COMM_MOM = const.COMM + momentum_idx_header_name
            LRG_MOM = const.LARGE + momentum_idx_header_name
            SML_MOM = const.SMALL + momentum_idx_header_name

            norm_momentum_idx_header_name = momentum_idx_header_name + const.NORMALIZED
            COMM_MOM_NORM = const.COMM + norm_momentum_idx_header_name
            LRG_MOM_NORM = const.LARGE + norm_momentum_idx_header_name
            SML_MOM_NORM = const.SMALL + norm_momentum_idx_header_name

            wow_header = lookback + const.WOW_MOVE
            COMM_WOW = const.COMM + wow_header
            LRG_WOW = const.LARGE + wow_header
            SML_WOW = const.SMALL + wow_header

            norm_wow_header = wow_header + const.NORMALIZED
            COMM_WOW_NORM = const.COMM + norm_wow_header
            LRG_WOW_NORM = const.LARGE + norm_wow_header
            SML_WOW_NORM = const.SMALL + norm_wow_header

            # _SRC because the alias constants below are one letter-case away: the
            # source column is "Open Interest 26 Zscore", the alias is "oi_zscore".
            OI_ZSCORE_SRC = const.OPEN_INTEREST + lookback + const.ZSCORE
            WILLCO_SRC = const.WILLCO + lookback

            df = instrument.df
            result = df.copy()

            result[const.DATE] = df[const.REPORT_DATE_XLS]

            result[const.COMMS_IDX] = df[COMM_NORM_IDX if normalized else COMM_IDX]
            result[const.LRG_IDX] = df[LRG_NORM_IDX if normalized else LRG_IDX]
            result[const.SML_IDX] = df[SML_NORM_IDX if normalized else SML_IDX]

            # Positioning-index setup (COT-index extremes): the same detector used by
            # the dashboard's setup highlighting, exposed as first-class feature columns
            # so every consumer reads identical setup long/short values.
            #
            # The gate follows the basis. These columns are built from the aliases just
            # assigned above, so on BASIS_OI_NORM they describe the normalized index and
            # have to be gated by the model that owns that basis. They previously used
            # the 95/5 CLS defaults regardless, which labelled normalized readings as
            # setups under a rule calibrated on raw contracts.
            _model = models.for_basis(basis)
            _setup_long, _setup_short, _near_long, _near_short = _model.setup_masks(
                result[const.COMMS_IDX], result[const.LRG_IDX], result[const.SML_IDX],
                self.is_equity(name)
            )
            result[const.POS_IDX_SETUP_LONG] = _setup_long.astype(int)
            result[const.POS_IDX_SETUP_SHORT] = _setup_short.astype(int)
            result[const.POS_IDX_SETUP_NEAR_LONG] = _near_long.astype(int)
            result[const.POS_IDX_SETUP_NEAR_SHORT] = _near_short.astype(int)

            result[const.COMMS_ZSCORE] = df[COMM_ZS_NORM if normalized else COMM_ZS]
            result[const.LRG_ZSCORE] = df[LRG_ZS_NORM if normalized else LRG_ZS]
            result[const.SML_ZSCORE] = df[SML_ZS_NORM if normalized else SML_ZS]

            result[const.COMMS_SPEARMAN] = df[COMM_NORM_SPR if normalized else COMM_SPR]
            result[const.LRG_SPEARMAN] = df[LRG_NORM_SPR if normalized else LRG_SPR]
            result[const.SML_SPEARMAN] = df[SML_NORM_SPR if normalized else SML_SPR]

            # Index momentum is a point change *of the index above* over MOMENTUM_PERIOD
            # weekly reports, so it follows the basis rather than staying raw. Unlike the
            # COT-MACD, which is derived independently from Comm Net and has no normalized
            # twin by design.
            result[const.COMM_MOMENTUM] = df[COMM_MOM_NORM if normalized else COMM_MOM]
            result[const.LRG_MOMENTUM] = df[LRG_MOM_NORM if normalized else LRG_MOM]
            result[const.SML_MOMENTUM] = df[SML_MOM_NORM if normalized else SML_MOM]

            # Week-over-week deltas of the same indices, following the basis for the
            # same reason index momentum does: they are a point change *of the index
            # above*, so a raw delta beside a normalized level would describe two
            # different series under one name.
            result[const.COMM_WOW] = df[COMM_WOW_NORM if normalized else COMM_WOW]
            result[const.LRG_WOW] = df[LRG_WOW_NORM if normalized else LRG_WOW]
            result[const.SML_WOW] = df[SML_WOW_NORM if normalized else SML_WOW]

            result[const.LSR] = df.get(const.LIQUIDITY_STRAIN + const.ZSCORE + lookback)
            result[const.PHD] = df.get(const.PRICE_HEDGING_DIV + const.ZSCORE + lookback)
            result[const.WILLCO_ALIAS] = df.get(WILLCO_SRC)
            result[const.OI_ZSCORE] = df.get(OI_ZSCORE_SRC)

            # Legacy compatibility mapping for UI/ML expecting exactly these generic labels
            if const.OPEN_INTEREST_XLS in df.columns:
                result[const.OPEN_INTEREST] = df[const.OPEN_INTEREST_XLS]

            result = metrics.append_trading_signals(result, asset_class=instrument.asset_class, normalized=normalized)

            result.set_index(const.DATE, inplace=True)

            # Reattach attrs after all dataframe operations to guarantee Pandas doesn't drop them
            result.attrs = getattr(df, "attrs", {}).copy()
            # Stamp the basis so downstream consumers (plot labels, CSV exports) can say
            # which one they are showing instead of guessing.
            result.attrs['basis'] = basis
            return result

    def available_reports_for(self, name):
        """Which category reports this instrument has data for, in (disagg, tff) order.

        Probes the store rather than config. params.yaml instrument entries carry no
        report-type field, and cotdata.registry.Symbol.report_type is derived from
        asset-class labels ("FX", "Rates") that the registry never actually uses, so
        it reads "disagg" for every currency, rates and crypto market whose data
        lives in cot_tff/. Do not read that field.

        In practice this returns a one-tuple or an empty tuple: the two universes are
        disjoint (Disaggregated is physical commodities, TFF is financials), so no
        market has both.
        """
        code = self.get_instrument_code_from_name(name)
        if code is None:
            return ()
        found = []
        if self.is_commodity_code(code):
            found.append(categories.REPORT_DISAGG)
        if self.has_tff_code(code):
            found.append(categories.REPORT_TFF)
        return tuple(found)

    # Not parquet-cached, only held in RAM. The COTMETRICS_CACHE key is a bare
    # {symbol}.parquet that already doubles as the price cache, so a report-type
    # dimension would collide with it, and its invalidation sidecar has no per-report
    # axis. Recomputing is cheap enough that this is not a trade: ~1,050 weekly rows
    # times five categories is a handful of rolling passes.
    @lru_cache(maxsize=64)
    def get_category_data(self, name, report, lookback="Custom", with_price=True):
        """Per-category frame for one instrument, indexed by Date like get_symbols_data.

        `report` is categories.REPORT_DISAGG or REPORT_TFF. `lookback` is the same
        "26"/"52"/"Custom" string the app's global lookback store carries. Returns
        None when the instrument has no such report, or on a load failure.

        The price columns are joined here rather than by the caller: cot-analyzer is
        a view over this package and computes nothing of its own, joining included.
        """
        if report not in categories.REPORT_CHOICES:
            raise ValueError(
                f"unknown report {report!r}, expected one of {categories.REPORT_CHOICES}"
            )

        instrument = self.get_instrument_from_name(name)
        if instrument is None:
            return None

        # Probe availability rather than inferring it from an empty frame: get_cot
        # returns empty for a missing file, so treating empty as "no such report"
        # would report a half-synced or corrupt store as a market that simply has no
        # TFF report, which is both wrong and unfalsifiable from the UI.
        if report not in self.available_reports_for(name):
            return None

        weeks = instrument.custom_lookback
        if lookback != "Custom":
            for lb_name, lb_weeks in self.lookbacks:
                if str(lb_weeks) == str(lookback) or lb_name == lookback:
                    weeks = lb_weeks
                    break
        header = const.get_lookback_header_str([lookback, weeks])

        import cotdata

        code = self.get_instrument_code_from_name(name)
        try:
            raw = cotdata.get_cot(code, report=report)
        except Exception as e:
            utils.cot_logger.warning(
                f"get_category_data: {report} load failed for {code}: {e}")
            return None
        if raw is None or raw.empty:
            return None

        frame = categories.build_category_frame(
            raw, report, weeks, lookback_header=header)
        if frame.empty:
            return None

        if with_price:
            price_cols = [const.OPEN_PRICE, const.HIGH_PRICE,
                          const.LOW_PRICE, const.CLOSING_PRICE]
            base = instrument.df
            have = [c for c in price_cols if c in base.columns]
            if have:
                prices = base[[const.REPORT_DATE_XLS] + have].copy()
                prices[const.REPORT_DATE_XLS] = pd.to_datetime(
                    prices[const.REPORT_DATE_XLS]).dt.tz_localize(None)
                frame[const.REPORT_DATE_XLS] = pd.to_datetime(
                    frame[const.REPORT_DATE_XLS]).dt.tz_localize(None)
                attrs = frame.attrs.copy()
                frame = frame.merge(prices, on=const.REPORT_DATE_XLS, how="left")
                frame.attrs = attrs

        frame[const.DATE] = pd.to_datetime(frame[const.REPORT_DATE_XLS])
        attrs = frame.attrs.copy()
        frame = frame.set_index(const.DATE)
        # Reattach after set_index: pandas drops attrs across most operations, which
        # is why get_symbols_data does the same thing at the end.
        frame.attrs = attrs
        return frame

    def get_available_dates(self):
        if not self.asset_class_map or not self.instruments:
            return []

        # Pick the first instrument to get the shared report dates
        instrument = list(self.instruments.values())[0]

        if instrument and not instrument.df.empty:
            dates = instrument.df[const.REPORT_DATE_XLS].dt.date.sort_values(ascending=False).unique()
            return [d.isoformat() for d in dates]
        return []

    @lru_cache(maxsize=32)
    def get_positioning_table_by_asset_class(self, asset_classes, lookback, target_date=None):
        from cotmetrics.options_data import get_max_pain_for_symbol
        # Convert list to tuple so lru_cache doesn't crash!
        if isinstance(asset_classes, list):
            asset_classes = tuple(asset_classes)

        lookback = " " + lookback
        idx_col_header_name = lookback + const.IDX
        COMM_IDX = const.COMM + idx_col_header_name
        LRG_IDX = const.LARGE + idx_col_header_name
        SML_IDX = const.SMALL + idx_col_header_name

        idx_norm_col_header_name = idx_col_header_name + const.NORMALIZED
        COMM_NORM_IDX = const.COMM + idx_norm_col_header_name
        LRG_NORM_IDX = const.LARGE + idx_norm_col_header_name
        SML_NORM_IDX = const.SMALL + idx_norm_col_header_name

        zscore_col_header_name = lookback + const.ZSCORE
        COMM_ZS = const.COMM + zscore_col_header_name
        LRG_ZS = const.LARGE + zscore_col_header_name
        SML_ZS = const.SMALL + zscore_col_header_name

        spearman_col_header_name = lookback + const.SPEARMAN
        COMM_SPR = const.COMM + spearman_col_header_name
        LRG_SPR = const.LARGE + spearman_col_header_name
        SML_SPR = const.SMALL + spearman_col_header_name

        norm_spearman_col_header_name = spearman_col_header_name + const.NORMALIZED
        COMM_NORM_SPR = const.COMM + norm_spearman_col_header_name
        LRG_NORM_SPR = const.LARGE + norm_spearman_col_header_name
        SML_NORM_SPR = const.SMALL + norm_spearman_col_header_name

        WILLCO = const.WILLCO + lookback
        LIQUIDITY_STRAIN = const.LIQUIDITY_STRAIN + const.ZSCORE + lookback
        OI_ZSCORE = const.OPEN_INTEREST + lookback + const.ZSCORE

        momentum_idx_header_name = lookback + const.MOMENTUM
        COMM_MOM = const.COMM + momentum_idx_header_name
        LRG_MOM = const.LARGE + momentum_idx_header_name
        SML_MOM = const.SMALL + momentum_idx_header_name

        cols = [const.DATE, const.ASSET_CLASS, const.OPEN_INTEREST,
                const.SYMBOL, const.NAME, const.LOOKBACK,
                const.COMM_NET, const.LARGE_NET, const.SMALL_NET,
                const.COMM_PCT_OI, const.LARGE_PCT_OI, const.SMALL_PCT_OI,
                COMM_IDX, LRG_IDX, SML_IDX,
                const.COMM_NET_NORM, const.LARGE_NET_NORM, const.SMALL_NET_NORM,
                COMM_NORM_IDX, LRG_NORM_IDX, SML_NORM_IDX,
                COMM_ZS, LRG_ZS, SML_ZS,
                COMM_MOM, LRG_MOM, SML_MOM,
                COMM_SPR, LRG_SPR, SML_SPR,
                COMM_NORM_SPR, LRG_NORM_SPR, SML_NORM_SPR,
                WILLCO, LIQUIDITY_STRAIN, OI_ZSCORE, const.LW_LRG_SENTIMENT, "Max Pain", "Delta IV"]
        positioning_df = pd.DataFrame(columns=cols)

        for asset in self.asset_class_map:
            if asset not in asset_classes:
                continue

            instruments = self.get_assets_for_asset_class(asset)
            for instrument_name in instruments:
                instrument = self.get_instrument_from_name(instrument_name)
                if instrument:
                    df = instrument.df

                    if target_date:
                        target_dt = pd.to_datetime(target_date)
                        past_df = df[df[const.REPORT_DATE_XLS] <= target_dt]
                        if past_df.empty:
                            continue
                        idx = past_df.index[-1]
                    else:
                        idx = len(df) - 1

                    symbol = instrument.symbol
                    res = get_max_pain_for_symbol(symbol, df.loc[idx, const.REPORT_DATE_XLS].date())
                    max_pain, delta_iv = (res["max_pain"], res["delta_iv"]) if res else (None, None)

                    new_df = pd.DataFrame(
                        [[df.loc[idx, const.REPORT_DATE_XLS].date(), instrument.asset_class, df.loc[idx, const.OPEN_INTEREST_XLS],
                          instrument.symbol, instrument.name, instrument.custom_lookback,
                          df.loc[idx, const.COMM_NET], df.loc[idx, const.LARGE_NET], df.loc[idx, const.SMALL_NET],
                          df.loc[idx, const.COMM_PCT_OI], df.loc[idx, const.LARGE_PCT_OI], df.loc[idx, const.SMALL_PCT_OI],
                          df.loc[idx, COMM_IDX], df.loc[idx, LRG_IDX], df.loc[idx, SML_IDX],
                          round(df.loc[idx, const.COMM_NET_NORM], 2), round(df.loc[idx, const.LARGE_NET_NORM], 2), round(df.loc[idx, const.SMALL_NET_NORM], 2),
                          df.loc[idx, COMM_NORM_IDX], df.loc[idx, LRG_NORM_IDX], df.loc[idx, SML_NORM_IDX],
                          round(df.loc[idx, COMM_ZS], 2), round(df.loc[idx, LRG_ZS], 2), round(df.loc[idx, SML_ZS], 2),
                          round(df.loc[idx, COMM_MOM], 2), round(df.loc[idx, LRG_MOM], 2), round(df.loc[idx, SML_MOM], 2),
                          round(df.loc[idx, COMM_SPR], 2), round(df.loc[idx, LRG_SPR], 2), round(df.loc[idx, SML_SPR], 2),
                          round(df.loc[idx, COMM_NORM_SPR], 2), round(df.loc[idx, LRG_NORM_SPR], 2), round(df.loc[idx, SML_NORM_SPR], 2),
                          df.loc[idx, WILLCO], round(df.loc[idx, LIQUIDITY_STRAIN], 2), round(df.loc[idx, OI_ZSCORE], 2), df.loc[idx, const.LW_LRG_SENTIMENT], max_pain, delta_iv
                          ]], columns=positioning_df.columns)

                    if positioning_df.empty:
                        positioning_df = new_df
                    else:
                        positioning_df = pd.concat([positioning_df, new_df])
        return positioning_df

    @lru_cache(maxsize=32)
    def get_asset_class_z_score_heat(self, asset_class, lookback):
        """Returns the latest Z-scores for all assets in a class."""
        assets = self.get_assets_for_asset_class(asset_class)
        heat_data = []

        for name in assets:
            instrument = self.get_instrument_from_name(name)
            if instrument is not None and not instrument.df.empty:
                df = instrument.df
                # Get the most recent non-NaN Z-scores
                latest = df.iloc[-1]
                if lookback == "26":
                    heat_data.append({
                        "Asset": name,
                        "Commercials": latest.get(const.COMM_26_ZSCORE, 0),
                        "Large Specs": latest.get(const.LARGE_26_ZSCORE, 0),
                        "Small Specs": latest.get(const.SMALL_26_ZSCORE, 0)
                    })
                elif lookback == "52":
                    heat_data.append({
                        "Asset": name,
                        "Commercials": latest.get(const.COMM_52_ZSCORE, 0),
                        "Large Specs": latest.get(const.LARGE_52_ZSCORE, 0),
                        "Small Specs": latest.get(const.SMALL_52_ZSCORE, 0)
                    })
                else:
                    heat_data.append({
                        "Asset": name,
                        "Commercials": latest.get(const.COMM_CUSTOM_ZSCORE, 0),
                        "Large Specs": latest.get(const.LARGE_CUSTOM_ZSCORE, 0),
                        "Small Specs": latest.get(const.SMALL_CUSTOM_ZSCORE, 0)
                    })

        return pd.DataFrame(heat_data)

    @lru_cache(maxsize=32)
    def get_asset_class_index_heat(self, asset_class, lookback):
        """Returns the latest Index for all assets in a class."""
        assets = self.get_assets_for_asset_class(asset_class)
        heat_data = []

        for name in assets:
            instrument = self.get_instrument_from_name(name)
            if instrument is not None and not instrument.df.empty:
                df = instrument.df
                # Get the most recent non-NaN Z-scores
                latest = df.iloc[-1]

                if lookback == "26":
                    heat_data.append({
                        "Asset": name,
                        "Commercials": latest.get(const.COMM_26_IDX, 0),
                        "Large Specs": latest.get(const.LARGE_26_IDX, 0),
                        "Small Specs": latest.get(const.SMALL_26_IDX, 0)
                    })
                elif lookback == "52":
                    heat_data.append({
                        "Asset": name,
                        "Commercials": latest.get(const.COMM_52_IDX, 0),
                        "Large Specs": latest.get(const.LARGE_52_IDX, 0),
                        "Small Specs": latest.get(const.SMALL_52_IDX, 0)
                    })
                else:
                    heat_data.append({
                        "Asset": name,
                        "Commercials": latest.get(const.COMM_CUSTOM_IDX, 0),
                        "Large Specs": latest.get(const.LARGE_CUSTOM_IDX, 0),
                        "Small Specs": latest.get(const.SMALL_CUSTOM_IDX, 0)
                    })

        return pd.DataFrame(heat_data)
