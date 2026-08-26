import os
from pathlib import Path

# Derived-cache location. As an installed package we can't anchor to a repo root,
# so honor COTMETRICS_CACHE (mirrors cotdata's COTDATA_STORE convention); default
# to a per-user cache dir. Kept self-contained (no cotmetrics imports) so importing
# constants never triggers the package __init__ re-export chain.
CACHE_DIR = os.environ.get(
    "COTMETRICS_CACHE", str(Path.home() / ".cache" / "cotmetrics")
)

# CIT PY research notes (dated .md/.txt: Citrindex, Top Allocations, TradingView
# watchlist) are hand-maintained artifacts copied in by a person, produced by an
# external tool and only read here — NOT a regenerable cache. They must not default
# under CACHE_DIR: ~/.cache is fair game for OS/cleanup purges, so durable notes there
# are silent data loss. Default to the XDG *data* dir instead, and point
# COTMETRICS_CITPY at the generating tool's own output directory. Do NOT point it
# inside $COTDATA_STORE: the store is a producer/consumer artifact that gets mirrored
# between machines, and no producer creates a citpy/, so a --delete sync removes it.
_DATA_HOME = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
CITPY_DIR = os.environ.get("COTMETRICS_CITPY", str(Path(_DATA_HOME) / "cotmetrics" / "citpy"))

# Visitor-log SQLite DB. Durable data, not a regenerable cache (the visit history
# cannot be rebuilt), so it follows the CITPY rule above: default under the XDG
# *data* dir, never CACHE_DIR (an OS purge would silently drop it) and never inside
# the installed package tree — resolving relative to __file__ wrote it to
# cotmetrics/data/cot_data.db, one shared file behind every venv/checkout pointing
# at this editable install. Honors COTMETRICS_DB.
DB_PATH = os.environ.get("COTMETRICS_DB", str(Path(_DATA_HOME) / "cotmetrics" / "cot_data.db"))

# Daily options max-pain snapshots. The THIRD thing to follow the CITPY rule above,
# and the one that most looks like a cache without being one: each run appends that
# day's live option chain to a permanent per-symbol history. yfinance serves only the
# CURRENT chain, so a deleted day cannot be refetched from anywhere — the history is
# accumulated, not derived, and `rm -rf` on it is unrecoverable data loss rather than
# a slow next request. It lived under CACHE_DIR/options until this constant existed,
# which is exactly the sort of path an operator (or a runbook, or an assistant
# debugging something unrelated) clears to force a rebuild. Honors COTMETRICS_OPTIONS.
OPTIONS_DIR = os.environ.get(
    "COTMETRICS_OPTIONS", str(Path(_DATA_HOME) / "cotmetrics" / "options")
)

# Derived-metrics cache version. The per-symbol cache guards key on *column
# presence*, and the cotdata schema marker only moves when the upstream store
# changes — so neither can see a value-only change in our own indicator logic
# (e.g. the Spearman fallback going 0.0 -> NaN). Bump this whenever a metrics
# change alters previously-cached values, and the parquet caches rebuild
# themselves instead of needing a manual `rm ~/.cache/cotmetrics/*.parquet`.
METRICS_CACHE_VERSION = 1

# Columns of COT data to consume
MARKET_NAME_XLS = "Market_and_Exchange_Names"
REPORT_DATE_XLS = "Report_Date_as_MM_DD_YYYY"
CONTRACT_CODE_XLS = "CFTC_Contract_Market_Code"
OPEN_INTEREST_XLS = "Open_Interest_All"
COMM_LONG_POS_XLS = "Comm_Positions_Long_All"
COMM_SHORT_POS_XLS = "Comm_Positions_Short_All"
LARGE_LONG_POS_XLS = "NonComm_Positions_Long_All"
LARGE_SHORT_POS_XLS = "NonComm_Positions_Short_All"
SMALL_LONG_POS_XLS = "NonRept_Positions_Long_All"
SMALL_SHORT_POS_XLS = "NonRept_Positions_Short_All"

COMM_LONG = "Comm Positions Long All"
COMM_SHORT = "Comm Positions Short All"
LARGE_LONG = "Lrg Positions Long All"
LARGE_SHORT = "Lrg Positions Short All"
SMALL_LONG = "Sml Positions Long All"
SMALL_SHORT = "Sml Positions Short All"

# Columns to create for consumed COT data
DATE = "Date"
SYMBOL = "Symbol"
NAME = "Name"
LOOKBACK = "Lookback"
ASSET_CLASS = "Asset Class"
OPEN_INTEREST = "Open Interest"

COMM = "Comm"
LARGE = "Lrg Spec"
SMALL = "Sml Spec"

NET_POS = " Net Pos"
IDX = " Idx"
EST = " Est"
PCT_OI = " Pct OI"
SPEARMAN = " Spearman"
NORMALIZED = " Norm"
ZSCORE = " Zscore"
MOMENTUM = " Move"

LB_CUSTOM = " Custom"
LB_26 = " 26"
LB_52 = " 52"
LB_3Y = " 3Y"

# Positioning basis: which net-position series the level metrics are built from.
# BASIS_RAW uses net contracts, BASIS_OI_NORM uses net / open interest. Every level
# metric (index, z-score, spearman, index momentum) already carries a NORMALIZED twin,
# so the basis just selects which of the two pairs get surfaced.
BASIS_RAW = "raw"
BASIS_OI_NORM = "oi_norm"
BASIS_CHOICES = (BASIS_RAW, BASIS_OI_NORM)

OPEN_INTEREST_CUSTOM_ZSCORE = OPEN_INTEREST + LB_CUSTOM + ZSCORE
OPEN_INTEREST_26_ZSCORE = OPEN_INTEREST + LB_26 + ZSCORE
OPEN_INTEREST_52_ZSCORE = OPEN_INTEREST + LB_52 + ZSCORE

COMM_NET = COMM + NET_POS
LARGE_NET = LARGE + NET_POS
SMALL_NET = SMALL + NET_POS
COMM_NET_CHANGE_PCT = COMM + NET_POS + " Change Pct"
COMM_NET_CHANGE_NORM = COMM + NET_POS + " Change Pct" + NORMALIZED
COMM_FLIP = COMM + " Flip"
LARGE_FLIP = LARGE + NET_POS + " Flip"
SMALL_FLIP = SMALL + NET_POS + " Flip"
LW_LRG_SENTIMENT = LARGE + " Sentiment"

COMM_MACD_LINE = COMM + " MACD Line"
COMM_MACD_SIGNAL = COMM + " MACD Signal"
COMM_MACD_HIST = COMM + " MACD Histogram"
COMM_MACD_BULL_CROSS = COMM + " MACD Bull Cross"
COMM_MACD_BEAR_CROSS = COMM + " MACD Bear Cross"

COMM_PCT_OI = COMM + PCT_OI
LARGE_PCT_OI = LARGE + PCT_OI
SMALL_PCT_OI = SMALL + PCT_OI

# Keenan Concentration (gross long/short as % of total OI) + its 52-wk range index.
# NOTE: on the Legacy store LARGE = NonCommercial (MM+OR) → this is Keenan's NC
# Concentration, a proxy for MM (see docs/spec_positioning_metrics_trio.md §2).
CONCENTRATION = " Concentration"
LARGE_LONG_CONC = LARGE + " Long" + CONCENTRATION
LARGE_SHORT_CONC = LARGE + " Short" + CONCENTRATION
LARGE_LONG_CONC_IDX = LARGE_LONG_CONC + LB_52 + IDX
LARGE_SHORT_CONC_IDX = LARGE_SHORT_CONC + LB_52 + IDX
# Commercial (PMPU proxy) Concentration — hedger conviction, not spec unwind risk.
COMM_LONG_CONC = COMM + " Long" + CONCENTRATION
COMM_SHORT_CONC = COMM + " Short" + CONCENTRATION
COMM_LONG_CONC_IDX = COMM_LONG_CONC + LB_52 + IDX
COMM_SHORT_CONC_IDX = COMM_SHORT_CONC + LB_52 + IDX

# TRUE Money-Manager (MM) Concentration — from the Disaggregated report (futures-only),
# merged in from the cotdata `disagg` store. This is the faithful speculative group
# (no OR dilution), only available for the ~24 physical-commodity markets; financials
# have no disaggregated report so these columns are absent/NaN there.
MM = "MM"
MM_LONG_POS_XLS = "M_Money_Positions_Long_All"      # disagg column names (already int64)
MM_SHORT_POS_XLS = "M_Money_Positions_Short_All"
MM_LONG_TRADERS_XLS = "Traders_M_Money_Long_All"    # whitespace-string trader counts
MM_SHORT_TRADERS_XLS = "Traders_M_Money_Short_All"
TOT_TRADERS_XLS = "Traders_Tot_All"
MM_LONG_CONC = MM + " Long" + CONCENTRATION
MM_SHORT_CONC = MM + " Short" + CONCENTRATION
MM_LONG_CONC_IDX = MM_LONG_CONC + LB_52 + IDX
MM_SHORT_CONC_IDX = MM_SHORT_CONC + LB_52 + IDX

# Clustering (herding) = # traders in group(dir) / total reportable traders.
# Position Size (conviction) = OI(dir) / # traders(dir). True MM only.
CLUSTERING = " Clustering"
POSITION_SIZE = " Position Size"
MM_LONG_CLUST = MM + " Long" + CLUSTERING
MM_SHORT_CLUST = MM + " Short" + CLUSTERING
MM_LONG_CLUST_IDX = MM_LONG_CLUST + LB_52 + IDX
MM_SHORT_CLUST_IDX = MM_SHORT_CLUST + LB_52 + IDX
MM_LONG_PSIZE = MM + " Long" + POSITION_SIZE
MM_SHORT_PSIZE = MM + " Short" + POSITION_SIZE
MM_LONG_PSIZE_IDX = MM_LONG_PSIZE + LB_52 + IDX
MM_SHORT_PSIZE_IDX = MM_SHORT_PSIZE + LB_52 + IDX

# True-MM decile OBOS — Money-Manager Concentration decile intersected with a price extreme.
OBOS_MM_OVERSOLD_DECILE = 'obos_mm_oversold_decile'          # Concentration only
OBOS_MM_OVERBOUGHT_DECILE = 'obos_mm_overbought_decile'
OBOS_MM_CLUST_OVERSOLD_DECILE = 'obos_mm_clust_oversold_decile'      # Clustering only
OBOS_MM_CLUST_OVERBOUGHT_DECILE = 'obos_mm_clust_overbought_decile'
OBOS_MM_PSIZE_OVERSOLD_DECILE = 'obos_mm_psize_oversold_decile'      # Position Size only
OBOS_MM_PSIZE_OVERBOUGHT_DECILE = 'obos_mm_psize_overbought_decile'
# Keenan's intersection — Concentration ∩ Clustering ∩ Position Size all at decile.
OBOS_MM_TRIPLE_OVERSOLD_DECILE = 'obos_mm_triple_oversold_decile'
OBOS_MM_TRIPLE_OVERBOUGHT_DECILE = 'obos_mm_triple_overbought_decile'

# TFF Leveraged Funds (LEV) — the speculative group for FINANCIAL futures, from the
# cotdata `tff` store (futures-only). The disjoint counterpart to MM: commodities get
# MM, financials get LEV, no market gets both. Independent OBOS test universe.
LEV = "LEV"
LEV_LONG_POS_XLS = "Lev_Money_Positions_Long_All"
LEV_SHORT_POS_XLS = "Lev_Money_Positions_Short_All"
LEV_LONG_TRADERS_XLS = "Traders_Lev_Money_Long_All"
LEV_SHORT_TRADERS_XLS = "Traders_Lev_Money_Short_All"
LEV_LONG_CONC = LEV + " Long" + CONCENTRATION
LEV_SHORT_CONC = LEV + " Short" + CONCENTRATION
LEV_LONG_CONC_IDX = LEV_LONG_CONC + LB_52 + IDX
LEV_SHORT_CONC_IDX = LEV_SHORT_CONC + LB_52 + IDX
LEV_LONG_CLUST = LEV + " Long" + CLUSTERING
LEV_SHORT_CLUST = LEV + " Short" + CLUSTERING
LEV_LONG_CLUST_IDX = LEV_LONG_CLUST + LB_52 + IDX
LEV_SHORT_CLUST_IDX = LEV_SHORT_CLUST + LB_52 + IDX
LEV_LONG_PSIZE = LEV + " Long" + POSITION_SIZE
LEV_SHORT_PSIZE = LEV + " Short" + POSITION_SIZE
LEV_LONG_PSIZE_IDX = LEV_LONG_PSIZE + LB_52 + IDX
LEV_SHORT_PSIZE_IDX = LEV_SHORT_PSIZE + LB_52 + IDX
OBOS_LEV_OVERSOLD_DECILE = 'obos_lev_oversold_decile'
OBOS_LEV_OVERBOUGHT_DECILE = 'obos_lev_overbought_decile'
OBOS_LEV_CLUST_OVERSOLD_DECILE = 'obos_lev_clust_oversold_decile'
OBOS_LEV_CLUST_OVERBOUGHT_DECILE = 'obos_lev_clust_overbought_decile'
OBOS_LEV_PSIZE_OVERSOLD_DECILE = 'obos_lev_psize_oversold_decile'
OBOS_LEV_PSIZE_OVERBOUGHT_DECILE = 'obos_lev_psize_overbought_decile'
OBOS_LEV_TRIPLE_OVERSOLD_DECILE = 'obos_lev_triple_oversold_decile'
OBOS_LEV_TRIPLE_OVERBOUGHT_DECILE = 'obos_lev_triple_overbought_decile'

COMM_CUSTOM_CORR = COMM + LB_CUSTOM + SPEARMAN
LARGE_CUSTOM_CORR = LARGE + LB_CUSTOM + SPEARMAN
SMALL_CUSTOM_CORR = SMALL + LB_CUSTOM + SPEARMAN
COMM_26_CORR = COMM + LB_26 + SPEARMAN
LARGE_26_CORR = LARGE + LB_26 + SPEARMAN
SMALL_26_CORR = SMALL + LB_26 + SPEARMAN
COMM_52_CORR = COMM + LB_52 + SPEARMAN
LARGE_52_CORR = LARGE + LB_52 + SPEARMAN
SMALL_52_CORR = SMALL + LB_52 + SPEARMAN

COMM_CUSTOM_NORM_CORR = COMM_CUSTOM_CORR + NORMALIZED
LARGE_CUSTOM_NORM_CORR = LARGE_CUSTOM_CORR + NORMALIZED
SMALL_CUSTOM_NORM_CORR = SMALL_CUSTOM_CORR + NORMALIZED
COMM_26_NORM_CORR = COMM_26_CORR + NORMALIZED
LARGE_26_NORM_CORR = LARGE_26_CORR + NORMALIZED
SMALL_26_NORM_CORR = SMALL_26_CORR + NORMALIZED
COMM_52_NORM_CORR = COMM_52_CORR + NORMALIZED
LARGE_52_NORM_CORR = LARGE_52_CORR + NORMALIZED
SMALL_52_NORM_CORR = SMALL_52_CORR + NORMALIZED

COMM_CUSTOM_IDX = COMM + LB_CUSTOM + IDX
LARGE_CUSTOM_IDX = LARGE + LB_CUSTOM + IDX
SMALL_CUSTOM_IDX = SMALL + LB_CUSTOM + IDX
COMM_26_IDX = COMM + LB_26 + IDX
LARGE_26_IDX = LARGE + LB_26 + IDX
SMALL_26_IDX = SMALL + LB_26 + IDX
COMM_52_IDX = COMM + LB_52 + IDX
LARGE_52_IDX = LARGE + LB_52 + IDX
SMALL_52_IDX = SMALL + LB_52 + IDX
COMM_3Y_IDX = COMM + LB_3Y + IDX

COMM_NET_NORM = COMM_NET + NORMALIZED
LARGE_NET_NORM = LARGE_NET + NORMALIZED
SMALL_NET_NORM = SMALL_NET + NORMALIZED
COMM_CUSTOM_IDX_NORM = COMM + LB_CUSTOM + IDX + NORMALIZED
LARGE_CUSTOM_IDX_NORM = LARGE + LB_CUSTOM + IDX + NORMALIZED
SMALL_CUSTOM_IDX_NORM = SMALL + LB_CUSTOM + IDX + NORMALIZED
COMM_26_IDX_NORM = COMM + LB_26 + IDX + NORMALIZED
LARGE_26_IDX_NORM = LARGE + LB_26 + IDX + NORMALIZED
SMALL_26_IDX_NORM = SMALL + LB_26 + IDX + NORMALIZED
COMM_52_IDX_NORM = COMM + LB_52 + IDX + NORMALIZED
LARGE_52_IDX_NORM = LARGE + LB_52 + IDX + NORMALIZED
SMALL_52_IDX_NORM = SMALL + LB_52 + IDX + NORMALIZED
COMM_3Y_IDX_NORM = COMM + LB_3Y + IDX + NORMALIZED

COMM_CUSTOM_ZSCORE = COMM + LB_CUSTOM + ZSCORE
LARGE_CUSTOM_ZSCORE = LARGE + LB_CUSTOM + ZSCORE
SMALL_CUSTOM_ZSCORE = SMALL + LB_CUSTOM + ZSCORE
COMM_26_ZSCORE = COMM + LB_26 + ZSCORE
LARGE_26_ZSCORE = LARGE + LB_26 + ZSCORE
SMALL_26_ZSCORE = SMALL + LB_26 + ZSCORE
COMM_52_ZSCORE = COMM + LB_52 + ZSCORE
LARGE_52_ZSCORE = LARGE + LB_52 + ZSCORE
SMALL_52_ZSCORE = SMALL + LB_52 + ZSCORE

COMM_CUSTOM_ZSCORE_NORM = COMM_CUSTOM_ZSCORE + NORMALIZED
LARGE_CUSTOM_ZSCORE_NORM = LARGE_CUSTOM_ZSCORE + NORMALIZED
SMALL_CUSTOM_ZSCORE_NORM = SMALL_CUSTOM_ZSCORE + NORMALIZED
COMM_26_ZSCORE_NORM = COMM_26_ZSCORE + NORMALIZED
LARGE_26_ZSCORE_NORM = LARGE_26_ZSCORE + NORMALIZED
SMALL_26_ZSCORE_NORM = SMALL_26_ZSCORE + NORMALIZED
COMM_52_ZSCORE_NORM = COMM_52_ZSCORE + NORMALIZED
LARGE_52_ZSCORE_NORM = LARGE_52_ZSCORE + NORMALIZED
SMALL_52_ZSCORE_NORM = SMALL_52_ZSCORE + NORMALIZED

COMM_MOMENTUM = "comm_momentum"
LRG_MOMENTUM = "lrg_momentum"
SML_MOMENTUM = "sml_momentum"
MOMENTUM_PERIOD = 6

# Week-over-week point change on the 0-100 index, distinct from the MOMENTUM_PERIOD
# family above. The two answer different questions: the 6-week change is a trend, this
# is "what moved at this release", which is what a weekly movers list ranks on.
WOW_PERIOD = 1
# Reports of closing price used to decide whether price is trending up. This is the
# directional context that turns rising open interest into accumulation or
# distribution, so both readers of that question have to use the same window.
# Distinct from calculate_price_hedging_divergence's velocity_window, which is also 3
# but measures a different thing.
PRICE_TREND_PERIOD = 3
WOW_MOVE = " WoW Move"
COMM_WOW = "comm_wow"
LRG_WOW = "lrg_wow"
SML_WOW = "sml_wow"
# Cache-guard probes: a parquet built before either family existed lacks the column, and
# get_symbols_data would KeyError on it. See try_load_from_cache. The normalized twin
# arrived later than the raw one, so both are checked -- a cache built in between has
# the first and not the second.
COMM_CUSTOM_WOW = COMM + LB_CUSTOM + WOW_MOVE
COMM_CUSTOM_WOW_NORM = COMM_CUSTOM_WOW + NORMALIZED

OPEN_PRICE = "Open Price"
HIGH_PRICE = "High Price"
LOW_PRICE = "Low Price"
CLOSING_PRICE = "Closing Price"
PRICE_CHANGE = "Price Change Pct"

WILLCO = "WILLCO"
WILLCO_CUSTOM = WILLCO + LB_CUSTOM
WILLCO_26 = WILLCO + LB_26
WILLCO_52 = WILLCO + LB_52

LIQUIDITY_STRAIN = "Liquidity Strain"
LIQUIDITY_STRAIN_CUSTOM = LIQUIDITY_STRAIN + ZSCORE + LB_CUSTOM
LIQUIDITY_STRAIN_26 = LIQUIDITY_STRAIN + ZSCORE + LB_26
LIQUIDITY_STRAIN_52 = LIQUIDITY_STRAIN + ZSCORE + LB_52

PRICE_HEDGING_DIV = "Price Hedging Divergence"
PRICE_HEDGING_DIV_CUSTOM = PRICE_HEDGING_DIV + ZSCORE + LB_CUSTOM
PRICE_HEDGING_DIV_26 = PRICE_HEDGING_DIV + ZSCORE + LB_26
PRICE_HEDGING_DIV_52 = PRICE_HEDGING_DIV + ZSCORE + LB_52

# ---------------------------------------------------------------------------
# Generic alias columns
#
# The output contract of CotIndexer.get_symbols_data. Everything above this block
# names a *source* column, which carries its lookback and basis in the name
# ("Comm 26 Index Norm"). An alias is the one the caller already resolved for
# lookback and basis, so a consumer reads "comms_idx" and gets whichever family
# the requested basis selected. Every alias moves together; see get_symbols_data.
#
# These appeared as bare string literals 238 times across three repos, which is the
# surface a typo had to survive. They are constants for the same reason the signal
# names below are.
COMMS_IDX = "comms_idx"
LRG_IDX = "lrg_idx"
SML_IDX = "sml_idx"

COMMS_ZSCORE = "comms_zscore"
LRG_ZSCORE = "lrg_zscore"
SML_ZSCORE = "sml_zscore"

COMMS_SPEARMAN = "comms_spearman"
LRG_SPEARMAN = "lrg_spearman"
SML_SPEARMAN = "sml_spearman"

# Not WILLCO: that one is the source-column prefix ("WILLCO" + " 26"), and this is
# the lookback-resolved alias built from it. Same reason MOMENTUM (" Move") and
# COMM_MOMENTUM ("comm_momentum") are separate names.
WILLCO_ALIAS = "willco"
OI_ZSCORE = "oi_zscore"

# Retired from the UI in cot-analyzer #45, still computed and still on the frame.
LSR = "lsr"
PHD = "phd"

# The rest of the contract is defined where its source family is, because the name
# is derived there: COMM_MOMENTUM / LRG_MOMENTUM / SML_MOMENTUM, COMM_WOW / LRG_WOW
# / SML_WOW, POS_IDX_SETUP_*, plus DATE and OPEN_INTEREST.
# ---------------------------------------------------------------------------

# Plotting Dimensions
PIXELS_PER_ROW = 250
FIXED_OVERHEAD = 25

app_timezone = "US/Eastern"

# Plot related
WILLCO_MIN_THRESHOLD = 20
WILLCO_MAX_THRESHOLD = 80

LW_LRG_SENTIMENT_MAX_THRESHOLD = 80
LW_LRG_SENTIMENT_MIN_THRESHOLD = 20

# Positioning-index extremes for the Signal Matrix. The raw and OI-normalized indices
# get different bands on purpose: dividing net by open interest strips out the secular
# growth in contract size, so the normalized series spends far less time pinned at the
# ends of its own range. Holding it to 95/5 would mean it almost never highlights.
# Both renderers (the Dash heatmap and the emailed HTML) read these, so the two stay
# in step instead of drifting apart as they did while each hardcoded its own copy.
INDEX_HIGH_THRESHOLD = 95
INDEX_LOW_THRESHOLD = 5
INDEX_NORM_HIGH_THRESHOLD = 80
INDEX_NORM_LOW_THRESHOLD = 20

# Signal Matrix colouring is driven by the *row's* setup state, not by each cell's own
# level, because a positioning index only means something in the company of the other
# legs. utils.is_setup requires all legs at once -- a bullish CLS setup is
# `comm >= 95 AND lrg <= 5 AND sml <= 5` -- so a cell scored on its own can look like a
# setup while the row is nowhere near one. Orange Juice at (96, 0, 100) is the standing
# example: Commercials and Large Specs are both through their gates, but Small Specs sit
# at the opposite extreme and block it outright.
#
# Three states, no gradation inside them. A setup is binary -- is_setup fires for New
# Zealand at (97, 3, 5) exactly as it does for the Canadian Dollar at (100, 0, 0):
#
#   SETUP_BULL / SETUP_BEAR            every leg through its gate  -> full wash
#   SETUP_NEAR_BULL / SETUP_NEAR_BEAR  Commercials close, one spec leg near its gate,
#                                      and no spec leg leaning against the setup (each
#                                      on its side of INDEX_NEUTRAL) -> tint
#   SETUP_NONE                                                     -> neutral
INDEX_NEUTRAL = 50

# How far short of a gate still counts as "close", matching the hardcoded +/-5 that
# is_setup has always used for its close_bullish / close_bearish variants.
SETUP_NEAR_WIDTH = 5

SETUP_NONE = ""
SETUP_BULL = "bull"
SETUP_BEAR = "bear"
SETUP_NEAR_BULL = "near_bull"
SETUP_NEAR_BEAR = "near_bear"

# How far back a setup-age walk will count. Bounds the WALK, not the market: the
# longest run either model has produced over the full history of all 42 markets is 51
# weeks, so this is roughly double the worst case and exists so a market pinned
# indefinitely cannot turn a card render into a full-history scan. A count that reaches
# it is returned as it, so a view displaying the number reads this value as "at least".
SETUP_AGE_CAP = 104

SETUP_FULL_STATES = (SETUP_BULL, SETUP_BEAR)
SETUP_NEAR_STATES = (SETUP_NEAR_BULL, SETUP_NEAR_BEAR)

# Carried on the Signal Matrix so both renderers style from one computation rather than
# each re-deriving the rules. Leading underscore: internal, never shown as a column.
SETUP_CLS_COL = "_setup_cls"
SETUP_NPF_COL = "_setup_npf"
IS_EQUITY_COL = "_is_equity"

ZSCORE_MIN_THRESHOLD = -2.0
ZSCORE_MAX_THRESHOLD = 2.0
# Second rung of the positioning z-score ladder. The signal cards read all three legs
# through the gate above as compression, and a weaker three-leg agreement here as the
# early form of the same thing.
ZSCORE_MODERATE_MIN_THRESHOLD = -1.0
ZSCORE_MODERATE_MAX_THRESHOLD = 1.0
# Deliberately not ZSCORE_MAX_THRESHOLD, and not a typo for it. The opposite-extremes
# skew in the tape synthesis already requires two legs pointing opposite ways, so it
# fires earlier than a single leg at its own extreme would.
ZSCORE_SKEW_THRESHOLD = 1.5

# Open interest z-score. Kept apart from the positioning z-score above because they are
# different series: retuning what counts as extreme positioning should not silently
# move what counts as extreme open interest.
OI_ZSCORE_MIN_THRESHOLD = -2.0
OI_ZSCORE_MAX_THRESHOLD = 2.0
OI_ZSCORE_ELEVATED_MIN_THRESHOLD = -1.0
OI_ZSCORE_ELEVATED_MAX_THRESHOLD = 1.0
# The OI Z cell highlight on the signal matrix, sitting between the two tiers above.
# Read by both renderers of that matrix, the Dash grid and the emailed HTML.
OI_ZSCORE_HIGHLIGHT_THRESHOLD = 1.5

# Speculator positioning extremes used by the tape synthesis pillars. The same numbers
# as the sentiment band below, but a different series, so changing one should not drag
# the other with it.
SPEC_IDX_EXTREME_MIN_THRESHOLD = 20
SPEC_IDX_EXTREME_MAX_THRESHOLD = 80

PHD_MIN_THRESHOLD = -1.0
PHD_MAX_THRESHOLD = 1.0

LSR_MIN_THRESHOLD = -1.0
LSR_MAX_THRESHOLD = 1.0

MOMENTUM_MIN_THRESHOLD = -40
MOMENTUM_MAX_THRESHOLD = 40

PIXELS_PER_PLOT = 300
PIXELS_OVERHEAD_PER_PLOT = 25

VERTICAL_SPACING = 0.1

DEFAULT_WEEKS_TO_VIEW = 156
MA_PRICE_TREND_WEEKS = 4

# Debug features for visualization
COMMS_ACCUMULATION = 'debug_comm_accumulation'
COMMS_NEW_ACCUMULATION = 'debug_comms_new_accumulation'
SHORT_COVERING = 'debug_short_covering'

# OBOS (Keenan Ch.8) — intersection of speculative Concentration extreme & price extreme.
# Oversold  = extreme SHORT spec concentration + price at structural bottom → buy.
# Overbought = extreme LONG  spec concentration + price at structural top    → sell.
OBOS_OVERSOLD = 'obos_oversold'
OBOS_OVERBOUGHT = 'obos_overbought'
# Positioning-leg threshold: top quartile of the 52-wk range (Keenan default 75).
OBOS_CONC_IDX_THRESHOLD = 75

# Decile variant — both legs at a genuine extreme (90/10) on their own 52-wk range.
# Tests whether selectivity rescues the edge the loose quartile version lacks.
OBOS_CONC_IDX_DECILE = 90
OBOS_PRICE_IDX_DECILE_HI = 90
OBOS_PRICE_IDX_DECILE_LO = 10
OBOS_OVERSOLD_DECILE = 'obos_oversold_decile'
OBOS_OVERBOUGHT_DECILE = 'obos_overbought_decile'

# Commercial (hedger) variant — smart-money CONVICTION, not spec unwind. Pairing is
# inverted vs the spec setup: extreme comm LONG concentration at a price low = bullish
# accumulation; extreme comm SHORT concentration at a price high = bearish distribution.
OBOS_COMM_OVERSOLD = 'obos_comm_oversold'
OBOS_COMM_OVERBOUGHT = 'obos_comm_overbought'
# Comm-decile — the fair test: apply the decile selectivity that worked on the
# spec side to the commercial-conviction pairing.
OBOS_COMM_OVERSOLD_DECILE = 'obos_comm_oversold_decile'
OBOS_COMM_OVERBOUGHT_DECILE = 'obos_comm_overbought_decile'

# Bullish / Bottoming Signals
BULLISH_BOTTOM = 'bullish_bottom'
STEALTH_BULLISH_BOTTOM = 'stealth_bullish_bottom'
SHORT_SQUEEZE = 'short_squeeze'
LW_MACRO_BULL_SETUP = 'lw_macro_bull_setup'
BULLISH_TREND_CONTINUING = 'bullish_trend_continuing'
MULTI_YR_BULL_EXTREME = 'multiyear_bull_extreme'

# Bearish / Topping Signals
BEARISH_TOP = 'bearish_top'
LW_MACRO_BEAR_SETUP = 'lw_macro_bear_setup'
MULTI_YR_BEAR_EXTREME = 'multiyear_bear_extreme'
BEARISH_TREND_CONTINUING = 'bearish_trend_continuing'

# Positioning Index Setup (COT-index extremes; see utils.is_setup / get_setup_highlighting)
POS_IDX_SETUP_LONG = 'pos_idx_setup_long'
POS_IDX_SETUP_SHORT = 'pos_idx_setup_short'
# "Near" variants: within 5 points of the extreme (is_setup close_bullish / close_bearish)
POS_IDX_SETUP_NEAR_LONG = 'pos_idx_setup_near_long'
POS_IDX_SETUP_NEAR_SHORT = 'pos_idx_setup_near_short'

# Liquidation / Exhaustion Signals
EXHAUSTION = 'exhaustion'
COMMS_CAPITULATION = 'comms_capitulation'
CAPITULATION = 'capitulation'

# Momentum Breakout / Breakdown Signals
SPEC_DRIVEN_BULL_BREAKOUT = 'spec_driven_bull_breakout'
SPEC_DRIVEN_BEAR_BREAKDOWN = 'spec_driven_bear_breakdown'

# Institutional Regime Shift Signals
COMMS_SPEARMAN_REGIME_SHIFT = "comms_spearman_regime_shift"

# Interaction Velocities (ML Features)
LRG_SPEC_MOMENTUM_DIVERGENCE = "lrg_spec_momentum_divergence"
OI_ACCELERATION = "oi_acceleration"
PRICE_VELOCITY_Z = "price_velocity_z"
BULL_REJECTION_SCORE = 'bull_rejection_score'
BEAR_REJECTION_SCORE = 'bear_rejection_score'
FLAG_BULL_CAPITULATION = 'flag_bull_capitulation'
FLAG_BEAR_CAPITULATION = 'flag_bear_capitulation'


def get_lookback_header_str(lookback):
    lb_name = lookback[0]
    lb_weeks = lookback[1]

    if lb_name == "Custom":
        return LB_CUSTOM

    return " " + str(lb_weeks)
