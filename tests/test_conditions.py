"""Golden / unit tests for the pure signal-condition math in metrics/conditions.py.

These functions are the building blocks of every trading signal, so they are
tested against hand-constructed inputs with known expected outputs. Everything
here is pure (no DB / network), so the tests are deterministic and fast.
"""
import numpy as np
import pandas as pd
import pytest

import cotmetrics.constants as const
from cotmetrics import conditions


def _df(closes, highs=None, lows=None, oi=None, large_idx=None):
    """Build a DataFrame keyed by the real column-name constants."""
    closes = list(closes)
    len(closes)
    data = {
        const.CLOSING_PRICE: closes,
        const.HIGH_PRICE: list(highs) if highs is not None else closes,
        const.LOW_PRICE: list(lows) if lows is not None else closes,
    }
    if oi is not None:
        data[const.OPEN_INTEREST] = list(oi)
    if large_idx is not None:
        data[const.LARGE_CUSTOM_IDX] = list(large_idx)
    return pd.DataFrame(data)


# ── is_commodity ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("asset_class,expected", [
    ("Energy", True),
    ("Energies", True),
    ("Grains", True),
    ("Metals", True),
    ("Softs", True),
    ("Financial", False),
    ("Currency", False),
    ("Equity Index", False),
])
def test_is_commodity(asset_class, expected):
    assert conditions.is_commodity(asset_class) is expected


# ── project_trendline ───────────────────────────────────────────────────────
def test_project_trendline_extrapolates_perfect_line():
    # y = x + 10 over x=0..9 -> slope 1, intercept 10 -> projected at x=10 is 20
    line = np.arange(10, 20, dtype=float)  # [10, 11, ..., 19]
    assert conditions.project_trendline(line) == pytest.approx(20.0)


def test_project_trendline_flat_line():
    flat = np.full(10, 42.0)
    assert conditions.project_trendline(flat) == pytest.approx(42.0)


# ── calculate_cot_macd ──────────────────────────────────────────────────────
def test_cot_macd_constant_series_is_all_zero():
    net = pd.Series([100.0] * 60)
    macd_line, signal_line, hist = conditions.calculate_cot_macd(net)
    assert macd_line.abs().max() == pytest.approx(0.0)
    assert signal_line.abs().max() == pytest.approx(0.0)
    assert hist.abs().max() == pytest.approx(0.0)
    assert len(macd_line) == len(signal_line) == len(hist) == 60


def test_cot_macd_histogram_is_macd_minus_signal():
    net = pd.Series(np.linspace(-500, 500, 80))
    macd_line, signal_line, hist = conditions.calculate_cot_macd(net)
    pd.testing.assert_series_equal(hist, macd_line - signal_line)


# ── is_short_term_low / high ────────────────────────────────────────────────
def test_is_short_term_low_on_decreasing_series():
    # strictly decreasing -> each full-window point is its own rolling min
    df = _df([5, 4, 3, 2, 1])
    low = conditions.is_short_term_low(df, const.CLOSING_PRICE, n_weeks=4)
    # first 3 have an incomplete window (NaN rolling min) -> False
    assert list(low) == [False, False, False, True, True]


def test_is_short_term_high_on_increasing_series():
    df = _df([1, 2, 3, 4, 5])
    high = conditions.is_short_term_high(df, const.CLOSING_PRICE, n_weeks=4)
    assert list(high) == [False, False, False, True, True]


def test_is_short_term_low_not_triggered_at_a_peak():
    df = _df([1, 2, 3, 4, 10])
    low = conditions.is_short_term_low(df, const.CLOSING_PRICE, n_weeks=4)
    assert not low.iloc[-1]  # last point is the window max, not the min


# ── in_up_trend ─────────────────────────────────────────────────────────────
def test_in_up_trend_rising_series():
    df = _df(list(range(1, 16)))  # 1..15 rising
    up, down = conditions.in_up_trend(df, const.CLOSING_PRICE, n_weeks=10)
    assert up.iloc[-1] and not down.iloc[-1]


def test_in_up_trend_falling_series():
    df = _df(list(range(15, 0, -1)))  # 15..1 falling
    up, down = conditions.in_up_trend(df, const.CLOSING_PRICE, n_weeks=10)
    assert not up.iloc[-1] and down.iloc[-1]


# ── calculate_oi_exhaustion_floor ───────────────────────────────────────────
def test_oi_exhaustion_floor_clings_to_low():
    # OI sitting on its recent floor (within 5%) -> True; a spike -> False
    oi = [100, 100, 100, 100, 103, 200]
    df = _df([1] * len(oi), oi=oi)
    floor = conditions.calculate_oi_exhaustion_floor(df, short_window=4, tolerance_pct=0.05)
    assert floor.dtype == bool
    assert floor.iloc[4]    # 103 <= min(100..)*1.05 = 105
    assert not floor.iloc[5]   # 200 far above the buffered floor


# ── calculate_oi_active_decline ─────────────────────────────────────────────
def test_oi_active_decline_on_bleeding_series():
    oi = [100, 98, 96, 94, 92, 90, 88, 86]
    df = _df([1] * len(oi), oi=oi)
    decl = conditions.calculate_oi_active_decline(df, lookback_window=4, threshold_pct=-0.04)
    assert decl.dtype == bool
    assert decl.iloc[-1]


def test_oi_active_decline_false_when_rising():
    oi = [80, 82, 84, 86, 88, 90, 92, 94]
    df = _df([1] * len(oi), oi=oi)
    decl = conditions.calculate_oi_active_decline(df, lookback_window=4, threshold_pct=-0.04)
    assert not decl.any()


# ── calculate_price_velocity_zscore ─────────────────────────────────────────
def test_price_velocity_zscore_constant_price_is_zero_and_no_nan():
    df = _df([50.0] * 40)
    z = conditions.calculate_price_velocity_zscore(df, const.CLOSING_PRICE)
    assert isinstance(z, pd.Series)
    assert len(z) == 40
    assert not z.isna().any()
    assert z.abs().max() == pytest.approx(0.0)


# ── calculate_oi_acceleration ───────────────────────────────────────────────
def test_oi_acceleration_constant_is_zero_and_no_nan():
    oi = [1000] * 40
    df = _df([1] * len(oi), oi=oi)
    acc = conditions.calculate_oi_acceleration(df)
    assert isinstance(acc, pd.Series)
    assert not acc.isna().any()
    assert acc.abs().max() == pytest.approx(0.0)


# ── stable_or_rising ────────────────────────────────────────────────────────
def test_stable_or_rising_constant_series_is_stable_on_both_masks():
    df = _df([10.0] * 20)
    rising, failing = conditions.stable_or_rising(df, const.CLOSING_PRICE, n_weeks=5)
    # after the shift window fills, a flat series counts as stable in both masks
    assert rising.iloc[-1]
    assert failing.iloc[-1]


def test_stable_or_rising_strong_uptrend_flags_rising_not_failing():
    df = _df([float(x) for x in range(30)])
    rising, failing = conditions.stable_or_rising(df, const.CLOSING_PRICE, n_weeks=5)
    assert rising.iloc[-1]
    assert not failing.iloc[-1]


# ── a_to_b_correlation ──────────────────────────────────────────────────────
def test_a_to_b_correlation_identical_columns():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5, 6], "b": [1, 2, 3, 4, 5, 6]})
    corr, consistent = conditions.a_to_b_correlation(df, "a", "b", n_weeks=4)
    assert corr.iloc[-1] == pytest.approx(1.0)
    assert consistent.iloc[-1]


def test_a_to_b_correlation_inverse_columns():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5, 6], "b": [6, 5, 4, 3, 2, 1]})
    corr, consistent = conditions.a_to_b_correlation(df, "a", "b", n_weeks=4)
    assert corr.iloc[-1] == pytest.approx(-1.0)
    assert not consistent.iloc[-1]


# ── calculate_violent_increase ──────────────────────────────────────────────
def test_violent_increase_flags_a_spike():
    prices = [100 + (i % 2) for i in range(30)]  # small oscillation -> nonzero std
    prices.append(160)                            # a violent breakout
    df = _df(prices)
    violent = conditions.calculate_violent_increase(df, lookback_window=26, sigma_multiplier=1.5)
    assert violent.dtype == bool
    assert violent.iloc[-1]
    assert not violent.iloc[20]


# ── is_sharp_increase ───────────────────────────────────────────────────────
def test_is_sharp_increase_flags_oi_spike():
    rng = np.random.default_rng(0)
    oi = list(1000 + rng.integers(-5, 5, size=40))
    oi.append(3000)  # structural spike
    df = _df([1] * len(oi), oi=oi)
    up, down = conditions.is_sharp_increase(df, const.OPEN_INTEREST, n_weeks=26, sigma_multiplier=1.5)
    assert up.iloc[-1]
    assert not down.iloc[-1]


# ── calculate_price_stabilization_at_support / stalling_at_highs ─────────────
def test_stabilization_and_stalling_return_bool_series():
    n = 40
    closes = [100.0] * n
    df = _df(closes, highs=[101.0] * n, lows=[99.0] * n)
    supp = conditions.calculate_price_stabilization_at_support(df)
    ceil = conditions.calculate_price_stalling_at_highs(df)
    assert supp.dtype == bool and ceil.dtype == bool
    assert len(supp) == n and len(ceil) == n


# ── calculate_lrg_spec_momentum_divergence ──────────────────────────────────
def test_lrg_spec_divergence_bullish_when_specs_sell_into_support():
    from types import SimpleNamespace
    # Large-spec index dropping ~2/week -> aggressive selling
    large = [20, 20, 20, 18, 16, 14, 12, 10]
    df = _df([1] * len(large), large_idx=large)
    n = len(large)
    price = SimpleNamespace(
        stalling_at_highs=pd.Series([False] * n),
        stabilizing_at_support=pd.Series([True] * n),
    )
    div = conditions.calculate_lrg_spec_momentum_divergence(df, price, momentum_window=3)
    assert div.dtype == int or div.dtype == np.int64
    assert div.iloc[-1] == 1   # bullish divergence


def test_lrg_spec_divergence_neutral_when_no_price_boundary():
    from types import SimpleNamespace
    large = [20, 20, 20, 18, 16, 14, 12, 10]
    df = _df([1] * len(large), large_idx=large)
    n = len(large)
    price = SimpleNamespace(
        stalling_at_highs=pd.Series([False] * n),
        stabilizing_at_support=pd.Series([False] * n),
    )
    div = conditions.calculate_lrg_spec_momentum_divergence(df, price, momentum_window=3)
    assert (div == 0).all()
