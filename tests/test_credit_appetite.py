"""Credit appetite and divergence days: the Python side of npf's credit_xray.pine.

What is pinned: ``percent_rank`` is Pine's (previous values only, ties count), the
appetite reproduces an independent loop written the way agi's reference is, the zone
edges are the pane's strict comparisons, and the divergence thresholds use the Hazen
rule, which is what TradingView's ``ta.percentile_linear_interpolation`` was measured to
be on 2026-11-15 (same six risk-off days over 300 sessions, thresholds to five decimals).
"""

import numpy as np
import pandas as pd
import pytest

from cotmetrics import indicators as ind


def _pair(n=400, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n, name="Date")
    junk = pd.Series(90 * np.exp(np.cumsum(rng.normal(0, 0.004, n))), index=idx)
    treasuries = pd.Series(85 * np.exp(np.cumsum(rng.normal(0, 0.008, n))), index=idx)
    return junk, treasuries


def test_percent_rank_counts_previous_values_at_or_below_the_current_one():
    s = pd.Series([1.0, 2.0, 3.0, 2.0, 5.0, 0.0])
    out = ind.percent_rank(s, 3)
    assert out.iloc[:3].isna().all()            # three PREVIOUS values are needed
    assert out.iloc[3] == pytest.approx(200 / 3)   # 1, 2 <= 2; the tie counts
    assert out.iloc[4] == 100.0                 # a new high is 100, not ranked with itself
    assert out.iloc[5] == 0.0


def test_percent_rank_is_nan_where_the_window_holds_one():
    out = ind.percent_rank(pd.Series([1.0, np.nan, 3.0, 4.0, 5.0, 6.0]), 2)
    assert np.isnan(out.iloc[2]) and np.isnan(out.iloc[3]) and out.iloc[4] == 100.0


def test_appetite_reproduces_an_independent_loop():
    """agi/credit_appetite.py's arithmetic, restated: plain lists, no pandas."""
    junk, treasuries = _pair()
    ma, rank = ind.CREDIT_AVERAGE_DAYS, ind.CREDIT_RANK_DAYS
    ratio = [j / t for j, t in zip(junk, treasuries)]
    n = len(ratio)
    dev = [None] * n
    for i in range(ma - 1, n):
        dev[i] = (ratio[i] / (sum(ratio[i - ma + 1:i + 1]) / ma) - 1) * 100
    expected = [None] * n
    for i in range(ma - 1 + rank, n):
        expected[i] = 100.0 * sum(p <= dev[i] for p in dev[i - rank:i]) / rank
    got = ind.credit_appetite(junk, treasuries)
    assert got.iloc[:ma - 1 + rank].isna().all()
    assert got.iloc[ma - 1 + rank:].tolist() == pytest.approx(expected[ma - 1 + rank:])
    assert ind.credit_ratio_deviation(junk, treasuries).iloc[ma - 1:].tolist() == \
        pytest.approx(dev[ma - 1:])


def test_series_are_joined_on_their_shared_sessions():
    junk, treasuries = _pair(60)
    out = ind.credit_gap(junk, treasuries.drop(treasuries.index[10]))
    assert treasuries.index[10] not in out.index and len(out) == 59


@pytest.mark.parametrize("value, zone", [
    (0.0, "stress"), (19.99, "stress"),
    (20.0, "neutral"),          # the pane tests `appetite < 20`
    (50.0, "neutral"),
    (80.0, "neutral"),          # and `appetite > 80`
    (80.01, "comfort"), (100.0, "comfort"),
    (float("nan"), None), (None, None),
])
def test_credit_zone_edges_are_the_panes(value, zone):
    assert ind.credit_zone(value) == zone


def test_credit_zone_refuses_a_fraction_scale_mistake_out_of_range():
    with pytest.raises(ValueError, match="percent"):
        ind.credit_zone(120.0)


def test_the_gap_is_treasuries_change_minus_junks_in_points():
    junk = pd.Series([100.0, 99.0, 99.0])
    treasuries = pd.Series([100.0, 101.0, 100.0])
    gap = ind.credit_gap(junk, treasuries)
    assert gap.iloc[1] == pytest.approx(2.0)                    # +1% against -1%
    assert gap.iloc[2] == pytest.approx(-100 / 101)


def _flat_then(junk_move, treasury_move, n=30):
    """n quiet sessions of small same-direction moves, then one chosen day."""
    idx = pd.bdate_range("2025-01-01", periods=n + 1)
    quiet = np.resize([0.001, -0.001, 0.002, -0.002], n - 1)
    j = np.concatenate([[100.0], 100 * np.cumprod(1 + quiet)])
    t = np.concatenate([[100.0], 100 * np.cumprod(1 + quiet * 1.5)])
    return (pd.Series(np.append(j, j[-1] * (1 + junk_move)), index=idx),
            pd.Series(np.append(t, t[-1] * (1 + treasury_move)), index=idx))


def test_a_divergence_day_needs_the_split_and_the_tail():
    off = ind.credit_divergence(*_flat_then(-0.01, 0.01), rank_days=20)
    assert off.iloc[-1] == "risk_off" and off.iloc[:-1].isna().all()
    on = ind.credit_divergence(*_flat_then(0.01, -0.01), rank_days=20)
    assert on.iloc[-1] == "risk_on"
    # A wide gap with both funds DOWN is rates, not credit: no flag.
    assert ind.credit_divergence(*_flat_then(-0.03, -0.001), rank_days=20).iloc[-1] is None
    # A split too small to reach the tail is an ordinary day.
    assert ind.credit_divergence(*_flat_then(-0.00001, 0.00001), rank_days=20).iloc[-1] is None


def test_the_threshold_is_hazens_and_excludes_the_day_itself():
    """Pine's ta.percentile_linear_interpolation, measured: Hazen, over gap[1]."""
    junk, treasuries = _pair(300, seed=11)
    gap = ind.credit_gap(junk, treasuries)
    rj, rt = junk.pct_change(), treasuries.pct_change()
    flags = ind.credit_divergence(junk, treasuries, rank_days=100)
    for i in range(101, 300):
        prev = gap.iloc[i - 100:i].values
        hi = np.percentile(prev, 95, method="hazen")
        lo = np.percentile(prev, 5, method="hazen")
        want = ("risk_off" if rt.iloc[i] > 0 and rj.iloc[i] < 0 and gap.iloc[i] >= hi else
                "risk_on" if rt.iloc[i] < 0 and rj.iloc[i] > 0 and gap.iloc[i] <= lo else None)
        assert flags.iloc[i] == want, i
    assert flags.iloc[:101].isna().all()
    assert set(flags.dropna()) == {"risk_off", "risk_on"}       # both arms exercised
