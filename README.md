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
extras: `pip install "cotmetrics[options]"` (max-pain options snapshots via yfinance).

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
| `COTMETRICS_CITPY` | CIT PY research notes (dated `.md`/`.txt`), persistent data not a cache. Point it at the generating tool's output dir, never inside `COTDATA_STORE` | `~/.local/share/cotmetrics/citpy` |
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

**This route suits a box that produces COT.** It runs `cotdata-update` itself, so on a
box whose store is a replica fed by a producer push, it would make a second producer
racing that push. Such a box has no download to trigger on, and should instead let the
consuming app send: cot-analyzer's store poller notices `status.json` advancing and
calls `cotmetrics.weekly_email` in-process, guarded by an opt-in flag and a ledger so it
sends once per COT week. Sending in-process also means the email inherits the app's own
`COTMETRICS_PARAMS`, which is worth more than it sounds: unset, that silently resolves
to the 6-symbol SAMPLE universe, and an email covering six markets looks exactly like an
email covering forty-seven.

### Sending it directly

`scripts/generate-weekly-report-email.py` sends one now, and is a thin CLI over
`cotmetrics.weekly_email.send_weekly_matrix_email`. It reads three variables from the
environment of the process invoking it and loads no `.env` of its own:

| env | meaning |
|-----|---------|
| `EMAIL_USER` | the sending account |
| `RECEIVER_EMAIL_USER` | where the report goes |
| `EMAIL_PASSWORD` | an app password, not the account password |

The subject line names the COT week the matrix carries, not the day the send ran.

## Development (from source)

Developed alongside its sibling repos in a shared workspace, with `cotdata` installed
editable rather than from PyPI:

```bash
git clone https://github.com/mspinola/cotmetrics
pip install -e ../cotdata -e ".[options,dev]"
export COTDATA_STORE=~/code/cotdata_store     # shared data store
pytest
```

## Docs

- [Two properties of positioning series that break naive statistics on them](docs/positioning-series-properties.md).
  Percentile exceedances arrive in episodes, so a count of them is not a sample size; and
  correlating positioning levels is spurious, because the series is near unit-root. Worth
  reading before computing a standard error, a p-value, or a correlation on anything this
  package emits.

## License

MIT — see [LICENSE](LICENSE).
