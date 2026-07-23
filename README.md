# cotmetrics

[![PyPI](https://img.shields.io/pypi/v/cotmetrics.svg)](https://pypi.org/project/cotmetrics/)
[![Python](https://img.shields.io/pypi/pyversions/cotmetrics.svg)](https://pypi.org/project/cotmetrics/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Turn raw COT (Commitments of Traders) data into positioning metrics and trading
signals — the positioning index, concentration / clustering / position-size,
reversal signals, and the `CotIndexer` that assembles per-instrument weekly panels.

Split out of the `cot-analyzer` dashboard so the metrics layer installs without the
Dash/Plotly UI stack. Reads prices and COT from the shared
[`cotdata`](https://github.com/mspinola/cotdata) store.

## Install

```bash
pip install cotmetrics
```

This pulls in [`cotdata`](https://pypi.org/project/cotdata/), the data layer beneath
it. cotmetrics computes metrics over a **populated cotdata store** — point
`COTDATA_STORE` at one before you can read real prices/COT (see
[cotdata](https://github.com/mspinola/cotdata) for how to build the store). Optional
extras: `pip install "cotmetrics[options]"` (max-pain options snapshots via yfinance),
`cotmetrics[scheduler]` (the ETL scheduler).

## Use

```python
import cotmetrics                                    # flat metric fns, side-effect-free import
from cotmetrics.indexer import get_indexer, boot_options_update
from cotmetrics.signals import append_trading_signals

cotmetrics.calculate_cot_index(...)
```

`import cotmetrics` is side-effect-free. `get_indexer()` constructs (and caches) the
`CotIndexer`, which loads the store on first use; the daily options fetch runs only
when you call `boot_options_update()` explicitly.

## Config / paths

| env | meaning | default |
|-----|---------|---------|
| `COTDATA_STORE` | shared price/COT store (from cotdata) | required |
| `COTMETRICS_CACHE` | derived per-instrument parquet cache | `~/.cache/cotmetrics` |
| `COTMETRICS_PARAMS` | instrument/params config | packaged **sample** `params.yaml` |
| `COTMETRICS_DATA` | legacy raw_cot_data.parquet + real_test_data exports | `<cache>/../cotmetrics_data` |

The packaged `params.yaml` is a small **generic sample** (a handful of well-known
symbols, untuned 52-week lookbacks) so cotmetrics runs out of the box. For a real
instrument universe and any tuned parameters, set `COTMETRICS_PARAMS` to your own
config file.

## Development (from source)

Developed alongside its sibling repos in a shared workspace, with `cotdata` installed
editable rather than from PyPI:

```bash
git clone https://github.com/mspinola/cotmetrics
pip install -e ../cotdata -e ".[options,scheduler,dev]"
export COTDATA_STORE=~/code/cotdata_store     # shared data store
pytest
```

## License

MIT — see [LICENSE](LICENSE).
