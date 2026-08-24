"""Is a cohort UNDERWATER? Cost basis marked to market, per contract.

Every other positioning measure in this package is a statement about position SIZE.
The range index and the z-score say how unusual the size is against its own history;
`exposure` says how large it is in dollars or dollar risk. None of them says whether
the people holding it are winning or losing, which is a first-moment claim about a
price and needs a price to compare against.

This module supplies the missing comparison: the cohort's own average cost.

    adding      B_t = (B_{t-1}|N_{t-1}| + A_t (|N_t| - |N_{t-1}|)) / |N_t|
    reducing    B_t = B_{t-1}                     closed at market, basis unchanged
    flat/flip   B_t = A_t                         fresh basis

    offside_t = sign(N_t) x log(P_t / B_t) / sigma_t       negative = underwater

**`sign(N)`, not `N`. Size does not enter.** This is a PER-CONTRACT return, so a
cohort holding 400 lots and one holding 400,000 read the same when both are the same
distance under water. That is the opposite choice from `exposure`, which multiplies BY
size and BY volatility to answer how much selling a vol move must force. The two are
complements and neither substitutes for the other: `exposure` says how big the position
is, this says how much it hurts to hold. Multiplying them would produce a dollar loss,
which is a third quantity and is not what either module returns.

**Dividing by sigma is what makes it comparable.** A 10% loss is a routine week in
crude and a generational move in a rates future, so the raw log return ranks markets by
their volatility rather than by distress. In units of the market's own trailing weekly
sigma, -3 means the same thing everywhere: the cohort sits three typical weekly moves
below its average entry.

**Extreme positioning is not offside positioning, and is closer to its opposite.**
Measured across 44 markets and 69,806 market-weeks (`npf/docs/analysis/
2026-08-23-offside-positioning-measure.md`), Large Specs at a range-index extreme are
underwater 14.2% of the time against 42.7% for neutral positioning, and the two
conditions overlap on 6.7% of crowded weeks where independence would give 10%. This is
mechanical once stated: positioning becomes extreme because a cohort added into a move
that was working, so extremity is built by WINNERS. A screen for trapped traders built
on the range index selects against the thing it is looking for. That is the whole reason
this module exists rather than a note saying the index already covers it.

**What this may be used for, and what it may not.** It is a DISPLAY of who is losing.
It is not a timing signal, and that is a measured result rather than caution: the
pre-registered test in `npf/docs/handoffs/2026-08-23-offside-capitulation-prereg.md`
asked whether deep offside predicts capitulation beyond the adverse price move it is
built from, and the verdict was **adverse-move proxy**. Within equally severe adverse
moves, deep-offside cohorts capitulated no more often (Large Specs -3.6pp, not
significant) and Small Traders significantly LESS (-11.8pp, CI [-15.2, -8.4]). The raw
association exists and is real; it is the price move wearing a different label. Anything
proposing to trade this needs its own pre-registration, and the direction the evidence
leans is not the intuitive one.

PRICE TIER. ``propadj``, and the failure of the alternative is measured. A cost basis is
a difference in points and looks like it wants ``backadj``, matched to an ATR in points.
Additive back-adjustment drives 14 of 45 markets through zero (HO 90.6% of bars, RB
77.1%, OJ 73.6%), and a negative price makes both the basis and the log ratio
meaningless while still returning a number. ``propadj`` is non-positive on exactly one
print across the universe (CL 2020-04-20, the real WTI event), which is masked. So the
basis runs on ratio-adjusted prices and the measure is a log ratio, which is unitless
and therefore indifferent to the arbitrary scale ratio adjustment leaves behind.

**Do not read Commercials as distress.** They sit underwater 65.6% of the time with a
tenth percentile of -4.32 sigma, and that is the hedge working. The futures leg offsets
a physical position COT cannot see, so a mark-to-market loss there is the cost of the
insurance, not evidence of a trapped holder. `is_hedge_leg` exists so a caller can label
it rather than rank it beside the speculative cohorts.

Where this lives: it is a joiner (COT x prices), and cot-analyzer computes no metrics of
its own, so the arithmetic belongs here and the drawing belongs there. It sits beside
`exposure` rather than inside `CotIndexer` for three reasons: it needs an explicit price
tier, which `tests/test_price_tier.py` forbids in that module by design; it is
lookback-invariant, where everything in `process_lookback` is scoped to a window; and it
is wanted per cohort, which in a flat `{symbol}.parquet` would mean three more columns
that nothing else reads.
"""
import functools

import numpy as np
import pandas as pd

from cotmetrics.exposure import (
    DEFAULT_MAX_STALENESS_DAYS,
    LEG_COLUMNS,
    LEG_LABELS,
    MAX_NONPOSITIVE_RATE,
    _asof,
    _close,
)

#: The basis, the mark and the volatility all come from ONE series, unlike `exposure`,
#: which deliberately reads two. Nothing here needs a tradeable level: a cost basis is
#: only ever compared against a price from the same series, and the comparison is a
#: RATIO, so any constant scale factor cancels. Ratio adjustment is the tier that keeps
#: that true across rolls.
BASIS_ADJUSTMENT = "propadj"

#: Weeks in the volatility window. Half a year: long enough that one week cannot
#: dominate the denominator, short enough to still be moving when a vol regime changes.
#: Weekly rather than daily because the numerator is a weekly series; mixing a daily
#: sigma into a weekly mark would report the distance in the wrong unit.
DEFAULT_SIGMA_WEEKS = 26

#: Minimum weeks before the window yields a number. Half the window, matching the
#: `min_periods=lb // 2` idiom used throughout `indicators`.
DEFAULT_MIN_WEEKS = 13

#: Legs whose futures position IS the position, so a mark-to-market loss is distress.
#: Commercials are excluded on purpose: see the module docstring.
DISTRESS_LEGS = frozenset({"large", "small", "spec"})


class OffsideError(RuntimeError):
    """A market cannot be marked against a cost basis, and the caller should know why."""


def is_hedge_leg(leg: str) -> bool:
    """True when a negative reading is the hedge working rather than a trapped holder."""
    return leg not in DISTRESS_LEGS


def cost_basis(net: pd.Series, avg: pd.Series) -> pd.Series:
    """Average-cost basis of a weekly net position.

    Average cost, not FIFO, and the choice is forced rather than preferred: COT reports
    a NET total per cohort per week and says nothing about which lots were closed, so
    there is no ordering to run FIFO over. The three branches are the only transitions a
    net position can make.

    A REDUCTION leaves the basis untouched. Contracts closed at market realize their P&L
    and leave; what remains was bought at the same average as before. Re-averaging on the
    way out would walk the basis toward the current price and quietly erase exactly the
    distance this measure exists to report.
    """
    n = net.to_numpy(dtype=float)
    a = avg.to_numpy(dtype=float)
    b = np.full(len(n), np.nan)
    for i in range(len(n)):
        if not np.isfinite(n[i]) or not np.isfinite(a[i]) or n[i] == 0:
            continue
        prior_ok = i > 0 and np.isfinite(b[i - 1]) and np.isfinite(n[i - 1]) and n[i - 1] != 0
        if not prior_ok or np.sign(n[i]) != np.sign(n[i - 1]):
            b[i] = a[i]                                          # fresh or flipped
        elif abs(n[i]) > abs(n[i - 1]):
            added = abs(n[i]) - abs(n[i - 1])
            b[i] = (b[i - 1] * abs(n[i - 1]) + a[i] * added) / abs(n[i])
        else:
            b[i] = b[i - 1]                                      # reduced at market
    return pd.Series(b, index=net.index, dtype="float64")


@functools.lru_cache(maxsize=256)
def _basis_close(symbol: str, adjustment: str = BASIS_ADJUSTMENT) -> pd.Series:
    """Daily close on the tier a cost basis may be built from.

    Refuses anything but ``propadj``. The refusal is the point: `marketdata.get_bars`
    defaults to ``backadj`` for futures and returns it without complaint, and a basis
    built on it looks entirely plausible right up to the market whose price history
    crosses zero.
    """
    if adjustment != BASIS_ADJUSTMENT:
        raise OffsideError(
            f"a cost basis needs a series that stays positive across rolls, so "
            f"adjustment must be {BASIS_ADJUSTMENT!r}, not {adjustment!r}. Additive "
            f"back-adjustment drives 14 of 45 markets through zero (HO 90.6% of bars, "
            f"RB 77.1%), and log(P/B) is undefined on either side of that.")
    px = _close(symbol, adjustment)
    if px.empty:
        return px
    nonpos = px <= 0
    rate = float(nonpos.mean())
    if rate > MAX_NONPOSITIVE_RATE:
        raise OffsideError(
            f"{symbol}: {int(nonpos.sum())} of {len(px)} closes ({rate:.1%}) are "
            f"non-positive in an adjustment={adjustment!r} series, above the "
            f"{MAX_NONPOSITIVE_RATE:.0%} bound. A ratio to a non-positive basis has no "
            f"meaning, so this cannot yield a mark. A rate this high is a wrong series, "
            f"not a market that traded below zero.")
    return px.where(px > 0)


def weekly_marks(symbol: str, dates: pd.Index, *,
                 max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
                 sigma_weeks: int = DEFAULT_SIGMA_WEEKS,
                 min_weeks: int = DEFAULT_MIN_WEEKS) -> pd.DataFrame:
    """The three price series a mark needs, on COT report dates.

    ``price`` is the close as of the report Tuesday, which is what the position is
    marked at. ``avg`` is the MEAN daily close across the report week, which is what new
    contracts are assumed to have been bought at: they arrived through the week, and
    marking a whole week's accumulation at one print is the larger of the two
    approximations in this construction. ``sigma`` is the trailing standard deviation of
    weekly log returns of the Tuesday series.
    """
    px = _basis_close(symbol)
    idx = pd.DatetimeIndex(pd.to_datetime(dates)).sort_values()
    if px.empty or idx.empty:
        nan = pd.Series(np.nan, index=idx, dtype="float64")
        return pd.DataFrame({"price": nan, "avg": nan, "sigma": nan})

    price = _asof(px, idx, max_staleness_days)
    # Each report week is (t-1 week, t]: the seven days ending on the Tuesday the
    # position is reported as of. `right=True` so the Tuesday bar itself lands in its
    # own week rather than the next one.
    edges = pd.DatetimeIndex([idx[0] - pd.Timedelta(days=7), *idx])
    bucket = pd.cut(px.index, bins=edges, labels=idx, right=True, ordered=False)
    avg = px.groupby(bucket, observed=False).mean()
    avg.index = pd.DatetimeIndex(avg.index)
    # A week with no bar at all has no average, and must not silently inherit the
    # Tuesday mark: that would price a whole week's additions at a stale print.
    avg = avg.reindex(idx)

    sigma = (np.log(price).diff()
             .rolling(sigma_weeks, min_periods=min_weeks).std())
    return pd.DataFrame({"price": price, "avg": avg, "sigma": sigma}, index=idx)


def market_offside(name: str, *, leg: str = "large", lookback: str = "Custom",
                   sigma_weeks: int = DEFAULT_SIGMA_WEEKS,
                   min_weeks: int = DEFAULT_MIN_WEEKS,
                   max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
                   frame: pd.DataFrame = None,
                   symbol: str = None) -> pd.DataFrame:
    """One market's weekly cost basis and how far the cohort sits from it.

    Indexed by COT report date, because that is the date the position is AS OF. It is
    not the date it was knowable: the CFTC publishes Tuesday's figures on the Friday, so
    anything acting on this owes the reader that gap. The basis accounting is correctly
    stamped at the as-of date, which is right for displaying history and wrong for
    trading it unlagged.

    `frame` and `symbol` are injectable so a caller that already holds the weekly frame
    does not pay for a second indexer read, and so this is testable without a store.
    """
    if leg not in LEG_COLUMNS:
        raise OffsideError(f"unknown leg {leg!r}, expected one of {tuple(LEG_COLUMNS)}")

    if frame is None or symbol is None:
        from cotmetrics.indexer import get_indexer
        indexer = get_indexer()
        instrument = indexer.get_instrument_from_name(name)
        if instrument is None:
            raise OffsideError(f"no instrument named {name!r}")
        symbol = symbol or instrument.symbol
        frame = indexer.get_symbols_data(name, lookback) if frame is None else frame

    columns = LEG_COLUMNS[leg]
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise OffsideError(f"{symbol}: weekly frame has no {missing} column(s)")

    net = sum(pd.to_numeric(frame[c], errors="coerce") for c in columns)
    dates = pd.DatetimeIndex(pd.to_datetime(frame.index))
    net = pd.Series(net.to_numpy(dtype="float64"), index=dates).sort_index()

    marks = weekly_marks(symbol, dates, max_staleness_days=max_staleness_days,
                         sigma_weeks=sigma_weeks, min_weeks=min_weeks)

    out = pd.DataFrame(index=marks.index)
    out.index.name = "Date"
    out["net_contracts"] = net.reindex(marks.index).to_numpy()
    out["price"] = marks["price"].to_numpy()
    out["basis"] = cost_basis(out["net_contracts"], marks["avg"]).to_numpy()
    out["sigma_weekly"] = marks["sigma"].to_numpy()
    # sign(), not the position: a per-contract return, so a small cohort and a huge one
    # read alike when both sit the same distance under. See the module docstring.
    ratio = np.log(out["price"] / out["basis"].where(out["basis"] > 0))
    out["offside"] = (np.sign(out["net_contracts"]) * ratio
                      / out["sigma_weekly"].replace(0, np.nan))
    return out.replace([np.inf, -np.inf], np.nan)


def leg_label(leg: str) -> str:
    """Display name, with the hedge leg saying so."""
    label = LEG_LABELS.get(leg, leg)
    return label if leg in DISTRESS_LEGS else f"{label} (hedge leg)"
