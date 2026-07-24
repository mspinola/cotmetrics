# cotmetrics

Turn raw COT (Commitments of Traders) data into positioning metrics and trading
signals — the positioning index, concentration / clustering / position-size,
reversal signals, and the `CotIndexer` that assembles per-instrument weekly panels.

Split out of `cot-analyzer` so the metrics layer installs without the Dash/Plotly
dashboard stack. Reads prices/COT from the shared [`cotdata`](../cotdata) store.

## Install (workspace, editable)

```bash
pip install -e ../cotdata -e .[options,dev]
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
| `COTMETRICS_DATA` | working dir for real_test_data (fixture) exports | `<cache>/../cotmetrics_data` |

The packaged `params.yaml` is a small **generic sample** (a handful of well-known
symbols, untuned 52-week lookbacks) so cotmetrics runs out of the box. For a real
instrument universe and any tuned parameters, set `COTMETRICS_PARAMS` to your own
config file.

## Scheduling (weekly COT refresh + email)

COT data is produced by cotdata, not here. cotmetrics only reads the shared store, so
refresh COT on the schedule cotdata documents (see the "Scheduling on Linux (cron)"
section of the [cotdata README](https://github.com/mspinola/cotdata#scheduling-on-linux-cron):
`cotdata-update --cot-all`, run through the CFTC's Friday ~3:30pm ET release window).

`scripts/cron_update.sh` wraps that refresh and emails the weekly report only when the
COT report date actually advances. It takes its config from the environment (no paths
baked in), so point the crontab at it:

```cron
# Friday afternoon (times in ET): refresh COT, email the report only if new data landed.
*/2 15-16 * * 5  COTDATA_STORE=/path/to/store /path/to/cotmetrics/scripts/cron_update.sh >> /path/to/cot.log 2>&1
```

| env | meaning | default |
|-----|---------|---------|
| `COTDATA_STORE` | shared cotdata store | required |
| `COTDATA_UPDATE` | the `cotdata-update` binary | `cotdata-update` on PATH |

The script reads `status.json`'s `newest_data.cot_legacy` before and after the update and
runs `scripts/generate-weekly-report-email.sh` only on a change, so re-running across the
release window is a harmless no-op until the CFTC zip lands.
