# COT flow states across the ADR-0005 universe: does the gold VALUE_ACCUM lean travel?

Point-in-time analysis, 2026-09-26. Never amended: if a later measurement contradicts
this, write a new document and link back.

Origin: [2026-09-26-cot-flow-states-gold.md](2026-09-26-cot-flow-states-gold.md) (gold only,
VALUE_ACCUM n=21, 13w t=1.92, marginal lean) and the handoff
[2026-09-26-cot-flow-states-cross-universe.md](../handoffs/2026-09-26-cot-flow-states-cross-universe.md).

Reproducer: [`scripts/analysis/cot_flow_states_cross_universe.py`](../../scripts/analysis/cot_flow_states_cross_universe.py),
run from `npf/.venv`. The state derivation is imported unchanged from
[`cot_flow_states_universe.py`](../../scripts/analysis/cot_flow_states_universe.py).

---

## Design, frozen before the run

This section was committed before the script was first run. Results below it were
written after.

**Prior looks.** A descriptive universe pass (`cot_flow_states_universe.py`, 2026-09-26
12:02, another session) already tabulated states against naive Tuesday-anchored returns on
all 42 non-heldout markets, equities and rates included. Its `SearchSpaceLog` (44 entries)
is the seed of this run's log, so every look already taken counts toward the denominator.
This session did not read that run's result tables before freezing the design below.

**Universe (ADR-0005 scope).** Non-heldout members of `cotmetrics-config/params.yaml` in
Metals, Energies, Grains, Softs, Live Stock (Disaggregated) and Currencies (TFF). 36
markets. Equities, Fixed Income and Crypto are out of scope and are not run.

**Cohort roles** (unchanged from the universe script, consistent with ADR-0005 point 2):

| role | Disaggregated | TFF (currencies) |
|---|---|---|
| TREND | Managed Money | Leveraged Funds |
| VALUE | Other Reportable | Asset Manager |
| RETAIL | Non-Reportable | Non-Reportable |

**State** (gold config, unchanged): `z = dNet / rolling_std(dNet, 52w, min 26w)`, active at
|z| > 1.0, state = signs of (TREND, VALUE, RETAIL), the eight all-active combinations named
as in the gold doc.

**Trades.** Each state-week is a trade signal.

- Entry: first daily close on or after report date + 3 days (the Friday release), from
  `marketdata.get_bars(sym, "propadj", domain="futures")` (ratio-adjusted, positive).
- Exit: first daily close on or after entry + h weeks, h in {13 (primary), 4}.
- Non-overlapping within a market: a signal is taken only if the market has no open trade
  of the same book.
- Risk unit: sigma = std of daily log returns over the 260 sessions before entry (min 120)
  times sqrt(sessions held). `R_raw = direction * log(exit/entry) / sigma`.
- Drift removal: `R = R_raw - d`, where d is the mean vol-normalised h-week long return of
  that market over every weekly anchor whose trade EXITED before this entry (min 52),
  direction-signed. Causal; a sign-permutation test on long-only trades would otherwise
  test commodity drift, not the state.

**Primary hypothesis (the only pre-named one):** VALUE_ACCUM, long, h=13, pooled over the
36 markets. Judged by `crucible.validation.holdout` at split 2019-01-01, embargo 8 weeks,
seed 0 (TEST verdict), and by `run_gauntlet` REAL + STRONG on the full log with
`n_variants=log` and GENERAL on per-class logs.

**Secondary, exploratory:** the other seven named states at h=13 and all eight at h=4, each
direction set by the sign of its TRAIN-period mean, TEST read at the same split. Each is a
logged variant. Per-class pooling (commodities, currencies) is logged. No claim is made off
a secondary row unless it clears the Sidak-corrected bar at the log's final count.

**What would close the study as a null:** VALUE_ACCUM TEST expectancy not distinguishable
from zero after drift removal, or its sign not replicating outside gold.
