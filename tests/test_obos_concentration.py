"""Tests for the Keenan OBOS-Concentration prototype:
- metrics.indicators.calculate_range_index (the Positioning-Component transform)
- the obos_oversold / obos_overbought setup wired into append_trading_signals.

The setup fires where a speculative-Concentration extreme (top quartile of its own
52-week range) coincides with a price extreme (existing structural top/bottom).
On the Legacy store LARGE = NonCommercial, so this is Keenan's NC Concentration
proxy for MM (see docs/spec_positioning_metrics_trio.md).
"""
import numpy as np
import pandas as pd
import pytest

import cotmetrics.constants as const
from cotmetrics import signals
from cotmetrics.indicators import calculate_range_index


# --------------------------------------------------------------------------- #
# calculate_range_index
# --------------------------------------------------------------------------- #
def test_range_index_ramp_hits_100_at_top():
    # Monotonic ramp: the last point is the window max -> index 100.
    s = pd.Series(np.arange(60, dtype=float))
    idx = calculate_range_index(s, window=52)
    assert idx.iloc[-1] == pytest.approx(100.0)


def test_range_index_bottom_is_zero():
    # Last point is the window min -> index 0.
    s = pd.Series(np.arange(60, 0, -1, dtype=float))
    idx = calculate_range_index(s, window=52)
    assert idx.iloc[-1] == pytest.approx(0.0)


def test_range_index_flat_window_is_nan():
    # Zero span -> degenerate -> NaN (which downstream thresholds treat as no-signal).
    s = pd.Series(np.full(60, 7.0))
    idx = calculate_range_index(s, window=52)
    assert np.isnan(idx.iloc[-1])


def test_range_index_insufficient_history_is_nan():
    s = pd.Series(np.arange(10, dtype=float))
    idx = calculate_range_index(s, window=52)
    assert idx.isna().all()


def test_range_index_midpoint():
    # Window = [0..50] + [25]: min 0, max 50, last 25 -> exactly halfway -> 50.
    s = pd.Series([float(i) for i in range(51)] + [25.0])
    idx = calculate_range_index(s, window=52)
    assert idx.iloc[-1] == pytest.approx(50.0)


# --------------------------------------------------------------------------- #
# OBOS setup wired into append_trading_signals
# --------------------------------------------------------------------------- #
N = 120


def _benign_frame(n=N):
    """A full frame with every column append_trading_signals reads, all benign
    (no other setup fires). Scenario tests override concentration + price only."""
    z = np.zeros(n)
    fifty = np.full(n, 50.0)
    oi = np.full(n, 500_000.0)
    flat_price = np.full(n, 100.0)
    return pd.DataFrame({
        const.OPEN_INTEREST_XLS: oi,
        const.OPEN_INTEREST: oi,
        const.CLOSING_PRICE: flat_price.copy(),
        const.OPEN_PRICE: flat_price.copy(),
        const.HIGH_PRICE: flat_price.copy(),
        const.LOW_PRICE: flat_price.copy(),
        const.PRICE_CHANGE: z.copy(),
        const.COMM_NET: z.copy(),
        const.COMM_PCT_OI: z.copy(),
        const.LARGE_CUSTOM_IDX: fifty.copy(),
        const.LARGE_LONG_POS_XLS: np.full(n, 100_000.0),
        const.LARGE_SHORT_POS_XLS: np.full(n, 100_000.0),
        const.COMM_LONG_POS_XLS: np.full(n, 100_000.0),
        const.COMM_SHORT_POS_XLS: np.full(n, 100_000.0),
        "comms_idx": fifty.copy(), "lrg_idx": fifty.copy(), "sml_idx": fifty.copy(),
        "comms_zscore": z.copy(), "lrg_zscore": z.copy(), "sml_zscore": z.copy(),
        "comms_spearman": z.copy(), "lrg_spearman": z.copy(), "sml_spearman": z.copy(),
        const.COMM_MOMENTUM: z.copy(), const.LRG_MOMENTUM: z.copy(), const.SML_MOMENTUM: z.copy(),
        const.COMM_3Y_IDX: fifty.copy(), const.COMM_3Y_IDX_NORM: fifty.copy(),
        "oi_zscore": z.copy(), "willco": fifty.copy(),
    })


def test_obos_columns_are_created():
    out = signals.append_trading_signals(_benign_frame(), asset_class="Energy")
    for col in (const.OBOS_OVERSOLD, const.OBOS_OVERBOUGHT,
                const.OBOS_OVERSOLD_DECILE, const.OBOS_OVERBOUGHT_DECILE,
                const.OBOS_COMM_OVERSOLD, const.OBOS_COMM_OVERBOUGHT,
                const.OBOS_COMM_OVERSOLD_DECILE, const.OBOS_COMM_OVERBOUGHT_DECILE,
                const.OBOS_MM_OVERSOLD_DECILE, const.OBOS_MM_OVERBOUGHT_DECILE,
                const.OBOS_MM_CLUST_OVERSOLD_DECILE, const.OBOS_MM_CLUST_OVERBOUGHT_DECILE,
                const.OBOS_MM_PSIZE_OVERSOLD_DECILE, const.OBOS_MM_PSIZE_OVERBOUGHT_DECILE,
                const.OBOS_MM_TRIPLE_OVERSOLD_DECILE, const.OBOS_MM_TRIPLE_OVERBOUGHT_DECILE,
                const.OBOS_LEV_OVERSOLD_DECILE, const.OBOS_LEV_OVERBOUGHT_DECILE,
                const.OBOS_LEV_TRIPLE_OVERSOLD_DECILE, const.OBOS_LEV_TRIPLE_OVERBOUGHT_DECILE,
                const.LARGE_LONG_CONC, const.LARGE_SHORT_CONC,
                const.LARGE_LONG_CONC_IDX, const.LARGE_SHORT_CONC_IDX,
                const.COMM_LONG_CONC, const.COMM_SHORT_CONC,
                const.COMM_LONG_CONC_IDX, const.COMM_SHORT_CONC_IDX):
        assert col in out.columns


def test_concentration_is_gross_pct_of_oi():
    df = _benign_frame()
    df[const.LARGE_LONG_POS_XLS] = 100_000.0   # 100k / 500k = 20%
    out = signals.append_trading_signals(df, asset_class="Energy")
    assert out[const.LARGE_LONG_CONC].iloc[-1] == pytest.approx(20.0)


def test_oversold_fires_on_short_extreme_at_price_bottom():
    df = _benign_frame()
    # Price declines 120 -> 100: last bar sits at the structural bottom.
    df[const.CLOSING_PRICE] = np.linspace(120.0, 100.0, N)
    # Short concentration low for the whole window, then spikes on the last bar
    # -> LARGE_SHORT_CONC_IDX == 100 (top quartile).
    short_pos = np.full(N, 50_000.0)   # 10% of OI
    short_pos[-1] = 150_000.0          # 30% of OI -> window max
    df[const.LARGE_SHORT_POS_XLS] = short_pos
    out = signals.append_trading_signals(df, asset_class="Energy")
    assert bool(out[const.OBOS_OVERSOLD].iloc[-1]) is True
    assert bool(out[const.OBOS_OVERBOUGHT].iloc[-1]) is False


def test_overbought_fires_on_long_extreme_at_price_top():
    df = _benign_frame()
    # Price rises 100 -> 120: last bar sits at the structural top.
    df[const.CLOSING_PRICE] = np.linspace(100.0, 120.0, N)
    long_pos = np.full(N, 50_000.0)
    long_pos[-1] = 150_000.0
    df[const.LARGE_LONG_POS_XLS] = long_pos
    out = signals.append_trading_signals(df, asset_class="Energy")
    assert bool(out[const.OBOS_OVERBOUGHT].iloc[-1]) is True
    assert bool(out[const.OBOS_OVERSOLD].iloc[-1]) is False


def test_true_mm_signal_absent_without_disagg_columns():
    # Financials (no disaggregated report) → MM columns absent → signal all-False,
    # no crash, and no MM concentration columns are fabricated.
    out = signals.append_trading_signals(_benign_frame(), asset_class="Financial")
    assert not out[const.OBOS_MM_OVERSOLD_DECILE].any()
    assert const.MM_LONG_CONC not in out.columns


def test_true_mm_oversold_fires_with_disagg_columns():
    df = _benign_frame()
    df[const.CLOSING_PRICE] = np.linspace(120.0, 100.0, N)          # price at decile bottom
    df[const.MM_LONG_POS_XLS] = np.full(N, 100_000.0)
    mm_short = np.full(N, 50_000.0)
    mm_short[-1] = 200_000.0  # MM short conc spikes → decile
    df[const.MM_SHORT_POS_XLS] = mm_short
    out = signals.append_trading_signals(df, asset_class="Energy")
    assert const.MM_SHORT_CONC_IDX in out.columns
    assert bool(out[const.OBOS_MM_OVERSOLD_DECILE].iloc[-1]) is True


def test_true_mm_triple_fires_when_all_three_legs_extreme():
    df = _benign_frame()
    df[const.CLOSING_PRICE] = np.linspace(120.0, 100.0, N)          # price at decile bottom
    df[const.MM_LONG_POS_XLS] = np.full(N, 100_000.0)
    df[const.MM_LONG_TRADERS_XLS] = np.full(N, 50.0)
    # Short legs all spike on the last bar: OI, trader count, and total-trader share.
    mm_short = np.full(N, 50_000.0)
    mm_short[-1] = 200_000.0  # Concentration + Position Size ↑
    mm_short_tr = np.full(N, 20.0)
    mm_short_tr[-1] = 60.0  # Clustering + trader count ↑
    df[const.MM_SHORT_POS_XLS] = mm_short
    df[const.MM_SHORT_TRADERS_XLS] = mm_short_tr
    df[const.TOT_TRADERS_XLS] = np.full(N, 200.0)
    out = signals.append_trading_signals(df, asset_class="Energy")
    assert const.MM_SHORT_PSIZE_IDX in out.columns
    assert const.MM_SHORT_CLUST_IDX in out.columns
    assert bool(out[const.OBOS_MM_TRIPLE_OVERSOLD_DECILE].iloc[-1]) is True


def test_tff_lev_triple_fires_with_leveraged_funds_columns():
    # Financials carry the LEV group; same decile-triple structure as MM.
    df = _benign_frame()
    df[const.CLOSING_PRICE] = np.linspace(120.0, 100.0, N)          # price at decile bottom
    df[const.LEV_LONG_POS_XLS] = np.full(N, 100_000.0)
    df[const.LEV_LONG_TRADERS_XLS] = np.full(N, 50.0)
    lev_short = np.full(N, 50_000.0)
    lev_short[-1] = 200_000.0
    lev_short_tr = np.full(N, 20.0)
    lev_short_tr[-1] = 60.0
    df[const.LEV_SHORT_POS_XLS] = lev_short
    df[const.LEV_SHORT_TRADERS_XLS] = lev_short_tr
    df[const.TOT_TRADERS_XLS] = np.full(N, 200.0)
    out = signals.append_trading_signals(df, asset_class="Financial")
    assert const.LEV_SHORT_PSIZE_IDX in out.columns
    assert bool(out[const.OBOS_LEV_TRIPLE_OVERSOLD_DECILE].iloc[-1]) is True
    # MM and LEV are disjoint: no MM data here → MM triple stays False.
    assert not out[const.OBOS_MM_TRIPLE_OVERSOLD_DECILE].any()


def test_true_mm_clustering_absent_without_trader_columns():
    # MM positions but no trader counts → Clustering/Position-Size stay all-False.
    df = _benign_frame()
    df[const.MM_LONG_POS_XLS] = np.full(N, 100_000.0)
    df[const.MM_SHORT_POS_XLS] = np.full(N, 100_000.0)
    out = signals.append_trading_signals(df, asset_class="Energy")
    assert not out[const.OBOS_MM_CLUST_OVERSOLD_DECILE].any()
    assert not out[const.OBOS_MM_TRIPLE_OVERSOLD_DECILE].any()
    assert const.MM_LONG_CLUST not in out.columns


def test_no_signal_when_positioning_not_extreme():
    df = _benign_frame()
    df[const.CLOSING_PRICE] = np.linspace(120.0, 100.0, N)  # price bottom, but...
    df[const.LARGE_SHORT_POS_XLS] = np.full(N, 100_000.0)   # ...flat concentration -> NaN idx
    out = signals.append_trading_signals(df, asset_class="Energy")
    assert bool(out[const.OBOS_OVERSOLD].iloc[-1]) is False
