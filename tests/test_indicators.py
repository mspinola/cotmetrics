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
