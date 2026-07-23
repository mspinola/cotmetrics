import math

import numpy as np
import pandas as pd

import cotmetrics.constants as const


def atr(df, n=14):
    high_low = df[const.HIGH_PRICE] - df[const.LOW_PRICE]
    high_close = np.abs(df[const.HIGH_PRICE] - df[const.CLOSING_PRICE].shift())
    low_close = np.abs(df[const.LOW_PRICE] - df[const.CLOSING_PRICE].shift())

    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(window=n).mean()
    return atr


def calculate_z_score(col_to_search, lb_weeks):
    roll_mean = col_to_search.rolling(window=lb_weeks).mean()
    roll_std = col_to_search.rolling(window=lb_weeks).std()
    z_score = (col_to_search - roll_mean) / (roll_std + 1e-9)
    # infer_objects before fillna: coerce object-but-numeric to a numeric dtype
    # first, so fillna(0) doesn't trigger the deprecated silent-downcast path.
    z_score = z_score.infer_objects(copy=False).fillna(0)
    return z_score


def calculate_cot_index(col_to_search, lb_idx, cur_idx):
    range_to_search = col_to_search[lb_idx:cur_idx+1]
    min_net = range_to_search.min()
    max_net = range_to_search.max()
    cur_net = col_to_search[cur_idx]
    result = (cur_net - min_net) / (max_net - min_net + 1e-9) * 100
    result = 0 if math.isnan(result) else round(result, 0)
    return result


def calculate_spearman_correlation(closing_price_col, pos_col, lb_weeks, nan_val=0.0):
    corrs = []
    for i in range(len(closing_price_col)):
        if i < lb_weeks - 1:
            corrs.append(nan_val)
        else:
            w_price = closing_price_col.iloc[i - lb_weeks + 1 : i + 1]
            w_pos = pos_col.iloc[i - lb_weeks + 1 : i + 1]

            # Extract valid overlapping pairs
            valid_mask = w_price.notna() & w_pos.notna()
            w_price_valid = w_price[valid_mask]
            w_pos_valid = w_pos[valid_mask]

            # Avoid covariance and zero-variance warnings by validating the slice
            if len(w_price_valid) < 2 or w_price_valid.nunique() <= 1 or w_pos_valid.nunique() <= 1:
                corr = 0.0
            else:
                corr = w_price_valid.rank().corr(w_pos_valid.rank())

            corrs.append(nan_val if pd.isna(corr) else corr)
    return pd.Series(corrs, index=closing_price_col.index)


def _pure_numpy_rank_2d(A):
    # Broadcast compare to rank along axis 1 (handling ties via average method)
    less_matrix = A[:, :, None] > A[:, None, :]
    equal_matrix = A[:, :, None] == A[:, None, :]
    less_count = less_matrix.sum(axis=-1)
    equal_count = equal_matrix.sum(axis=-1)
    return 1.0 + less_count + 0.5 * (equal_count - 1)


def _pure_numpy_rank_1d(x):
    # Broadcast compare to rank 1D array (handling ties via average method)
    less_matrix = x[:, None] > x
    equal_matrix = x[:, None] == x
    less_count = less_matrix.sum(axis=-1)
    equal_count = equal_matrix.sum(axis=-1)
    return 1.0 + less_count + 0.5 * (equal_count - 1)


def calculate_spearman_correlation_vectorized(df, price_col, pos_col, lb_weeks, fallback_val=np.nan):
    """
    Vectorized, high-performance rolling Spearman Rank Correlation using pure NumPy.
    Eliminates Python loops when no NaNs are present using sliding window strides,
    and falls back to an optimized NumPy loop when NaNs exist to match pandas NaN handling.
    Does not require scipy or external rank packages.
    """
    prices_series = df[price_col]
    pos_series = df[pos_col]

    # Check if there are any NaNs in the inputs
    has_nans = prices_series.isna().any() or pos_series.isna().any()

    prices = prices_series.to_numpy()
    positions = pos_series.to_numpy()
    n = len(prices)

    if n < lb_weeks:
        return pd.Series(np.full(n, fallback_val), index=df.index)

    if not has_nans:
        # 100% Vectorized Path (no loops, extremely fast)
        shape = (n - lb_weeks + 1, lb_weeks)
        strides = (prices.strides[0], prices.strides[0])
        prices_2d = np.lib.stride_tricks.as_strided(prices, shape=shape, strides=strides)

        strides_pos = (positions.strides[0], positions.strides[0])
        pos_2d = np.lib.stride_tricks.as_strided(positions, shape=shape, strides=strides_pos)

        ranks_price = _pure_numpy_rank_2d(prices_2d)
        ranks_pos = _pure_numpy_rank_2d(pos_2d)

        mean_price = ranks_price.mean(axis=-1, keepdims=True)
        mean_pos = ranks_pos.mean(axis=-1, keepdims=True)

        p_centered = ranks_price - mean_price
        pos_centered = ranks_pos - mean_pos

        cov = (p_centered * pos_centered).sum(axis=-1)
        var_p = (p_centered ** 2).sum(axis=-1)
        var_pos = (pos_centered ** 2).sum(axis=-1)

        den = np.sqrt(var_p * var_pos)
        with np.errstate(divide='ignore', invalid='ignore'):
            # Zero-variance (degenerate) windows have an undefined correlation ->
            # fallback (NaN by default so the plot draws a gap rather than a flat 0).
            corr = np.where(den > 0, cov / den, fallback_val)

        result = np.full(n, fallback_val)
        result[lb_weeks - 1:] = corr
        return pd.Series(result, index=df.index)
    else:
        # Optimized NumPy Loop Path (handles NaNs dynamically and matches pandas exactly)
        corrs = np.full(n, fallback_val, dtype=float)
        for i in range(lb_weeks - 1, n):
            w_price = prices[i - lb_weeks + 1 : i + 1]
            w_pos = positions[i - lb_weeks + 1 : i + 1]

            mask = ~np.isnan(w_price) & ~np.isnan(w_pos)
            wp = w_price[mask]
            wpos = w_pos[mask]

            if len(wp) < 2 or wp.min() == wp.max() or wpos.min() == wpos.max():
                corrs[i] = fallback_val
                continue

            r_price = _pure_numpy_rank_1d(wp)
            r_pos = _pure_numpy_rank_1d(wpos)

            mx = r_price.mean()
            my = r_pos.mean()
            xm, ym = r_price - mx, r_pos - my
            r_num = np.dot(xm, ym)
            r_den = np.sqrt(np.dot(xm, xm) * np.dot(ym, ym))

            corrs[i] = fallback_val if r_den == 0 else r_num / r_den

        return pd.Series(corrs, index=df.index)


def calculate_liquidity_strain_ratio_index(comm_net_col, large_net_col, lb_weeks):
    """
    Calculates the Liquidity Strain Ratio (LSR) Index to quantify structural crowding.

    This metric measures the physical contract leverage of speculative trend-followers
    against the baseline absorption capacity of commercial hedgers. By evaluating the
    ratio of Large Speculator net positions to the absolute mass of Commercial net
    positions, it identifies regimes where speculative liquidity demand is severely
    straining or outgrowing institutional liquidity supply.

    The resulting raw ratio is normalized into a rolling Z-score to create a
    bounded, cross-asset indicator.

    Mathematical Mechanics:
        - High Positive Z-Score: Speculators are heavily net long while commercial
          capacity is relatively flat or shrinking (Extreme Long Crowding).
        - High Negative Z-Score: Speculators are heavily net short while commercial
          capacity is relatively flat or shrinking (Extreme Short Crowding).
        - Near Zero: Speculative positioning is flowing safely within normal historical
          limits, or commercials have scaled up open interest to absorb the momentum.

    Args:
        comm_net_col (pd.Series): The net position column for Commercial traders.
        large_net_col (pd.Series): The net position column for Large Speculators.
        lb_weeks (int): The lookback window in weeks for the rolling Z-score normalization.

    Returns:
        pd.Series: A rolling Z-score representing the directional Liquidity Strain Ratio Index.
    """
    # Add 1.0 contract instead of 1e-9 to prevent mathematically exploding floats
    # when commercial positioning is exactly 0 (e.g. in some Crypto or soft markets).
    # Since normal positioning is in the tens of thousands, a 1.0 offset is statistically invisible.
    liquidty_strain = large_net_col / (comm_net_col.abs() + 1.0)
    return calculate_z_score(liquidty_strain, lb_weeks)


def calculate_price_hedging_divergence(df: pd.DataFrame, close_col: str, comm_net_col: str, velocity_window: int = 3, macro_window: int = 26) -> pd.Series:
    """
    Calculates PRICE_HEDGING_DIVERGENCE: The kinetic friction between immediate price momentum
    and commercial accumulation/distribution rates.

    Args:
        df (pd.DataFrame): DataFrame containing price and COT data.
        close_col (str): The column name for the asset's closing price.
        comm_net_col (str): The column name for the Commercial Net position.
        velocity_window (int): Lookback period for immediate rate-of-change (default 3 weeks).
        macro_window (int): The rolling window to normalize the Z-scores (default 26 or 52 weeks).

    Returns:
        pd.Series: The TENSION_VELOCITY metric as a bounded Z-Score.
    """

    # Helper function to generate safe rolling Z-scores, preventing division by zero
    def safe_zscore(series: pd.Series, window: int) -> pd.Series:
        rolling_mean = series.rolling(window=window, min_periods=4).mean()
        rolling_std = series.rolling(window=window, min_periods=4).std()
        # Fallback to a small number (0.05) if std is 0 to avoid NaNs during flatlines
        safe_std = np.where((rolling_std > 0) & (rolling_std.notna()), rolling_std, 0.05)
        return (series - rolling_mean) / safe_std

    # Step 1: Standardized Price Velocity
    # Measures the immediate directional momentum of the asset
    price_roc = df[close_col] - df[close_col].shift(velocity_window)
    price_vel_z = safe_zscore(price_roc, macro_window)

    # Step 2: Standardized Commercial Velocity
    # Measures the immediate accumulation/distribution rate of the smart money
    comm_roc = df[comm_net_col] - df[comm_net_col].shift(velocity_window)
    comm_vel_z = safe_zscore(comm_roc, macro_window)

    # Step 3: Raw Tension (The Kinetic Mismatch)
    # E.g., If price drops (-2.0 Z) but commercials violently buy (+2.0 Z),
    # the mismatch is (+2.0) - (-2.0) = +4.0 (A massive Bull Coil)
    price_hedging_divergence_raw = comm_vel_z - price_vel_z

    # Step 4: Final Macro Normalization
    # Converts the raw divergence back into a clean -2.0 to +2.0 scale for the ML model
    price_hedging_divergence_z = safe_zscore(price_hedging_divergence_raw, macro_window)

    return pd.Series(price_hedging_divergence_z, index=df.index).fillna(0.0)


def calculate_momentum_index(col_to_search, periods=None):
    """Point change on a 0-100 index over `periods` weekly reports.

    Not a rate of change: a percentage move on a bounded index is distorted at the
    ends, where 5 -> 10 is +100% but only +5 points. Defaults to MOMENTUM_PERIOD;
    pass 1 for the week-over-week delta the movers leaderboard ranks on.
    """
    result = col_to_search - col_to_search.shift(
        const.MOMENTUM_PERIOD if periods is None else periods
    )
    # infer_objects before fillna: coerce object-but-numeric to a numeric dtype
    # first, so fillna(0) doesn't trigger the deprecated silent-downcast path.
    result = result.infer_objects(copy=False).fillna(0)
    return result


def calculate_range_index(series, window=52, min_periods=None):
    """Vectorised rolling min-max range index, 0-100 (Keenan's OBOS Positioning-Component
    transform): 100 * (x - rolling_min) / (rolling_max - rolling_min).

    Same math as ``calculate_cot_index``/``calculate_willco`` but computed over the whole
    series in one pass (rolling window) instead of a single (lb_idx, cur_idx) slice, so it
    is cheap to build at cache time. Early rows with insufficient history stay NaN, which
    downstream boolean thresholds (``>= 75``) treat as False (no signal) — the safe default.

    Args:
        series (pd.Series): the metric to normalise (e.g. gross Concentration %).
        window (int): rolling lookback in weeks (Keenan default 52 = one year).
        min_periods (int|None): min observations before emitting a value; defaults to window.

    Returns:
        pd.Series: range index in [0, 100], NaN until ``min_periods`` history exists.
    """
    if min_periods is None:
        min_periods = window
    roll = series.rolling(window=window, min_periods=min_periods)
    lo = roll.min()
    hi = roll.max()
    span = (hi - lo)
    # Where span == 0 (flat window) the metric is degenerate; return NaN (→ no signal).
    idx = (series - lo) / span.where(span > 0) * 100
    return idx


def calculate_willco(col_to_search, lb_idx, cur_idx):
    # We find the rolling min and max of the Commercial Normalized Net position
    oi_min = col_to_search.iloc[lb_idx:cur_idx+1].min()
    oi_max = col_to_search.iloc[lb_idx:cur_idx+1].max()
    cur_normalized_net = col_to_search.iloc[cur_idx]
    willco = round((cur_normalized_net - oi_min) / (oi_max - oi_min + 1e-9) * 100)
    return int(willco)
