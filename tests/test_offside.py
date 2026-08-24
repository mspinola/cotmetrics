"""A cohort's cost basis, and how far under water it sits.

Every test here injects its own weekly frame and monkeypatches the daily price series,
so none of it needs a store. The recurrence and the guards are the interesting part.

The properties pinned below are the ones the measure would still LOOK correct without:
a basis that re-averages on the way out, a mark in raw log units, or a size-weighted
reading all produce plausible numbers that mean something else.
"""
import numpy as np
import pandas as pd
import pytest

import cotmetrics.constants as const
import cotmetrics.offside as off


def weekly(dates, comm=None, large=None, small=None):
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    n = len(idx)
    return pd.DataFrame({
        const.COMM_NET: comm if comm is not None else [0.0] * n,
        const.LARGE_NET: large if large is not None else [0.0] * n,
        const.SMALL_NET: small if small is not None else [0.0] * n,
    }, index=idx)


def tuesdays(n, start="2026-01-06"):
    return pd.date_range(start, periods=n, freq="7D")


def flat_daily(dates, price):
    """Daily bars covering every report week, all at one price."""
    idx = pd.date_range(dates[0] - pd.Timedelta(days=7), dates[-1], freq="D")
    return pd.Series([float(price)] * len(idx), index=idx)


def daily_from_weekly(dates, prices):
    """Daily bars that hold one price for each whole report week.

    Flat within a week, so the week's mean close equals its Tuesday close and the
    arithmetic under test is exactly predictable from `prices` alone.
    """
    idx = pd.date_range(dates[0] - pd.Timedelta(days=7), dates[-1], freq="D")
    out = pd.Series(np.nan, index=idx)
    for d, p in zip(dates, prices):
        out[(out.index > d - pd.Timedelta(days=7)) & (out.index <= d)] = float(p)
    return out.ffill().bfill()


def wiggle(n, amplitude, base=100.0):
    """A price path that alternates by `amplitude` each week, so sigma is non-zero.

    A perfectly flat series has zero volatility, and offside divides by it. Every test
    that wants a finite reading needs a market that actually moves.
    """
    return [base * (1.0 + amplitude * (-1) ** i) for i in range(n)]


# ── the recurrence ────────────────────────────────────────────────────────────

def test_a_fresh_position_takes_the_weeks_average_as_its_basis():
    net = pd.Series([0.0, 100.0], index=tuesdays(2))
    avg = pd.Series([10.0, 20.0], index=net.index)
    assert off.cost_basis(net, avg).iloc[1] == 20.0


def test_adding_averages_the_new_contracts_in_at_this_weeks_price():
    net = pd.Series([100.0, 300.0], index=tuesdays(2))
    avg = pd.Series([10.0, 20.0], index=net.index)
    # 100 lots at 10 and 200 more at 20 is 5000/300.
    assert off.cost_basis(net, avg).iloc[1] == pytest.approx(50.0 / 3.0)


def test_reducing_leaves_the_basis_untouched():
    """Closed lots realize their P&L and leave; the survivors kept their cost.

    Re-averaging on the way out would walk the basis toward the current price and erase
    exactly the distance the measure exists to report, while still returning a number.
    """
    net = pd.Series([100.0, 40.0], index=tuesdays(2))
    avg = pd.Series([10.0, 99.0], index=net.index)
    assert off.cost_basis(net, avg).iloc[1] == 10.0


def test_flipping_through_zero_starts_a_new_basis():
    net = pd.Series([100.0, -50.0], index=tuesdays(2))
    avg = pd.Series([10.0, 20.0], index=net.index)
    assert off.cost_basis(net, avg).iloc[1] == 20.0


def test_a_flat_week_has_no_basis_and_does_not_poison_the_next_one():
    net = pd.Series([100.0, 0.0, 60.0], index=tuesdays(3))
    avg = pd.Series([10.0, 15.0, 20.0], index=net.index)
    b = off.cost_basis(net, avg)
    assert np.isnan(b.iloc[1])
    assert b.iloc[2] == 20.0


def test_holding_carries_the_basis_forward_unchanged():
    net = pd.Series([100.0] * 4, index=tuesdays(4))
    avg = pd.Series([10.0, 20.0, 30.0, 40.0], index=net.index)
    assert list(off.cost_basis(net, avg)) == [10.0, 10.0, 10.0, 10.0]


# ── the mark ──────────────────────────────────────────────────────────────────

@pytest.fixture
def priced(monkeypatch):
    """A market whose daily close is whatever the test asks for."""
    def use(series):
        monkeypatch.setattr(off, "_basis_close", lambda *a, **k: series)
    return use


def test_a_long_below_its_basis_reads_negative(priced):
    dates = tuesdays(30)
    prices = wiggle(30, 0.01)
    prices[-1] = 80.0                       # bought around 100, now well below
    priced(daily_from_weekly(dates, prices))
    r = off.market_offside("x", leg="large", frame=weekly(dates, large=[100.0] * 30),
                           symbol="TEST", min_weeks=2, sigma_weeks=4)
    assert r["basis"].iloc[0] == pytest.approx(prices[0])
    assert r["offside"].iloc[-1] < 0


def test_a_short_above_its_basis_reads_negative_too(priced):
    """sign() is what makes the two sides comparable, and it is easy to drop."""
    dates = tuesdays(30)
    prices = wiggle(30, 0.01)
    prices[-1] = 120.0                      # sold around 100, now well above
    priced(daily_from_weekly(dates, prices))
    r = off.market_offside("x", leg="large", frame=weekly(dates, large=[-100.0] * 30),
                           symbol="TEST", min_weeks=2, sigma_weeks=4)
    assert r["offside"].iloc[-1] < 0


def test_the_reading_does_not_depend_on_position_size(priced):
    """Per contract, not per position. A tiny cohort and a huge one read alike."""
    dates = tuesdays(30)
    prices = wiggle(30, 0.01)
    prices[-1] = 80.0
    priced(daily_from_weekly(dates, prices))
    small = off.market_offside("x", leg="large", frame=weekly(dates, large=[10.0] * 30),
                               symbol="TEST", min_weeks=2, sigma_weeks=4)
    huge = off.market_offside("x", leg="large", frame=weekly(dates, large=[1e6] * 30),
                              symbol="TEST", min_weeks=2, sigma_weeks=4)
    pd.testing.assert_series_equal(small["offside"], huge["offside"])


def test_the_reading_is_in_units_of_the_markets_own_volatility(priced):
    """Two markets down the same percentage read differently if their vol differs.

    This is the property that makes a cross-market ranking mean anything: without the
    division, the ranking is by volatility rather than by distress.
    """
    dates = tuesdays(40)

    def run(amplitude):
        prices = wiggle(40, amplitude)
        prices[-1] = 90.0               # the SAME 10% mark-to-market loss in both
        priced(daily_from_weekly(dates, prices))
        return off.market_offside("x", leg="large", frame=weekly(dates, large=[100.0] * 40),
                                  symbol="TEST", min_weeks=4, sigma_weeks=8)

    calm = run(0.002)
    wild = run(0.05)
    # Same percentage loss, different markets. The calm one is further under in ITS OWN
    # sigma units, which is the whole point of the denominator.
    assert calm["offside"].iloc[-1] < wild["offside"].iloc[-1] < 0


def test_a_position_at_its_basis_reads_zero(priced):
    dates = tuesdays(30)
    prices = wiggle(30, 0.01)
    prices[-1] = prices[0]                  # back to exactly where it was bought
    priced(daily_from_weekly(dates, prices))
    r = off.market_offside("x", leg="large", frame=weekly(dates, large=[100.0] * 30),
                           symbol="TEST", min_weeks=2, sigma_weeks=4)
    assert r["basis"].iloc[-1] == pytest.approx(prices[0])
    assert r["offside"].iloc[-1] == pytest.approx(0.0)


# ── the guards ────────────────────────────────────────────────────────────────

def test_a_non_propadj_tier_is_refused_by_name():
    with pytest.raises(off.OffsideError, match="propadj"):
        off._basis_close("TEST", "backadj")


def test_an_unknown_leg_is_refused():
    with pytest.raises(off.OffsideError, match="unknown leg"):
        off.market_offside("x", leg="nobody", frame=weekly(tuesdays(3)), symbol="TEST")


def test_a_frame_without_the_legs_column_says_which_one():
    frame = weekly(tuesdays(3)).drop(columns=[const.LARGE_NET])
    with pytest.raises(off.OffsideError, match=const.LARGE_NET):
        off.market_offside("x", leg="large", frame=frame, symbol="TEST")


def test_a_market_with_no_bars_yields_nan_rather_than_raising(priced):
    priced(pd.Series(dtype="float64"))
    r = off.market_offside("x", leg="large", frame=weekly(tuesdays(5), large=[1.0] * 5),
                           symbol="TEST")
    assert r["offside"].isna().all()


def test_sigma_is_nan_until_the_window_has_enough_weeks(priced):
    dates = tuesdays(30)
    priced(flat_daily(dates, 100.0))
    r = off.market_offside("x", leg="large", frame=weekly(dates, large=[100.0] * 30),
                           symbol="TEST", sigma_weeks=10, min_weeks=5)
    assert r["sigma_weekly"].iloc[:4].isna().all()


# ── the hedge leg ─────────────────────────────────────────────────────────────

def test_commercials_are_labelled_a_hedge_leg():
    """They are underwater 65.6% of the time by design, so ranking them as distress
    beside the speculative cohorts is a category error the label exists to prevent."""
    assert off.is_hedge_leg("comm")
    assert "hedge leg" in off.leg_label("comm")


def test_the_speculative_cohorts_are_not_labelled_that_way():
    for leg in ("large", "small", "spec"):
        assert not off.is_hedge_leg(leg)
        assert "hedge" not in off.leg_label(leg)
