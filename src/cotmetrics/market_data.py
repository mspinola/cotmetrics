"""Symbol → display-name lookup, derived from the params config (see cotmetrics.config).

The Databento daily-price fetch that used to live here has moved to the dormant
cotdata provider (cotdata/providers/databento.py). All live price reads now go
through `cotdata.get_prices` (Norgate-backed store). Only the params.yaml-derived
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
