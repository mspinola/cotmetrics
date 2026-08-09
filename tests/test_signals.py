"""Golden tests for the pure geometric functions in metrics/signals.py:
calculate_reversal_matrices (candle rejection scores) and
flag_capitulation_events (blow-off flags). Both are pure DataFrame transforms.
"""
import numpy as np
import pandas as pd

import cotmetrics.constants as const
from cotmetrics import signals


def test_reversal_matrices_flags_bullish_rejection_candle():
    # Last bar closes near its high off a deep low -> strong bullish push.
    df = pd.DataFrame({
        "Close": [100, 100, 108],
        "High":  [101, 101, 110],
        "Low":   [ 99,  99, 100],
    })
    out = signals.calculate_reversal_matrices(df, atr_window=14)
    # bull_push = (108-100)/TR(=10) = 0.8 > 0.65 -> positive score
    assert out[const.BULL_REJECTION_SCORE].iloc[-1] > 0
    # bear_push = (110-108)/10 = 0.2 < 0.65 -> no bearish score
    assert out[const.BEAR_REJECTION_SCORE].iloc[-1] == 0.0


def test_reversal_matrices_no_score_for_doji():
    # Close sits in the middle of the range -> neither side pushes >65%.
    df = pd.DataFrame({
        "Close": [100, 100, 105],
        "High":  [101, 101, 110],
        "Low":   [ 99,  99, 100],
    })
    out = signals.calculate_reversal_matrices(df)
    assert out[const.BULL_REJECTION_SCORE].iloc[-1] == 0.0
    assert out[const.BEAR_REJECTION_SCORE].iloc[-1] == 0.0


def test_reversal_matrices_drops_intermediate_columns():
    df = pd.DataFrame({"Close": [1, 2, 3], "High": [2, 3, 4], "Low": [0, 1, 2]})
    out = signals.calculate_reversal_matrices(df)
    for tmp in ("prev_close", "tr0", "tr1", "tr2"):
        assert tmp not in out.columns


def test_capitulation_flags_bullish_blowoff():
    df = pd.DataFrame({
        const.BULL_REJECTION_SCORE: [0.0, 2.0],
        const.BEAR_REJECTION_SCORE: [0.0, 0.0],
        const.OI_ACCELERATION:      [0.0, 1.5],
        const.LIQUIDITY_STRAIN_CUSTOM: [0.0, -2.0],
    })
    out = signals.flag_capitulation_events(df)
    assert out[const.FLAG_BULL_CAPITULATION].tolist() == [0, 1]
    assert out[const.FLAG_BEAR_CAPITULATION].tolist() == [0, 0]


def test_capitulation_flags_bearish_blowoff():
    df = pd.DataFrame({
        const.BULL_REJECTION_SCORE: [0.0, 0.0],
        const.BEAR_REJECTION_SCORE: [0.0, 2.0],
        const.OI_ACCELERATION:      [0.0, 1.5],
        const.LIQUIDITY_STRAIN_CUSTOM: [0.0, 2.0],
    })
    out = signals.flag_capitulation_events(df)
    assert out[const.FLAG_BEAR_CAPITULATION].tolist() == [0, 1]
    assert out[const.FLAG_BULL_CAPITULATION].tolist() == [0, 0]


def test_capitulation_flags_default_zero_when_columns_missing():
    # Missing input columns should be treated as 0.0, not raise.
    df = pd.DataFrame({"unrelated": [1, 2, 3]})
    out = signals.flag_capitulation_events(df)
    assert (out[const.FLAG_BULL_CAPITULATION] == 0).all()
    assert (out[const.FLAG_BEAR_CAPITULATION] == 0).all()


def test_capitulation_requires_all_three_conditions():
    # Strong rejection + OI accel but strain not squeezed -> no flag.
    df = pd.DataFrame({
        const.BULL_REJECTION_SCORE: [2.0],
        const.OI_ACCELERATION:      [1.5],
        const.LIQUIDITY_STRAIN_CUSTOM: [0.0],  # not <= -1.0
    })
    out = signals.flag_capitulation_events(df)
    assert out[const.FLAG_BULL_CAPITULATION].tolist() == [0]


# ---------------------------------------------------------------------------
# Point-in-time guard for the weekly rejection feature.
#
# Mirrors pardo's tests/integration/test_integration_feature_asof.py. The weekly
# score is keyed by the COT cutoff and later as-of-joined onto trade entries, which
# fall AFTER the cutoff. The old feature summarized the post-cutoff window (which
# straddles the entry), leaking post-entry price. The prior-week window must read
# only bars up to and including the cutoff, so a huge rejection ON or AFTER the
# cutoff (i.e. on/after the entry) can never enter the feature, while a rejection
# strictly before it is captured. See pardo docs/cmr_ml_lookahead.md.
# ---------------------------------------------------------------------------


def test_prior_week_window_excludes_post_cutoff_bars():
    dates = pd.date_range("2021-01-04", periods=10, freq="D")
    df = pd.DataFrame(
        {const.BULL_REJECTION_SCORE: 0.0, const.BEAR_REJECTION_SCORE: 0.0},
        index=dates,
    )
    cot_date = dates[5]
    w = signals.prior_week_rejection_window(df, cot_date, lookback_days=7)
    # every returned bar is <= the cutoff; nothing after it (where the entry lives)
    assert (w.index <= cot_date).all(), "prior-week window leaked a post-cutoff bar"
    assert w.index.max() == cot_date, "window must include the cutoff bar itself"
    assert (w.index > cot_date).sum() == 0


def test_post_cutoff_rejection_does_not_leak_into_window():
    """A massive rejection ON the cutoff-successor bars (the entry / post-entry bars)
    must be invisible; a rejection strictly before the cutoff is the honest signal."""
    dates = pd.date_range("2021-01-04", periods=10, freq="D")
    cot_date = dates[5]
    bull = np.zeros(10)
    bull[3] = 2.4    # strictly before the cutoff -> honest, must be captured
    bull[6] = 99.0   # first bar after the cutoff (~the entry) -> must NOT leak
    bull[7] = 99.0   # post-entry -> must NOT leak
    df = pd.DataFrame(
        {const.BULL_REJECTION_SCORE: bull, const.BEAR_REJECTION_SCORE: np.zeros(10)},
        index=dates,
    )
    w = signals.prior_week_rejection_window(df, cot_date, lookback_days=7)
    assert w[const.BULL_REJECTION_SCORE].max() == 2.4


def _rejection_ohlc(dates, monster_post=False):
    """Flat doji bars, with one honest bull rejection strictly before the cutoff and,
    optionally, enormous rejections on the post-cutoff (entry / post-entry) bars."""
    n = len(dates)
    openp = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    close = np.full(n, 100.0)
    # honest bull rejection strictly BEFORE the cutoff (idx 3): close near high off a deep low
    low[3] = 90.0
    high[3] = 100.6
    close[3] = 100.5
    if monster_post:
        # enormous bull rejections AFTER the cutoff (idx 7, 8) — the entry / post-entry bars
        for j in (7, 8):
            low[j] = 40.0
            high[j] = 101.0
            close[j] = 100.9
    return pd.DataFrame(
        {"Open": openp, "High": high, "Low": low, "Close": close}, index=dates
    )


def test_compute_weekly_rejection_scores_ignores_post_cutoff_bars(monkeypatch):
    """End-to-end: the weekly feature at the cutoff is identical whether the post-cutoff
    bars are calm or violently rejecting — proving those bars never enter the window.
    The old forward-window implementation would have captured the monster spike."""
    dates = pd.date_range("2021-01-04", periods=12, freq="D")
    cot_date = dates[5]
    cot_index = pd.DatetimeIndex([cot_date])

    monkeypatch.setattr(signals.marketdata, "get_bars",
                        lambda *a, **k: _rejection_ohlc(dates, monster_post=False))
    calm = signals.compute_weekly_rejection_scores("TEST", cot_index)

    monkeypatch.setattr(signals.marketdata, "get_bars",
                        lambda *a, **k: _rejection_ohlc(dates, monster_post=True))
    monster = signals.compute_weekly_rejection_scores("TEST", cot_index)

    # the honest pre-cutoff rejection is captured...
    assert calm[const.BULL_REJECTION_SCORE].iloc[0] > 0
    # ...and the monstrous post-cutoff bars change nothing (never in the window)
    assert (monster[const.BULL_REJECTION_SCORE].iloc[0]
            == calm[const.BULL_REJECTION_SCORE].iloc[0])
