# cotmetrics

Turn raw COT (Commitments of Traders) data into positioning metrics and trading
signals — the positioning index, concentration / clustering / position-size,
reversal signals, and the `CotIndexer` that assembles per-instrument weekly panels.

Split out of `cot-analyzer` so the metrics layer installs without the Dash/Plotly
dashboard stack. Reads prices/COT from the shared [`cotdata`](../cotdata) store.

## Install (workspace, editable)

```bash
pip install -e ../cotdata -e .[options,scheduler,dev]
export COTDATA_STORE=~/code/cotdata_store     # shared data store
export COTMETRICS_CACHE=~/.cache/cotmetrics    # derived per-instrument parquet cache
```

## Use

```python
import cotmetrics                                   # flat metric fns
from cotmetrics.indexer import cotIndexer, boot_options_update
from cotmetrics.signals import append_trading_signals
cotmetrics.calculate_cot_index(...)
```

`import cotmetrics` is side-effect-free. Constructing the indexer
(`from cotmetrics.indexer import cotIndexer`) loads the store; the daily options
fetch runs only when you call `boot_options_update()` explicitly.

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
