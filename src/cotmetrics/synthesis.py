"""
core/synthesis.py

Dash-free signal synthesis: turns a positioning/indicator data row into plain
Python signal labels, tooltips, and the multi-pillar tape narrative. Kept out of
the Dash card layer so headless consumers (core.reports, the email report path)
can build report text without importing dash.
"""
import pandas as pd

import cotmetrics.constants as const
import cotmetrics.utils as utils


def _collect_active_signals(latest, include_accumulation=True):
    """Return (bull_signals, bear_signals, tooltips) from a data row.

    Parameters
    ----------
    latest              : pandas Series – the row to inspect
    include_accumulation: bool – whether to include the softer accumulation
                          signals (used by the desktop panel but not the
                          compact mobile card)

    Returns
    -------
    tuple[list[str], list[str], list[str]]
        Active bull labels, active bear labels, tooltip texts (one per signal,
        in the order they were appended).
    """
    bull_signals:  list[str] = []
    bear_signals:  list[str] = []
    debug_signals: list[str] = []
    tooltips:      list[str] = []

    # ---- Bullish ----
    if latest.get(const.BULLISH_TREND_CONTINUING, False):
        bull_signals.append("BULL TREND")
        tooltips.append("Bullish Bottom: Extreme Commercial longs met with Open Interest divergence (absorption or short covering).")
    if latest.get(const.BULLISH_BOTTOM, False):
        bull_signals.append("BULL BOTTOM")
        tooltips.append("Bullish Bottom: Extreme Commercial longs aligned with Open Interest divergence. Smart money has successfully trapped late sellers.")
    if latest.get(const.SHORT_SQUEEZE, False):
        bull_signals.append("SHORT SQZ")
        tooltips.append("Short Squeeze: Price exhaustion at support with actively declining Open Interest (trapped shorts covering).")
    if latest.get(const.STEALTH_BULLISH_BOTTOM, False):
        bull_signals.append("STEALTH BULL")
        tooltips.append("Stealth Bullish Bottom: Commercials are quietly accumulating massive structural longs under the radar during a slow, grinding downtrend.")
    if latest.get(const.SPEC_DRIVEN_BULL_BREAKOUT, False):
        bull_signals.append("STRUCTURAL BULL")
        tooltips.append("Structural Bull Breakout: Price is rallying to new highs directly through a massive commercial selling surge. Commercial resistance has failed, signaling a speculative-driven trend.")
    if latest.get(const.COMM_MACD_BULL_CROSS, False) and not latest.get(const.SPEC_DRIVEN_BEAR_BREAKDOWN, False):
        bull_signals.append("MACD BUY")
        tooltips.append("COT-MACD Bull Crossover: Commercial structural momentum is actively accelerating upward. This is a leading indicator that smart money is taking control.")
    if latest.get(const.LW_MACRO_BULL_SETUP, False):
        bull_signals.append("LW MACO BULL")  # typo preserved from original
        tooltips.append("Macro Bull Setup: The market is in a sideways consolidation while Open Interest has collapsed by over 25%. Commercials have quietly covered their shorts and cleared the liquidity ceiling, priming the market for an upside breakout.")
    if latest.get(const.MULTI_YR_BULL_EXTREME, False):
        bull_signals.append("4-YR BUY EXTREME")
        tooltips.append(
            "Multiyear Net Extreme: Commercials have reached their highest net buying position "
            "in at least 4 years. This absolute historical boundary signals massive accumulation "
            "and strongly indicates a major structural bull market is imminent."
        )

    if include_accumulation:
        if latest.get(const.COMMS_ACCUMULATION, False):
            debug_signals.append("ACCUMULATION")
            tooltips.append("Comm Accumulation: Price dropping while Open Interest rises. Commercials picking up new spec short selling at a discount.")
        if latest.get(const.COMMS_NEW_ACCUMULATION, False):
            debug_signals.append("NEW ACCUM")
            tooltips.append("Comm New Accumulation: Price at shortterm low as Open Interest surges. Commercials are actively taking the other side of aggressive new short sellers to trap the late shorts.")
        if latest.get(const.SHORT_COVERING, False):
            debug_signals.append("SHORT COVERING")
            tooltips.append("Short Covering: Price breaks downtrend with a sharp OI decrease and recent extreme short positioning.")

    # ---- Bearish ----
    if latest.get(const.BEARISH_TREND_CONTINUING, False):
        bear_signals.append("BEAR TREND")
        tooltips.append("Bear Trend Continuation: A short-term relief rally in an established downtrend. Commercials are aggressively selling into the bounce.")
    if latest.get(const.BEARISH_TOP, False):
        bear_signals.append("BEAR TOP")
        tooltips.append("Bear Top: Extreme Commercial short positioning meets Open Interest divergence. Smart money is quietly absorbing euphoric late buyers.")
    if latest.get(const.EXHAUSTION, False):
        bear_signals.append("EXHAUSTION")
        tooltips.append("Trend Exhaustion: Price struggles to push higher while Open Interest actively declines. The current trend has run out of new participants.")
    if latest.get(const.CAPITULATION, False):
        bear_signals.append("CAPITULATION")
        tooltips.append("Capitulation / Wash-out: Violent price action meets a massive collapse in Open Interest. Panicked traders are being forced into margin calls and liquidations.")
    if latest.get(const.SPEC_DRIVEN_BEAR_BREAKDOWN, False):
        bear_signals.append("STRUCTURAL BEAR")
        tooltips.append("Structural Bear Breakdown: Price drops to new lows directly through massive commercial buying. Commercial support has failed, signaling a definitive macro trend change.")
    if latest.get(const.COMMS_CAPITULATION, False):
        bear_signals.append("COMM CAPITULATION")
        tooltips.append("Commercial Capitulation: Price is plunging and Commercials have abandoned their standard dip-buying strategy. Smart money is aggressively liquidating longs, removing the market's natural braking system and triggering a downward stampede.")
    if latest.get(const.COMM_MACD_BEAR_CROSS, False):
        bear_signals.append("MACD SELL")
        tooltips.append("COT-MACD Bear Crossover: Commercial structural momentum is actively accelerating downward. Smart money is aggressively distributing ahead of a potential ceiling.")
    if latest.get(const.LW_MACRO_BEAR_SETUP, False):
        bear_signals.append("MACRO BEAR SETUP")
        tooltips.append(
            "Macro Bear Setup: The market is consolidating sideways while Open Interest has surged over 25%. "
            "Commercials are aggressively layering in short hedges against speculator buying, building a heavy "
            "resistance ceiling and priming the market for a high-probability downside breakdown."
        )
    if latest.get(const.MULTI_YR_BEAR_EXTREME, False):
        bear_signals.append("4-YR SELL EXTREME")
        tooltips.append(
            "Multiyear Net Extreme: Commercials have reached their lowest net selling position "
            "in at least 4 years. This absolute historical boundary proves smart-money is heavily "
            "short-hedged against a top, warning of a severe structural bear market."
        )

    return bull_signals, bear_signals, debug_signals, tooltips


def generate_exhaustive_tape_synthesis(row: pd.Series, symbol_str: str = None, df: pd.DataFrame = None) -> dict:
    """
    Exhaustively synthesizes all 10 dashboard cards into a single
    multi-dimensional narrative risk matrix.
    """
    # [Core Primitives]
    willco = row.get(const.WILLCO_ALIAS, 50)
    large_spec_idx = row.get(const.LRG_IDX, 50)
    oi_z = row.get(const.OI_ZSCORE, 0.0)
    comm_roc = row.get(const.COMM_MOMENTUM, 0.0)

    # [Advanced Primitives from Remaining Cards]
    spearman_regime = row.get(const.COMMS_SPEARMAN_REGIME_SHIFT, False)
    comm_spearman = row.get(const.COMMS_SPEARMAN, 0.0)
    lrg_spearman = row.get(const.LRG_SPEARMAN, 0.0)
    comm_z = row.get(const.COMMS_ZSCORE, 0.0)
    spec_z = row.get(const.LRG_ZSCORE, 0.0)
    lrg_sentiment = row.get(const.LW_LRG_SENTIMENT, 50)

    def safe_fmt(val, fmt):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "N/A"
        try:
            return format(val, fmt)
        except Exception:
            return str(val)

    row.get(const.COMM_MACD_BULL_CROSS, False)
    row.get(const.COMM_MACD_BEAR_CROSS, False)
    row.get(const.BULL_REJECTION_SCORE, 0.0)
    row.get(const.BEAR_REJECTION_SCORE, 0.0)
    row.get(const.FLAG_BULL_CAPITULATION, 0)
    row.get(const.FLAG_BEAR_CAPITULATION, 0)

    # Absolute directional filters
    row.get(const.LARGE_NET, 0) < 0
    commercials_are_net_long = row.get(const.COMM_NET, 0) > 0
    price_trend_is_up = utils.price_trend_is_up(df, row.name)

    # ------------------------------------------------------------------
    # PILLAR 1: COMMERCIAL COMPRESSION (Cards: WILLCO, Comm Mom, Setup)
    # ------------------------------------------------------------------
    if willco >= const.WILLCO_MAX_THRESHOLD or (oi_z > const.OI_ZSCORE_ELEVATED_MAX_THRESHOLD and not price_trend_is_up and commercials_are_net_long):
        p_inst = {"status": "STRONG ACCUMULATION", "desc": "Commercials are aggressively absorbing retail short selling via passive limit floors."}
    elif willco <= const.WILLCO_MIN_THRESHOLD or (oi_z > const.OI_ZSCORE_ELEVATED_MAX_THRESHOLD and price_trend_is_up and not commercials_are_net_long):
        p_inst = {"status": "HEAVY DISTRIBUTION", "desc": "Commercial inventory is being actively distributed into late breakout buyers."}
    else:
        p_inst = {"status": "NEUTRAL DISTRIBUTION", "desc": "Commercial hedging is operating within standard baseline limits."}

    # Define directional extreme flags
    # The index and the sentiment stochastic share a band by coincidence, not by rule,
    # so each reads its own constant.
    spec_short_extreme = (large_spec_idx <= const.SPEC_IDX_EXTREME_MIN_THRESHOLD) or (lrg_sentiment <= const.LW_LRG_SENTIMENT_MIN_THRESHOLD)
    spec_long_extreme = (large_spec_idx >= const.SPEC_IDX_EXTREME_MAX_THRESHOLD) or (lrg_sentiment >= const.LW_LRG_SENTIMENT_MAX_THRESHOLD)

    # Resolve conflict if both are triggered (e.g., the index and the sentiment
    # stochastic can sit at opposite ends of their own lookback windows)
    if spec_short_extreme and spec_long_extreme:
        if large_spec_idx <= const.SPEC_IDX_EXTREME_MIN_THRESHOLD or lrg_sentiment <= const.LW_LRG_SENTIMENT_MIN_THRESHOLD:
            spec_long_extreme = False
        else:
            spec_short_extreme = False

    if spec_short_extreme and not spec_long_extreme:
        p_spec = {"status": "SPECULATIVE EXHAUSTION (SHORT)", "desc": "Public trend-followers have reached max short capacity, leaving the tape thin."}
    elif spec_long_extreme and not spec_short_extreme:
        p_spec = {"status": "SPECULATIVE EXHAUSTION (LONG)", "desc": "Retail long positioning is structurally overcrowded and vulnerable to a margin flush."}
    else:
        p_spec = {"status": "BALANCED CAPACITY", "desc": "Speculative positions are safely distributed within normal historical ranges."}

    # ------------------------------------------------------------------
    # PILLAR 3: KINETIC FLOW (Card: Commercial Momentum)
    # ------------------------------------------------------------------
    if abs(comm_roc) >= const.MOMENTUM_MAX_THRESHOLD:
        p_kinetic = {"status": "ELEVATED MOMENTUM", "desc": "Active commercial positioning flows are steadily expanding and leading the current price leg."}
    else:
        p_kinetic = {"status": "SYNCHRONIZED BASELINE", "desc": "Capital flows and price velocity are moving in historical equilibrium."}

    # ------------------------------------------------------------------
    # NEW PILLAR 4: REGIME COHESION & SKEW (Cards: Spearman, Positioning Z)
    # ------------------------------------------------------------------
    # ZSCORE_SKEW_THRESHOLD, not ZSCORE_MAX_THRESHOLD: this gate is deliberately looser
    # than a single-leg extreme, because it already requires two legs opposed.
    _skew = const.ZSCORE_SKEW_THRESHOLD
    opposite_extremes = (comm_z >= _skew and spec_z <= -_skew) or (comm_z <= -_skew and spec_z >= _skew)

    if spearman_regime and opposite_extremes:
        p_cohesion = {"status": "STRUCTURAL REGIME ANOMALY", "desc": f"CRITICAL RISK: Commercial correlation matrices have fractured (Comm: {safe_fmt(comm_spearman, '.2f')}, Spec: {safe_fmt(lrg_spearman, '.2f')}) alongside standard deviation boundaries. A major macro turning point is active."}
    elif opposite_extremes:
        p_cohesion = {"status": "BOUNDARY EXTREME DETECTED", "desc": f"Commercials and Speculators are pinned at opposite standard deviation bands with stable correlation (Comm: {safe_fmt(comm_spearman, '.2f')}). Coiling energy is high."}
    else:
        p_cohesion = {"status": "COHESIVE BALANCE", "desc": f"Correlation structures and statistical distance scores are stable and normal (Comm: {safe_fmt(comm_spearman, '.2f')}, Spec: {safe_fmt(lrg_spearman, '.2f')})."}

    # ------------------------------------------------------------------
    # NEW PILLAR 6: OPTIONS STRUCTURING
    # ------------------------------------------------------------------
    from cotmetrics.options_data import get_max_pain_for_symbol
    try:
        report_date_str = pd.to_datetime(row.name).strftime('%Y-%m-%d')
        res = get_max_pain_for_symbol(symbol_str, report_date_str)
        max_pain, delta_iv, current_price = (res["max_pain"], res["delta_iv"], res.get("current_price")) if res else (None, None, None)
    except Exception:
        max_pain, delta_iv, current_price = None, None, None

    def fmt_div(val):
        if val is None:
            return "N/A"
        val_k = val * 1000
        if abs(val_k) < 1.0:
            return f"{val_k:,.1f}K"
        return f"{val_k:,.0f}K"

    if max_pain and current_price:
        pull_pct = ((max_pain - current_price) / current_price) * 100
        pull_str = f" | PULL: {pull_pct:+.1f}%"
    else:
        pull_str = ""

    {
        "status": f"MAX PAIN DETECTED: {max_pain:,.1f} | ΔIV: {fmt_div(delta_iv)}{pull_str}" if max_pain else "NO OPTIONS DATA",
        "desc": "Calculated point of maximum options seller profitability (Intrinsic Value Minimum)." if max_pain else "Decoupled options data cache not found or currently unavailable."
    }

    # ------------------------------------------------------------------
    # THE HOLISTIC EXECUTIVE HEADLINE GENERATOR
    # ------------------------------------------------------------------
    tape_bias = "neutral"
    tape_summary = "Commercial hedging and speculative capacity are balanced."

    if "ACCUMULATION" in p_inst["status"] and "SHORT" in p_spec["status"]:
        tape_bias = "bullish"
        tape_summary = "Broad commercial accumulation at support floor and public speculator exhaustion."
    elif "DISTRIBUTION" in p_inst["status"] and "LONG" in p_spec["status"]:
        tape_bias = "bearish"
        tape_summary = "Heavy commercial distribution at resistance ceiling and public speculator exhaustion."

    overall_bias = "neutral"
    if tape_bias == "bullish":
        overall_bias = "bullish"
        exec_headline = "COMMERCIAL FLOOR SETUP (CONTRARIAN BULLISH)"
        exec_summary = "An elite, fully-vetted long entry configuration is live. Broad commercial buying floors and public speculator exhaustion are verified."
    elif tape_bias == "bearish":
        overall_bias = "bearish"
        exec_headline = "COMMERCIAL CEILING SETUP (CONTRARIAN BEARISH)"
        exec_summary = "A commercial topping process is verified. Smart money is aggressively liquidating inventory directly into late-stage retail FOMO buyers. High risk of a sudden downside margin flush."
    else:
        exec_headline = "TACTICAL ASSET DRIFT (NO SYSTEMIC EDGE)"
        exec_summary = "The asset lacks aligned commercial backing across structural, kinetic, and predictive layers. Maintain baseline risk or stand aside."

    return {
        "headline": exec_headline,
        "summary": exec_summary,
        "overall_bias": overall_bias,
        "tape_bias": tape_bias,
        "tape_summary": tape_summary,
        "matrix": {
            "1. Commercial Matrix": p_inst,
            "2. Speculator Crowding": p_spec,
            "3. Capital Flow Velocity": p_kinetic,
            "4. Statistical Cohesion": p_cohesion
        }
    }
