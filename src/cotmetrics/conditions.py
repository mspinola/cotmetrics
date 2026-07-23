
import numpy as np
import pandas as pd

import cotmetrics.constants as const


def safe_log_return(prices):
    """Log return of a price series, quiet on non-positive back-adjusted prices.
    Deep-history back-adjusted futures can go <= 0, making the ratio <= 0 so log()
    emits divide-by-zero/invalid warnings; those bars never form a valid setup, so
    the resulting NaN is harmless."""
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.log(prices / prices.shift(1))


def is_commodity(asset_class):
    return asset_class.startswith("Energ") or asset_class.startswith("Grain") or asset_class.startswith("Metal") or asset_class.startswith("Soft")


def is_price_consolidation(df, range_pct=0.15, window=10):
    """
    Requires volatility compression and strict geometric boundary tightness.
    """
    # Calculate the Price Consolidation Box
    # Find the highest high and lowest low over the same window
    price_peak = df[const.CLOSING_PRICE].rolling(window=window).max()
    price_trough = df[const.CLOSING_PRICE].rolling(window=window).min()

    # Calculate the width of the trading range as a percentage
    price_range_pct = (price_peak - price_trough) / price_trough
    inside_tight_range = price_range_pct <= range_pct

    # Ensure the CURRENT candle isn't a violent breakout
    # A consolidation setup requires the current week to be relatively quiet.
    # We use the absolute value of the log return to ensure it didn't violently
    # spike up OR violently dump down.
    log_returns = safe_log_return(df[const.CLOSING_PRICE])
    rolling_std = log_returns.rolling(window=26, min_periods=4).std()
    quiet_candle = np.abs(log_returns) < (rolling_std * 0.75)

    # Price is consolidating sideways (e.g., range is tighter than 15%)
    # You may want to tweak the 0.15 threshold depending on the volatility of the specific asset
    price_consolidation = inside_tight_range & quiet_candle
    return price_consolidation


def in_up_trend(df, col_to_search, n_weeks=10):
    mean = df[col_to_search].rolling(n_weeks).mean()
    uptrend = df[col_to_search] > mean
    downtrend = df[col_to_search] < mean
    return uptrend, downtrend


def is_short_term_low(df, col_to_search, n_weeks=4):
    is_low = df[col_to_search] == df[col_to_search].rolling(window=n_weeks).min()
    return is_low


def is_short_term_high(df, col_to_search, n_weeks=4):
    is_high = df[col_to_search] == df[col_to_search].rolling(window=n_weeks).max()
    return is_high


def stable_or_rising(df, col_to_search, n_weeks=5, tolerance_pct=0.02):
    """
    Evaluates whether a metric's trend is expanding upward or holding stable,
    safely handling zero-crossings and bounded oscillators.

    Returns:
        stable_or_rising (Series): Boolean mask
        stable_or_failing (Series): Boolean mask
    """
    # 1. Smooth the underlying data to remove weekly noise
    smoothed = df[col_to_search].rolling(window=3, min_periods=1).mean()

    # 2. Calculate the change over your designated chunk of time
    rolling_change = smoothed - smoothed.shift(n_weeks)

    # 3. Calculate a dynamic threshold based on the rolling standard deviation
    # This prevents tight, low-volatility tracking from throwing false trend signals
    rolling_std = df[col_to_search].rolling(window=26, min_periods=1).std()
    threshold = rolling_std * tolerance_pct

    # 4. Strictly isolate the three states cleanly
    is_rising = rolling_change > threshold
    is_falling = rolling_change < -threshold
    is_stable = np.abs(rolling_change) <= threshold

    # 5. Return the synergistic masks
    return (is_stable | is_rising), (is_stable | is_falling)


def is_sharp_increase(df, col_to_search, n_weeks=26, sigma_multiplier=1.5):
    """
    Measures structural expansions or liquidations in Open Interest
    by comparing the current candle against a shifted macro baseline.
    """
    # 1. Shift by 1 to isolate today's candle from the baseline metrics
    baseline_series = df[col_to_search].shift(1)

    # 2. Use a macro window (e.g., 26 weeks) to capture true structural regimes
    historical_mean = baseline_series.rolling(window=n_weeks, min_periods=4).mean()
    historical_std = baseline_series.rolling(window=n_weeks, min_periods=4).std()

    # 3. Handle the beginning of the dataframe where std might be NaN or 0
    # Safely fallback to a minor baseline percentage if standard deviation is unavailable
    safe_std = historical_std.where(
        (historical_std > 0) & (historical_std.notna()),
        historical_mean * 0.02
    )

    # 4. Calculate dynamic thresholds
    sharp_increase = df[col_to_search] > (historical_mean + (sigma_multiplier * safe_std))
    sharp_decrease = df[col_to_search] < (historical_mean - (sigma_multiplier * safe_std))

    return sharp_increase, sharp_decrease


def is_parabolic(df, col_to_search, n_weeks=10):
    # Calculate 1-day percentage change
    roc = df[col_to_search].pct_change()

    # Calculate the mean and std dev of the ROC to identify outliers
    roc_mean = roc.rolling(window=n_weeks).mean()
    roc_std = roc.rolling(window=n_weeks).std()

    # Parabolic condition: Current growth is > 2 standard deviations above the mean
    parabolic_up = roc > (roc_mean + (2 * roc_std))
    parabolic_down = roc < (roc_mean - (2 * roc_std))
    return parabolic_down, parabolic_up


def a_to_b_correlation(df, a_col, b_col, n_weeks=4):
    a_to_b_corr = df[a_col].rolling(window=n_weeks).corr(df[b_col])
    consistent = a_to_b_corr > 0.5
    return a_to_b_corr, consistent


def project_trendline(price_col):
    """Fits a line to the historical highs and projects the value for the *next* bar."""
    # x coordinates for the 10 historical bars (0 through 9)
    x = np.arange(len(price_col))

    # Fit the linear regression line: y = mx + c
    m, c = np.polyfit(x, price_col, 1)

    # Project the line to the CURRENT day.
    # Since our historical x-array ended at 9, today is x=10.
    projected_y = (m * len(price_col)) + c
    return projected_y


def is_down_trend_line_break(df, price_col=const.CLOSING_PRICE, last_n_highs=5):
    is_downtrend = (df[price_col].shift(1) < df[price_col].shift(2)) & (df[price_col].shift(2) < df[price_col].shift(3))

    # Shift the data FIRST, then apply the rolling window.
    projected_resistance = df[price_col].shift(1).rolling(window=last_n_highs).apply(project_trendline, raw=True)

    # The Breakout Logic
    # Compare today's Close to projected resistance line.
    trend_break = is_downtrend & (df[price_col] > projected_resistance) & \
                  (df[price_col].shift(1) <= projected_resistance.shift(1))
    return trend_break


def calculate_cot_macd(comm_net_col, fast_span=12, slow_span=26, signal_span=9):
    """
    Calculates a traditional MACD but applies it to Commercial Net Positioning.
    Returns the MACD Line, Signal Line, and the Histogram.
    """
    # 1. Calculate the Fast and Slow EMAs of the Commercial Net Position
    ema_fast = comm_net_col.ewm(span=fast_span, adjust=False).mean()
    ema_slow = comm_net_col.ewm(span=slow_span, adjust=False).mean()

    # 2. The MACD Line is the difference between the Fast and Slow EMAs
    macd_line = ema_fast - ema_slow

    # 3. The Signal Line is an EMA of the MACD Line itself
    signal_line = macd_line.ewm(span=signal_span, adjust=False).mean()

    # 4. The Histogram measures the divergence between the MACD and the Signal
    macd_histogram = macd_line - signal_line

    return macd_line, signal_line, macd_histogram


def calculate_oi_exhaustion_floor(df, short_window=4, tolerance_pct=0.05):
    """
    Calculates whether Open Interest has flatlined at its recent cyclical floor.
    Prevents buying signals from firing if Open Interest has already begun
    surging back up due to aggressive new trend-followers.
    """
    # 1. Establish the rolling multi-week minimum floor
    oi_floor = df[const.OPEN_INTEREST].rolling(window=short_window).min()

    # 2. Apply the structural tolerance multiplier (e.g., 1.05 for 5%)
    buffered_boundary = oi_floor * (1.0 + tolerance_pct)

    # 3. Generate the boolean mask: Is current OI clinging near that absolute low?
    oi_at_floor = df[const.OPEN_INTEREST] <= buffered_boundary

    return oi_at_floor.astype(bool)


def calculate_price_velocity_zscore(df: pd.DataFrame, close_col: str, velocity_window: int = 3, macro_window: int = 26) -> pd.Series:
    """
    Calculates the standardized price velocity (price_vel_z) for order flow analysis.

    Args:
        df (pd.DataFrame): Input DataFrame containing historical price action.
        close_col (str): Column name representing the closing price of the asset.
        velocity_window (int): Short-term momentum lookback in weeks (default: 3).
        macro_window (int): Long-term normalization lookback in weeks (default: 26).

    Returns:
        pd.Series: Bounded price velocity Z-scores.
    """
    # 1. Compute the raw rate of change over the velocity window
    price_roc = df[close_col] - df[close_col].shift(velocity_window)

    # 2. Calculate rolling statistical baseline markers
    rolling_mean = price_roc.rolling(window=macro_window, min_periods=4).mean()
    rolling_std = price_roc.rolling(window=macro_window, min_periods=4).std()

    # 3. Enforce a safety floor on standard deviation to handle flat lines safely
    safe_std = np.where((rolling_std > 0) & (rolling_std.notna()), rolling_std, 0.05)

    # 4. Compute the final standardized Z-Score vector
    price_vel_z = (price_roc - rolling_mean) / safe_std

    return pd.Series(price_vel_z, index=df.index).fillna(0.0)


def calculate_violent_increase(df, lookback_window=26, sigma_multiplier=1.5):
    """
    Identifies abnormal, explosive upward price expansions.
    Returns a clean boolean series.
    """
    # 1. Calculate continuous log returns to normalize velocity
    log_returns = safe_log_return(df[const.CLOSING_PRICE])

    # 2. Establish the historical macro baseline of price volatility
    historical_mean = log_returns.rolling(window=lookback_window).mean()
    historical_std = log_returns.rolling(window=lookback_window).std()

    # 3. Trigger True if the current candle breaks out past the volatility ceiling
    violent_increase = log_returns >= (historical_mean + (sigma_multiplier * historical_std))

    return violent_increase.astype(bool)


def calculate_price_stabilization_at_support(df, base_window=6, macro_window=26, tightness_threshold=0.10):
    """
    Quantifies whether price has structurally stabilized at a support floor.
    Ensures momentum has decayed and price is bounded tightly at macro lows.
    """
    # Dimension 1: The Geometric Bounding Box (Channel Width)
    rolling_high = df[const.HIGH_PRICE].rolling(window=base_window).max()
    rolling_low = df[const.LOW_PRICE].rolling(window=base_window).min()
    channel_width_pct = (rolling_high - rolling_low) / rolling_low
    is_tight_box = channel_width_pct <= tightness_threshold

    # Dimension 2: Momentum Exhaustion (Quiet Candle Switch)
    log_return = safe_log_return(df[const.CLOSING_PRICE])
    rolling_std = log_return.rolling(window=macro_window, min_periods=4).std()
    # Current week's return must be tightly bounded near zero noise
    is_quiet_candle = np.abs(log_return) <= (rolling_std * 0.75)

    # Dimension 3: Location Gating (Is it actually at Support?)
    macro_low = df[const.CLOSING_PRICE].rolling(window=macro_window).min()
    macro_high = df[const.CLOSING_PRICE].rolling(window=macro_window).max()
    macro_range = macro_high - macro_low
    # Price must reside within the bottom 30% of its 6-month macro range
    at_macro_support = df[const.CLOSING_PRICE] <= (macro_low + (macro_range * 0.30))

    # Combine dimensions into a single immutable structural state
    stabilizing_at_support = is_tight_box & is_quiet_candle & at_macro_support

    return stabilizing_at_support.astype(bool)


def calculate_price_stalling_at_highs(df, base_window=6, macro_window=26, tightness_threshold=0.10):
    """
    Quantifies whether price has structurally stalled at a macro resistance ceiling.
    Ensures upward momentum has decayed and price is bounded tightly at highs.
    """
    # Dimension 1: The Geometric Bounding Box (Channel Width at the Top)
    rolling_high = df[const.HIGH_PRICE].rolling(window=base_window).max()
    rolling_low = df[const.LOW_PRICE].rolling(window=base_window).min()
    channel_width_pct = (rolling_high - rolling_low) / rolling_low
    is_tight_box = channel_width_pct <= tightness_threshold

    # Dimension 2: Momentum Exhaustion (Quiet Candle Switch)
    log_return = safe_log_return(df[const.CLOSING_PRICE])
    rolling_std = log_return.rolling(window=macro_window, min_periods=4).std()
    # Current week's return must be tightly bounded near zero noise (no active vertical thrusts)
    is_quiet_candle = np.abs(log_return) <= (rolling_std * 0.75)

    # Dimension 3: Location Gating (Is it actually at a Macro Top?)
    macro_low = df[const.CLOSING_PRICE].rolling(window=macro_window).min()
    macro_high = df[const.CLOSING_PRICE].rolling(window=macro_window).max()
    macro_range = macro_high - macro_low
    # Price must reside within the top 30% of its 6-month macro range
    at_macro_ceiling = df[const.CLOSING_PRICE] >= (macro_low + (macro_range * 0.70))

    # Combine dimensions into a single immutable structural state
    stalling_at_highs = is_tight_box & is_quiet_candle & at_macro_ceiling

    return stalling_at_highs.astype(bool)

def calculate_oi_active_decline(df, lookback_window=4, threshold_pct=-0.04):
    """
    Quantifies whether Open Interest is undergoing a sustained, structural decline.
    Used to verify that a market trend is actively losing its participant base.
    """
    # 1. Establish the maximum open interest achieved inside the trailing window
    oi_rolling_peak = df[const.OPEN_INTEREST].rolling(window=lookback_window).max()

    # 2. Calculate the rolling rate of change relative to that local peak
    # A negative value represents the active bleed of contracts out of the market
    oi_drawdown = (df[const.OPEN_INTEREST] - oi_rolling_peak) / oi_rolling_peak

    # 3. Establish a sequential directional confirmation (Is it consistently down?)
    # Ensure current OI is lower than it was 2 weeks ago AND 4 weeks ago
    is_falling_directionally = (
        (df[const.OPEN_INTEREST] < df[const.OPEN_INTEREST].shift(2)) &
        (df[const.OPEN_INTEREST] < df[const.OPEN_INTEREST].shift(lookback_window))
    )

    # 4. Generate the final boolean mask
    # Open interest must pass the threshold drop (e.g., dropped > 4%) and be directionally down
    oi_actively_declining = (oi_drawdown <= threshold_pct) & is_falling_directionally

    return oi_actively_declining.astype(bool)


def calculate_oi_acceleration(df, velocity_window=3, acceleration_window=2):
    """
    Calculates the second derivative (acceleration) of Open Interest capital flows.
    Returns a normalized continuous Series representing rate-of-change changes.
    """
    # 1. Capture the base velocity (1st derivative)
    oi_velocity = df[const.OPEN_INTEREST] - df[const.OPEN_INTEREST].shift(velocity_window)

    # 2. Capture the change in velocity (2nd derivative)
    oi_raw_acceleration = oi_velocity - oi_velocity.shift(acceleration_window)

    # 3. Normalize via a rolling Z-score over a 26-week macro window
    # This strips out asset-class unit scaling and makes it plug-and-play
    rolling_mean = oi_raw_acceleration.rolling(window=26, min_periods=4).mean()
    rolling_std = oi_raw_acceleration.rolling(window=26, min_periods=4).std()

    # Handle zero-variance windows defensively to avoid division-by-zero NaN errors
    safe_std = np.where((rolling_std > 0) & (rolling_std.notna()), rolling_std, 0.05)

    oi_acceleration_z = (oi_raw_acceleration - rolling_mean) / safe_std

    return pd.Series(oi_acceleration_z, index=df.index).fillna(0.0)


def calculate_lrg_spec_momentum_divergence(df, price, momentum_window=3):
    """
    Quantifies friction where Large Speculator momentum accelerates
    but price actions hits an absolute structural stalemate wall.

    Returns a categorical integer Series:
     +1  = Bullish Divergence (Specs panic selling into a solid price floor)
     -1  = Bearish Divergence (Specs frantic buying into a heavy price ceiling)
      0  = Synchronized/Normal Market Physics
    """
    # 1. Calculate Large Speculator momentum velocity
    # Using the same 3-week smoothing logic established in your positioning module
    large_idx_smooth = df[const.LARGE_CUSTOM_IDX].rolling(window=3, min_periods=1).mean()
    spec_velocity = large_idx_smooth - large_idx_smooth.shift(momentum_window)

    # Define aggressive momentum thresholds based on your standard +/- 2.0 point shifts
    specs_aggressively_buying = spec_velocity >= 2.0
    specs_aggressively_selling = spec_velocity <= -2.0

    # 2. Extract structural price boundaries from your existing primitives
    price_stalling_at_ceilings = price.stalling_at_highs
    price_stabilizing_at_floors = price.stabilizing_at_support

    # 3. Construct the Divergence Logic Array via np.select
    conditions = [
        (specs_aggressively_selling & price_stabilizing_at_floors), # Bullish Divergence
        (specs_aggressively_buying & price_stalling_at_ceilings)    # Bearish Divergence
    ]

    choices = [1, -1]

    divergence_series = np.select(conditions, choices, default=0)

    return pd.Series(divergence_series, index=df.index).astype(int)
