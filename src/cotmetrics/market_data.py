"""Symbol → display-name lookup, derived from the params config (see cotmetrics.config).

The Databento daily-price fetch that used to live here has moved to the dormant
cotdata provider (cotdata/providers/databento.py). All live price reads now go
through `marketdata.get_bars` (Norgate-backed store; bars moved out of cotdata under
ADR-0007). Only the params.yaml-derived
`_SYMBOL_TO_NAME` map remains here — used by core.options_data for max-pain.
"""
import yaml

import cotmetrics.config as config
import cotmetrics.utils as utils

# Resolved via config.params_path() (COTMETRICS_PARAMS, else the packaged copy). This
# used to be built from `<repo>/config/params.yaml`, a layout that only ever existed in
# the consuming app — so as an installed package the open always raised, the bare except
# swallowed it, and this map was silently empty. That made update_all_daily_options()
# iterate nothing, i.e. the daily max-pain refresh was a no-op.
_SYMBOL_TO_NAME = {}
try:
    with open(config.params_path(), "r") as f:
        _params = yaml.safe_load(f)
        for category in _params.get("AssetClasses", []):
            for _k, items in category.items():
                for item in items:
                    _SYMBOL_TO_NAME[item["Symbol"]] = item["Name"]
except Exception as e:
    # Still best-effort (this runs at import), but no longer silent.
    utils.cot_logger.warning(f"symbol->name map unavailable ({config.params_path()}): {e}")


# Markets whose PRICE comes from an ETF rather than from their own futures series.
#
# Deliberately NOT options_data.ETF_PROXIES, and the difference is the whole point.
# That map exists because a futures options chain is illiquid, so it names a proxy for
# markets that have perfectly good prices of their own: it maps ES to SPY. Reusing it
# here would silently replace S&P futures prices with an ETF's across the entire book.
#
# This map is the narrow case: two ICE MSCI markets that Norgate carries no continuous
# series for, so there is no futures price to prefer. cotdata still has their COT, which
# is why they are in the universe at all. Both are Role: heldout, so a proxied price is
# used for display and indexing rather than for anything selected or traded.
#
# THE SUBSTITUTION IS REAL AND IS NOT A DETAIL. An ETF tracks its index net of fees, in
# USD, on US session hours, and the future prices a different thing: MSCI EAFE futures
# carry basis, financing and a currency treatment the ETF does not. Levels are not
# comparable and neither are returns over a dividend date. Anything comparing these two
# markets against genuinely futures-priced ones has to know.
PRICE_PROXIES = {
    "MFS": "EFA",   # ICE MSCI EAFE future -> iShares MSCI EAFE
    "MME": "EEM",   # ICE MSCI Emerging Markets future -> iShares MSCI EM
}


def price_symbol(symbol: str) -> str:
    """The symbol to ask marketdata for. Its own, unless it is priced off a proxy."""
    return PRICE_PROXIES.get(symbol, symbol)
