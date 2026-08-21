import types

import marketdata
import numpy as np
import pandas as pd

import cotmetrics.constants as const

from .conditions import (
    a_to_b_correlation,
    calculate_lrg_spec_momentum_divergence,
    calculate_oi_acceleration,
    calculate_oi_active_decline,
    calculate_oi_exhaustion_floor,
    calculate_price_stabilization_at_support,
    calculate_price_stalling_at_highs,
    calculate_price_velocity_zscore,
    calculate_violent_increase,
    in_up_trend,
    is_down_trend_line_break,
    is_parabolic,
    is_price_consolidation,
    is_sharp_increase,
    is_short_term_high,
    is_short_term_low,
    safe_log_return,
    stable_or_rising,
)
from .indicators import (
    calculate_range_index,
    calculate_spearman_correlation_vectorized,
)


def _get_oi_conditions(df):
    oi = types.SimpleNamespace()
    oi.window_length = 26
    oi.up = df[const.OI_ZSCORE] >= 0.5
    oi.up_extreme = (df[const.OI_ZSCORE] >= 1.5)
    oi.uptrend, oi.downtrend = in_up_trend(df, const.OPEN_INTEREST)
    oi.stable_or_rising, oi.stable_or_falling = stable_or_rising(df, const.OPEN_INTEREST, 10)
    oi.sharp_increase, oi.sharp_decrease = is_sharp_increase(df, const.OPEN_INTEREST)
    oi.short_term_low = is_short_term_low(df, const.OPEN_INTEREST, 4)
    oi.down = (df[const.OI_ZSCORE] <= -0.5)
    oi.down_extreme = (df[const.OI_ZSCORE] <= -1.5)
    oi.parabolic_down, oi.parabolic_up = is_parabolic(df, const.OPEN_INTEREST)
    oi.parabolic = oi.parabolic_up | oi.parabolic_down
    oi.at_floor = calculate_oi_exhaustion_floor(df, short_window=4, tolerance_pct=0.05)
    oi.peak = df[const.OPEN_INTEREST].rolling(window=oi.window_length).max()
    oi.trough = df[const.OPEN_INTEREST].rolling(window=oi.window_length).min()

    oi.drawdown_pct = (df[const.OPEN_INTEREST] - oi.peak) / oi.peak
    oi.surge_pct = (df[const.OPEN_INTEREST] - oi.trough) / oi.trough

    oi.surging = oi.surge_pct >= 0.25
    oi.crashing = oi.drawdown_pct <= -0.25
    oi.collapsing = oi.drawdown_pct <= -0.15
    oi.actively_declining = calculate_oi_active_decline(df)

    oi.velocity = df[const.OPEN_INTEREST] - df[const.OPEN_INTEREST].shift(3)
    oi.is_expanding = oi.velocity > 0
    oi.is_contracting = oi.velocity < 0

    oi.is_fresh = df[const.OPEN_INTEREST] >= df[const.OPEN_INTEREST].shift(4)

    return oi

def _get_price_conditions(df, oi):
    price = types.SimpleNamespace()
    price.up = (df[const.PRICE_CHANGE] > 0.1)
    price.uptrend, price.downtrend = in_up_trend(df, const.CLOSING_PRICE)
    price.short_term_high = is_short_term_high(df, const.CLOSING_PRICE)
    price.down = (df[const.PRICE_CHANGE] < -0.1)
    price.short_term_low = is_short_term_low(df, const.CLOSING_PRICE, 4)
    price.oi_corr, price.oi_consistent = a_to_b_correlation(df, const.CLOSING_PRICE, const.OPEN_INTEREST)

    price.macro_high = df[const.CLOSING_PRICE].rolling(window=26).max()
    price.macro_low = df[const.CLOSING_PRICE].rolling(window=26).min()
    price.macro_range = price.macro_high - price.macro_low
    price.at_structural_top = df[const.CLOSING_PRICE] >= (price.macro_low + (price.macro_range * 0.70))
    price.at_structural_bottom = df[const.CLOSING_PRICE] <= (price.macro_high - (price.macro_range * 0.30))
    price.sideways = is_price_consolidation(df)

    price.log_return = safe_log_return(df[const.CLOSING_PRICE])
    price.violent_drop = price.log_return <= -0.02
    price.violent_increase = calculate_violent_increase(df)
    price.is_explosive_up_candle = price.violent_increase | (price.log_return >= 0.02)
    price.crashing = df[const.CLOSING_PRICE] < df[const.CLOSING_PRICE].rolling(window=10).mean()

    # Measure current week's volatility expansion/momentum
    price.rolling_std = price.log_return.rolling(window=26, min_periods=4).std()

    # Define a clean boundary between an active crash and a quiet base
    price.current_week_crashing = price.log_return <= -(price.rolling_std * 1.5) # Violent down candle
    price.quiet_candle = np.abs(price.log_return) <= (price.rolling_std * 0.75)   # Compressed stable candle

    price.stabilizing_at_support = calculate_price_stabilization_at_support(df)
    price.stalling_at_highs = calculate_price_stalling_at_highs(df)

    price.price_velocity_z = calculate_price_velocity_zscore(df, const.CLOSING_PRICE)
    return price

def _concentration_trio(df, oi_all, prefix, long_pos, short_pos, long_tr, short_tr, ns):
    """Compute the Keenan positioning trio (Concentration / Clustering / Position Size)
    for a speculative group that reports trader counts, and populate `ns` with decile
    booleans. Shared by MM (Disaggregated commodities) and LEV (TFF financials) so the
    two are identical by construction. Output column names are built from `prefix` and
    match the constants (e.g. prefix='MM' → const.MM_LONG_CONC). Guards on column
    presence: absent group (wrong universe) → all-False booleans, no columns fabricated.
    Total reportable traders come from the shared const.TOT_TRADERS_XLS."""
    D = const.OBOS_CONC_IDX_DECILE
    false_s = pd.Series(False, index=df.index)
    for a in ("conc_long_decile", "conc_short_decile", "clust_long_decile",
              "clust_short_decile", "psize_long_decile", "psize_short_decile"):
        setattr(ns, a, false_s.copy())
    if long_pos not in df.columns or short_pos not in df.columns:
        return
    cL, cS = f"{prefix} Long{const.CONCENTRATION}", f"{prefix} Short{const.CONCENTRATION}"
    idx = const.LB_52 + const.IDX
    # Concentration (risk) — position as % of total OI.
    df[cL] = df[long_pos] / oi_all * 100
    df[cS] = df[short_pos] / oi_all * 100
    df[cL + idx] = calculate_range_index(df[cL], window=52)
    df[cS + idx] = calculate_range_index(df[cS], window=52)
    ns.conc_long_decile = df[cL + idx] >= D
    ns.conc_short_decile = df[cS + idx] >= D
    if const.TOT_TRADERS_XLS in df.columns and long_tr in df.columns and short_tr in df.columns:
        tot = df[const.TOT_TRADERS_XLS].replace(0, np.nan)
        lt, st = df[long_tr].replace(0, np.nan), df[short_tr].replace(0, np.nan)
        klL, klS = f"{prefix} Long{const.CLUSTERING}", f"{prefix} Short{const.CLUSTERING}"
        # Clustering (herding) — # group traders / total reportable traders.
        df[klL] = df[long_tr] / tot * 100
        df[klS] = df[short_tr] / tot * 100
        df[klL + idx] = calculate_range_index(df[klL], window=52)
        df[klS + idx] = calculate_range_index(df[klS], window=52)
        ns.clust_long_decile = df[klL + idx] >= D
        ns.clust_short_decile = df[klS + idx] >= D
        pL, pS = f"{prefix} Long{const.POSITION_SIZE}", f"{prefix} Short{const.POSITION_SIZE}"
        # Position Size (conviction) — OI(dir) / # traders(dir).
        df[pL] = df[long_pos] / lt
        df[pS] = df[short_pos] / st
        df[pL + idx] = calculate_range_index(df[pL], window=52)
        df[pS + idx] = calculate_range_index(df[pS], window=52)
        ns.psize_long_decile = df[pL + idx] >= D
        ns.psize_short_decile = df[pS + idx] >= D


def _get_positioning_conditions(df, normalized):
    comms = types.SimpleNamespace()
    large = types.SimpleNamespace()
    small = types.SimpleNamespace()

    comms_zscore_col = const.COMMS_ZSCORE
    comms.idx_col = const.COMMS_IDX
    comms_momentum_col = const.COMM_MOMENTUM
    comms.three_yr_idx_col = const.COMM_3Y_IDX_NORM if normalized else const.COMM_3Y_IDX

    comms.is_long = df[const.COMM_NET] > 0
    comms.heavy_buying = (df[comms_momentum_col] >= const.MOMENTUM_MAX_THRESHOLD)
    comms.heavy_selling = (df[comms_momentum_col] <= const.MOMENTUM_MIN_THRESHOLD)

    comms.net_up = (df[comms_zscore_col] >= 1.0) | (df[comms_momentum_col] >= const.MOMENTUM_MAX_THRESHOLD)
    comms.zscore_uptrend, comms.zscore_downtrend = in_up_trend(df, comms_zscore_col, 5)
    comms.idx_uptrend, comms.idx_downtrend = in_up_trend(df, comms.idx_col, 5)
    comms.movement_up = (df[comms_momentum_col] >= const.MOMENTUM_MAX_THRESHOLD)
    comms.net_up_extreme = (df[comms_zscore_col] >= 1.5) | ((df[comms_zscore_col] >= 1.0) & comms.movement_up)
    comms.net_up_3yr = (df[comms.three_yr_idx_col] >= 80)
    comms.net_up_3yr_extreme = (df[comms.three_yr_idx_col] >= 95)
    comms.net_down = (df[comms_zscore_col] <= -1.0) | (df[comms_momentum_col] <= const.MOMENTUM_MIN_THRESHOLD)
    comms.movement_down = (df[comms_momentum_col] <= const.MOMENTUM_MIN_THRESHOLD)
    comms.net_down_extreme = (df[comms_zscore_col] <= -1.5) | ((df[comms_zscore_col] <= -1.0) & comms.movement_down)
    comms.net_down_3yr = (df[comms.three_yr_idx_col] <= 20)
    comms.net_down_3yr_extreme = (df[comms.three_yr_idx_col] <= 5)
    comms.stable_or_rising, comms.stable_or_falling = stable_or_rising(df, const.COMM_NET, 10)

    comms.extreme_short_posture = comms.net_down_extreme | comms.net_down_3yr_extreme
    comms.extreme_long_posture = comms.net_up_extreme | comms.net_up_3yr_extreme

    window_4yr = 208
    comms.net_4yr_max = df[const.COMM_NET].rolling(window=window_4yr).max()
    comms.net_4yr_min = df[const.COMM_NET].rolling(window=window_4yr).min()

    large_zscore_col = const.LRG_ZSCORE
    large_idx_col = const.LRG_IDX
    small_zscore_col = const.SML_ZSCORE
    small_idx_col = const.SML_IDX

    large.net_up = (df[large_zscore_col] >= 1.0)
    large.net_up_extreme = (df[large_zscore_col] >= 1.5)
    large.idx_up_trend, large.idx_down_trend = in_up_trend(df, large_idx_col, 3)
    large.net_down = (df[large_zscore_col] <= -1.0) | (df[large_idx_col] <= 5.0)
    large.net_down_extreme = (df[large_zscore_col] <= -1.5) | (df[large_idx_col] <= 5.0)

    small.net_up = (df[small_zscore_col] >= 1.0)
    small.net_up_extreme = (df[small_zscore_col] >= 1.5)
    small.net_down = (df[small_zscore_col] <= -1.0) | (df[small_idx_col] <= 5.0)
    small.net_down_extreme = (df[small_zscore_col] <= -1.5) | (df[small_idx_col] <= 5.0)

    small.idx_smooth = df[small_idx_col].rolling(window=3).mean()
    comms.idx_smooth = df[comms.idx_col].rolling(window=3).mean()
    large.idx_smooth = df[large_idx_col].rolling(window=3).mean()

    comms.accumulating = (comms.idx_smooth > (comms.idx_smooth.shift(1) + 2.0))
    comms.bearish = comms.idx_smooth < 40
    comms.bullish = comms.idx_smooth > 60
    comms.net_short = df[const.COMM_NET] < 0
    comms.net_long = df[const.COMM_NET] > 0
    comms.pulling_back = (comms.idx_smooth < (comms.idx_smooth.shift(1) - 2.0))
    comms.distributing = (comms.idx_smooth < (comms.idx_smooth.shift(1) - 2.0))
    comms.covering_shorts = (df[comms_zscore_col]< 0.0) & (comms.idx_smooth > (comms.idx_smooth.shift(1) + 2.0))

    small.aggressively_buying = (df[small_zscore_col] > 0.0) & (small.idx_smooth > (small.idx_smooth.shift(1) + 2.0))
    small.aggressively_selling = (df[small_zscore_col] < 0.0) & (small.idx_smooth < (small.idx_smooth.shift(1) - 2.0))
    small.liquidating_longs = (df[small_zscore_col] > 0.0) & (small.idx_smooth < (small.idx_smooth.shift(1) - 2.0))
    small.covering_shorts = (df[small_zscore_col] < 0.0) & (small.idx_smooth > (small.idx_smooth.shift(1) + 2.0))

    large.aggressively_selling = (df[large_zscore_col] > 1.0) & (large.idx_smooth < large.idx_smooth.shift(1) - 2.0)
    large.liquidating_longs = (df[large_zscore_col] > 0.0) & (large.idx_smooth < large.idx_smooth.shift(1) - 2.0)
    large.covering_shorts = (df[large_zscore_col] < 0.0) & (large.idx_smooth > (large.idx_smooth.shift(1) + 2.0))
    large.short = (df[large_zscore_col] < 0.0)

    # --- Keenan OBOS positioning leg: gross Concentration on the speculative group ---
    # LARGE = NonCommercial (MM+OR) on the Legacy store → NC Concentration, an MM proxy
    # (see docs/spec_positioning_metrics_trio.md §2). Persist the columns so the scorecard
    # / pardo can consume them, and expose top-quartile booleans for the setup.
    oi_all = df[const.OPEN_INTEREST_XLS].replace(0, np.nan)
    df[const.LARGE_LONG_CONC] = (df[const.LARGE_LONG_POS_XLS] / oi_all * 100).fillna(0)
    df[const.LARGE_SHORT_CONC] = (df[const.LARGE_SHORT_POS_XLS] / oi_all * 100).fillna(0)
    df[const.LARGE_LONG_CONC_IDX] = calculate_range_index(df[const.LARGE_LONG_CONC], window=52)
    df[const.LARGE_SHORT_CONC_IDX] = calculate_range_index(df[const.LARGE_SHORT_CONC], window=52)

    # Extreme = top quartile of its own 52-wk range (NaN history → False, no signal).
    large.conc_long_extreme = df[const.LARGE_LONG_CONC_IDX] >= const.OBOS_CONC_IDX_THRESHOLD
    large.conc_short_extreme = df[const.LARGE_SHORT_CONC_IDX] >= const.OBOS_CONC_IDX_THRESHOLD
    # Decile (90) variant — a genuine extreme for the selectivity test.
    large.conc_long_decile = df[const.LARGE_LONG_CONC_IDX] >= const.OBOS_CONC_IDX_DECILE
    large.conc_short_decile = df[const.LARGE_SHORT_CONC_IDX] >= const.OBOS_CONC_IDX_DECILE

    # Commercial (PMPU proxy) Concentration — same transform on the hedger group.
    df[const.COMM_LONG_CONC] = (df[const.COMM_LONG_POS_XLS] / oi_all * 100).fillna(0)
    df[const.COMM_SHORT_CONC] = (df[const.COMM_SHORT_POS_XLS] / oi_all * 100).fillna(0)
    df[const.COMM_LONG_CONC_IDX] = calculate_range_index(df[const.COMM_LONG_CONC], window=52)
    df[const.COMM_SHORT_CONC_IDX] = calculate_range_index(df[const.COMM_SHORT_CONC], window=52)
    comms.conc_long_extreme = df[const.COMM_LONG_CONC_IDX] >= const.OBOS_CONC_IDX_THRESHOLD
    comms.conc_short_extreme = df[const.COMM_SHORT_CONC_IDX] >= const.OBOS_CONC_IDX_THRESHOLD
    comms.conc_long_decile = df[const.COMM_LONG_CONC_IDX] >= const.OBOS_CONC_IDX_DECILE
    comms.conc_short_decile = df[const.COMM_SHORT_CONC_IDX] >= const.OBOS_CONC_IDX_DECILE

    # Concentration/Clustering/Position-Size trio on a speculative group from a
    # trader-count report — MM (Disaggregated, commodities) and LEV (TFF Leveraged
    # Funds, financials). Disjoint by market: each frame carries at most one.
    mm = types.SimpleNamespace()
    _concentration_trio(df, oi_all, const.MM, const.MM_LONG_POS_XLS, const.MM_SHORT_POS_XLS,
                        const.MM_LONG_TRADERS_XLS, const.MM_SHORT_TRADERS_XLS, mm)
    lev = types.SimpleNamespace()
    _concentration_trio(df, oi_all, const.LEV, const.LEV_LONG_POS_XLS, const.LEV_SHORT_POS_XLS,
                        const.LEV_LONG_TRADERS_XLS, const.LEV_SHORT_TRADERS_XLS, lev)

    return comms, large, small, mm, lev


def append_trading_signals(df, asset_class=None, normalized=False):
    """Calculates advanced trading setups and appends them to the dataframe."""
    # We copy the df to avoid SettingWithCopy warnings
    df = df.copy()


    oi = _get_oi_conditions(df)
    price = _get_price_conditions(df, oi)
    comms, large, small, mm, lev = _get_positioning_conditions(df, normalized)

    def _append_larry_williams_bull_market_setup():
        # ==============================================================================
        # SIGNAL: LARRY WILLIAMS BULL MARKET SETUP
        # ==============================================================================
        # When a market enters a well-defined sideways trading range or consolidation,
        # and Open Interest declines significantly (ideally by 25% or more), it is a
        # classic buy setup. This tells us commercials are actively covering their
        # short positions because they expect prices to break out to the upside.
        #
        # Conditions:
        # 1. Gradual sustained bleed in Open Interest over longer period of time
        # 2. Market trading sideways
        # ==============================================================================
        df[const.LW_MACRO_BULL_SETUP] = (
            price.sideways &
            oi.crashing &
            oi.at_floor &
            price.quiet_candle &
            price.at_structural_bottom &
            comms.is_long
        )


    def _append_larry_williams_bear_market_setup():
        # ==============================================================================
        # SIGNAL: LARRY WILLIAMS BEAR MARKET SETUP
        # ==============================================================================
        # When a market enters a well-defined sideways trading range or consolidation,
        # and Open Interest surges significantly (ideally by 25% or more), it is a
        # classic sell setup.
        # Commercials set at major market tops: quietly absorbing speculator buying
        # until the buying power exhausts, leaving a massive pile of short hedges
        # ready to drive the market down.
        #
        # Conditions:
        # 1. Gradual sustained surge in Open Interest over longer period of time
        # 2. Market trading sideways
        # ==============================================================================
        # Ensure that any historical 'sideways' calculation is instantly overridden
        # if the current candle is actively blowing out of the range.
        market_is_genuinely_flat = price.sideways & ~price.is_explosive_up_candle
        df[const.LW_MACRO_BEAR_SETUP] = (
            market_is_genuinely_flat &
            oi.surging &
            oi.is_fresh &
            price.at_structural_top &
            comms.net_short &
            price.quiet_candle
        )


    def _append_4_year_commercial_buying_extreme_multiyear_high():
        # ==============================================================================
        # SIGNAL: 4-YEAR COMMERCIAL BUYING EXTREME (MULTIYEAR HIGH)
        # ==============================================================================
        # When commercials reach a multiyear high in net buying, it strongly begets a
        # bull market. Sometimes you don't even need a complex formula; you just look
        # at a multiyear chart of the absolute commercial net position.
        #
        # Unlike bounded oscillators that constantly cross back and forth, hitting a
        # true 4-year absolute extreme is a rare, high-conviction macro event. It
        # proves massive accumulation by smart-money, setting an absolute historical
        # boundary that indicates a structural bull market is imminent.
        #
        # Conditions:
        # 1. Commercial Net Position evaluated over a 208-week (4-year) rolling window
        # 2. Current Commercial Net Position is the highest seen in that entire window
        # ==============================================================================
        # Condition: The current net position IS the highest or lowest seen in the 4-year window
        # (Using >= or <= as a safety net, though == works identically here)
        df[const.MULTI_YR_BULL_EXTREME] = df[const.COMM_NET] >= comms.net_4yr_max


    def _append_4_year_commercial_selling_extreme_multiyear_low():
        # ==============================================================================
        # SIGNAL: 4-YEAR COMMERCIAL SELLING EXTREME (MULTIYEAR LOW)
        # ==============================================================================
        # When commercials reach a multiyear low in net selling, it indicates a
        # structural bear market is close at hand.
        #
        # Hitting an extreme historical boundary of net selling that hasn't been seen
        # in the last four years proves commercials are heavily short-hedged against a
        # top. This massive absorption of buying liquidity warns of a severe downside
        # reversal.
        #
        # Conditions:
        # 1. Commercial Net Position evaluated over a 208-week (4-year) rolling window
        # 2. Current Commercial Net Position is the lowest seen in that entire window
        # ==============================================================================
        df[const.MULTI_YR_BEAR_EXTREME] = df[const.COMM_NET] <= comms.net_4yr_min

    def _append_the_fundamental_synergy_backwardation_cot_oi():
        # TODO revisit this when using actual futures data like databento
        # ==============================================================================
        # SIGNAL: THE FUNDAMENTAL SYNERGY (BACKWARDATION + COT + OI)
        # ==============================================================================
        # 1. Calculate the Premium Spread
        # Spread > 0 means Backwardation (Front month is more expensive than Back month)
        # Spread < 0 means Contango (Normal market, Back month is more expensive)
        # df['premium_spread'] = df['front_month_price'] - df['back_month_price']
        # 2. Define the conditions
        # Condition A: Market is in Backwardation (or spread is rapidly widening)
        # is_backwardation = df['premium_spread'] > 0
        # Condition B: Open Interest is declining (Commercials covering/clearing the deck)
        # (Re-using your existing 13-week or 26-week OI drawdown logic)
        # oi_declining = df['oi.drawdown_pct'] <= -0.15
        # Condition C: Price is in a pullback (e.g., trading below its 20-day moving average)
        # price_pullback = df['closing_price'] < df['closing_price'].rolling(window=20).mean()
        # 3. Trigger the Master Signal
        # df['signal_fundamental_synergy'] = is_backwardation & oi_declining & price_pullback
        pass


    def _append_structural_bull_breakout_commercial_resistance_failed():
        # ==============================================================================
        # SIGNAL: STRUCTURAL BULL BREAKOUT (COMMERCIAL RESISTANCE FAILED)
        # ==============================================================================
        # Commercials are aggressively dumping into the rally (index momentum <= -40 points
        # over MOMENTUM_PERIOD weekly reports), setting
        # up what should be a price ceiling. However, price ignores the structural selling
        # pressure and rallies to a short-term high anyway. Commercial resistance has
        # broken, signaling the onset of a spec-driven structural bull market.
        # ==============================================================================
        signal_struct_bull_breakout = (
            price.short_term_high &
            comms.heavy_selling &
            price.is_explosive_up_candle
        )
        df[const.SPEC_DRIVEN_BULL_BREAKOUT] = signal_struct_bull_breakout


    def _append_structural_bear_breakdown_commercial_support_failed():
        # ==============================================================================
        # SIGNAL: STRUCTURAL BEAR BREAKDOWN (COMMERCIAL SUPPORT FAILED)
        # ==============================================================================
        # Commercials are aggressively buying the dip (index momentum >= 40 points
        # over MOMENTUM_PERIOD weekly reports), setting
        # up what should be a price floor. However, price ignores the structural buying
        # pressure and drops to a short-term low anyway. Commercial support has
        # broken, signaling a definitive macro trend change and a speculative-driven bear market.
        # ==============================================================================
        # Don't just check for a short-term low. Mandate that the weekly candle
        # closed significantly lower than the previous week (e.g., down 2%+)
        # to prove speculative momentum is crushing the commercials.
        signal_struct_bear_breakdown = (
            price.short_term_low &
            comms.heavy_buying &
            comms.accumulating &
            price.violent_drop
        )
        df[const.SPEC_DRIVEN_BEAR_BREAKDOWN] = signal_struct_bear_breakdown


    def _append_commercial_capitulation_the_briese_stampede():
        # ==============================================================================
        # SIGNAL: COMMERCIAL CAPITULATION (THE BRIESE STAMPEDE)
        # ==============================================================================
        # Commercials normally buy into weakness. Capitulation occurs when price drops
        # but commercials abandon their counter-trend buying and aggressively SELL the
        # drop instead. When the market's natural braking system joins the momentum,
        # a violent stampede results.
        # ==============================================================================
        # 2. Commercials are aggressively selling/shorting
        comm_net_change_pct = df[const.COMM_PCT_OI] <= -0.15

        # 3. They were structurally long recently (They tried to catch the knife and failed)
        # We look back 6 weeks to see if their index was highly accumulated (>= 80)
        comms_were_trapped_long = (df[comms.idx_col] >= 80).rolling(window=6).max().astype(bool)
        df[const.COMMS_CAPITULATION] = (
            price.crashing &
            oi.crashing &
            (comm_net_change_pct | comms.heavy_selling) &
            comms_were_trapped_long &
            comms.is_long
        )


    def _append_bullish_trend_continuation_healthy_dip_buying():
        # ==============================================================================
        # SIGNAL: BULLISH TREND CONTINUATION (HEALTHY DIP BUYING)
        # ==============================================================================
        # A healthy bull market driven by informed "smart money" adding long positions
        # into weakness. While a healthy uptrend is defined by consistent price action
        # and no parabolic blow-off tops, Commercials will naturally sell into rallies.
        # Therefore, the continuation signal fires when this healthy market experiences
        # a short-term dip, and the Commercials use that dip to aggressively buy and
        # add to their long-term structural positions.
        #
        # Conditions:
        # 1. Market Health: Open Interest is consistent, with no parabolic blow-offs.
        # 2. The Dip: Price is currently at a short-term low (a correction).
        # 3. Structural Posture: Commercials maintain a generally bullish long-term
        #    posture (3-year index > 50).
        # 4. Aggressive Entry: Commercial momentum surges upward as they buy the dip.
        # =============================================================================
        # 1. Market Health: Consistent price action and NO blow-off tops
        healthy_bull_market = ~oi.parabolic & price.oi_consistent
        base_bull_trend_cont = (
            healthy_bull_market &
            price.short_term_low &
            (df[comms.three_yr_idx_col] > 50) &
            comms.movement_up
        )
        # It is only a healthy trend continuation if the Commercial support wall DID NOT break.
        signal_struct_bear_breakdown = comms.heavy_buying & price.violent_drop & price.short_term_low
        df[const.BULLISH_TREND_CONTINUING] = base_bull_trend_cont & ~signal_struct_bear_breakdown


    def _append_short_covering_rally_trend_line_break():
        # ==============================================================================
        # SIGNAL: SHORT COVERING RALLY (TREND LINE BREAK)
        # ==============================================================================
        # Smart money has been "buying into weakness," accumulating massive long positions
        # as prices dropped to reduce their base costs. Now, the trap is sprung. Trapped
        # short-sellers are forced to panic-buy to cover their positions. This rapid
        # decrease in Open Interest fuels a price rally that breaks the established
        # short-term downtrend line.
        #
        # Conditions:
        # 1. Price Confirmation: Price breaks the short-term downtrend line.
        # 2. Open Interest: Sharp decrease, confirming trapped shorts are covering.
        # 3. Extreme Positioning: Speculators (Large or Small) are trapped at extreme
        #    short levels, while Commercials hold massive (standard or 3-year) net longs.
        # ==============================================================================
        # 1. Price Confirmation
        down_trend_line_break = is_down_trend_line_break(df)

        # 3. Extreme Positioning: Require Specs to be trapped short AND Comms heavily long
        extreme_positioning = (
            (small.net_down_extreme | large.net_down_extreme) &
            (comms.net_up_extreme | comms.net_up_3yr_extreme)
        )
        # Give the extreme state a 4-week "memory"
        # If they were extreme anytime in the last month, the trap is set.
        recent_extreme_positioning = extreme_positioning.rolling(window=4).max().astype(bool)
        df[const.SHORT_COVERING] = (
            down_trend_line_break &
            oi.sharp_decrease &
            recent_extreme_positioning
        )


    def _append_commercial_new_accumulation_bear_trap_setting():
        # ==============================================================================
        # SIGNAL: COMMERCIAL NEW ACCUMULATION (BEAR TRAP SETTING)
        # ==============================================================================
        # A classic tape-reading signal verified by COT data. Price is at a short-term
        # low and Open Interest is surging. In traditional futures theory, this implies
        # that aggressive new short sellers (the speculative public) are piling in at
        # the bottom. Meanwhile, the "smart money" (Commercials) is quietly taking the
        # other side of these trades, accumulating long positions to trap the late shorts.
        #
        # Conditions:
        # 1. Open Interest: Sharply increasing (new money is flooding the market).
        # 2. Price: Must be at a short-term low.
        # 3. Commercial Accumulation: COT data confirms Commercials are adding to longs.
        # ==============================================================================
        # All components must align perfectly on the same weekly candle.
        bear_trap_trigger = (
            price.short_term_low &  # Must be an active, real-time short-term low
            oi.sharp_increase &     # New money must be aggressively flooding in right here
            comms.accumulating &    # Commercials must be actively absorbing the panic
            price.quiet_candle &
            ~price.violent_drop
        )

        # Once a true bear trap is identified, we keep the flag True for a 3-week
        # window so the dashboard highlights the accumulation zone and the ML
        # model can evaluate execution entries.
        df[const.COMMS_NEW_ACCUMULATION] = bear_trap_trigger.rolling(window=3, min_periods=1).max().astype(bool)


    def _append_commercial_accumulation_absorbing_risk():
        # ==============================================================================
        # SIGNAL: COMMERCIAL ACCUMULATION (ABSORBING RISK)
        # ==============================================================================
        # If price drops and Open Interest remains stable or rises, it means that for
        # every short seller entering the market, there is a buyer on the other side
        # absorbing that risk. The "smart money" is not closing their positions; they
        # are effectively picking up contracts at a discount from the panicking public.
        # We check the COT data to empirically verify they are the ones buying.
        #
        # Conditions:
        # 1. Price: Dropping (providing a discount).
        # 2. Open Interest: Stable or rising (confirming new risk is entering the market).
        # 3. Commercial Accumulation: COT data explicitly shows Commercials stepping
        #    in to buy and pushing their smoothed index up by at least 2.0 points.
        # ==============================================================================
        df[const.COMMS_ACCUMULATION] = (
            (df[const.PRICE_CHANGE] < -0.05) &
            oi.stable_or_rising &
            comms.accumulating &
            ~df[const.COMMS_NEW_ACCUMULATION]
        )


    def _append_bullish_bottom_oi_divergence_event():
        # ==============================================================================
        # SIGNAL: BULLISH BOTTOM (OI DIVERGENCE EVENT)
        # ==============================================================================
        # A true bullish bottom forms when extreme Commercial long positioning meets
        # a sudden divergence in Open Interest at the lows. This divergence happens
        # in one of two ways: either the smart money is actively absorbing new
        # short-sellers (New Accumulation), or trapped short-sellers are panicking
        # and buying back their contracts (Short Covering).
        #
        # Conditions:
        # 1. Extreme Posture: Commercials must be at a standard or multi-year extreme long.
        # 2. Divergence Event: Must trigger either New Accumulation or Short Covering.
        # 3. Proof of Halt: Commercials successfully halted the slide
        #                   (eg, a green weekly close, or a failure to make a lower low).
        # ==============================================================================
        # 2. Divergence Event: Absorbing new shorts OR forcing old shorts to cover
        oi_divergence = df[const.COMMS_NEW_ACCUMULATION] | df[const.SHORT_COVERING]

        # 3. Bullish Bottom requires price to stabilize or close positive (The floor holds)
        # Even if they tested a low this week, Commercials fought back and forced a green close.
        price_stabilizing = price.short_term_low & price.up
        df[const.BULLISH_BOTTOM] = price_stabilizing & comms.extreme_long_posture & oi_divergence


    def _append_short_squeeze_bear_trap():
        # ==============================================================================
        # SIGNAL: SHORT SQUEEZE (BEAR TRAP)
        # ==============================================================================
        # Public shorts are being "squeezed" out or old longs are capitulating, while
        # commercials quietly add to longs. This is a "giveaway" bullish pattern and
        # an excellent setup for a bottom. To have a short squeeze, you need a massive
        # amount of trapped short sellers. Open interest figures will actively decline
        # if, and only if, those short sellers are forced to cover their positions.
        #
        # Conditions:
        # 1. Price: Exhaustion at support (price has stopped making short-term lows).
        # 2. Open Interest: Actively declining (confirming shorts are covering).
        # 3. Speculator Covering: Specs (Large or Small) are trapped net short but are
        #    now aggressively buying to cover their positions.
        # 4. Commercial Accumulation: Smart money is quietly adding to longs.
        # ==============================================================================
        # 3. Speculator Covering: They are net short, but their index is surging
        # upward as they are forced to buy back their contracts.
        df[const.SHORT_SQUEEZE] = (
            price.stalling_at_highs &
            price.stabilizing_at_support &
            oi.is_contracting &
            price.at_structural_bottom &
            (oi.downtrend | oi.sharp_decrease) &
            comms.covering_shorts
        )


    def _append_stealth_bull_market_smart_money_accumulation():
        # ==============================================================================
        # SIGNAL: STEALTH BULL MARKET (SMART MONEY ACCUMULATION)
        # ==============================================================================
        # A stealth bull market occurs when a market is quietly building the
        # foundation for a massive upward trend, but the general public and
        # mainstream financial media are either completely oblivious or actively
        # bearish. During this phase, prices often look terrible on the
        # surface—perhaps locked in a slow, grinding downtrend or a boring
        # sideways consolidation. However, beneath the surface, the "smart money"
        # is aggressively accumulating positions.
        #
        # Conditions:
        # 1. Price: Boring or bad (not in an established uptrend).
        # 2. Open Interest: Extremely low (public has completely abandoned the market).
        # 3. Commercials: Pushed to massive, multi-year extreme long levels (e.g., 95+).
        # 4. Speculators (Large & Small): Aggressively positioned short or overwhelmingly bearish.
        # ==============================================================================
        # 1. Price: Not breaking out
        boring_or_bad_price = ~price.uptrend
        df[const.STEALTH_BULLISH_BOTTOM] = (
            boring_or_bad_price &
            oi.down_extreme &
            comms.net_up_3yr_extreme &
            large.net_down &
            small.net_down
        )


    def _append_bearish_trend_continuation_liquidity_vacuum():
        # ==============================================================================
        # SIGNAL: BEARISH TREND CONTINUATION (LIQUIDITY VACUUM)
        # ==============================================================================
        # The public is aggressively selling or shorting into a downtrend while commercials
        # pull back, indicating trend continuation. If a market is falling and the
        # commercials completely refuse to buy, it means they know the fundamental bottom
        # is nowhere in sight. The market falls into a liquidity vacuum. Do not catch a
        # falling knife.
        #
        # Conditions:
        # 1. Price: Must be in an established downtrend.
        # 2. Open Interest: Rising (new money entering the market to drive the trend).
        # 3. Institutional Momentum: Large Specs are confirmed to be net short.
        # 4. Public Momentum: Small Specs are net short and aggressively pressing shorts.
        # 5. Commercial Abstinence: Commercials are actively withdrawing bids (pulling back).
        # ==============================================================================
        # 4. Public Momentum: Retail is net short and pressing shorts heavily
        # 5. Commercial Abstinence: Actively withdrawing bids (liquidity vacuum)
        # 3. Institutional Momentum: Confirm trend-followers are actually short
        df[const.BEARISH_TREND_CONTINUING] = (
            price.downtrend &
            oi.uptrend &
            large.short &
            small.aggressively_selling &
            comms.pulling_back
        )


    def _append_bearish_top_distribution_trap():
        # ==============================================================================
        # SIGNAL: BEARISH TOP (DISTRIBUTION TRAP)
        # ==============================================================================
        # A classic "symptom of a top." The uninformed crowd is aggressively buying
        # the rally while insiders distribute or sell short. The market uses a confirmed
        # uptrend as a lure to attract retail traders. While the public and large
        # trend-followers euphorically add to their longs, the Commercials are already
        # at max short capacity and are actively dumping contracts into the retail bids.
        #
        # Conditions:
        # 1. Price: Must be in a confirmed uptrend.
        # 2. Open Interest: Pushed to extreme highs (an insanely crowded trade).
        # 3. Institutional Euphoria: Large Specs are heavily net long.
        # 4. Public Euphoria: Small Specs are net long and aggressively buying.
        # 5. Extreme Posture: Commercials are structurally max short (standard or 3-yr).
        # 6. Commercial Distribution: Commercials are actively driving their net position lower.
        # ==============================================================================
        # 4. Public Euphoria: Retail is net long and aggressively buying late into the rally
        # 6. Commercial Distribution: Smart money is actively dumping contracts into the rally
        # 3. Institutional Euphoria: Confirm the big trend-followers are also heavily long
        # 5. Extreme Posture: Commercials are structurally max short
        base_bear_top = (
            price.uptrend &
            oi.up_extreme &
            large.net_up &
            small.aggressively_buying &
            comms.extreme_short_posture &
            comms.distributing
        )
        # Apply Override: It is only a Bear Top if the Commercials are actually holding the line
        signal_struct_bull_breakout = (
            comms.heavy_selling &
            price.is_explosive_up_candle &
            price.short_term_high
        )
        df[const.BEARISH_TOP] = base_bear_top & ~signal_struct_bull_breakout


    def _append_exhaustion_starving_trend():
        # ==============================================================================
        # SIGNAL: EXHAUSTION (STARVING TREND)
        # ==============================================================================
        # Longs are taking profits and leaving. The lack of new commercial buying signals
        # an exhausted rally. When a market is in a healthy uptrend, new money enters to
        # push prices higher (rising OI). However, when an uptrend becomes "exhausted,"
        # the price might still be hovering near highs, but Open Interest begins to
        # steadily decline because early buyers are cashing out without replacement.
        #
        # Conditions:
        # 1. Price: In an established uptrend or resting near recent highs.
        # 2. Open Interest: Actively declining (the absolute footprint of liquidation).
        # 3. Speculator Profit-Taking: Large Specs were heavily long and are now dumping.
        # 4. Commercial Abstinence: Commercials are not buying (net position is stable/falling).
        # ==============================================================================
        # 3. Speculator Profit-Taking: Large Specs cashing out of extended longs
        df[const.EXHAUSTION] = (
            price.stalling_at_highs &
            oi.actively_declining &
            price.quiet_candle &
            ~price.is_explosive_up_candle
        )


    def _append_capitulation_liquidity_vacuum():
        # ==============================================================================
        # SIGNAL: CAPITULATION (LIQUIDITY VACUUM)
        # ==============================================================================
        # Total capitulation and liquidation. Longs are giving up, but the smart money
        # is not stepping in to buy the dip, meaning there is no bottom in sight.
        # While a standard bottom forms when the public panics and commercials eagerly
        # scoop up cheap contracts, a capitulation vacuum occurs when the public panics
        # and the Commercials step back, refusing to catch the falling knife.
        #
        # Conditions:
        # 1. Price: Must be in an established downtrend.
        # 2. Open Interest: Actively collapsing (indicating liquidation, not new shorts).
        # 3. Speculator Liquidation: Retail or Institutions dumping long positions
        # 4. Commercial Abstinence: Smart money pulls bids
        # ==============================================================================
        df[const.CAPITULATION] = (
            ~df[const.COMMS_CAPITULATION] &
            oi.crashing &
            (small.liquidating_longs | large.liquidating_longs) &
            comms.pulling_back &
            price.current_week_crashing &
            price.at_structural_bottom
        )


    def _append_spearman_regime_shift_signal(spearman_window=13, momentum_window=4, baseline_window=26, fallback_val=-0.75):
        """
        Develops a high-conviction signal indicating that the Commercials'
        Spearman correlation is breaking out of its expected negative regime
        and accelerating into an anomalous positive correlation with price.

        Uses high-performance vectorized operations to eliminate iterative loops.
        """
        comm_spearman_raw = calculate_spearman_correlation_vectorized(
            df,
            price_col=const.CLOSING_PRICE,
            pos_col=const.COMM_NET,
            lb_weeks=spearman_window,
            fallback_val=fallback_val
        )

        # Measure the velocity (momentum) of the correlation shift over the last month
        # A positive value means the correlation is moving away from -1.0 and toward +1.0
        spearman_velocity = comm_spearman_raw - comm_spearman_raw.shift(momentum_window)

        # Establish a trailing baseline of what normal velocity variations look like
        historical_vel_mean = spearman_velocity.rolling(window=baseline_window, min_periods=4).mean()
        historical_vel_std = spearman_velocity.rolling(window=baseline_window, min_periods=4).std()

        # Handle the beginning of the series where std dev is unavailable to prevent NaN pollution
        safe_vel_std = np.where(
            (historical_vel_std > 0) & (historical_vel_std.notna()),
            historical_vel_std,
            0.05
        )

        # CRITERIA A: Velocity is experiencing a significant statistical expansion upward
        spearman_accelerating = spearman_velocity > (historical_vel_mean + (1.5 * safe_vel_std))

        # CRITERIA B: The correlation has completely broken out of its traditional
        # deep short-hedging zone (typically below -0.50) and entered weak-negative/positive space.
        out_of_normal_bounds = comm_spearman_raw > -0.30

        # CRITERIA C: Ensure the price is actively moving to lock in path dependency
        price_moving = df[const.CLOSING_PRICE] != df[const.CLOSING_PRICE].shift(1)

        # Compile the unified signal mask into the main dataframe
        df[const.COMMS_SPEARMAN_REGIME_SHIFT] = (
            spearman_accelerating &
            out_of_normal_bounds &
            price_moving
        ).astype(bool)

        return df

    def _append_obos_concentration_setup():
        # ==============================================================================
        # SIGNAL: OBOS CONCENTRATION (Keenan Ch.8) — intersection of extremes
        # ==============================================================================
        # Keenan's Overbought/Oversold framework fires where an extreme in speculative
        # positioning coincides with an extreme in price. Both legs are already present
        # in this codebase; this setup simply intersects them:
        #
        #   Positioning leg = gross speculative Concentration (position as % of total OI)
        #                     in the top quartile of its own 52-week range
        #                     (Keenan Positioning Component; see calculate_range_index).
        #   Price leg       = the existing structural top/bottom (macro 70/30 band).
        #
        # OVERSOLD  (buy):  extreme SHORT concentration + price at structural bottom.
        #                   Crowded shorts at a price low → vulnerable to short-covering.
        # OVERBOUGHT (sell): extreme LONG concentration + price at structural top.
        #                   Crowded longs at a price high → vulnerable to liquidation.
        #
        # Caveat: LARGE = NonCommercial (MM+OR) on the Legacy store, so this is Keenan's
        # NC Concentration — an MM proxy (docs/spec_positioning_metrics_trio.md §2).
        # A catalyst is still required (Keenan §8.5); this flags the condition, not a fill.
        # ==============================================================================
        df[const.OBOS_OVERSOLD] = (
            large.conc_short_extreme &
            price.at_structural_bottom
        )
        df[const.OBOS_OVERBOUGHT] = (
            large.conc_long_extreme &
            price.at_structural_top
        )

        # --- Decile variant: both legs at a genuine 90/10 extreme of their 52-wk range.
        # Uses a decile Pricing Component (Keenan §6.1) instead of the loose 70/30 band,
        # to test whether selectivity rescues the edge the quartile version lacks.
        price_idx = calculate_range_index(df[const.CLOSING_PRICE], window=52)
        df[const.OBOS_OVERSOLD_DECILE] = (
            large.conc_short_decile &
            (price_idx <= const.OBOS_PRICE_IDX_DECILE_LO)
        )
        df[const.OBOS_OVERBOUGHT_DECILE] = (
            large.conc_long_decile &
            (price_idx >= const.OBOS_PRICE_IDX_DECILE_HI)
        )

        # --- Commercial (hedger) variant: CONVICTION, not unwind → pairing is inverted.
        # Extreme comm LONG concentration at a price low = smart-money accumulation (bull);
        # extreme comm SHORT concentration at a price high = distribution (bear).
        df[const.OBOS_COMM_OVERSOLD] = (
            comms.conc_long_extreme &
            price.at_structural_bottom
        )
        df[const.OBOS_COMM_OVERBOUGHT] = (
            comms.conc_short_extreme &
            price.at_structural_top
        )
        # Comm-decile — same conviction pairing at a genuine 90/10 extreme on both legs.
        df[const.OBOS_COMM_OVERSOLD_DECILE] = (
            comms.conc_long_decile &
            (price_idx <= const.OBOS_PRICE_IDX_DECILE_LO)
        )
        df[const.OBOS_COMM_OVERBOUGHT_DECILE] = (
            comms.conc_short_decile &
            (price_idx >= const.OBOS_PRICE_IDX_DECILE_HI)
        )

        # TRUE-MM decile — on real Money-Manager Concentration (Disaggregated).
        # All-False on financials.
        price_low = price_idx <= const.OBOS_PRICE_IDX_DECILE_LO
        price_high = price_idx >= const.OBOS_PRICE_IDX_DECILE_HI
        df[const.OBOS_MM_OVERSOLD_DECILE] = mm.conc_short_decile & price_low
        df[const.OBOS_MM_OVERBOUGHT_DECILE] = mm.conc_long_decile & price_high
        # Clustering-only (herding extreme).
        df[const.OBOS_MM_CLUST_OVERSOLD_DECILE] = mm.clust_short_decile & price_low
        df[const.OBOS_MM_CLUST_OVERBOUGHT_DECILE] = mm.clust_long_decile & price_high
        # Position-Size-only (conviction extreme).
        df[const.OBOS_MM_PSIZE_OVERSOLD_DECILE] = mm.psize_short_decile & price_low
        df[const.OBOS_MM_PSIZE_OVERBOUGHT_DECILE] = mm.psize_long_decile & price_high
        # Keenan's intersection — all three positioning legs at decile + price extreme.
        df[const.OBOS_MM_TRIPLE_OVERSOLD_DECILE] = (
            mm.conc_short_decile & mm.clust_short_decile & mm.psize_short_decile & price_low
        )
        df[const.OBOS_MM_TRIPLE_OVERBOUGHT_DECILE] = (
            mm.conc_long_decile & mm.clust_long_decile & mm.psize_long_decile & price_high
        )

        # TFF Leveraged Funds (financials) — the independent-universe re-test. Same
        # decile structure on the LEV group; all-False on commodities (no LEV data).
        df[const.OBOS_LEV_OVERSOLD_DECILE] = lev.conc_short_decile & price_low
        df[const.OBOS_LEV_OVERBOUGHT_DECILE] = lev.conc_long_decile & price_high
        df[const.OBOS_LEV_CLUST_OVERSOLD_DECILE] = lev.clust_short_decile & price_low
        df[const.OBOS_LEV_CLUST_OVERBOUGHT_DECILE] = lev.clust_long_decile & price_high
        df[const.OBOS_LEV_PSIZE_OVERSOLD_DECILE] = lev.psize_short_decile & price_low
        df[const.OBOS_LEV_PSIZE_OVERBOUGHT_DECILE] = lev.psize_long_decile & price_high
        df[const.OBOS_LEV_TRIPLE_OVERSOLD_DECILE] = (
            lev.conc_short_decile & lev.clust_short_decile & lev.psize_short_decile & price_low
        )
        df[const.OBOS_LEV_TRIPLE_OVERBOUGHT_DECILE] = (
            lev.conc_long_decile & lev.clust_long_decile & lev.psize_long_decile & price_high
        )

    # Execute the pipeline
    _append_larry_williams_bull_market_setup()
    _append_larry_williams_bear_market_setup()
    _append_4_year_commercial_buying_extreme_multiyear_high()
    _append_4_year_commercial_selling_extreme_multiyear_low()
    _append_the_fundamental_synergy_backwardation_cot_oi()
    _append_structural_bull_breakout_commercial_resistance_failed()
    _append_structural_bear_breakdown_commercial_support_failed()
    _append_commercial_capitulation_the_briese_stampede()
    _append_bullish_trend_continuation_healthy_dip_buying()
    _append_short_covering_rally_trend_line_break()
    _append_commercial_new_accumulation_bear_trap_setting()
    _append_commercial_accumulation_absorbing_risk()
    _append_bullish_bottom_oi_divergence_event()
    _append_short_squeeze_bear_trap()
    _append_stealth_bull_market_smart_money_accumulation()
    _append_bearish_trend_continuation_liquidity_vacuum()
    _append_bearish_top_distribution_trap()
    _append_exhaustion_starving_trend()
    _append_capitulation_liquidity_vacuum()
    _append_obos_concentration_setup()
    _append_spearman_regime_shift_signal()

    df[const.LRG_SPEC_MOMENTUM_DIVERGENCE] = calculate_lrg_spec_momentum_divergence(df, price)
    df[const.OI_ACCELERATION] = calculate_oi_acceleration(df)
    df[const.PRICE_VELOCITY_Z] = price.price_velocity_z

    # === ASSET CLASS SIGNAL FILTERING ===
    if asset_class == "Equities":
        df[const.LW_MACRO_BEAR_SETUP] = False
        df[const.LW_MACRO_BULL_SETUP] = False
        df[const.MULTI_YR_BEAR_EXTREME] = False
        df[const.MULTI_YR_BULL_EXTREME] = False

    return df


def calculate_reversal_matrices(df: pd.DataFrame, atr_window: int = 14) -> pd.DataFrame:
    """
    Calculates continuous geometric rejection scores to identify
    structural liquidity absorption.
    """
    df = df.copy()
    # 1. Calculate True Range and Baseline Volatility (ATR)
    df['prev_close'] = df['Close'].shift(1)
    df['tr0'] = abs(df['High'] - df['Low'])
    df['tr1'] = abs(df['High'] - df['prev_close'])
    df['tr2'] = abs(df['Low'] - df['prev_close'])
    df['TR'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['ATR'] = df['TR'].ewm(alpha=1/atr_window, adjust=False).mean()

    # 2. Geometric Primitives (Refactored for Gap-and-Go Reversals)
    # By measuring (Close - Low) against the True Range, we capture BOTH
    # intraday hammer wicks AND massive green bodies that reverse a gap down.
    df['bull_push_ratio'] = (df['Close'] - df['Low']) / (df['TR'] + 1e-9)
    df['bear_push_ratio'] = (df['High'] - df['Close']) / (df['TR'] + 1e-9)

    df['vol_expansion'] = df['TR'] / (df['ATR'] + 1e-9)

    # 3. Construct the Continuous Rejection Scores
    # Bullish: Buyers must recover/push at least 65% of the total True Range
    # combined with structural volatility expansion.
    df[const.BULL_REJECTION_SCORE] = np.where(
        df['bull_push_ratio'] > 0.65,
        df['bull_push_ratio'] * df['vol_expansion'],
        0.0
    )

    # Bearish: Sellers must reject/push down at least 65% of the total True Range
    df[const.BEAR_REJECTION_SCORE] = np.where(
        df['bear_push_ratio'] > 0.65,
        df['bear_push_ratio'] * df['vol_expansion'],
        0.0
    )

    # Clean up intermediate columns
    df.drop(columns=['prev_close', 'tr0', 'tr1', 'tr2'], inplace=True)

    return df


def prior_week_rejection_window(daily_df: pd.DataFrame, cot_date, lookback_days: int = 7) -> pd.DataFrame:
    """The daily bars in ``(cot_date - lookback_days, cot_date]`` — the week LEADING UP
    TO the COT cutoff, and never a bar after it.

    Point-in-time guarantee. This weekly value is keyed by ``cot_date`` and later
    as-of-joined onto trade entries (``report_date <= entry_date``); a trade always
    fills on a bar *after* the cutoff (the COT signal isn't even released until later
    that week), so summarizing only bars ``<= cot_date`` can never read the entry bar
    or anything after it. It replaces the old forward window ``(cot_date, cot_date + 7]``,
    which straddled the entry and leaked post-entry price into the feature — a
    per-row feature-construction lookahead that purged CV does not catch
    (see pardo ``docs/cmr_ml_lookahead.md`` and ``src/ml/features_pit.py``)."""
    idx = daily_df.index
    lo = pd.Timestamp(cot_date) - pd.Timedelta(days=lookback_days)
    hi = pd.Timestamp(cot_date)
    return daily_df.loc[(idx > lo) & (idx <= hi)]


def compute_weekly_rejection_scores(symbol: str, cot_dates: pd.DatetimeIndex, force_refresh: bool = False) -> pd.DataFrame:
    """
    Fetch daily OHLC, calculate rejection matrices, and extract the max rejection
    score over the ~5 trading days UP TO AND INCLUDING each COT cutoff (the prior
    week). Point-in-time: the summarized bars all precede any trade's entry, so the
    feature cannot peek past the entry the way the old post-cutoff window did — see
    ``prior_week_rejection_window``.
    """
    # force_refresh is now a no-op: prices come from the marketdata store
    # (producer-updated). Moved off cotdata by ADR-0007, which makes cotdata CFTC
    # positioning only; the tier name and the returned frame are unchanged.
    # Tier resolved from the symbol's domain rather than pinned, so this works
    # for the ETF-proxy equities as well as for futures.
    from cotmetrics.market_data import price_symbol
    daily_df = marketdata.get_bars(price_symbol(symbol))
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()

    daily_df = calculate_reversal_matrices(daily_df)

    records = []

    for cot_date in cot_dates:
        observation = prior_week_rejection_window(daily_df, cot_date)

        if observation.empty:
            continue

        max_bull = observation[const.BULL_REJECTION_SCORE].max()
        max_bear = observation[const.BEAR_REJECTION_SCORE].max()

        records.append({
            const.REPORT_DATE_XLS: cot_date,
            const.BULL_REJECTION_SCORE: max_bull,
            const.BEAR_REJECTION_SCORE: max_bear
        })

    if not records:
        return pd.DataFrame()

    res_df = pd.DataFrame(records).set_index(const.REPORT_DATE_XLS)
    return res_df


def flag_capitulation_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    Combines geometric rejection scores with Open Interest kinetics
    to flag highly asymmetrical blow-off bottoms/tops.
    """
    df = df.copy()

    # 1. Define the extreme structural thresholds
    REJECTION_THRESHOLD = 1.5   # Candle must be mathematically extreme
    OI_ACCEL_THRESHOLD = 1.0    # Capital velocity must be actively surging
    LSR_SQUEEZE_FLOOR = 1.0     # Specs must be overcrowded / trapped

    # Ensure columns exist, fill with 0 if missing
    for col in [const.BULL_REJECTION_SCORE, const.BEAR_REJECTION_SCORE, const.OI_ACCELERATION, const.LIQUIDITY_STRAIN_CUSTOM]:
        if col not in df.columns:
            df[col] = 0.0

    # 2. Flag the Bullish Capitulation Blow-Off (The Institutional Floor)
    df[const.FLAG_BULL_CAPITULATION] = np.where(
        (df[const.BULL_REJECTION_SCORE] >= REJECTION_THRESHOLD) &
        (df[const.OI_ACCELERATION] >= OI_ACCEL_THRESHOLD) &
        (df[const.LIQUIDITY_STRAIN_CUSTOM] <= -LSR_SQUEEZE_FLOOR),
        1, 0
    )

    # 3. Flag the Bearish Capitulation Blow-Off (The Institutional Ceiling)
    df[const.FLAG_BEAR_CAPITULATION] = np.where(
        (df[const.BEAR_REJECTION_SCORE] >= REJECTION_THRESHOLD) &
        (df[const.OI_ACCELERATION] >= OI_ACCEL_THRESHOLD) &
        (df[const.LIQUIDITY_STRAIN_CUSTOM] >= LSR_SQUEEZE_FLOOR), # Specs overcrowded long
        1, 0
    )

    return df
