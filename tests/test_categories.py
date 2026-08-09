"""Unit tests for the per-category Disaggregated / TFF frame builder.

Store-free by construction: every test builds its own DataFrame, so these run
against CI's empty COTDATA_STORE.
"""

import numpy as np
import pandas as pd
import pytest

import cotmetrics.categories as categories
import cotmetrics.constants as const
import cotmetrics.indicators as indicators


def _frame(report, n=60, seed=0):
    """A synthetic CFTC-shaped wide frame carrying every column the specs name."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-07", periods=n, freq="7D")
    data = {const.OPEN_INTEREST_XLS: rng.integers(400_000, 600_000, n)}
    for spec in categories.categories_for(report):
        data[spec.long_col] = rng.integers(10_000, 90_000, n)
        data[spec.short_col] = rng.integers(10_000, 90_000, n)
        if spec.spread_col:
            data[spec.spread_col] = rng.integers(1_000, 9_000, n)
        if spec.traders_long_col:
            data[spec.traders_long_col] = [f"   {v}" for v in rng.integers(5, 90, n)]
        if spec.traders_short_col:
            data[spec.traders_short_col] = [f"   {v}" for v in rng.integers(5, 90, n)]
    return pd.DataFrame(data, index=dates)


def test_category_specs_match_cotdata_vintage():
    """Our column literals must equal cotdata's canonicalisers, key for key.

    This deliberately reaches for a private name in a peer package. It is a drift
    alarm, not an API: cotdata's dicts serve the long-form vintage schema and carry
    no labels or prefixes, so we duplicate the literals rather than import them. If
    the CFTC renames a header and cotdata follows, this is where you want to hear
    about it, rather than in a chart that silently lost a category.
    """
    from cotdata import vintage_ingest as vi

    for report, upstream in ((categories.REPORT_DISAGG, vi._DISAGG_CATEGORIES),
                             (categories.REPORT_TFF, vi._TFF_CATEGORIES)):
        specs = {s.key: s for s in categories.categories_for(report)}
        assert set(specs) == set(upstream), report
        for key, spec in specs.items():
            assert (spec.long_col, spec.short_col, spec.spread_col,
                    spec.traders_long_col, spec.traders_short_col) == tuple(
                        upstream[key]), f"{report}/{key}"


def test_unknown_report_raises_naming_choices():
    """"disaggregated" is crowdmon's spelling; this package uses cotdata's."""
    with pytest.raises(ValueError, match=r"disagg.*tff"):
        categories.categories_for("disaggregated")


def test_swap_double_underscore_resolves_both_spellings():
    """CFTC writes Swap_Positions_Long_All but Swap__Positions_Short_All."""
    df = _frame(categories.REPORT_DISAGG)
    swap = next(s for s in categories.categories_for(categories.REPORT_DISAGG)
                if s.key == "swap")

    doubled = categories.build_category_frame(df, categories.REPORT_DISAGG, 12)
    single = df.rename(columns={swap.short_col: swap.short_col.replace("__", "_"),
                                swap.spread_col: swap.spread_col.replace("__", "_")})
    single = categories.build_category_frame(single, categories.REPORT_DISAGG, 12)

    col = categories.net_col(swap)
    pd.testing.assert_series_equal(doubled[col], single[col])
    assert doubled[col].notna().all()


def test_missing_category_column_is_skipped_not_raised():
    """A missing leg drops its category, it does not take the other four down.

    This pins the deliberate inversion of cotdata's raise-on-missing contract: this
    is a read path feeding a chart, so a missing category is a missing panel.
    """
    df = _frame(categories.REPORT_TFF).drop(columns=["Dealer_Positions_Long_All"])
    out = categories.build_category_frame(df, categories.REPORT_TFF, 12)

    present = {s.key for s in categories.present_categories(out, categories.REPORT_TFF)}
    assert "dealer" not in present
    assert present == {"asset_manager", "leveraged", "other_reportable", "nonreportable"}
    assert not any(c.startswith("Dealer") for c in out.columns)


def test_trader_counts_coerced_from_padded_strings():
    df = _frame(categories.REPORT_DISAGG, n=3)
    mm = next(s for s in categories.categories_for(categories.REPORT_DISAGG)
              if s.key == "managed_money")
    df[mm.traders_long_col] = ["     60", "   .", None]

    out = categories.build_category_frame(df, categories.REPORT_DISAGG, 2)
    got = out[categories.traders_long_col(mm)]

    assert got.iloc[0] == 60.0
    assert pd.isna(got.iloc[1])
    assert pd.isna(got.iloc[2])


def test_net_and_pct_oi_arithmetic():
    dates = pd.date_range("2020-01-07", periods=2, freq="7D")
    mm = next(s for s in categories.categories_for(categories.REPORT_DISAGG)
              if s.key == "managed_money")
    df = pd.DataFrame({
        const.OPEN_INTEREST_XLS: [100_000, 0],
        mm.long_col: [30_000, 10],
        mm.short_col: [10_000, 10],
    }, index=dates)

    out = categories.build_category_frame(df, categories.REPORT_DISAGG, 1)

    assert out[categories.net_col(mm)].tolist() == [20_000, 0]
    # 20,000 / 100,000 = 20%. The +1e-9 denominator guard keeps a zero-OI week from
    # raising; it lands on 0.0 rather than inf because the numerator is zero too.
    assert out[categories.pct_oi_col(mm)].iloc[0] == pytest.approx(20.0)
    assert np.isfinite(out[categories.pct_oi_col(mm)].iloc[1])


def test_index_window_matches_legacy_convention():
    """"52-week lookback" must mean the same thing here as on the legacy pages.

    process_lookback slices [idx - lb : idx + 1], inclusive of the current row, so
    its window spans lb + 1 observations. Two known residual differences from
    calculate_cot_index, neither of which matters for a chart: it rounds to whole
    points and this does not, and it returns 0 on a flat window where this is NaN.
    """
    lb = 12
    df = _frame(categories.REPORT_TFF, n=40, seed=7)
    out = categories.build_category_frame(df, categories.REPORT_TFF, lb)
    lev = next(s for s in categories.categories_for(categories.REPORT_TFF)
               if s.key == "leveraged")

    net = (df[lev.long_col] - df[lev.short_col]).reset_index(drop=True)
    got = out[categories.index_col(lev, " 12")].reset_index(drop=True)

    for i in (lb, lb + 5, len(df) - 1):
        expected = indicators.calculate_cot_index(net, i - lb, i)
        assert got.iloc[i] == pytest.approx(expected, abs=0.5), i


def test_index_is_nan_before_lookback_history():
    lb = 12
    out = categories.build_category_frame(
        _frame(categories.REPORT_TFF, n=40), categories.REPORT_TFF, lb)
    lev = next(s for s in categories.categories_for(categories.REPORT_TFF)
               if s.key == "leveraged")
    col = out[categories.index_col(lev, " 12")]

    assert col.iloc[:lb].isna().all()
    assert col.iloc[lb:].notna().all()


def test_spreadless_categories_have_no_spread_column():
    """Hedgers and the sub-threshold residual have no spreading leg to report."""
    disagg = categories.build_category_frame(
        _frame(categories.REPORT_DISAGG), categories.REPORT_DISAGG, 12)
    tff = categories.build_category_frame(
        _frame(categories.REPORT_TFF), categories.REPORT_TFF, 12)

    def spread_keys(frame, report):
        return {s.key for s in categories.categories_for(report)
                if categories.spread_col(s) in frame.columns}

    assert spread_keys(disagg, categories.REPORT_DISAGG) == {
        "swap", "managed_money", "other_reportable"}
    assert spread_keys(tff, categories.REPORT_TFF) == {
        "dealer", "asset_manager", "leveraged", "other_reportable"}


def test_lookback_header_lands_in_column_names_and_attrs():
    out = categories.build_category_frame(
        _frame(categories.REPORT_DISAGG), categories.REPORT_DISAGG, 52,
        lookback_header=" Custom")
    mm = next(s for s in categories.categories_for(categories.REPORT_DISAGG)
              if s.key == "managed_money")

    assert categories.index_col(mm, " Custom") in out.columns
    assert out.attrs["report"] == categories.REPORT_DISAGG
    assert out.attrs["lookback_weeks"] == 52
    assert out.attrs["lookback_header"] == " Custom"


def test_frame_can_be_merged_on_the_report_date_column():
    """The report date must be a column only, never also the index name.

    get_cot names its DatetimeIndex Report_Date_as_MM_DD_YYYY, and the same label has
    to travel as a column so callers can merge prices onto it. Carrying both makes
    every downstream merge raise "is both an index level and a column label", which is
    exactly what the price join in get_category_data does.
    """
    df = _frame(categories.REPORT_DISAGG, n=6)
    df.index.name = const.REPORT_DATE_XLS
    out = categories.build_category_frame(df, categories.REPORT_DISAGG, 2)

    assert out.index.name is None
    assert const.REPORT_DATE_XLS in out.columns

    prices = pd.DataFrame({
        const.REPORT_DATE_XLS: out[const.REPORT_DATE_XLS],
        const.CLOSING_PRICE: range(len(out)),
    })
    merged = out.merge(prices, on=const.REPORT_DATE_XLS, how="left")
    assert merged[const.CLOSING_PRICE].notna().all()


def test_empty_input_returns_empty_frame():
    assert categories.build_category_frame(
        pd.DataFrame(), categories.REPORT_DISAGG, 12).empty
    assert categories.build_category_frame(
        None, categories.REPORT_TFF, 12).empty


def test_has_report_code_matches_symbol_prefixed_stems(tmp_path):
    """Store files are {SYMBOL}_{code}.parquet, so a bare-stem set matches nothing.

    Both callers of this probe are cache-staleness guards, so for as long as it
    returned False for everything, neither guard could fire.
    """
    from cotmetrics.CotIndexer import CotIndexer

    (tmp_path / "GC_088691.parquet").touch()
    (tmp_path / "CL_067651.parquet").touch()

    probe = CotIndexer.__new__(CotIndexer)
    assert probe._has_report_code("088691", "_probe_set", lambda: tmp_path)
    assert probe._has_report_code("67651", "_probe_set", lambda: tmp_path)  # zfill
    assert not probe._has_report_code("999999", "_probe_set", lambda: tmp_path)


def test_cache_schema_guards_key_on_persisted_columns():
    """The MM/LEV cache guards must name a column the cache writer actually writes.

    MM_LONG_PSIZE_IDX and its LEV twin are produced by append_trading_signals at read
    time and never land in the per-symbol parquet, so a guard keyed on them fails,
    forces a full rebuild, and then fails again on the rebuilt cache: an unbounded
    rebuild loop, one per request. It stayed hidden only because the probe feeding the
    first guard matched nothing. The raw merged positions are what _attach_disagg_mm
    persists, so they are what "predates the merge" looks like on disk.
    """
    import inspect
    import io
    import tokenize

    from cotmetrics.CotIndexer import CotIndexer

    def code_only(fn):
        """Source with comments and docstrings dropped.

        The prose right above each guard names the wrong constant on purpose, to say
        why it is wrong, so a plain substring search over the source would match its
        own explanation.
        """
        src = inspect.getsource(fn)
        kept = []
        prev = tokenize.INDENT
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and prev in (
                    tokenize.INDENT, tokenize.NEWLINE, tokenize.NL):
                continue
            kept.append(tok.string)
            if tok.type not in (tokenize.NL, tokenize.COMMENT):
                prev = tok.type
        return " ".join(kept)

    for fn in (CotIndexer.try_load_from_cache,
               CotIndexer.retrieve_report_date_closing_prices):
        src = code_only(fn)
        assert "MM_LONG_PSIZE_IDX" not in src, fn.__name__
        assert "LEV_LONG_PSIZE_IDX" not in src, fn.__name__
        assert "MM_LONG_POS_XLS" in src, fn.__name__
        assert "LEV_LONG_POS_XLS" in src, fn.__name__


def test_cache_marker_watches_both_upstream_stores(tmp_path, monkeypatch):
    """ADR-0007 split the upstream: COT stays in cotdata, bars moved to marketdata.

    The cache-busting marker was written for a PRICE schema bump — reconstructed
    volume being promoted — and prices are no longer in cotdata. Watching cotdata
    alone would leave uncovered the exact case the guard exists for, and the failure
    is silent: stale cached metrics computed off a superseded bar schema, with no
    error anywhere.

    The two versions are kept as separate keys on purpose. Collapsing them into one
    number (a max, say) would hide a bump in whichever store sits lower.
    """
    import cotmetrics.constants as const
    from cotmetrics.CotIndexer import CotIndexer

    # Both roots must be set for either version to be readable: each store raises on
    # an unset root rather than defaulting to somewhere nobody looks.
    monkeypatch.setenv("COTDATA_STORE", str(tmp_path / "cot"))
    monkeypatch.setenv("MARKETDATA_STORE", str(tmp_path / "bars"))
    import marketdata.store as md_store
    md_store.stamp_flags()          # give the bar store a manifest to report

    monkeypatch.setattr(const, "CACHE_DIR", str(tmp_path / "cache"))
    CotIndexer._stamp_cache_schema()

    marker = CotIndexer._read_cache_marker()
    assert "schema_version" in marker, "cotdata's store version is not recorded"
    assert "marketdata_schema_version" in marker, (
        "marketdata's store version is not recorded, so a bar schema bump would "
        "not bust the caches computed from it")
    assert CotIndexer._read_cache_marketdata_schema() >= 1


def test_a_marker_predating_the_split_busts_once(tmp_path, monkeypatch):
    """Backward compatibility, and the right kind of it. A marker written before the
    split records no marketdata version; that reads as 0, which is below any real
    store and therefore forces exactly one rebuild. Correct rather than merely
    tolerated — the price source moved underneath those caches."""
    import json

    import cotmetrics.constants as const
    from cotmetrics.CotIndexer import CotIndexer

    monkeypatch.setattr(const, "CACHE_DIR", str(tmp_path))
    with open(CotIndexer._cache_schema_marker_path(), "w") as f:
        json.dump({"metrics_version": const.METRICS_CACHE_VERSION,
                   "schema_version": 99}, f)      # old marker: cotdata only

    assert CotIndexer._read_cache_schema() == 99
    assert CotIndexer._read_cache_marketdata_schema() == 0
