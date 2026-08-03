"""Per-category positioning for the CFTC Disaggregated and TFF reports.

The Legacy report pools actors that behave differently: its "Commercial" leg is
Producer/Merchant plus Swap Dealers, and its "Non-Commercial" leg is Managed Money
plus Other Reportable. The Disaggregated report (physical commodities) and the TFF
report (financials) split those out. This module turns one wide CFTC frame into a
per-category frame carrying net position, percent of open interest, the raw
long/short/spreading legs, trader counts, and the same index / z-score / momentum
indicators the legacy path computes.

Deliberately pure: no store access, no config read, no indexer import. Everything
here runs against a hand-built DataFrame, which is what makes it testable under the
empty store CI uses.

Naming: this module spells the report types "disagg" and "tff", which is what
`cotdata.get_cot(report=...)` accepts, so one vocabulary spans the whole call with
no translation table in the middle. `crowdmon` spells the first one "disaggregated"
because it reads the long-form canonical vintage schema through
`cotdata.vintage_ingest` instead, and no seam joins the two packages. Do not
"reconcile" them; you would only be adding a mapping that has to stay correct.
"""

from dataclasses import dataclass

import pandas as pd

import cotmetrics.constants as const
import cotmetrics.indicators as indicators

REPORT_DISAGG = "disagg"
REPORT_TFF = "tff"
REPORT_CHOICES = (REPORT_DISAGG, REPORT_TFF)

# Display names for the report itself, so the UI never spells these either.
REPORT_LABELS = {
    REPORT_DISAGG: "Disaggregated",
    REPORT_TFF: "Traders in Financial Futures",
}


@dataclass(frozen=True)
class CategorySpec:
    """One trader category: how to find it in the CFTC frame, what to call it.

    `key` is the stable identifier and matches cotdata's canonical vintage
    vocabulary byte for byte (`vintage_ingest._DISAGG_CATEGORIES` /
    `_TFF_CATEGORIES`), so a key here and a `category` value in the long-form
    vintage store mean the same thing. `prefix` is what derived column names are
    built from, and `label` is what a human reads.
    """

    key: str
    label: str
    prefix: str
    long_col: str
    short_col: str
    spread_col: str = None
    traders_long_col: str = None
    traders_short_col: str = None


# Column literals below are duplicated from cotdata's `vintage_ingest`, not imported
# from it: those are a peer package's private names, shaped for the long-form schema,
# and they carry no display labels or column prefixes. The duplication is pinned by
# `test_category_specs_match_cotdata_vintage`, which is a drift alarm rather than an
# API contract.
#
# Two omissions that look like oversights and are not:
#   * `Tot_Rept_*` is excluded on purpose. It is a roll-up of the reportable
#     categories already listed, so charting it alongside them double-counts.
#   * The `_Old` / `_Other` crop-year families are ignored, which is most of why the
#     Disaggregated frame has 190 columns to TFF's 86. Only the `_All` combined
#     figures surface here.
_DISAGG_SPECS = (
    CategorySpec(
        key="producer_merchant",
        label="Producer/Merchant",
        prefix="Prod Merc",
        long_col="Prod_Merc_Positions_Long_All",
        short_col="Prod_Merc_Positions_Short_All",
        # No spreading leg: a hedger with an offsetting position is reported net.
        traders_long_col="Traders_Prod_Merc_Long_All",
        traders_short_col="Traders_Prod_Merc_Short_All",
    ),
    CategorySpec(
        key="swap",
        label="Swap Dealers",
        prefix="Swap",
        # CFTC's own header typo: the long leg has one underscore after "Swap" and
        # the short and spread legs have two. `_resolve` tolerates either spelling
        # so a future correction upstream does not break this.
        long_col="Swap_Positions_Long_All",
        short_col="Swap__Positions_Short_All",
        spread_col="Swap__Positions_Spread_All",
        traders_long_col="Traders_Swap_Long_All",
        traders_short_col="Traders_Swap_Short_All",
    ),
    CategorySpec(
        key="managed_money",
        label="Managed Money",
        prefix="Managed Money",
        long_col="M_Money_Positions_Long_All",
        short_col="M_Money_Positions_Short_All",
        spread_col="M_Money_Positions_Spread_All",
        traders_long_col="Traders_M_Money_Long_All",
        traders_short_col="Traders_M_Money_Short_All",
    ),
    CategorySpec(
        key="other_reportable",
        label="Other Reportable",
        prefix="Other Rept",
        long_col="Other_Rept_Positions_Long_All",
        short_col="Other_Rept_Positions_Short_All",
        spread_col="Other_Rept_Positions_Spread_All",
        traders_long_col="Traders_Other_Rept_Long_All",
        traders_short_col="Traders_Other_Rept_Short_All",
    ),
    CategorySpec(
        key="nonreportable",
        label="Non-Reportable",
        prefix="Non Rept",
        long_col="NonRept_Positions_Long_All",
        short_col="NonRept_Positions_Short_All",
        # No spreading leg and no trader counts: below the reporting threshold, so
        # the CFTC publishes only the residual.
    ),
)

_TFF_SPECS = (
    CategorySpec(
        key="dealer",
        label="Dealer/Intermediary",
        prefix="Dealer",
        long_col="Dealer_Positions_Long_All",
        short_col="Dealer_Positions_Short_All",
        spread_col="Dealer_Positions_Spread_All",
        traders_long_col="Traders_Dealer_Long_All",
        traders_short_col="Traders_Dealer_Short_All",
    ),
    CategorySpec(
        key="asset_manager",
        label="Asset Manager",
        prefix="Asset Mgr",
        long_col="Asset_Mgr_Positions_Long_All",
        short_col="Asset_Mgr_Positions_Short_All",
        spread_col="Asset_Mgr_Positions_Spread_All",
        traders_long_col="Traders_Asset_Mgr_Long_All",
        traders_short_col="Traders_Asset_Mgr_Short_All",
    ),
    CategorySpec(
        key="leveraged",
        label="Leveraged Funds",
        prefix="Lev Money",
        long_col="Lev_Money_Positions_Long_All",
        short_col="Lev_Money_Positions_Short_All",
        spread_col="Lev_Money_Positions_Spread_All",
        traders_long_col="Traders_Lev_Money_Long_All",
        traders_short_col="Traders_Lev_Money_Short_All",
    ),
    CategorySpec(
        key="other_reportable",
        label="Other Reportable",
        prefix="Other Rept",
        long_col="Other_Rept_Positions_Long_All",
        short_col="Other_Rept_Positions_Short_All",
        spread_col="Other_Rept_Positions_Spread_All",
        traders_long_col="Traders_Other_Rept_Long_All",
        traders_short_col="Traders_Other_Rept_Short_All",
    ),
    CategorySpec(
        key="nonreportable",
        label="Non-Reportable",
        prefix="Non Rept",
        long_col="NonRept_Positions_Long_All",
        short_col="NonRept_Positions_Short_All",
    ),
)

CATEGORIES = {
    REPORT_DISAGG: _DISAGG_SPECS,
    REPORT_TFF: _TFF_SPECS,
}


def categories_for(report):
    """Ordered category specs for a report type.

    Raises ValueError naming REPORT_CHOICES on anything else, rather than returning
    an empty tuple: a typo'd report ("disaggregated", the crowdmon spelling) would
    otherwise render as a market with no categories, which looks like missing data.
    """
    try:
        return CATEGORIES[report]
    except KeyError:
        raise ValueError(
            f"unknown report {report!r}, expected one of {REPORT_CHOICES}"
        ) from None


# --- column-name builders -------------------------------------------------------
# The UI never spells a derived column itself; it asks for one of these.

def net_col(spec):
    return spec.prefix + const.NET_POS


def pct_oi_col(spec):
    return spec.prefix + const.PCT_OI


def long_col(spec):
    return spec.prefix + " Long"


def short_col(spec):
    return spec.prefix + " Short"


def spread_col(spec):
    return spec.prefix + " Spread"


def traders_long_col(spec):
    return spec.prefix + " Traders Long"


def traders_short_col(spec):
    return spec.prefix + " Traders Short"


def index_col(spec, lookback_header):
    return spec.prefix + lookback_header + const.IDX


def zscore_col(spec, lookback_header):
    return spec.prefix + lookback_header + const.ZSCORE


def momentum_col(spec, lookback_header):
    return spec.prefix + lookback_header + const.MOMENTUM


# --- frame construction ---------------------------------------------------------

def _resolve(df, name):
    """Look a column up tolerating CFTC's single/double-underscore inconsistency.

    Returns None when the column is absent, where cotdata's ingest-side twin
    (`vintage_ingest._series`) raises. The asymmetry is deliberate: cotdata is
    writing observations, where a silent null decays into fake revision history.
    This is a read path feeding a chart, where the honest answer to a missing
    category is a missing panel, not a crash that takes the other four with it.
    """
    if name is None or df is None:
        return None
    if name in df.columns:
        return df[name]
    for alt in (name.replace("__", "_"), name.replace("_Positions", "__Positions")):
        if alt != name and alt in df.columns:
            return df[alt]
    return None


def _numeric(series):
    """Coerce a CFTC column to float, tolerating whitespace-padded strings.

    Applied to every column, not only trader counts. Trader counts are the ones
    that arrive as objects today ("     72", and "." where the count is suppressed)
    because the CFTC writes a dot for suppression and cotdata's providers cast
    object columns to str wholesale. Position columns happen to be int64 right now,
    but the same wholesale cast means one suppressed value upstream would turn a
    position column into strings and silently poison the arithmetic.
    """
    if series is None:
        return None
    if series.dtype == object:
        series = series.astype(str).str.strip()
    return pd.to_numeric(series, errors="coerce")


def build_category_frame(raw, report, lookback_weeks, lookback_header=None,
                         momentum_periods=None):
    """Per-category positioning and indicators from one wide CFTC frame.

    Args:
        raw: what `cotdata.get_cot(..., report=report)` returns, a wide frame in the
            CFTC image indexed by report date.
        report: REPORT_DISAGG or REPORT_TFF.
        lookback_weeks: index / z-score lookback in weekly reports.
        lookback_header: the column-name infix, e.g. " 52" or " Custom". Defaults to
            " <weeks>". Passed explicitly rather than derived so the caller cannot
            end up computing a different header than the one baked into the columns;
            the frame stamps its own under attrs["lookback_header"].
        momentum_periods: passed through to `calculate_momentum_index`; None uses
            const.MOMENTUM_PERIOD.

    Returns:
        pd.DataFrame indexed like `raw`, carrying const.REPORT_DATE_XLS,
        const.OPEN_INTEREST, and per present category the columns named by the
        builders above. A category whose long or short leg does not resolve is
        skipped entirely rather than filled with NaN, so a missing category shows up
        as a missing panel instead of a flat line at zero.

    The index window is `lookback_weeks + 1` observations, matching
    `CotIndexer.process_lookback`, which slices `[idx - lb : idx + 1]` inclusive of
    the current row. So "52-week lookback" means the same thing here as on every
    other page. Two residual differences from the legacy path, neither of which
    matters for a chart but both of which will otherwise get rediscovered as bugs:
    `calculate_cot_index` rounds to whole points and `calculate_range_index` does
    not, and the legacy version returns 0 on a flat window where this returns NaN.
    """
    specs = categories_for(report)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()

    if lookback_header is None:
        lookback_header = const.get_lookback_header_str(["", lookback_weeks])

    # Strip the index name. get_cot indexes by report date and names the index
    # REPORT_DATE_XLS, and the report date also has to travel as a column so callers
    # can merge on it the way _attach_disagg_mm does. Carrying both makes every
    # subsequent merge raise "is both an index level and a column label".
    out = pd.DataFrame(index=raw.index.rename(None))

    if const.REPORT_DATE_XLS in raw.columns:
        out[const.REPORT_DATE_XLS] = raw[const.REPORT_DATE_XLS].to_numpy()
    else:
        out[const.REPORT_DATE_XLS] = raw.index.to_numpy()

    open_interest = _numeric(_resolve(raw, const.OPEN_INTEREST_XLS))
    if open_interest is not None:
        out[const.OPEN_INTEREST] = open_interest

    for spec in specs:
        longs = _numeric(_resolve(raw, spec.long_col))
        shorts = _numeric(_resolve(raw, spec.short_col))
        if longs is None or shorts is None:
            continue

        net = longs - shorts
        out[long_col(spec)] = longs
        out[short_col(spec)] = shorts
        out[net_col(spec)] = net

        spread = _numeric(_resolve(raw, spec.spread_col))
        if spread is not None:
            out[spread_col(spec)] = spread

        if open_interest is not None:
            # Derived from long/short/OI rather than read from the CFTC's own
            # Pct_of_OI_* block: those are per-leg and rounded to one decimal, and
            # net percent of OI has to be derived anyway. One arithmetic path.
            out[pct_oi_col(spec)] = (net / (open_interest + 1e-9) * 100).round(2)

        traders_long = _numeric(_resolve(raw, spec.traders_long_col))
        if traders_long is not None:
            out[traders_long_col(spec)] = traders_long
        traders_short = _numeric(_resolve(raw, spec.traders_short_col))
        if traders_short is not None:
            out[traders_short_col(spec)] = traders_short

        window = lookback_weeks + 1
        idx = indicators.calculate_range_index(net, window=window, min_periods=window)
        out[index_col(spec, lookback_header)] = idx
        out[zscore_col(spec, lookback_header)] = indicators.calculate_z_score(
            net, lookback_weeks
        )
        out[momentum_col(spec, lookback_header)] = indicators.calculate_momentum_index(
            idx, momentum_periods
        )

    out.attrs["report"] = report
    out.attrs["lookback_weeks"] = lookback_weeks
    out.attrs["lookback_header"] = lookback_header
    return out


def present_categories(frame, report):
    """The specs `build_category_frame` actually produced columns for.

    Callers use this rather than `categories_for` when deciding what to draw, so a
    market missing a category renders four panels instead of five plus a KeyError.
    """
    if frame is None or frame.empty:
        return ()
    return tuple(s for s in categories_for(report) if net_col(s) in frame.columns)
