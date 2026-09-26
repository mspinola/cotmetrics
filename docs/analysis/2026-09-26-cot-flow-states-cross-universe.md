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

---

## Results (written after the run)

Run 2026-09-26 against `COTDATA_STORE=~/code/cotdata_store` (weeks 2006-06-13 to
2026-09-22) and `MARKETDATA_STORE=~/code/marketdata_store` (propadj futures closes through
2026-09-25). Sibling commits: crucible `baee3f5`, marketdata `c5828e1`, cotdata `aefd411`;
cotmetrics at the parent of this branch. Output beside this file:
`2026-09-26-cot-flow-states-cross-universe.{json,parquet,searchlog.jsonl}`. Runtime 10s,
deterministic (seed 0).

**Universe count correction.** The design section says 36 markets. The frozen class list
resolves to 32 (Metals 5, Energies 4, Grains 5, Softs 6, Live Stock 3, Currencies 9); 36 was
an arithmetic slip in the prose, not a change of scope. All 32 loaded, none skipped. 29 of
them produced at least one VALUE_ACCUM trade.

**Search denominator.** 63 entries in the log: 44 from the prior descriptive pass (one per
market plus two diagnostics) and 19 scored here (primary, two class subsets, gold alone,
15 secondary state/horizon rows). `run_gauntlet` corrects against the 19 of this session,
which is crucible's rule (`variant_count` reads `session_n_variants`, ADR-0002); the
table's `p Sidak` column uses all 63. The primary fails on either count.

**Drift removal works as intended.** The unconditional non-overlapping long book (every
week, same construction) is E = +0.007R (n=2,364, t=0.28) at 13w and -0.003R at 4w. So a
state's E below is its excess over what that market was already doing.

### Primary: VALUE_ACCUM, long, 13 weeks, pooled

| read | n | E (R) | 90% CI | verdict |
|---|---|---|---|---|
| full sample | 249 (29 mkts) | +0.107 | | t 1.68, hit 57% |
| TRAIN (exit before 2019-01-01) | 160 | +0.108 | [-0.055, +0.269] | FRAGILE |
| **TEST** (entry from 2019-02-26) | **85** | **+0.124** | **[-0.070, +0.317]** | **FRAGILE** |

Gauntlet on the full log: **FAIL, 0 of 3 gates.**

- REAL: sign-permutation p = 0.049 raw, 0.61 Sidak-corrected for 19 (0.96 for 63).
- STRONG: expectancy CI lower -0.016, profit-factor CI lower 0.96 against 1.25.
- GENERAL: cross-market Reality Check p = 0.069 across the 24 markets with at least 3
  trades (best HE, 4 trades).

Clustering makes it weaker, not stronger. The 249 trades enter in 202 distinct weeks
(commodities fire together). Averaging within entry week gives t = 1.67; within calendar
quarter, t = 1.24 on 70 quarters. crucible's bootstrap treats trades as independent, so its
intervals above are, if anything, too narrow. By entry year the mean is positive in 13 of
20 years, with no single year carrying it (largest: 2007 +1.68 on 5 trades, 2008 -1.36 on 6).

### By class and the gold check

| subset | n | E | TRAIN E | TEST n | TEST E | TEST verdict |
|---|---|---|---|---|---|---|
| commodities (21 of 23 mkts traded) | 224 | +0.127 | +0.139 | 80 | +0.133 | FRAGILE |
| currencies (TFF, 8 of 9 mkts traded) | 25 | -0.078 | -0.120 | 5 | -0.035 | FAIL |
| GC alone | 14 | +0.106 | **-0.475** | 5 | +1.153 | HELD (n=5) |

The currency cell is negative and too small to say anything. The lean, such as it is, sits
in physical commodities. On this construction (Friday entry, non-overlapping, drift removed)
**gold itself does not replicate its own lean in-sample**: its TRAIN trades are negative and
the positive full-sample figure comes from five post-2019 trades. The gold doc's n=21 at
t=1.92 counted overlapping weekly observations on Tuesday closes; 14 independent trades
remain once overlap is removed.

Per market (n at least 5): 13 of 19 positive. The six negative are 6E, ZL, SI, PA, CT and ZM;
the positive ones span energies, softs and metals. No class is uniform.

### Secondary rows (exploratory, direction set from TRAIN)

Nothing clears. Smallest corrected TEST p among the 15: 0.967 (MM_SELL_OTHERS_BUY long,
13w, TEST E +0.168 on 120, raw p 0.053). Two rows worth naming only because they agree in
sign with the primary:

- VALUE_ACCUM long at **4w**: full-sample E +0.168, t 2.79, n 296; TEST +0.146 on 101,
  FRAGILE, raw p 0.107. Same state, other pre-set horizon, same sign in both halves.
- MM_SELL_OTHERS_BUY (TREND selling, VALUE and RETAIL buying) long at 13w: TEST +0.168.
  It shares the "TREND out, VALUE in" core with VALUE_ACCUM.

Seven of the 15 secondary rows FAIL on TEST: TREND+RETAIL_BUY at both horizons,
INST_BUY_RETAIL_SELL and BROAD_LIQUID at 13w, MM_ALONE_BUY, MM_SELL_OTHERS_BUY and
RETAIL_ALONE_BUY at 4w. The TRAIN-picked direction flipped sign out of sample in each. The full table is in the json
under `results`.

### Not run

Equities, Fixed Income and Crypto (out of ADR-0005 scope; the handoff's optional expiry-
masked heatmap was not built). No threshold, window, or horizon variant beyond the frozen
design. No walk-forward: there is no parameter to re-fit per fold, so a single holdout is
the whole out-of-sample instrument here.

---

## Bottom line

1. The VALUE_ACCUM lean is **not a gold artifact in sign**: pooled over 29 commodity and
   currency markets it is +0.11R per 13-week trade, and the post-2019 holdout (+0.12R)
   matches the pre-2019 half (+0.11R).
2. It is **not distinguishable from zero** at any honest bar. TEST CI spans zero, the
   gauntlet fails REAL, STRONG and GENERAL, and time clustering drops the t to 1.2.
3. It lives in **physical commodities only**. The currency cell is negative on 25 trades.
4. Gold, the market that suggested it, has a negative TRAIN half on this construction.
5. No other state clears. Nothing here is a candidate npf gate.

If anyone reopens this, the one pre-registrable next step is VALUE_ACCUM long,
commodities only, 4w and 13w, judged on data after 2026-09-26 (the only data that has
not been looked at). Every variant tried is in the log; a re-cut of these 20 years is
not a new test.

## Plain-language recap

We asked whether the one promising pattern from gold (value money buying while trend-
followers and small traders sell, followed by better quarters) shows up across the other
commodity and currency markets. It does point the same way across most of them, and it
points the same way in both halves of the history, which is more consistency than gold
showed alone. But the size is small, about a tenth of a unit of risk per trade, and it is
well inside what chance produces. It fails every test the judge applies. In currencies it
goes the wrong way. That is a **marginal lean** at most, and a **genuine null** as a
tradable signal. The study closes here unless new data after today is used to test it
fresh.
