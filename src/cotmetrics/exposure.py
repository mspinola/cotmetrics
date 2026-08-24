"""Positioning in commensurable units: contracts, then USD notional, then USD risk.

Every other level metric in this package normalizes a market against ITSELF: the range
index against its own lookback window, the OI-norm basis against its own open interest.
Both answer "is this extreme for this market", and neither can be summed, because a
percentile has no units and an OI share weights a tiny market equally with ES.

This module answers the other question. It converts a net position into a unit that is
the same across markets, so a book-wide or complex-wide TOTAL is a real quantity rather
than a sum of incommensurable contracts.

    contracts                       comparable? no    summable? no
    x point value x price   = USD   comparable? no    summable? YES
    x sigma_daily           = USD   comparable? YES   summable? YES

The middle rung is worth stating plainly because it is the one that reads as an answer
and is not. Dollar notional makes ES dwarf orange juice permanently, because the ES
market is larger, not because anyone is crowded. Ranking markets by notional produces a
market-size ranking wearing a positioning label. It is the right unit for a SUM and the
wrong one for a COMPARISON.

The last rung is the one to compare on, and it MULTIPLIES by volatility rather than
dividing. A vol-targeting book sizes at ``target_vol / sigma``, so its notional is
inversely proportional to volatility, and ``notional x sigma`` is the quantity that
stays constant while such a book sits at its target. Its deviation is therefore what
says how much mechanical selling a volatility move must force. Dividing would describe
nothing anybody does.

**Neither rung is stationary through time, and no unit here makes it so.** Notional
carries the price level, and dollar risk carries it too (``price x percent vol`` is
dollar vol, which grows with price). A 20-year notional history is substantially a
history of the index level, and its most recent swings will always look the largest.
That is what `pct_rank` is for, and it is why `aggregate_exposure` returns it beside
every level rather than leaving it to the caller to remember.

**The multiplier is effective-dated, and the middle rung is where that bites.** A
contract is not a fixed quantity of anything: ICE halved the Russell multiplier on
2016-12-05 and converted each open lot into two, with no CFTC rename to mark it. Today's
`contract_specs` row cannot say so, so `point_values` answers only whether a market can
be priced and `point_value_series` answers what each WEEK is worth. Getting this wrong
is quiet in a way the price-series mix-up below is not: the number stays plausible, and
because `expanding_pct_rank` ranks each week against its own past, an under-scaled first
half makes the second half read as more extreme rather than merely smaller.

**The two factors come from two different price series, deliberately.** Notional needs
tradeable price LEVELS and takes only ``unadj``; volatility needs correct percentage
RETURNS and takes only ``propadj``. Neither substitutes for the other and both failures
are silent. See `sigma_series` for the measured cost of getting the second one wrong.

Prior art: this is the arithmetic of `crowdmon.futures.notional` / `.riskunits`, whose
package is deprecated (2026-08-07) and whose implementation no longer runs, because it
reads `cotdata.get_prices` and ADR-0007 deleted that. The reasoning and the measured
guards are ported here; the composite damage thesis is NOT, and is not to be reopened.

Where this lives: it is a joiner (COT x prices x contract specs), and cot-analyzer
computes no metrics of its own, so the arithmetic belongs here and the drawing belongs
there. This package already reads `marketdata` for prices and proxies, so no new seam
is crossed.
"""
import functools
from typing import NamedTuple

import numpy as np
import pandas as pd

import cotmetrics.constants as const

#: Notional wants tradeable price LEVELS. ``backadj`` is not a price level: additive
#: back-adjustment restates history on every roll and can drive the level through zero,
#: so a notional history built on it is fiction that looks plausible.
#:
#: This is not a hypothetical mis-selection. `marketdata.get_bars` DEFAULTS to
#: ``backadj`` for futures (``DOMAIN_TIERS["futures"][0]``), and the `Closing Price`
#: column already on every CotIndexer frame is that default. It is the obvious column to
#: reach for and it is the wrong one for this. Ask for the level explicitly.
LEVEL_ADJUSTMENT = "unadj"

#: Volatility wants correct percentage RETURNS, which only ratio adjustment preserves.
RISK_ADJUSTMENT = "propadj"

#: Trading days in the volatility window. One quarter: long enough that a single day
#: cannot dominate, short enough to still be moving when a vol regime changes, which is
#: the event this unit exists to anticipate.
DEFAULT_VOL_WINDOW = 63

#: Minimum observations before a window yields a number. Two thirds of the window. A
#: sigma from a handful of points is noise wearing a number's clothes, and it would feed
#: straight into a cross-market ranking.
DEFAULT_MIN_PERIODS = 42

#: For the reported annualised figure only. Nothing here consumes it; it exists because
#: humans read annualised vol and cannot read daily vol.
TRADING_DAYS = 252

#: Above this share of non-positive closes the series is the WRONG series rather than a
#: market that traded below zero. Measured across the store by crowdmon: ``propadj`` has
#: exactly one non-positive close anywhere (CL, 2020-04-20, 0.009% of its history),
#: while ``backadj`` runs 52.3% for soybeans and 41.2% for Class III Milk. One percent
#: sits in the empty space between a real settlement and a broken transformation.
MAX_NONPOSITIVE_RATE = 0.01

#: How stale a daily price or sigma may be when carried onto a weekly COT date. A COT
#: Tuesday with no bar within a week is a market that was not trading, not a market to
#: silently value at last month's price.
DEFAULT_MAX_STALENESS_DAYS = 5

#: What the dollars are measured against.
#:
#: NUMERAIRE_GOLD divides every figure by the gold price, so the series is in TROY
#: OUNCES rather than dollars. It measures positioning against HARD MONEY rather than
#: against a currency, which is Larry Williams' WillVal applied to a book, and gold is
#: the benchmark this stack already carries: daily, back to 1978, in the same store,
#: needing no new source.
#:
#: It is a benchmark and not a ruler. Gold is a second asset with its own trend, 6.6% a
#: year since 1978 at 19% volatility and a 63% fall between 1980 and 1999, so both ends
#: of the comparison move. This is deliberately NOT an inflation adjustment and nothing
#: here claims it is one: gold and consumer prices come apart for decades at a time, and
#: an inflation framing would invite reading a rise as real growth.
#:
#: A side effect worth knowing, since it is why the view is legible at all: measuring
#: against gold happens to flatten these series a great deal, as the ratio of the last
#: third's median absolute weekly figure to the first third's shows. That is a property
#: of gold's last twenty-five years rather than a guarantee.
#:
#:     Equities   4.2x in USD  ->  1.3x in gold
#:     Metals    30.6x in USD  ->  6.2x in gold
#:     Energies   2.8x in USD  ->  1.3x in gold
#:     Grains     4.3x in USD  ->  0.9x in gold
#:
#: Two things a reader has to know, both measured rather than assumed.
#:
#: Gold is not a stable ruler. It is an asset with its own 22x move since 1978, so a
#: change in the gold-denominated series can be gold moving rather than positioning.
#: That risk is real and turns out to be small week to week: the USD and gold series
#: disagree on the SIGN of a weekly change 1.7% of weeks on Equities, 2.5% on Grains and
#: 4.0% on Metals. Over years it is exactly the point, since removing gold's trend is
#: what the deflation is for.
#:
#: And gold measured in gold is circular, exactly and not approximately. GC's notional
#: divided by the gold price is `contracts x 100` to a difference of 0.0, because the
#: multiplier IS 100 troy ounces. That is not a defect: ounces of gold controlled is the
#: cleanest statement of a gold position there is. It does mean a Metals total in gold
#: terms carries one self-referential term, and anything reading it should know which.
NUMERAIRE_USD = "usd"
NUMERAIRE_GOLD = "gold"

#: The gold contract, whose unadjusted close is USD per troy ounce.
GOLD_SYMBOL = "GC"

NUMERAIRE_LABELS = {NUMERAIRE_USD: "USD", NUMERAIRE_GOLD: "oz gold"}


def numeraire_series(numeraire, dates,
                     max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS):
    """What to divide the dollars by, or None for dollars.

    Carried onto the weekly COT dates the same way a price is, last known value within
    the staleness bound, so a holiday Tuesday does not lose a week and a gap does not
    silently value one at last month's gold.
    """
    if numeraire == NUMERAIRE_USD or not len(dates):
        return None
    if numeraire != NUMERAIRE_GOLD:
        raise ExposureError(
            f"unknown numeraire {numeraire!r}, expected one of "
            f"{(NUMERAIRE_USD, NUMERAIRE_GOLD)}")
    price = _asof(price_levels(GOLD_SYMBOL), pd.DatetimeIndex(dates),
                  max_staleness_days)
    # A zero or negative gold price is not a market event, it is a broken read, and
    # dividing by it would produce an infinity that looks like a record position.
    return price.where(price > 0)


#: The legs, and what "spec" means here.
#:
#: In the Legacy report the three legs sum to zero, so the mirror of Commercial net is
#: Non-Commercial net PLUS Non-Reportable net. `LEG_SPEC` is that sum, computed as the
#: sum, not as the negation of Commercials: the two agree only where the report balances
#: exactly, and calling one the other hides which series was actually read.
LEG_COMM = "comm"
LEG_LARGE = "large"
LEG_SMALL = "small"
LEG_SPEC = "spec"

LEG_COLUMNS = {
    LEG_COMM: (const.COMM_NET,),
    LEG_LARGE: (const.LARGE_NET,),
    LEG_SMALL: (const.SMALL_NET,),
    LEG_SPEC: (const.LARGE_NET, const.SMALL_NET),
}

LEG_LABELS = {
    LEG_COMM: "Commercials",
    LEG_LARGE: "Large Speculators",
    LEG_SMALL: "Small Traders",
    LEG_SPEC: "Speculators (Large + Small)",
}


class ExposureError(RuntimeError):
    """The inputs would produce a number that is not the unit it claims to be."""


# ── contract specs ────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def point_values() -> dict:
    """Symbol -> USD per point, from marketdata's contract-specs table.

    cotdata's copy of this table is frozen forever (its `--metadata` writer and its
    public reader were both deleted with the price code), so marketdata's is the only
    one that is refreshed. See the workspace CLAUDE.md.

    A market absent from here has no notional, and that is the honest answer rather than
    a gap to paper over: MFS and MME are ICE MSCI futures priced off the EFA and EEM
    ETFs, and an ETF share is not a contract, so there is no multiplier that would make
    their contract count into dollars. `aggregate_exposure` names what it dropped.

    **This is the CURRENT multiplier, so it answers membership, not arithmetic.** Ask it
    whether a market can be priced at all; ask `point_value_series` what to multiply a
    given week by. The two differ wherever an exchange re-denominated a contract, and
    the difference is not small: ICE halved the Russell multiplier on 2016-12-05, so
    using this value for the whole history understates 59% of RTY's priced weeks by
    exactly 2x. See `point_value_series`.
    """
    from marketdata.store import read_metadata
    specs = read_metadata()
    if specs is None or specs.empty:
        raise ExposureError(
            "marketdata's contract-specs table is empty, so no contract count can be "
            "converted to dollars. Refresh it with `marketdata-update --metadata`.")
    pv = pd.to_numeric(specs["Point Value"], errors="coerce")
    return {str(sym): float(val)
            for sym, val in zip(specs["Symbol"], pv)
            if pd.notna(val) and val > 0}


def point_value_series(symbol: str, dates) -> pd.Series:
    """USD per point FOR EACH WEEK, which is not the same as USD per point.

    `point_values` reads `contract_specs`, which carries one row per symbol and no
    effective date. That is the right shape for "can this market be priced" and the
    wrong input for "what was this position worth in 2010", because an exchange can
    re-denominate a contract and the current table cannot say so.

    The live case is the Russell. ICE cut the multiplier from $100 to $50 per index
    point effective 2016-12-05 and converted each open lot into two, with no CFTC rename
    to mark it, so 740 of RTY's 1,247 priced weeks sit on the old contract. Multiplying
    them by today's $50 halves both notional and dollar risk. Worse than the level error,
    it compresses the first half of the history that `expanding_pct_rank` ranks the
    second half against, so every post-2016 reading comes out more extreme than it is.

    marketdata owns the regime table (`contract_regimes.yaml`, added in 0.2.0) because a
    contract's history is a property of the contract, not of this package, and because
    npf's cost model needs the same answer. Here we only ask it.

    Undeclared symbols keep the current value for every date, which is a positive claim
    and not a shrug: nothing established a re-denomination for them. Where a multiplier
    was never established at all, marketdata returns NaN and the dollars go with it,
    which is the outcome to want. A gap is visible on a chart; a guess is not.
    """
    index = pd.DatetimeIndex(pd.to_datetime(dates))
    current = point_values().get(symbol)

    try:
        import marketdata
        declared = not marketdata.read_contract_regimes(symbol).empty
    except (ImportError, AttributeError) as e:
        # A marketdata too old to carry regimes. Refuse rather than silently returning
        # the flat series: the whole point of this function is that the flat answer is
        # wrong for some markets, and a wrong number here is invisible downstream.
        raise ExposureError(
            f"effective-dated contract multipliers need marketdata >= 0.2.0 "
            f"(`marketdata.read_contract_regimes` is unavailable: {e}). Without it a "
            f"re-denominated contract, such as RTY before 2016-12-05, would be valued "
            f"at today's multiplier for its whole history.") from e

    if not declared:
        return pd.Series(current, index=index, dtype="float64")
    return marketdata.point_value_asof(symbol, index)


# ── the two price series ──────────────────────────────────────────────────────

@functools.lru_cache(maxsize=256)
def price_levels(symbol: str, adjustment: str = LEVEL_ADJUSTMENT) -> pd.Series:
    """Daily close as a tradeable LEVEL, for the notional factor.

    Refuses anything but ``unadj``. The refusal is the point: `marketdata.get_bars`
    defaults to ``backadj`` and returns it without complaint, so nothing but an explicit
    guard distinguishes a notional history from a plausible-looking fiction.
    """
    if adjustment != LEVEL_ADJUSTMENT:
        raise ExposureError(
            f"notional needs tradeable price levels, so adjustment must be "
            f"{LEVEL_ADJUSTMENT!r}, not {adjustment!r}. Additive back-adjustment "
            f"restates history on every roll and can drive the level through zero; "
            f"ratio adjustment preserves returns, not levels.")
    return _close(symbol, adjustment)


@functools.lru_cache(maxsize=256)
def sigma_series(symbol: str, *, adjustment: str = RISK_ADJUSTMENT,
                 window: int = DEFAULT_VOL_WINDOW,
                 min_periods: int = DEFAULT_MIN_PERIODS) -> pd.Series:
    """Rolling daily volatility of percentage returns, as a fraction.

    Refuses anything but ``propadj``, and the reason is measured rather than stylistic.
    Annualised vol from ``backadj`` percent returns against the real store, as recorded
    by crowdmon's riskunits module:

        ZS (soybeans)   4366.9%  vs  21.7%   201x
        ZN (10-year)    1183.1%  vs   6.5%   182x
        CL (crude)       676.1%  vs  63.4%    11x
        GC (gold)          8.8%  vs  18.9%   0.47x

    Gold is why this is a guard rather than a note. It never goes negative, so it
    survives every sanity check for a non-finite or absurd number, and its volatility is
    still wrong by a factor of two in the UNDERSTATING direction. A screen for
    implausible volatility clears it and flags nothing.

    ``unadj`` fails more quietly still: full-sample vol barely moves (GC 1.01x), because
    the contamination is a fabricated jump at each roll and is concentrated on a few
    dozen days. Any SHORT window spanning one is badly wrong, and this window is 63 days.
    """
    if adjustment != RISK_ADJUSTMENT:
        raise ExposureError(
            f"volatility needs correct percentage returns, so adjustment must be "
            f"{RISK_ADJUSTMENT!r}, not {adjustment!r}. Additive back-adjustment "
            f"inflates annualised vol by 201x for ZS and 182x for ZN, and UNDERSTATES "
            f"it by half for GC, which no plausibility screen would catch.")
    px = _close(symbol, adjustment)
    if px.empty:
        return px

    # Ratio adjustment scales by a positive factor, so it preserves the sign of the
    # underlying rather than imposing one, and WTI settled at -37.63 on 2020-04-20. A
    # few non-positive closes are a market event, where only the returns TOUCHING them
    # are undefined; many are a wrong series. The store separates the two cases by three
    # orders of magnitude with nothing in between.
    nonpos = px <= 0
    rate = float(nonpos.mean())
    if rate > MAX_NONPOSITIVE_RATE:
        raise ExposureError(
            f"{symbol}: {int(nonpos.sum())} of {len(px)} closes ({rate:.1%}) are "
            f"non-positive in an adjustment={adjustment!r} series, above the "
            f"{MAX_NONPOSITIVE_RATE:.0%} bound. Percentage returns are undefined across "
            f"a sign change, so this cannot yield a volatility. A rate this high is a "
            f"wrong series, not a market that traded below zero.")

    ret = px.pct_change().replace([np.inf, -np.inf], np.nan)
    # A return is undefined if EITHER endpoint is non-positive: from a negative base the
    # percentage is meaningless, and to a negative close it is a sign change. Masking
    # both leaves the window short by a day or two around the event rather than
    # discarding the market, and min_periods decides whether what remains is enough.
    masked = ret.where(~(nonpos | nonpos.shift(fill_value=False)))
    return masked.rolling(window, min_periods=min_periods).std()


def _close(symbol: str, adjustment: str) -> pd.Series:
    import marketdata
    bars = marketdata.get_bars(symbol, adjustment)
    if bars is None or bars.empty:
        return pd.Series(dtype="float64", name=symbol)
    px = pd.to_numeric(bars["Close"], errors="coerce").dropna()
    px.index = pd.to_datetime(px.index).tz_localize(None).astype("datetime64[ns]")
    return px.astype("float64").sort_index()


def _asof(daily: pd.Series, dates: pd.Index, max_staleness_days: int) -> pd.Series:
    """Carry a daily series onto weekly COT dates, last known value on or before.

    A plain reindex would drop every Tuesday that was a holiday. An unbounded fill would
    value a delisted market at whatever it last printed, forever, which is the failure
    this bound exists for.
    """
    if daily.empty:
        return pd.Series(np.nan, index=dates, dtype="float64")
    left = pd.DataFrame({"when": pd.to_datetime(dates)}).sort_values("when")
    right = pd.DataFrame({"when": daily.index, "value": daily.to_numpy()})
    merged = pd.merge_asof(
        left, right, on="when", direction="backward",
        tolerance=pd.Timedelta(days=max_staleness_days))
    return pd.Series(merged["value"].to_numpy(), index=left["when"].to_numpy())


# ── one market ────────────────────────────────────────────────────────────────

def _open_interest(frame) -> "pd.Series | None":
    """The weekly open-interest column, under whichever name this frame carries.

    `CotIndexer.get_symbols_data` writes `OPEN_INTEREST`, assigning it FROM the raw
    `OPEN_INTEREST_XLS`, so on an indexer-built frame the first name is the one that
    exists. The second is kept because callers inject frames, and because the indexer's
    own handling branches three ways on exactly this question, which is the evidence that
    the name is not guaranteed. Returning None rather than raising is deliberate: a market
    with no open interest has no share, exactly as a market with no multiplier has no
    dollar value, and taking the other 45 down with it would be the wrong trade.
    """
    for column in (const.OPEN_INTEREST, const.OPEN_INTEREST_XLS):
        if column in getattr(frame, "columns", ()):
            return frame[column]
    return None


def market_exposure(name: str, *, leg: str = LEG_COMM, lookback: str = "Custom",
                    window: int = DEFAULT_VOL_WINDOW,
                    min_periods: int = DEFAULT_MIN_PERIODS,
                    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
                    frame: pd.DataFrame = None,
                    symbol: str = None) -> pd.DataFrame:
    """One market's weekly positioning in contracts, USD notional and USD risk.

    Indexed by COT report date, because that is the date the position is AS OF. It is
    not the date the position was knowable: the CFTC publishes Tuesday's figures on the
    Friday. Anything plotting this against a daily price owes the reader that gap; this
    frame states the as-of date and takes no view on how a chart should shift it.

    `frame` and `symbol` are injectable so a caller that already holds the weekly frame
    does not pay for a second indexer read, and so this is testable without a store.
    """
    if leg not in LEG_COLUMNS:
        raise ExposureError(f"unknown leg {leg!r}, expected one of {tuple(LEG_COLUMNS)}")

    if frame is None or symbol is None:
        from cotmetrics.indexer import get_indexer
        indexer = get_indexer()
        instrument = indexer.get_instrument_from_name(name)
        if instrument is None:
            raise ExposureError(f"no instrument named {name!r}")
        symbol = symbol or instrument.symbol
        frame = indexer.get_symbols_data(name, lookback) if frame is None else frame

    columns = LEG_COLUMNS[leg]
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ExposureError(f"{symbol}: weekly frame has no {missing} column(s)")

    net = sum(pd.to_numeric(frame[c], errors="coerce") for c in columns)
    dates = pd.to_datetime(frame.index)
    out = pd.DataFrame({"net_contracts": net.to_numpy()}, index=dates)
    out.index.name = "Date"

    # Membership only. The per-week values come from `point_value_series` below.
    pv = point_values().get(symbol)
    if pv is None:
        # Not an error. A market with no multiplier has no dollar value, and saying so
        # in a column beats raising and taking the other 45 markets down with it.
        out["point_value"] = np.nan
        out["price"] = np.nan
        out["notional_usd"] = np.nan
        out["sigma_daily"] = np.nan
        out["risk_usd"] = np.nan
        return out

    # Elementwise, not a scalar multiply. `pv` above answered whether this market has a
    # multiplier at all; this answers what it was in each of these weeks.
    out["point_value"] = point_value_series(symbol, out.index).to_numpy()
    out["price"] = _asof(price_levels(symbol), out.index, max_staleness_days).to_numpy()
    out["notional_usd"] = out["net_contracts"] * out["point_value"] * out["price"]
    out["sigma_daily"] = _asof(
        sigma_series(symbol, window=window, min_periods=min_periods),
        out.index, max_staleness_days).to_numpy()
    # x sigma, not / sigma. See the module docstring: a vol targeter's notional is
    # inversely proportional to sigma, so the PRODUCT is what stays constant while it
    # sits at target, and its deviation is what says how much a vol move must force.
    out["risk_usd"] = out["notional_usd"] * out["sigma_daily"]

    # The MARKET's size in the same two units, which is what turns a position into a
    # share of it. Open interest is one side of the book, so `net / OI` is the standard
    # OI normalisation this package already computes per market elsewhere
    # (`COMM_PCT_OI` and friends), and these columns are that same idea carried into
    # dollars so it can be aggregated. See `aggregate_exposure` for why that matters:
    # summing shares is meaningless, summing the two sides and dividing is not.
    oi = _open_interest(frame)
    if oi is None:
        out["oi_notional_usd"] = np.nan
        out["oi_risk_usd"] = np.nan
    else:
        oi = pd.to_numeric(oi, errors="coerce").to_numpy()
        # Non-positive open interest is not a market with no positions, it is a bad row,
        # and it would divide into an infinite share that reads as a record crowding.
        oi = np.where(oi > 0, oi, np.nan)
        out["oi_notional_usd"] = oi * out["point_value"] * out["price"]
        out["oi_risk_usd"] = out["oi_notional_usd"] * out["sigma_daily"]
    return out


# ── many markets ──────────────────────────────────────────────────────────────

class AggregateExposure(NamedTuple):
    """A total, and everything a reader needs to know it is a total OF something.

    An aggregate is a claim about a set, so the set travels with it. Four of these five
    fields exist because a sum that quietly changed its constituents, or quietly stopped
    in 2026, looks exactly like one that did neither.
    """

    #: The weekly total: notional_usd, risk_usd, n_markets, sigma_weighted, the two
    #: share-of-open-interest columns, and the four expanding percentile columns.
    #:
    #: The share columns are the set's position over the set's own open interest, in
    #: matched units, so each is a true dimensionless share and NEITHER carries a `_usd`
    #: suffix or a numeraire caveat: a ratio of two quantities in the same unit is the
    #: same number in dollars and in ounces. They answer a different question from the
    #: dollar columns, "how much of this market does the set hold" rather than "how much
    #: money is at stake", and they fail to add information on Softs and Currencies. There is deliberately no contracts column; see
    #: `aggregate_exposure` for why the one unit that does not add across markets is
    #: absent from the frame whose whole job is adding. `sigma_weighted` is the one
    #: quantity here that is neither a sum nor a rank: it is the gross-notional-weighted
    #: mean of the members' daily volatility, and it is the second factor of `risk_usd`
    #: made visible, since `risk = notional x sigma` market by market.
    frame: pd.DataFrame
    #: name -> why it is not in the total at all.
    dropped: dict
    #: name -> (first priced date, last priced date), for every market that IS in it.
    coverage: dict
    #: "start" / "end" -> the market whose coverage sets that end of the total, present
    #: only where that market actually costs the total weeks the others could have
    #: filled. This is the field that catches a retired constituent truncating a live
    #: series, which is otherwise invisible: the total simply stops.
    bounded_by: dict
    #: Weeks inside the union that at least one included market could not price, and
    #: which are therefore absent from `frame`.
    weeks_lost: int
    #: What the dollar columns are actually denominated in. `frame` and `members` keep
    #: their `_usd` column names under either numeraire, because renaming them per call
    #: would make every downstream lookup conditional; this field is how a caller knows
    #: what the numbers mean and how to label an axis.
    numeraire: str = NUMERAIRE_USD
    #: name -> that market's own exposure frame, restricted to the weeks the total
    #: covers, so the members sum to `frame` exactly and column for column.
    #:
    #: Returned rather than discarded because a total conceals its own composition, and
    #: the concealment is not marginal. On the equity complex at the time of writing one
    #: market is 59.5% of the gross speculator total and another leans the other way, so
    #: "equity speculators are crowded long" is substantially "the S&P is". A reader
    #: cannot recover any of that from the sum.
    members: dict = {}


def aggregate_exposure(names, *, leg: str = LEG_COMM, lookback: str = "Custom",
                       window: int = DEFAULT_VOL_WINDOW,
                       min_periods: int = DEFAULT_MIN_PERIODS,
                       max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
                       min_rank_periods: int = 104,
                       rank_window: int = None,
                       numeraire: str = NUMERAIRE_USD,
                       frames: dict = None) -> AggregateExposure:
    """Sum a set of markets into one weekly series, and say what that cost.

    Only weeks where EVERY included market has a value are summed. A total that silently
    changes its constituents week to week is a different series each week, and the seam
    lands exactly where a market's history starts or stops, which is where a reader is
    most likely to read a level change as news.

    That rule is right and it is expensive, so `AggregateExposure` reports the bill. The
    live case at the time of writing: the US equity-index complex includes NKD, whose
    COT history ends 2026-03-03, so a strict total of six markets ends there too while
    the other five run to the current week. Nothing about the resulting chart would say
    so. `bounded_by["end"]` names NKD, and the caller can drop it and get its five
    months back, or keep it and say why the series stops.

    `pct_rank` is EXPANDING, not full-sample: each week is ranked against the history up
    to and including itself, so the series can be read at any past date without knowing
    the future. It is the answer to "is this a lot", which no level in this frame gives
    on its own, because both notional and dollar risk carry the price level and so drift
    upward over a long history whatever the positioning did.

    **The total carries no contracts column, only dollars.** Contracts do not add across
    markets, which is the entire reason this module converts to dollars: summing ES
    contracts and corn contracts produces a number in no unit at all. The dangerous
    place for such a number is exactly here, in the same frame beside two columns that
    ARE summable and named the same way, where it reads as a third quantity of the same
    kind and would be plotted as one. It was carried for several commits and nothing
    read it, so it is dropped rather than qualified. `net_contracts` stays on
    `market_exposure`, and so on every frame in `members`, which is where one market's
    contract count means something.
    """
    frames = frames or {}
    per_market, dropped = {}, {}
    for name in names:
        try:
            ex = market_exposure(name, leg=leg, lookback=lookback, window=window,
                                 min_periods=min_periods,
                                 max_staleness_days=max_staleness_days,
                                 **(frames.get(name) or {}))
        except ExposureError as e:
            dropped[name] = str(e)
            continue
        if ex["notional_usd"].notna().sum() == 0:
            dropped[name] = ("no contract multiplier, so its contracts cannot be "
                             "converted to dollars")
            continue
        per_market[name] = ex

    # Same columns AND the same ORDER as a populated frame. A caller that handles the
    # empty case first would otherwise be written against a second schema nothing tests.
    empty = pd.DataFrame(columns=["notional_usd", "risk_usd", "n_markets",
                                  "notional_oi_share", "risk_oi_share",
                                  "sigma_weighted", "notional_pct_rank",
                                  "risk_pct_rank", "notional_oi_share_pct_rank",
                                  "risk_oi_share_pct_rank"])
    if not per_market:
        return AggregateExposure(empty, dropped, {}, {}, 0, numeraire, {})

    def _stack(column):
        return pd.DataFrame({n: ex[column] for n, ex in per_market.items()})

    # The numeraire divides BEFORE anything is summed or ranked, so the total, its
    # percentile, its band and every member all speak the same units. Applying it later
    # would leave a percentile computed on a dollar series describing a gold one, which
    # is the kind of mismatch nothing on screen would reveal.
    #
    # Applied to the VALUE columns only. Contracts are contracts under any numeraire.
    divisor = numeraire_series(numeraire, _stack("notional_usd").index,
                               max_staleness_days)
    if divisor is not None:
        per_market = {
            name: ex.assign(**{c: ex[c] / divisor.reindex(ex.index)
                               # The open-interest columns are dollar quantities like
                               # the other two and are deflated with them. Not cosmetic:
                               # the share divides one by the other, so deflating only
                               # the numerator would leave the "share" carrying 1/gold
                               # and moving when the Gold switch moved. A test asserts
                               # the two numeraires give identical shares.
                               for c in ("notional_usd", "risk_usd",
                                         "oi_notional_usd", "oi_risk_usd")})
            for name, ex in per_market.items()
        }

    notional, risk = _stack("notional_usd"), _stack("risk_usd")
    oi_notional, oi_risk = _stack("oi_notional_usd"), _stack("oi_risk_usd")
    priced = notional.notna() & risk.notna()
    coverage = {n: (col[col].index.min(), col[col].index.max())
                for n, col in priced.items() if col.any()}

    complete = priced.all(axis=1)
    out = pd.DataFrame({
        "notional_usd": notional[complete].sum(axis=1),
        "risk_usd": risk[complete].sum(axis=1),
    })
    out["n_markets"] = len(per_market)

    # ── how much of the market this set holds ────────────────────────────────────────
    #
    # The SUMS are what get divided, never the shares. A mean of per-market shares
    # weights orange juice equally with ES and answers a different question; dividing
    # one sum by the other weights each market by its own size, which is the question a
    # complex-wide view asks. On ONE market the two coincide exactly, and more than
    # that, the whole dollar apparatus cancels: `net x pv x p / (OI x pv x p)` is
    # `net / OI`, the plain contract share this package already computes as
    # `COMM_PCT_OI`. That identity is asserted in the tests rather than assumed, and it
    # is the reason this is a defensible thing to put beside the dollar columns.
    #
    # The denominators are matched to their numerators, so both columns are true
    # dimensionless shares and both reduce to `net / OI` on one market (the volatility
    # cancels in the risk pair exactly as the multiplier does). An earlier version
    # divided dollar RISK by dollar NOTIONAL, which is a share scaled by volatility and
    # is not a percentage of anything; see the note in the study cited below.
    #
    # **Numeraire-free, and that is structural rather than lucky.** A share is a ratio of
    # two quantities in the same unit, so dividing both by the gold price leaves it
    # unchanged. These columns therefore read identically under either numeraire, which
    # is why they carry no `_usd` suffix and no numeraire caveat.
    #
    # Evidence for offering this at all, rather than a design opinion:
    # `npf/docs/analysis/2026-08-24-exposure-numeraire-levels.md` measured it against USD,
    # CPI-deflated dollars and gold on the full 43-market universe. It moved a reader's
    # percentile by 10 points or more, or flipped the headline band on 10% of weeks, on
    # 7 of 9 asset classes on BOTH units, where CPI managed 0 of 9 and gold 8 of 9 on the
    # band-flip half of the bar alone. On drift it is the strongest of the four: Metals
    # 24.4x to 1.8x, Fixed Income 14.1x to 1.0x.
    #
    # **It fails two classes and that travels with it.** Softs and Currencies do not
    # clear on either unit, so this is not a universal improvement over reading dollars.
    # And it removes market GROWTH rather than the price level, including the 2004 to
    # 2006 commodity-index influx, so it answers "how crowded relative to the market"
    # and not "how much money is at stake". Those are different questions and the dollar
    # columns are still the right answer to the second.
    oi_n = oi_notional[complete].sum(axis=1, min_count=len(per_market))
    oi_r = oi_risk[complete].sum(axis=1, min_count=len(per_market))
    # `min_count` is the whole membership on purpose. One member missing open interest
    # would otherwise put the numerator over ALL markets above a denominator over the
    # rest, inflating the share with nothing in the frame to say so.
    out["notional_oi_share"] = out["notional_usd"] / oi_n.where(oi_n > 0)
    out["risk_oi_share"] = out["risk_usd"] / oi_r.where(oi_r > 0)

    # The volatility of what the set is HOLDING, weighted by how much of it is held.
    #
    # A set has no volatility of its own, so this is the one summary that survives the
    # aggregation honestly, and the weights are GROSS on purpose. Signed weights are the
    # obvious choice and they are wrong: ``risk_usd / notional_usd`` is a signed-weighted
    # mean, so on a set whose members lean opposite ways the denominator passes through
    # zero and the "volatility" goes to infinity and changes sign, on a week where
    # nothing about any member's volatility happened.
    #
    # For a single market it reduces to that market's own sigma exactly, so a caller
    # drawing this has one code path rather than a special case.
    #
    # Numeraire-free, and that falls out rather than being arranged: sigma is a fraction,
    # and dividing every notional by the same gold price leaves the weights unchanged.
    gross = notional[complete].abs()
    weight = gross.sum(axis=1)
    out["sigma_weighted"] = (
        (gross * _stack("sigma_daily")[complete]).sum(axis=1)
        # A week where every member is flat has no holdings to weight by. NaN says so;
        # zero would claim the set holds something with no volatility.
        / weight.where(weight > 0)
    )
    # `rank_window=None` keeps the expanding form, which is the default and the one
    # that can say "the most ever". A window answers "the most lately" instead; see
    # `windowed_pct_rank` for what that costs.
    out["notional_pct_rank"] = windowed_pct_rank(out["notional_usd"], rank_window,
                                                 min_rank_periods)
    out["risk_pct_rank"] = windowed_pct_rank(out["risk_usd"], rank_window,
                                             min_rank_periods)
    out["notional_oi_share_pct_rank"] = windowed_pct_rank(
        out["notional_oi_share"], rank_window, min_rank_periods)
    out["risk_oi_share_pct_rank"] = windowed_pct_rank(
        out["risk_oi_share"], rank_window, min_rank_periods)

    # Which market sets each end, and only where it costs weeks the others could have
    # filled. A market that merely starts latest is named at "start" only if some other
    # market has earlier data that the rule is discarding.
    bounded_by = {}
    if coverage and not out.empty:
        latest_start = max(c[0] for c in coverage.values())
        earliest_end = min(c[1] for c in coverage.values())
        if any(c[0] < latest_start for c in coverage.values()):
            bounded_by["start"] = next(n for n, c in coverage.items()
                                       if c[0] == latest_start)
        if any(c[1] > earliest_end for c in coverage.values()):
            bounded_by["end"] = next(n for n, c in coverage.items()
                                     if c[1] == earliest_end)
    weeks_lost = int((priced.any(axis=1) & ~complete).sum())
    members = {n: ex[complete.reindex(ex.index, fill_value=False)]
               for n, ex in per_market.items()}
    return AggregateExposure(out, dropped, coverage, bounded_by, weeks_lost,
                             numeraire, members)


def expanding_pct_rank(series: pd.Series, min_periods: int = 104) -> pd.Series:
    """Each value's percentile against the history up to and including itself, 0-100.

    Expanding rather than full-sample, so the series carries no look-ahead and a reader
    can put a finger on any past week and read what was knowable then. A full-sample
    rank would tell 2010 where it sat in a distribution half of which had not happened,
    which is the kind of number that makes a backtest look prescient.

    `min_periods` defaults to two years of weekly data. Below that a percentile is
    mostly a statement about how few observations there are.
    """
    s = pd.to_numeric(series, errors="coerce")
    ranks = s.expanding(min_periods=min_periods).apply(
        lambda w: (w <= w[-1]).mean() * 100.0, raw=True)
    return ranks


def windowed_pct_rank(series: pd.Series, window: int = None,
                      min_periods: int = 104) -> pd.Series:
    """`expanding_pct_rank`, or the same thing over a TRAILING WINDOW of `window` weeks.

    `window=None` is the expanding form and is the default everywhere, because the two
    answer different questions and only one of them can say "the most ever".

        expanding    where does this week sit in EVERY week up to now
        windowed     where does this week sit in the last N weeks

    A window renormalises every week, so a market that has been heavily short all year
    reads near 100 on its least-short week. That is the right answer to "extreme lately"
    and the wrong one to "extreme ever", and the difference is not small: measured
    across 46 markets on a 52-week window, a reading above 50 is actually a net SHORT
    position 12.5% of the time at the median market and 62% of the time on the Russell,
    against 0.2% on the expanding form.

    Neither carries look-ahead. A trailing window ends at the week it describes.

    `min_periods` is clamped to the window, since a window cannot wait for more
    observations than it holds; a caller asking for a 26-week window and two years of
    minimum history means the first, and getting NaN forever would be the other reading.
    """
    s = pd.to_numeric(series, errors="coerce")
    if window is None:
        return expanding_pct_rank(s, min_periods)
    roller = s.rolling(window, min_periods=min(min_periods, window))
    return roller.apply(lambda w: (w <= w[-1]).mean() * 100.0, raw=True)


def windowed_quantile(series: pd.Series, q: float, window: int = None,
                      min_periods: int = 104) -> pd.Series:
    """The band form of `windowed_pct_rank`, expanding or over a trailing window.

    Has to move with the rank it is drawn beside: a band from all history under a line
    ranked against the last year would put a 90th-percentile reading inside its own
    envelope, and nothing on the chart would say the two were measuring different
    stretches of time.
    """
    s = pd.to_numeric(series, errors="coerce")
    if window is None:
        return expanding_quantile(s, q, min_periods)
    return s.rolling(window, min_periods=min(min_periods, window)).quantile(q)


def expanding_quantile(series: pd.Series, q: float,
                       min_periods: int = 104) -> pd.Series:
    """The q-th quantile of the history up to and including each week.

    The band form of `expanding_pct_rank`, and the same look-ahead argument: a static
    threshold drawn from the whole sample marks 2010 as extreme using 2026's
    distribution. Drawn as an envelope this is what lets a level chart show whether
    today is unusual, which is the one thing a chart about crowding must not leave the
    reader to eyeball.
    """
    s = pd.to_numeric(series, errors="coerce")
    return s.expanding(min_periods=min_periods).quantile(q)


def composite_price_index(names, *, base: float = 100.0,
                          max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
                          numeraire: str = NUMERAIRE_USD,
                          dates=None, frames: dict = None) -> pd.Series:
    """An equal-weight price index of the SAME set the aggregate sums, rebased to `base`.

    A price panel above an aggregate has to be the thing the aggregate is exposed to.
    The printed reference this view was built from puts the S&P 500 alone above a total
    that aggregates ES, NQ, YM and RTY, so its reference is not its subject and the two
    lines come apart whenever the four disagree.

    Equal-weight of each member rebased to its own first observation, which is the
    weighting that needs no defending: it is the set, each member counted once. It is
    NOT the capitalisation-weighted index anyone quotes, and the axis says so by
    carrying an index level rather than a price.

    Prices are ``unadj`` levels for the same reason notional uses them, but with the
    opposite consequence worth knowing: an unadjusted continuous series steps at every
    roll, so this index inherits those steps. It is a reference for shape and direction
    over years, not a tradeable return series, and nothing here computes a return from
    it.

    Under NUMERAIRE_GOLD this is the set priced in gold, which is Larry Williams'
    WillVal applied to a complex rather than to one market: an asset measured against a
    hard-money benchmark rather than against a currency. It has to follow the numeraire
    rather than staying in dollars, because a price panel above an exposure panel is a
    reference for it, and a reference in a different unit from its subject is the same
    defect as the printed source's S&P-over-four-markets.

    The transform is exact rather than approximate. Rebasing each member to its own
    first observation and then dividing by gold gives `(p/p0) x (g0/g)`, which is what
    dividing the finished composite by gold and rebasing gives, so this applies it once
    at the end.

    What it shows is worth stating, because it is the reason to offer it. Since August
    2002 the US equity-index composite is up 13.88x in dollars and 0.99x in gold: the
    same value in hard money, after twenty-four years. Grains are 2.04x in dollars and
    0.13x in gold.
    """
    frames = frames or {}
    series = {}
    for name in names:
        symbol = (frames.get(name) or {}).get("symbol")
        if symbol is None:
            from cotmetrics.indexer import get_indexer
            instrument = get_indexer().get_instrument_from_name(name)
            if instrument is None:
                continue
            symbol = instrument.symbol
        if symbol not in point_values():
            continue
        px = price_levels(symbol)
        if px.empty:
            continue
        series[name] = px

    if not series:
        return pd.Series(dtype="float64", name="composite")

    if dates is None:
        frame = pd.DataFrame(series).sort_index()
    else:
        frame = pd.DataFrame(
            {n: _asof(px, pd.DatetimeIndex(dates), max_staleness_days).to_numpy()
             for n, px in series.items()},
            index=pd.DatetimeIndex(dates))

    complete = frame.notna().all(axis=1)
    frame = frame[complete]
    if frame.empty:
        return pd.Series(dtype="float64", name="composite")
    rebased = frame.divide(frame.iloc[0], axis=1) * base
    out = rebased.mean(axis=1)
    divisor = numeraire_series(numeraire, out.index, max_staleness_days)
    if divisor is not None:
        out = out / divisor
        first = out.dropna()
        if not first.empty:
            out = out / first.iloc[0] * base
    out.name = "composite"
    return out


def agreement(values) -> float:
    """`|sum| / sum|.|` over a set of signed contributions, 0 to 1.

    One number for whether a total is a crowd or an argument. At 1.00 every contributor
    points the same way and the total is the whole story; at 0.50 half the gross size is
    cancelling out and the total is a residual between markets doing different things.

    Worth having beside any aggregate on this page because it moves a lot and moves
    independently of the level. Measured on one week of the equity complex: 1.00 for
    Small Traders, who were unanimous, and 0.63 for Large Speculators, who were split,
    on the same markets on the same day.

    Returns NaN on an empty set or an all-zero one, where the ratio is undefined rather
    than perfect.
    """
    vals = [float(v) for v in values if v == v]
    gross = sum(abs(v) for v in vals)
    if not vals or gross == 0:
        return float("nan")
    return abs(sum(vals)) / gross


def contributions(members: dict, column: str, when=None) -> pd.Series:
    """Each member's value for one week, largest absolute contribution first.

    `when` defaults to the last week any member has. Sorted by magnitude rather than by
    name because the question this answers is "what is driving the total", and the
    answer is usually the first row.
    """
    out = {}
    for name, frame in (members or {}).items():
        series = frame[column].dropna() if column in frame.columns else pd.Series(dtype=float)
        if series.empty:
            continue
        if when is None:
            out[name] = float(series.iloc[-1])
        elif when in series.index:
            out[name] = float(series.loc[when])
    if not out:
        return pd.Series(dtype="float64")
    return pd.Series(out).reindex(
        sorted(out, key=lambda n: -abs(out[n])))


#: The columns a contribution table carries, in both units, so a reader can see the
#: number the page is NOT currently drawing without changing a control. The two are not
#: substitutes: measured on the Energies complex their percentiles correlate 0.802 with
#: a median gap of 9.6 percentile points and a worst gap of 69.
TABLE_COLUMNS = ("notional_usd", "risk_usd")


def rank_column(column: str) -> str:
    """The percentile column that goes with a value column.

    One function because `AggregateExposure.frame` and `contribution_table` both carry
    these and must name them the same way. They did not, for one commit: the frame said
    `notional_pct_rank` while the table said `notional_usd_pct_rank`, which is the kind
    of near-miss a caller resolves by writing whichever one their fixture happened to
    have.
    """
    return column.replace("_usd", "") + "_pct_rank"


def contribution_table(members: dict, *, when=None,
                       min_rank_periods: int = 104) -> pd.DataFrame:
    """One week of every member, in both units, each ranked against ITS OWN history.

    The per-market answer to the question the aggregate's percentile answers for the
    set. A market at its own 99th percentile inside a total sitting at its 40th is the
    kind of thing a sum cannot show and a reader would want to know, and it is invisible
    in a contribution figure that plots levels alone.

    Ranked per member rather than against the total, for the same reason the companion
    panel ranks each leg against itself: they are different quantities on different
    scales, and ranking them against the total would put them back on its axis by
    another route.

    Rows are ordered by absolute contribution in the FIRST unit that has values, so the
    market driving the total leads. Members with no value that week are dropped rather
    than carried as blanks: the table is a decomposition of a number, and a row that
    contributed nothing to it is not part of that decomposition.
    """
    rows = {}
    for name, frame in (members or {}).items():
        row = {}
        for column in TABLE_COLUMNS:
            if column not in frame.columns:
                continue
            series = pd.to_numeric(frame[column], errors="coerce")
            ranks = expanding_pct_rank(series, min_rank_periods)
            stamp = when if (when is not None and when in series.index) else None
            if stamp is None:
                valid = series.dropna()
                if valid.empty:
                    continue
                stamp = valid.index[-1]
            value = series.get(stamp)
            if value is None or value != value:
                continue
            row[column] = float(value)
            rank = ranks.get(stamp)
            row[rank_column(column)] = (float(rank) if rank is not None
                                        and rank == rank else float("nan"))
        if row:
            rows[name] = row

    if not rows:
        return pd.DataFrame(columns=[c for col in TABLE_COLUMNS
                                     for c in (col, rank_column(col))])
    table = pd.DataFrame(rows).T
    lead = next((c for c in TABLE_COLUMNS if c in table.columns), None)
    if lead is not None:
        table = table.reindex(table[lead].abs().sort_values(ascending=False).index)
    return table
