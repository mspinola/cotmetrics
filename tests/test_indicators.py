"""Golden tests for the core index primitives in metrics/indicators.py.

calculate_cot_index is the stochastic 0-100 COT index that underpins every
positioning signal in the system, so it (and its siblings) are pinned here
against hand-verifiable inputs.
"""

import numpy as np
import pandas as pd
import pytest

import cotmetrics.constants as const
from cotmetrics import indicators


# ── calculate_cot_index (stochastic 0-100 normalization) ────────────────────
def test_cot_index_at_window_max_is_100():
    s = pd.Series([0.0, 10.0, 20.0, 30.0, 40.0])
    assert indicators.calculate_cot_index(s, 0, 4) == pytest.approx(100.0)


def test_cot_index_at_window_min_is_0():
    s = pd.Series([40.0, 30.0, 20.0, 10.0, 0.0])
    assert indicators.calculate_cot_index(s, 0, 4) == pytest.approx(0.0)


def test_cot_index_midpoint():
    s = pd.Series([0.0, 100.0, 50.0])  # current (idx 2) sits halfway in [0, 100]
    assert indicators.calculate_cot_index(s, 0, 2) == pytest.approx(50.0)


def test_cot_index_respects_lookback_window_start():
    # Only [idx 2 .. idx 4] is considered; the earlier extreme is ignored.
    s = pd.Series([1000.0, -1000.0, 10.0, 20.0, 30.0])
    # window = [10, 20, 30]; current 30 -> max -> 100
    assert indicators.calculate_cot_index(s, 2, 4) == pytest.approx(100.0)


def test_cot_index_flat_window_returns_zero():
    s = pd.Series([5.0, 5.0, 5.0])
    assert indicators.calculate_cot_index(s, 0, 2) == 0


def test_cot_index_nan_returns_zero():
    s = pd.Series([np.nan, np.nan])
    assert indicators.calculate_cot_index(s, 0, 1) == 0


# ── calculate_z_score ───────────────────────────────────────────────────────
def test_z_score_constant_series_is_zero_and_no_nan():
    s = pd.Series([7.0] * 20)
    z = indicators.calculate_z_score(s, lb_weeks=5)
    assert len(z) == 20
    assert not z.isna().any()
    assert z.abs().max() == pytest.approx(0.0)


def test_z_score_positive_for_upside_outlier():
    s = pd.Series([10.0] * 10 + [100.0])  # last point far above its window mean
    z = indicators.calculate_z_score(s, lb_weeks=5)
    assert z.iloc[-1] > 0


# ── calculate_momentum_index ────────────────────────────────────────────────
def test_momentum_constant_series_is_zero():
    s = pd.Series([3.0] * 30)
    mom = indicators.calculate_momentum_index(s)
    assert mom.abs().max() == pytest.approx(0.0)


def test_momentum_linear_series_equals_period():
    p = const.MOMENTUM_PERIOD
    s = pd.Series(np.arange(3 * p, dtype=float))
    mom = indicators.calculate_momentum_index(s)
    assert (mom.iloc[:p] == 0).all()          # leading window filled with 0
    assert mom.iloc[-1] == pytest.approx(p)   # arange diff over p bars == p


# ── calculate_willco (Williams %R style 0-100) ──────────────────────────────
def test_willco_at_top_is_100():
    s = pd.Series([0.0, 50.0, 100.0])
    val = indicators.calculate_willco(s, 0, 2)
    assert val == 100
    assert isinstance(val, int)


def test_willco_at_bottom_is_0():
    s = pd.Series([100.0, 50.0, 0.0])
    assert indicators.calculate_willco(s, 0, 2) == 0


def test_willco_midpoint():
    s = pd.Series([0.0, 100.0, 50.0])
    assert indicators.calculate_willco(s, 0, 2) == 50


# ── rolling forms: must equal the per-row calls they replaced, exactly ─────────
# process_lookback used to call calculate_cot_index / calculate_willco once per
# row. The rolling forms exist only for speed (they were ~95% of a rebuild), so
# the contract is equality with the per-row call at every row, NaN placement
# included, not closeness.
def _messy_series(n=300, seed=7):
    rng = np.random.default_rng(seed)
    s = pd.Series(np.round(rng.normal(0, 1000, n)))  # integer-valued, like net contracts
    s.iloc[[3, 40, 41, 42, 150]] = np.nan              # isolated and clustered gaps
    s.iloc[200:210] = 5.0                              # a flat stretch
    s.iloc[60:80] = np.nan                             # a gap wider than a short window
    return s


@pytest.mark.parametrize("lb", [0, 1, 15, 26, 52, 156, 400])
def test_rolling_cot_index_equals_per_row(lb):
    s = _messy_series()
    got = indicators.rolling_cot_index(s, lb)
    for i in range(len(s)):
        if i < lb:
            assert np.isnan(got.iloc[i])
        else:
            assert got.iloc[i] == indicators.calculate_cot_index(s, i - lb, i), i


def test_rolling_cot_index_negative_lookback_is_all_nan():
    assert indicators.rolling_cot_index(_messy_series(), -1).isna().all()


@pytest.mark.parametrize("lb", [1, 26, 52])
def test_rolling_willco_equals_per_row(lb):
    s = _messy_series().fillna(0.0)  # the per-row call raises on NaN
    got = indicators.rolling_willco(s, lb)
    for i in range(lb, len(s)):
        assert got.iloc[i] == indicators.calculate_willco(s, i - lb, i), i
    assert got.iloc[:lb].isna().all()


@pytest.mark.parametrize("lb", [5, 26, 52])
def test_spearman_matches_per_window_reference_with_gaps(lb):
    # Leading NaN prices are the ordinary case (COT history predates the bars), and
    # used to send the whole series down the loop. Clean windows now take the strided
    # path; both must agree with a plain per-window reference, exactly.
    rng = np.random.default_rng(3)
    n = 250
    price = pd.Series(np.round(rng.normal(100, 5, n), 2))
    price.iloc[:40] = np.nan
    price.iloc[[90, 91, 180]] = np.nan
    price.iloc[120:130] = 100.0            # ties and a flat window
    pos = pd.Series(np.round(rng.normal(0, 1000, n)))
    pos.iloc[[60, 200]] = np.nan
    df = pd.DataFrame({"p": price, "q": pos})

    got = indicators.calculate_spearman_correlation_vectorized(df, "p", "q", lb).to_numpy()

    ref = np.full(n, np.nan)
    for i in range(lb - 1, n):
        wp, wq = price.iloc[i - lb + 1:i + 1], pos.iloc[i - lb + 1:i + 1]
        m = wp.notna() & wq.notna()
        wp, wq = wp[m].to_numpy(), wq[m].to_numpy()
        if len(wp) < 2 or wp.min() == wp.max() or wq.min() == wq.max():
            continue
        rp, rq = indicators._pure_numpy_rank_1d(wp), indicators._pure_numpy_rank_1d(wq)
        xm, ym = rp - rp.mean(), rq - rq.mean()
        den = np.sqrt(np.dot(xm, xm) * np.dot(ym, ym))
        ref[i] = np.nan if den == 0 else np.dot(xm, ym) / den
    np.testing.assert_array_equal(got, ref)


@pytest.mark.parametrize("L", [1, 2, 8, 52, 216])
def test_rank_2d_by_sort_equals_broadcast_ranks(L):
    # The 2D ranks moved from a broadcast compare to a sort; the 1D broadcast form is
    # kept and is the reference. Heavy ties (values drawn from a handful), repeated
    # runs, negatives and a signed zero, at widths up to the widest custom lookback.
    rng = np.random.default_rng(L)
    A = rng.integers(-3, 4, size=(300, L)).astype(float)
    A[::7] = rng.normal(0, 1, size=A[::7].shape)       # tie-free rows too
    A[5] = 2.0                                         # an all-tied row
    if L > 1:
        A[6, :2] = [0.0, -0.0]                         # -0.0 ties with 0.0
    got = indicators._pure_numpy_rank_2d(A)
    for r in range(A.shape[0]):
        np.testing.assert_array_equal(got[r], indicators._pure_numpy_rank_1d(A[r]))
