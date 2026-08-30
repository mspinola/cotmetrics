import logging
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

import cotmetrics.constants as const

logger = logging.getLogger(__name__)

#: The per-symbol history filename, as both a writer target and a "is there anything
#: here?" probe. One pattern so the two can never drift.
HISTORY_GLOB = "*_options_history.parquet"


def _legacy_options_dir() -> Path:
    """Where the history lived before it had a constant of its own: under CACHE_DIR.

    Kept as a READ fallback only. See `options_history_dir` for why it cannot simply
    be dropped.
    """
    return Path(const.CACHE_DIR) / "options"


def _holds_history(directory: Path) -> bool:
    return directory.is_dir() and any(directory.glob(HISTORY_GLOB))


#: Paths already named in a location warning. The reader resolves once PER SYMBOL, so
#: an unthrottled warning is ~24 identical lines every time the Signal Matrix renders.
#: That volume is not harmless: a real traceback on this deployment was once buried
#: under exactly this kind of repeated line. Once per path per process is enough to act
#: on, and `clear()` keeps it testable.
_WARNED_PATHS: set = set()


def _warn_once(key, message, *args) -> None:
    if key in _WARNED_PATHS:
        return
    _WARNED_PATHS.add(key)
    logger.warning(message, *args)


def options_history_dir() -> Path:
    """Where option snapshots live, for both readers and writers.

    NOT a cache, despite where it used to sit. Each run appends the current live chain
    to a permanent per-symbol history and yfinance serves only today's chain, so a
    deleted day is gone for good. `constants.OPTIONS_DIR` carries the full reasoning;
    it defaults under the XDG *data* dir alongside the citpy notes and the visitor DB,
    the other two durable things that must not sit under a cache root.

    Resolution deliberately prefers an EXISTING history over a tidy default, because
    the failure this function already has a scar from is a silent one. From the test
    module's own docstring: snapshots once "landed where nothing read them", and the
    symptom was Max Pain quietly empty for 22 of 24 symbols rather than an error. Moving
    the default without a fallback would reproduce that exactly -- the old history
    orphaned, a new one accumulating beside it, and nothing on screen saying so.

      1. COTMETRICS_OPTIONS set -> honour it, no guessing.
      2. the new location already holds a history -> use it.
      3. only the legacy location does -> use it, and say so once per process.
      4. neither -> the new location. A fresh install starts in the right place.
    """
    new = Path(const.OPTIONS_DIR)
    legacy = _legacy_options_dir()
    if os.environ.get("COTMETRICS_OPTIONS"):
        return new
    if _holds_history(new):
        if _holds_history(legacy):
            # Both populated. Prefer the new one (it is the configured default) but do
            # not let the other rot unmentioned: whichever the daily job last appended
            # to is the complete one, and only an operator can say which that is.
            _warn_once(
                ("both", new, legacy),
                "Options history exists in BOTH %s and %s. Reading the first. The "
                "second is not being appended to and is not merged automatically; "
                "reconcile them by hand, since only you can tell which run wrote which.",
                new, legacy)
        return new
    if _holds_history(legacy):
        _warn_once(
            ("legacy", legacy),
            "Options max-pain history is still at the legacy path %s, which sits under "
            "the derived-cache root and is not safe there (clearing the cache would "
            "destroy it permanently -- yfinance cannot refetch past chains). Reading it "
            "from there for now. Migrate with:  mv %s %s",
            legacy, legacy, new)
        return legacy
    return new

# Map CME futures symbols to their most liquid ETF proxy for options data
ETF_PROXIES = {
    # Equities
    "ES": "SPY",
    "NQ": "QQQ",
    "YM": "DIA",
    "RTY": "IWM",
    # Metals
    "GC": "GLD",
    "SI": "SLV",
    "HG": "CPER",
    "PA": "PALL",
    "PL": "PPLT",
    # Energies
    "CL": "USO",
    "NG": "UNG",
    "RB": "UGA",
    # Fixed Income
    "ZB": "TLT",
    "ZN": "IEF",
    "ZF": "IEI",
    "ZT": "SHY",
    # Currencies
    "6E": "FXE",
    "6J": "FXY",
    "6B": "FXB",
    "6A": "FXA",
    "6C": "FXC",
    "6S": "FXF",
    "DX": "UUP",
    # Grains
    "ZC": "CORN",
    "ZW": "WEAT",
    "ZS": "SOYB",
    # Softs
    "LBR": "WOOD",
    "SB": "CANE",
    # Crypto
    "BTC": "BITO",
    "ETH": "ETHE",
}

def fetch_options_chain(etf_symbol: str):
    """
    Fetches the nearest expiration options chain for a given ETF proxy using yfinance.
    Returns the chain dataframe, underlying price, and expiration date.
    """
    try:
        tk = yf.Ticker(etf_symbol)
        if not tk.options:
            logger.warning(f"No options found for {etf_symbol}")
            return None, None, None, None

        # Get the nearest expiration date
        # Usually we want the monthly opex, but for proxies we just take the nearest front-month
        # that has significant volume. For simplicity, we just take the first available.
        # To avoid 0DTE noise, let's pick the first expiry that is at least 3 days out.
        expirations = tk.options
        today = pd.Timestamp.now().normalize()
        valid_expiries = [exp for exp in expirations if pd.Timestamp(exp) > today + pd.Timedelta(days=3)]

        target_expiry = valid_expiries[0] if valid_expiries else expirations[0]

        opt = tk.option_chain(target_expiry)
        calls = opt.calls
        puts = opt.puts

        # We need strike, openInterest, type
        calls['type'] = 'call'
        puts['type'] = 'put'

        chain = pd.concat([calls, puts])

        if chain.empty:
            logger.warning(f"Options chain is completely empty for {etf_symbol}")
            return None, None, None, None

        total_strikes_before = len(chain)

        # yfinance glitch failsafe: try to fill NaN open interest with volume
        if 'volume' in chain.columns:
            chain['openInterest'] = chain['openInterest'].fillna(chain['volume'])
        chain['openInterest'] = chain['openInterest'].fillna(0)

        # Filter out extreme OTM strikes with 0 open interest to save computation
        chain = chain[chain['openInterest'] > 0]

        total_strikes_after = len(chain)

        # Sanity check: abort if the chain lost more than 80% of its strikes due to missing OI (yfinance glitch)
        if total_strikes_after < (total_strikes_before * 0.2):
            logger.warning(f"Aborting options snapshot for {etf_symbol}: Chain lost {((total_strikes_before - total_strikes_after)/total_strikes_before)*100:.1f}% of strikes (yfinance OI glitch detected).")
            return None, None, None, None

        # Sanity check: abort if we have suspiciously few strikes left
        if total_strikes_after < 10:
            logger.warning(f"Aborting options snapshot for {etf_symbol}: Only {total_strikes_after} valid strikes left after filtering.")
            return None, None, None, None

        # Get live underlying price and actual quote date
        hist = tk.history(period="5d")
        if not hist.empty:
            underlying_price = hist['Close'].iloc[-1]
            quote_date = hist.index[-1].strftime("%Y-%m-%d")
        else:
            underlying_price = None
            quote_date = pd.Timestamp.now().strftime("%Y-%m-%d")

        if underlying_price is None:
            info = tk.info
            underlying_price = info.get('regularMarketPrice', info.get('previousClose', 0))

        return chain, underlying_price, target_expiry, quote_date
    except Exception as e:
        logger.error(f"Error fetching options for {etf_symbol}: {e}")
        return None, None, None, None


def calculate_intrinsic_curve(chain: pd.DataFrame, underlying_price: float, points=200):
    """
    Calculates the notional intrinsic value of the entire options chain across a simulated
    range of underlying prices.

    Returns:
        simulated_prices: array of x-axis prices
        total_intrinsic: array of y-axis notional values (in Millions)
        max_pain_strike: the strike price where total_intrinsic is minimized
    """
    # Create a range of prices around the current underlying (+/- 20%)
    min_strike = chain['strike'].min()
    max_strike = chain['strike'].max()

    # Bound the simulation to relevant strikes where there is OI
    sim_min = max(underlying_price * 0.8, min_strike)
    sim_max = min(underlying_price * 1.2, max_strike)

    simulated_prices = np.linspace(sim_min, sim_max, points)
    total_intrinsic = np.zeros(points)

    calls = chain[chain['type'] == 'call']
    puts = chain[chain['type'] == 'put']

    # Standard option contract multiplier is 100 shares per contract
    # Intrinsic Value of Call = max(0, Underlying - Strike) * OI * 100
    # Intrinsic Value of Put = max(0, Strike - Underlying) * OI * 100

    for i, sim_px in enumerate(simulated_prices):
        call_iv = np.maximum(0, sim_px - calls['strike']) * calls['openInterest'] * 100
        put_iv = np.maximum(0, puts['strike'] - sim_px) * puts['openInterest'] * 100

        total_value = call_iv.sum() + put_iv.sum()
        # Convert to Millions for readability on the graph
        total_intrinsic[i] = total_value / 1_000_000.0

    min_idx = np.argmin(total_intrinsic)
    max_pain_price = simulated_prices[min_idx]

    # Usually max pain is defined strictly at available strike prices, not arbitrary floats.
    # We find the nearest actual strike to our mathematical minimum.
    all_strikes = np.sort(chain['strike'].unique())
    nearest_strike_idx = np.abs(all_strikes - max_pain_price).argmin()
    max_pain_strike = all_strikes[nearest_strike_idx]

    return simulated_prices, total_intrinsic, max_pain_strike


def build_daily_options_snapshot(futures_symbol: str, live_futures_price: float = None):
    """
    Fetches the live options chain for the ETF proxy of the futures_symbol,
    calculates the intrinsic value curve, scales it to match the futures price,
    and saves it to the local cache.
    """
    try:
        etf_symbol = ETF_PROXIES.get(futures_symbol)
        if not etf_symbol:
            logger.info(f"No ETF proxy mapped for {futures_symbol}. Skipping options snapshot.")
            return None

        chain, underlying_price, expiry, quote_date = fetch_options_chain(etf_symbol)
        # np.isfinite rather than `is None or == 0`: a NaN quote is neither, so it used
        # to pass this guard and get written. The snapshot is appended to a permanent
        # parquet and nothing repairs it, so one bad quote day poisoned that date
        # forever -- which is what emptied Max Pain for 22 of 24 symbols on 2026-07-14.
        if chain is None or chain.empty:
            return None
        if underlying_price is None or not np.isfinite(underlying_price) or underlying_price == 0:
            logger.warning(
                f"Skipping options snapshot for {futures_symbol}: unusable underlying "
                f"price from {etf_symbol} ({underlying_price!r})")
            return None

        sim_px, total_iv, max_pain = calculate_intrinsic_curve(chain, underlying_price)

        # Scale ETF prices back to Futures prices if a futures price is provided
        # e.g., if SPY is 550 and ES is 5500, ratio is ~10.
        ratio = 1.0
        if live_futures_price is not None and live_futures_price > 0:
            ratio = live_futures_price / underlying_price

        scaled_sim_px = sim_px * ratio
        scaled_max_pain = max_pain * ratio
        scaled_underlying = underlying_price * ratio

        # Appended to the permanent per-symbol history. See `options_history_dir`:
        # this is accumulated data, not a cache, and today's chain is the only one
        # yfinance will ever serve.
        cache_dir = options_history_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Build the snapshot dataframe using the actual market quote date
        target_date_str = quote_date

        snapshot_df = pd.DataFrame({
            'Date': [target_date_str] * len(sim_px),
            'Expiry': [expiry] * len(sim_px),
            'UnderlyingPrice': [scaled_underlying] * len(sim_px),
            'SimulatedStrike': scaled_sim_px,
            'IntrinsicValue_M': total_iv,
            'MaxPainStrike': [scaled_max_pain] * len(sim_px),
            'ETF_Proxy': [etf_symbol] * len(sim_px)
        })

        # Append to historical parquet file
        history_file = cache_dir / f"{futures_symbol}_options_history.parquet"
        if history_file.exists():
            try:
                hist_df = pd.read_parquet(history_file)
                # Remove target_date if already ran on this quote date
                hist_df = hist_df[hist_df['Date'] != target_date_str]
                snapshot_df = pd.concat([hist_df, snapshot_df], ignore_index=True)
            except Exception as e:
                # An unreadable history means a torn write (concurrent writers, or
                # a kill mid-write), and the history is unrecoverable data: yfinance
                # serves only today's chain. Overwriting here used to turn one
                # corrupt READ into permanent loss of every prior date. Set the
                # bytes aside for hand recovery and start a fresh file instead.
                aside = history_file.with_name(
                    f"{history_file.name}.corrupt-{int(time.time())}")
                history_file.replace(aside)
                logger.error(
                    f"Unreadable options history for {futures_symbol} ({e}); moved "
                    f"it aside to {aside.name}, starting a fresh history from today")

        # Write-then-rename, with a per-process temp name, so a concurrent reader
        # or a kill mid-write can never leave a half-written file at the real name.
        tmp_file = history_file.with_name(f"{history_file.name}.tmp-{os.getpid()}")
        snapshot_df.to_parquet(tmp_file)
        tmp_file.replace(history_file)
        logger.info(f"Saved options snapshot for {futures_symbol} (Proxy: {etf_symbol}) to {history_file.name}")

        return snapshot_df
    except Exception as e:
        logger.error(f"Failed to build daily options snapshot for {futures_symbol}: {e}")
        return None

_MAX_PAIN_CACHE = {}

def get_max_pain_for_symbol(futures_symbol: str, target_date=None) -> Optional[float]:
    """
    Reads the decoupled options cache and returns the Max Pain simulated strike for a given date.
    Returns None if no options data exists for the symbol or date.
    """
    import cotmetrics.utils as utils

    global _MAX_PAIN_CACHE
    cache_key = f"{futures_symbol}_{target_date}"
    current_time = time.time()

    if cache_key in _MAX_PAIN_CACHE:
        cached_time, cached_data = _MAX_PAIN_CACHE[cache_key]
        if current_time - cached_time < 3600 * 3: # Valid for 3 hours
            return cached_data

    try:
        filepath = options_history_dir() / f"{futures_symbol}_options_history.parquet"
        if not filepath.exists():
            return None

        df = pd.read_parquet(filepath)
        if df.empty:
            return None

        if target_date:
            target_dt = pd.to_datetime(target_date).date()
            df['DateObj'] = pd.to_datetime(df['Date']).dt.date

            # Calculate absolute differences
            df['DateDiff'] = (df['DateObj'] - target_dt).apply(lambda x: abs(x.days))

            # Filter to within 14 days (since COT reports have a ~10 day lag before the next publish)
            valid_df = df[df['DateDiff'] <= 14]
            if valid_df.empty:
                return None

            # Get the closest date
            closest_diff = valid_df['DateDiff'].min()
            best_date = valid_df[valid_df['DateDiff'] == closest_diff]['Date'].max()
            daily_df = valid_df[valid_df['Date'] == best_date]
        else:
            latest_date = df['Date'].max()
            daily_df = df[df['Date'] == latest_date]

        if daily_df.empty:
            return None

        # A snapshot written before the NaN guard above can still be sitting in the
        # cache, so the unusable case is detected rather than walked into. idxmin on an
        # all-NA series returns NaN, .loc[NaN] then raises KeyError('nan'), and the
        # resulting log line named neither the symbol's real problem nor the date. It
        # is also a FutureWarning that pandas will turn into a hard ValueError.
        snapshot_date = daily_df['Date'].iloc[0]
        current_price = daily_df['UnderlyingPrice'].iloc[0]
        if current_price is None or not np.isfinite(current_price) or current_price == 0:
            utils.cot_logger.warning(
                f"Max pain unavailable for {futures_symbol} on {snapshot_date}: "
                f"snapshot carries no usable underlying price")
            return None
        if daily_df['IntrinsicValue_M'].isna().all() or daily_df['SimulatedStrike'].isna().all():
            utils.cot_logger.warning(
                f"Max pain unavailable for {futures_symbol} on {snapshot_date}: "
                f"snapshot carries no usable intrinsic-value curve")
            return None

        # Max Pain is the simulated strike with the absolute minimum intrinsic value
        min_idx = daily_df['IntrinsicValue_M'].idxmin()
        max_pain = daily_df.loc[min_idx, 'SimulatedStrike']
        min_iv = daily_df.loc[min_idx, 'IntrinsicValue_M']

        # Calculate Delta IV
        closest_strike_idx = (daily_df['SimulatedStrike'] - current_price).abs().idxmin()
        current_iv = daily_df.loc[closest_strike_idx, 'IntrinsicValue_M']
        delta_iv = current_iv - min_iv


        res = {"max_pain": float(max_pain), "delta_iv": float(delta_iv), "current_price": float(current_price)}
        _MAX_PAIN_CACHE[cache_key] = (current_time, res)
        return res
    except Exception as e:
        utils.cot_logger.error(f"Error retrieving max pain for {futures_symbol}: {e}")
        return None

def update_all_daily_options():
    """
    Iterates over all supported instruments and fetches the daily options Max Pain snapshot.
    """
    import marketdata

    import cotmetrics.utils as utils
    from cotmetrics.market_data import _SYMBOL_TO_NAME, price_symbol

    utils.cot_logger.info("Starting daily options Max Pain fetch for all instruments...")
    for symbol in _SYMBOL_TO_NAME.keys():
        try:
            # Fetch the latest prices to provide the live price for scaling the proxy ETF
            # Tier left to marketdata: this loop covers the whole universe,
            # including the ETF-proxy equities, and a futures tier raises on those.
            price_df = marketdata.get_bars(price_symbol(symbol))
            if price_df is not None and not price_df.empty:
                live_price = price_df['Close'].iloc[-1]
            else:
                live_price = None

            build_daily_options_snapshot(symbol, live_price)
        except Exception as e:
            utils.cot_logger.error(f"Daily options update failed for {symbol}: {e}")

    utils.cot_logger.info("Finished daily options Max Pain fetch.")
