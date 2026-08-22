"""Contracts into dollars, and dollars into risk.

Every test here injects its own weekly frame and monkeypatches the two price series, so
none of it needs a store. That is deliberate: the arithmetic and the guards are the
interesting part, and the I/O is not.
"""
import numpy as np
import pandas as pd
import pytest

import cotmetrics.constants as const
import cotmetrics.exposure as ex


def weekly(dates, comm=None, large=None, small=None):
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    n = len(idx)
    return pd.DataFrame({
        const.COMM_NET: comm if comm is not None else [0.0] * n,
        const.LARGE_NET: large if large is not None else [0.0] * n,
        const.SMALL_NET: small if small is not None else [0.0] * n,
    }, index=idx)


def daily(start, values):
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series([float(v) for v in values], index=idx)


@pytest.fixture
def priced(monkeypatch):
    """A market called TEST: multiplier 50, price 100, daily vol 2%."""
    monkeypatch.setattr(ex, "point_values", lambda: {"TEST": 50.0})
    monkeypatch.setattr(ex, "price_levels", lambda s, *a, **k: daily("2026-01-01", [100.0] * 40))
    monkeypatch.setattr(ex, "sigma_series", lambda s, **k: daily("2026-01-01", [0.02] * 40))


# ── the arithmetic ────────────────────────────────────────────────────────────

def test_notional_is_contracts_times_multiplier_times_price(priced):
    frame = weekly(["2026-01-06", "2026-01-13"], comm=[-1000.0, -2000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="TEST")
    assert list(out["notional_usd"]) == [-1000 * 50 * 100, -2000 * 50 * 100]


def test_risk_MULTIPLIES_by_volatility(priced):
    """A vol targeter sizes at target/sigma, so its notional is inversely proportional
    to sigma and the PRODUCT is what stays constant while it sits at target. Dividing
    would describe nothing anybody does, and would move the wrong way when vol spikes."""
    frame = weekly(["2026-01-06"], comm=[-1000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="TEST")
    notional = out["notional_usd"].iloc[0]
    assert out["risk_usd"].iloc[0] == pytest.approx(notional * 0.02)
    assert out["risk_usd"].iloc[0] != pytest.approx(notional / 0.02)


def test_the_spec_leg_is_the_sum_of_two_legs_not_the_negation_of_commercials(priced):
    """The three Legacy legs sum to zero, so the mirror of Commercial net is Large PLUS
    Small. Computing it as a negation would agree only where the report balances exactly
    and would hide which series was actually read."""
    frame = weekly(["2026-01-06"], comm=[-1000.0], large=[700.0], small=[250.0])
    out = ex.market_exposure("t", leg=ex.LEG_SPEC, frame=frame, symbol="TEST")
    assert out["net_contracts"].iloc[0] == 950.0
    assert out["net_contracts"].iloc[0] != 1000.0


def test_a_market_with_no_multiplier_yields_no_dollars_rather_than_raising(monkeypatch):
    """MFS and MME are ICE MSCI futures priced off ETFs, and an ETF share is not a
    contract. Saying so in a column beats raising and taking the other 45 markets with
    it."""
    monkeypatch.setattr(ex, "point_values", lambda: {})
    frame = weekly(["2026-01-06"], comm=[-1000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="MFS")
    assert out["net_contracts"].iloc[0] == -1000.0
    assert np.isnan(out["notional_usd"].iloc[0])


# ── the two price series are not interchangeable ──────────────────────────────

def test_notional_refuses_anything_but_unadjusted_levels():
    """get_bars DEFAULTS to backadj for futures, and the `Closing Price` column already
    on every CotIndexer frame is that default, so the wrong series is the one nearest to
    hand. Additive adjustment restates history on every roll."""
    with pytest.raises(ex.ExposureError, match="tradeable price levels"):
        ex.price_levels("ES", "backadj")


def test_volatility_refuses_anything_but_ratio_adjusted_returns():
    with pytest.raises(ex.ExposureError, match="percentage returns"):
        ex.sigma_series("ES", adjustment="backadj")
    with pytest.raises(ex.ExposureError, match="percentage returns"):
        ex.sigma_series("ES", adjustment="unadj")


def test_the_two_series_ask_for_different_adjustments():
    """Stated as a pin because the whole module rests on it: one product, two price
    series, neither substituting for the other."""
    assert ex.LEVEL_ADJUSTMENT == "unadj"
    assert ex.RISK_ADJUSTMENT == "propadj"
    assert ex.LEVEL_ADJUSTMENT != ex.RISK_ADJUSTMENT


# ── staleness ─────────────────────────────────────────────────────────────────

def test_a_holiday_tuesday_takes_the_last_known_price(priced, monkeypatch):
    """A plain reindex would drop every COT date that was not a trading day."""
    px = daily("2026-01-01", [100.0] * 5).drop(pd.Timestamp("2026-01-05"))
    monkeypatch.setattr(ex, "price_levels", lambda s, *a, **k: px)
    out = ex.market_exposure("t", leg=ex.LEG_COMM,
                             frame=weekly(["2026-01-05"], comm=[-10.0]), symbol="TEST")
    assert out["price"].iloc[0] == 100.0


def test_a_price_older_than_the_staleness_bound_is_not_carried(priced, monkeypatch):
    """An unbounded fill would value a delisted market at whatever it last printed,
    forever, which is the silence this bound exists for."""
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 2))
    out = ex.market_exposure("t", leg=ex.LEG_COMM,
                             frame=weekly(["2026-03-01"], comm=[-10.0]), symbol="TEST")
    assert np.isnan(out["price"].iloc[0])
    assert np.isnan(out["notional_usd"].iloc[0])


# ── the aggregate states its set ──────────────────────────────────────────────

def _two_market_frames():
    return {
        "A": {"frame": weekly(["2026-01-06", "2026-01-13"], comm=[-100.0, -200.0]),
              "symbol": "TEST"},
        "B": {"frame": weekly(["2026-01-06", "2026-01-13"], comm=[-300.0, -400.0]),
              "symbol": "TEST"},
    }


def test_the_total_sums_only_weeks_every_member_can_price(priced):
    """A total that silently changes constituents is a different series each week, and
    the seam lands where a market's history starts or stops, which is exactly where a
    reader would read a level change as news."""
    frames = _two_market_frames()
    frames["B"]["frame"] = weekly(["2026-01-13"], comm=[-400.0])
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=frames)
    assert list(agg.frame.index) == [pd.Timestamp("2026-01-13")]
    assert agg.frame["notional_usd"].iloc[0] == (-200 - 400) * 50 * 100
    assert agg.weeks_lost == 1


def test_the_member_that_truncates_the_total_is_named(priced):
    """The live case this exists for: NKD's COT history ends 2026-03-03, so a strict
    six-market equity total ends there while the other five run to the current week, and
    nothing about the chart would say so."""
    frames = _two_market_frames()
    frames["B"]["frame"] = weekly(["2026-01-06"], comm=[-300.0])
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=frames)
    assert agg.bounded_by["end"] == "B"
    assert "start" not in agg.bounded_by


def test_a_member_with_no_multiplier_is_dropped_by_name_not_silently(monkeypatch):
    monkeypatch.setattr(ex, "point_values", lambda: {"TEST": 50.0})
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 40))
    monkeypatch.setattr(ex, "sigma_series", lambda s, **k: daily("2026-01-01", [0.02] * 40))
    frames = _two_market_frames()
    frames["B"]["symbol"] = "NOPE"
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=frames)
    assert "B" in agg.dropped
    assert "multiplier" in agg.dropped["B"]
    assert agg.frame["n_markets"].iloc[0] == 1


def test_an_unbounded_total_names_no_bound(priced):
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    assert agg.bounded_by == {}
    assert agg.weeks_lost == 0
    assert len(agg.frame) == 2


# ── the percentile ────────────────────────────────────────────────────────────

def test_the_percentile_is_expanding_so_it_carries_no_look_ahead():
    """A full-sample rank tells 2010 where it sat in a distribution half of which had
    not happened, which is the kind of number that makes a backtest look prescient."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    rank = ex.expanding_pct_rank(s, min_periods=1)
    # Each value is the largest SO FAR, so every week is the 100th percentile of its own
    # history. Under a full-sample rank the first would be the 25th.
    assert list(rank) == [100.0, 100.0, 100.0, 100.0]


def test_the_percentile_says_nothing_until_it_has_enough_history():
    """Below min_periods a percentile is mostly a statement about how few observations
    there are."""
    rank = ex.expanding_pct_rank(pd.Series([1.0, 2.0, 3.0]), min_periods=3)
    assert list(rank.isna()) == [True, True, False]


def test_the_percentile_ranks_a_low_value_low():
    rank = ex.expanding_pct_rank(pd.Series([10.0, 20.0, 30.0, 5.0]), min_periods=1)
    assert rank.iloc[-1] == pytest.approx(25.0)


# ── the legs ──────────────────────────────────────────────────────────────────

def test_an_unknown_leg_is_refused(priced):
    with pytest.raises(ex.ExposureError, match="unknown leg"):
        ex.market_exposure("t", leg="middle",
                           frame=weekly(["2026-01-06"]), symbol="TEST")


def test_every_leg_has_a_label_and_a_column_set():
    assert set(ex.LEG_COLUMNS) == set(ex.LEG_LABELS)
