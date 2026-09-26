# COT flow states across the universe: the gold design replicated on 42 markets, pooled, and read on two price bases

Point-in-time analysis, 2026-09-26. Never amended: if a later measurement contradicts
this, write a new document and link back.

Reproducer:
[`scripts/analysis/cot_flow_states_universe.py`](../../scripts/analysis/cot_flow_states_universe.py),
run against `COTDATA_STORE=~/code/cotdata_store` (Disaggregated and TFF, newest COT week
2026-09-22), the non-heldout universe from `cotmetrics-config/params.yaml`, weekly closes
from `cot-analyzer/data_cache/<SYM>.parquet` (`Closing Price` on the Tuesday report date,
the gold doc's price source) and, beside it, the ratio-adjusted `propadj` futures tier of
`MARKETDATA_STORE=~/code/marketdata_store` read through `marketdata.get_bars`. Every table
below is in
[`2026-09-26-cot-flow-states-universe.json`](2026-09-26-cot-flow-states-universe.json), the
per-week frame in `2026-09-26-cot-flow-states-universe.parquet` (43,085 market-weeks), and
the search log at `2026-09-26-cot-flow-states-universe.searchlog.jsonl` (scope
`cot_flow_states:universe-2026-09-26`, `n_variants = 44`: one `tried` entry per market plus
the Friday-anchor and price-basis diagnostics). Nine per-class heatmap PNGs and one board
PNG share the date prefix.

```bash
cd cotmetrics && COTDATA_STORE=~/code/cotdata_store MARKETDATA_STORE=~/code/marketdata_store \
  COTMETRICS_PARAMS=../cotmetrics-config/params.yaml \
  ../npf/.venv/bin/python scripts/analysis/cot_flow_states_universe.py \
    --params ../cotmetrics-config/params.yaml --prices ../cot-analyzer/data_cache --out docs/analysis
```

A second script,
[`scripts/analysis/cot_flow_states_scope.py`](../../scripts/analysis/cot_flow_states_scope.py),
reads that parquet and re-cuts it to the handoff's scope (section "The handoff's scope"
below). It writes `2026-09-26-cot-flow-states-scope.json` and its own search log
`2026-09-26-cot-flow-states-scope.searchlog.jsonl` (scope
`cot_flow_states:adr0005-scope-2026-09-26`, `n_variants = 9`):

```bash
cd cotmetrics && COTDATA_STORE=~/code/cotdata_store MARKETDATA_STORE=~/code/marketdata_store \
  ../npf/.venv/bin/python scripts/analysis/cot_flow_states_scope.py --analysis docs/analysis
```

Origin: [`2026-09-26-cot-flow-states-gold.md`](2026-09-26-cot-flow-states-gold.md) built a
per-cohort week-over-week flow primitive and an eight-state vocabulary on gold alone, found
the single-cohort read to be a genuine null and one state (VALUE_ACCUM) to be a marginal
lean, and asked whether any of it holds beyond one market. This document is that
replication: the gold configuration, unchanged, run one market at a time across the 42
non-heldout markets and then pooled. It is descriptive. No parameter was searched, no
crucible verdict is rendered, and any lean below is a hypothesis for crucible.

---

## Bottom line

1. **The gold design replicates unchanged on 42 of 42 non-heldout markets** (23
   Disaggregated physicals, 19 TFF financials), 43,085 market-weeks, and the sum-of-dNet
   identity holds to the contract on every one. GC reproduces the gold doc's VALUE_ACCUM
   row exactly on the gold doc's price source: n=21, +2.20% against +1.24% unconditional,
   hit 71.4%.

2. **The eight named states are as rare everywhere as they were on gold.** Pooled, PARTIAL
   is 51.2% of market-weeks, QUIET 44.2%, and the eight named states together are 1,977
   of 43,085 (4.6%). VALUE_ACCUM is the commonest at 401 (0.93%); RETAIL_ALONE_BUY and
   INST_BUY_RETAIL_SELL occur 77 and 70 times across 42 markets in twenty years. On TFF
   financials the named states are about half as frequent as on physicals (VALUE_ACCUM
   0.49% against 1.27%).

3. **Single-cohort one-sigma moves carry no 13-week information across the universe
   either.** On the ratio-adjusted basis (the one that measures what the design intends)
   every pooled buy/sell row sits within 0.4 percentage points of the unconditional
   +0.31%, and the largest HAC t is VALUE buy at 1.85. The gold null generalises.

4. **VALUE_ACCUM is a marginal lean pooled, on the same footing as it was on gold.**
   Ratio-adjusted, Tuesday-anchored: 13 weeks n=395, +1.13% against +0.31% unconditional,
   hit 54.4% against 53.2%, plain t 1.72, HAC t 1.56; 4 weeks +0.93% against +0.11%, hit
   57.5% against 52.3%, HAC t 2.08. The lean lives in the Disaggregated physicals (13w
   +1.39% against +0.07%, HAC t 1.57, n=304) and is absent on TFF (n=91, +0.26% against
   +0.62%, t 0.30). Per market it is a coin flip: 16 of 28 markets with n>=5 sit above
   their own unconditional mean.

5. **Anchoring after the publication instead of at the Tuesday report date does not remove
   the VALUE_ACCUM lean; it widens it, and it removes the BROAD_LIQUID one.** The first
   cut, from the settlement on report date + 3 days, gives 13 weeks n=395, +1.64%, hit
   55.4%, plain t 2.45, HAC t 2.19, against ALL +0.32%. That settlement prints before the
   15:30 ET publication, and 13 reports of late 2025 were published 7 to 50 days late, so
   the section "The handoff's scope" re-anchors at the first settlement strictly after the
   resolved release date: on the ADR-0005 universe VALUE_ACCUM is +1.86% against +0.04%
   (n=332, hit 56.6%, HAC t 2.18) where the Tuesday anchor gave +1.32% (HAC t 1.60), and
   BROAD_LIQUID falls from +1.84% (HAC t 2.26) to +0.69% (HAC t 0.83). Two more
   tabulations in the log.

6. **BROAD_LIQUID (all three opinion cohorts selling more than one sigma in the same week)
   is the one state the gold doc could not see (n=5 there) that leans the same way on both
   report types.** Pooled 13 weeks n=152, +2.44%, hit 59.9%, plain t 2.50, HAC t 2.92;
   Disaggregated +2.91% (HAC t 2.14, n=71), TFF +2.03% (HAC t 2.04, n=81). It is the
   largest HAC t on any named state in any table, and it came out of tabulating eight
   states at two horizons on three pools and two price bases, so it is a hypothesis for
   crucible, not a result. Anchored after the publication on the ADR-0005 universe it is
   +0.69% with HAC t 0.83 (section "The handoff's scope"): what looked like a lean was
   mostly the sessions between the report date and its release.

7. **The price source the gold design names does not survive the universe.** The cache
   `Closing Price` is additively back-adjusted and goes non-positive on 11 of the 23
   physicals (HO 952 of 1,059 weeks, RB 835, OJ 780, ZM 492); 1,228 market-weeks carry
   |fwd13| > 50% on that basis, and CC's VALUE_ACCUM mean reads +48.7% on cache against
   +9.6% ratio-adjusted. The gold figures were unaffected because gold never approaches
   zero. Any cross-market study of this design has to read the ratio-adjusted marketdata
   tier; the cache tables are kept here only to show the gold row reproduces.

8. **Plain t overstates every 13-week row.** Overlapping windows sampled weekly push the
   pooled ALL plain t to 4.74 where the within-market Newey-West t gives 1.60, and the HAC
   itself still treats 42 markets as independent. Every t in this document is an upper
   bound.

No parameter search was run. The configuration is the gold configuration, fixed before
any universe result was seen: 52-week rolling std with 26-week minimum, activity at |z| >
1.0, horizons 4 and 13 weeks, one role mapping per report type. The variants an honest
search would have to log are listed at the end; none were tried.

---

## What was run

The derivation is the gold derivation, per market, from the Disaggregated frame for
physicals and the TFF frame for financials (the two universes are disjoint in the store):

```
dNet_c    = (Long_c - Short_c).diff()
dGross_c  = |Long_c.diff()| + |Short_c.diff()|
z_c       = dNet_c / rolling_std(dNet_c, 52w, min_periods=26)      (no mean subtraction)
dSpread_c = Spread_c.diff()                                          (where reported)
OI_less_spread = OI - sum(Spread_c)
sign_c    = +1 if z_c > 1.0, -1 if z_c < -1.0, else 0
state     = (sign_TREND, sign_VALUE, sign_RETAIL); eight named, else PARTIAL, (0,0,0) QUIET
straddle_c = dGross_c > 2 * rolling_std(dGross_c)  and  |dNet_c| < 0.25 * dGross_c
derisk_TREND = dSpread_TREND > 1 * rolling_std(dSpread_TREND)  and  dNet_TREND < 0
```

The gold script names the three opinion cohorts MM / Other / NonRep. Here they are
generic roles so one state vocabulary spans both reports. The mapping was fixed before
results and one mapping was tried:

| role | Disaggregated (23 physicals) | TFF (19 financials) |
|---|---|---|
| TREND | managed_money | leveraged |
| VALUE | other_reportable | asset_manager |
| RETAIL | nonreportable | nonreportable |
| COUNTERPARTY | producer_merchant + swap | dealer |
| OTHER | (not carried) | other_reportable, dNet and z only, not in the state |

The gold state names are kept verbatim for comparability, so `MM_ALONE_BUY` on a TFF
market reads as "leveraged funds alone buying". The TFF mapping is an analogy (asset
managers are not "other reportables" and dealers are not producers), which is why the
TFF-only rows are reported on their own throughout.

Universe: the 47 markets of `cotmetrics-config/params.yaml` less the five `heldout` (EMD,
NKD, MME, MFS, KE), 42 in nine asset classes. All 42 loaded, none skipped. History is
1,059 weekly rows from 2006-06-13 on most markets; BTC 442 rows from 2018-04-10, ETH 286
from 2021-04-06, 6N 1,056.

Forward returns are h-week log returns anchored on the Tuesday report date, h in {4, 13},
exactly as the gold script measures them, on two price bases:

- **cache**: `cot-analyzer/data_cache/<SYM>.parquet` `Closing Price`, nearest bar within 3
  days. This is the gold doc's stated source. It is additively back-adjusted and is masked
  to NaN wherever it is non-positive (see Diagnostics).
- **propadj**: the ratio-adjusted `propadj` tier of the marketdata futures store, same
  3-day nearest reindex. This preserves percentage returns and stays positive. It is
  derived on read from Norgate's two stored tiers and restates on every roll, so it is
  reproducible against today's store, not a pinned vintage.

A third measurement, the **Friday anchor**, starts the 13-week return at the first
propadj daily close on or after report date + 3 days (the release) and ends at the first
close on or after that anchor + 13 weeks. It is reported for two pooled rows only
(VALUE_ACCUM and ALL) and is logged as a diagnostic.

Statistics per row: n, mean, median, hit rate, the plain t the gold doc reports, and a
Newey-West HAC t (Bartlett kernel, lag h-1, long-run variance computed within each
market on residuals from the pooled mean and summed across markets, so a lag never
straddles two markets). On the named-state rows the lags run over subset-adjacent rows,
so the overlap correction is exact only where a market sits in the same state in
consecutive weeks and approximate elsewhere. All t are against zero. The HAC corrects the within-market
overlap of h-week returns sampled weekly; it does not correct cross-market dependence,
and TFF financials in particular co-move, so pooled t values remain optimistic.

Pooling is by market-week: every market contributes every week it has, so long histories
weigh more than BTC and ETH.

---

## Results

### State frequency by report type, all history

| state | disagg n | disagg % | tff n | tff % | all n | all % |
|---|---|---|---|---|---|---|
| PARTIAL | 12,507 | 51.35 | 9,538 | 50.93 | 22,045 | 51.17 |
| QUIET | 10,583 | 43.45 | 8,480 | 45.28 | 19,063 | 44.25 |
| VALUE_ACCUM | 310 | 1.27 | 91 | 0.49 | 401 | 0.93 |
| TREND+RETAIL_BUY | 315 | 1.29 | 83 | 0.44 | 398 | 0.92 |
| MM_SELL_OTHERS_BUY | 220 | 0.90 | 153 | 0.82 | 373 | 0.87 |
| MM_ALONE_BUY | 202 | 0.83 | 160 | 0.85 | 362 | 0.84 |
| BROAD_LIQUID | 73 | 0.30 | 82 | 0.44 | 155 | 0.36 |
| BROAD_ACCUM | 56 | 0.23 | 85 | 0.45 | 141 | 0.33 |
| RETAIL_ALONE_BUY | 50 | 0.21 | 27 | 0.14 | 77 | 0.18 |
| INST_BUY_RETAIL_SELL | 41 | 0.17 | 29 | 0.15 | 70 | 0.16 |

PARTIAL and QUIET together are 95.4% of market-weeks pooled. The eight named states are
1,977 market-weeks in total. The gold doc's 55 of 1,059 (5.2%) on GC is typical of a
physical; TFF financials populate the named states less often (3.8% of 18,728
market-weeks against 5.2% of 24,357 on Disaggregated).

### Forward return by state, pooled ALL, ratio-adjusted (propadj) basis

Read these first. They are the tables that measure what the design intends.

13 weeks:

| state | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|
| ALL | 41,696 | 0.31 | 0.40 | 53.2 | 4.74 | 1.60 |
| PARTIAL | 21,367 | 0.28 | 0.34 | 52.6 | 2.96 | 1.20 |
| QUIET | 18,415 | 0.34 | 0.48 | 53.9 | 3.52 | 1.49 |
| VALUE_ACCUM | 395 | 1.13 | 0.86 | 54.4 | 1.72 | 1.56 |
| TREND+RETAIL_BUY | 387 | 0.28 | 0.79 | 52.7 | 0.39 | 0.37 |
| MM_SELL_OTHERS_BUY | 361 | 0.50 | 0.17 | 52.6 | 0.69 | 0.80 |
| MM_ALONE_BUY | 346 | -0.74 | -0.08 | 49.4 | -1.04 | -0.83 |
| BROAD_LIQUID | 152 | 2.44 | 1.85 | 59.9 | 2.50 | 2.92 |
| BROAD_ACCUM | 136 | 0.05 | 0.37 | 52.2 | 0.06 | 0.08 |
| RETAIL_ALONE_BUY | 71 | -1.56 | 0.67 | 57.7 | -0.80 | -0.79 |
| INST_BUY_RETAIL_SELL | 66 | 1.12 | -0.25 | 47.0 | 0.42 | 0.63 |

4 weeks:

| state | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|
| ALL | 42,074 | 0.11 | 0.17 | 52.3 | 3.01 | 1.81 |
| PARTIAL | 21,553 | 0.07 | 0.14 | 51.8 | 1.42 | 0.98 |
| QUIET | 18,588 | 0.15 | 0.19 | 52.7 | 2.73 | 1.94 |
| VALUE_ACCUM | 395 | 0.93 | 0.80 | 57.5 | 2.40 | 2.08 |
| TREND+RETAIL_BUY | 392 | -0.54 | -0.06 | 49.5 | -1.39 | -1.43 |
| MM_SELL_OTHERS_BUY | 365 | -0.01 | 0.21 | 55.6 | -0.03 | -0.03 |
| MM_ALONE_BUY | 351 | -0.19 | 0.06 | 50.4 | -0.43 | -0.38 |
| BROAD_LIQUID | 153 | 1.16 | 1.03 | 58.2 | 1.96 | 2.13 |
| BROAD_ACCUM | 137 | -0.31 | -0.08 | 47.4 | -0.61 | -0.59 |
| RETAIL_ALONE_BUY | 72 | -0.00 | 0.51 | 56.9 | -0.00 | -0.00 |
| INST_BUY_RETAIL_SELL | 68 | 0.83 | 0.06 | 50.0 | 0.50 | 0.56 |

The rows to notice, and what the HAC does to them:

- **ALL**: +0.31% at 13 weeks with plain t 4.74 and HAC t 1.60. The plain t is inflated
  by the 13-week overlap by roughly a factor of three; the pooled unconditional drift is
  itself not distinguishable from zero once that is corrected. At 4 weeks the two agree
  more closely (3.01 against 1.81) because the overlap is shorter.
- **VALUE_ACCUM**: 13 weeks +1.13%, plain 1.72, HAC 1.56; 4 weeks +0.93%, plain 2.40, HAC
  2.08. The correction shaves about a tenth off each, and the 4-week row survives it
  better than the 13-week row. Hit rate is 54.4% at 13 weeks against 53.2% unconditional
  and 57.5% at 4 weeks against 52.3%.
- **BROAD_LIQUID**: 13 weeks +2.44%, hit 59.9%, plain 2.50, HAC 2.92; 4 weeks +1.16%, HAC
  2.13. The HAC t is larger than the plain t here, which happens when successive returns
  inside the state are negatively autocorrelated; n=152.
- **TREND+RETAIL_BUY** at 4 weeks: -0.54%, HAC t -1.43. The mirror of VALUE_ACCUM (trend
  and retail buying while value money sells) leans the other way and does not reach 1.5.
- Every named state not listed above has |HAC t| < 1.2 (QUIET itself is 1.49 at 13 weeks
  and 1.94 at 4 weeks, which is the pooled drift, not a state).

### Forward 13-week return by state, per report type, propadj basis

Disaggregated physicals (23 markets):

| state | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|
| ALL | 23,215 | 0.07 | 0.22 | 50.7 | 0.66 | 0.22 |
| PARTIAL | 11,966 | 0.11 | 0.17 | 50.6 | 0.71 | 0.29 |
| QUIET | 10,030 | -0.00 | 0.24 | 50.8 | -0.01 | -0.00 |
| TREND+RETAIL_BUY | 305 | 0.08 | -0.17 | 49.2 | 0.09 | 0.08 |
| VALUE_ACCUM | 304 | 1.39 | 1.46 | 53.6 | 1.71 | 1.57 |
| MM_SELL_OTHERS_BUY | 210 | 1.01 | 0.08 | 50.5 | 1.17 | 1.07 |
| MM_ALONE_BUY | 191 | -2.19 | -2.02 | 45.5 | -1.92 | -1.56 |
| BROAD_LIQUID | 71 | 2.91 | 4.32 | 63.4 | 1.52 | 2.14 |
| BROAD_ACCUM | 54 | 1.77 | 3.19 | 63.0 | 1.01 | 1.44 |
| RETAIL_ALONE_BUY | 44 | -4.43 | -0.13 | 50.0 | -1.52 | -1.53 |
| INST_BUY_RETAIL_SELL | 40 | 0.15 | -1.09 | 42.5 | 0.04 | 0.06 |

TFF financials (19 markets):

| state | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|
| ALL | 18,481 | 0.62 | 0.46 | 56.3 | 9.31 | 3.15 |
| PARTIAL | 9,401 | 0.50 | 0.38 | 55.3 | 5.20 | 2.08 |
| QUIET | 8,385 | 0.75 | 0.57 | 57.5 | 7.94 | 3.48 |
| MM_ALONE_BUY | 155 | 1.05 | 0.30 | 54.2 | 1.46 | 1.35 |
| MM_SELL_OTHERS_BUY | 151 | -0.20 | 0.19 | 55.6 | -0.16 | -0.26 |
| VALUE_ACCUM | 91 | 0.26 | 0.23 | 57.1 | 0.30 | 0.26 |
| TREND+RETAIL_BUY | 82 | 1.03 | 1.03 | 65.9 | 1.09 | 1.22 |
| BROAD_ACCUM | 82 | -1.08 | -0.78 | 45.1 | -1.72 | -1.95 |
| BROAD_LIQUID | 81 | 2.03 | 1.10 | 56.8 | 2.75 | 2.04 |
| RETAIL_ALONE_BUY | 27 | 3.11 | 1.86 | 70.4 | 1.76 | 1.54 |
| INST_BUY_RETAIL_SELL | 26 | 2.62 | 0.88 | 53.8 | 1.23 | 1.15 |

The two report types have different unconditional rows. Disaggregated physicals drift
+0.07% per 13 weeks (HAC t 0.22); TFF financials drift +0.62% (plain t 9.31, HAC t 3.15),
which is equity and bond carry over twenty years. Any TFF state row has to be read against
+0.62%, not zero. On that reading VALUE_ACCUM on TFF (+0.26%, n=91) is below its own
unconditional, and the pooled VALUE_ACCUM lean is entirely a Disaggregated result
(+1.39% against +0.07%, HAC t 1.57, n=304). BROAD_LIQUID is above its own unconditional on
both (Disaggregated +2.91% against +0.07%, TFF +2.03% against +0.62%). MM_ALONE_BUY on
Disaggregated is -2.19% (HAC t -1.56, n=191), the most negative named row by plain t;
RETAIL_ALONE_BUY is more negative by mean at -4.43% on n=44.
RETAIL_ALONE_BUY has opposite signs on the two reports (-4.43% on physicals, +3.11% on
financials) on n=44 and n=27, which is what a state that occurs 77 times in twenty years
across 42 markets looks like.

The 4-week per-report tables add nothing beyond what the pooled 4-week table shows and
are in the JSON under `price_basis_check.pooled.<report>.by_state_fwd4`.

### Forward return by state, pooled ALL, cache basis (the gold doc's price source)

Kept so the gold row can be seen to reproduce and so the price-basis problem is visible.
Do not read the physicals' means off these tables; see Diagnostics.

13 weeks:

| state | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|
| ALL | 38,211 | 0.83 | 0.31 | 52.8 | 6.67 | 2.71 |
| PARTIAL | 19,657 | 0.73 | 0.25 | 52.3 | 4.20 | 2.06 |
| QUIET | 16,835 | 0.94 | 0.40 | 53.5 | 5.05 | 2.84 |
| MM_SELL_OTHERS_BUY | 355 | 0.90 | 0.10 | 51.8 | 0.97 | 1.01 |
| MM_ALONE_BUY | 336 | -0.42 | -0.04 | 49.7 | -0.51 | -0.45 |
| VALUE_ACCUM | 322 | 2.36 | 0.20 | 51.9 | 1.59 | 1.30 |
| TREND+RETAIL_BUY | 303 | 1.83 | 0.48 | 52.5 | 1.05 | 0.95 |
| BROAD_LIQUID | 141 | 2.00 | 1.61 | 58.9 | 1.61 | 2.48 |
| BROAD_ACCUM | 127 | -1.59 | 0.10 | 50.4 | -1.03 | -1.14 |
| RETAIL_ALONE_BUY | 70 | -3.47 | 0.62 | 57.1 | -1.22 | -1.16 |
| INST_BUY_RETAIL_SELL | 65 | 0.86 | -0.31 | 46.2 | 0.33 | 0.60 |

4 weeks:

| state | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|
| ALL | 38,680 | 0.30 | 0.13 | 52.0 | 3.59 | 2.53 |
| PARTIAL | 19,893 | 0.25 | 0.10 | 51.5 | 2.14 | 1.77 |
| QUIET | 17,040 | 0.31 | 0.16 | 52.6 | 2.41 | 1.91 |
| MM_SELL_OTHERS_BUY | 359 | 0.33 | 0.19 | 55.4 | 0.53 | 0.56 |
| MM_ALONE_BUY | 345 | 1.92 | 0.06 | 50.7 | 1.35 | 1.03 |
| VALUE_ACCUM | 323 | 2.67 | 0.28 | 54.2 | 2.54 | 2.11 |
| TREND+RETAIL_BUY | 310 | -0.47 | -0.06 | 49.0 | -0.37 | -0.42 |
| BROAD_LIQUID | 143 | 1.42 | 1.02 | 59.4 | 2.29 | 2.42 |
| BROAD_ACCUM | 128 | -2.02 | -0.10 | 46.9 | -1.61 | -1.63 |
| RETAIL_ALONE_BUY | 72 | -0.06 | 0.36 | 56.9 | -0.05 | -0.05 |
| INST_BUY_RETAIL_SELL | 67 | 1.37 | -0.02 | 49.3 | 0.72 | 0.83 |

On this basis the pooled unconditional 13-week mean is +0.83% against +0.31% ratio-adjusted,
and VALUE_ACCUM is +2.36% with a median of +0.20% (against +1.13% and +0.86% ratio-adjusted).
The gap between mean and median is the near-zero cache closes on the physicals inflating a
handful of returns. The two bases agree on which rows lean and disagree on how much.

### Single-cohort baseline, forward 13 weeks

Pooled ALL, propadj basis:

| role | move | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|---|
| TREND | buy | 5,709 | -0.04 | 0.14 | 50.9 | -0.25 | -0.15 |
| TREND | sell | 5,871 | 0.38 | 0.45 | 53.9 | 2.13 | 1.36 |
| VALUE | buy | 5,623 | 0.55 | 0.43 | 53.1 | 2.95 | 1.85 |
| VALUE | sell | 5,671 | 0.41 | 0.41 | 53.3 | 2.24 | 1.42 |
| RETAIL | buy | 5,744 | 0.21 | 0.21 | 51.8 | 1.16 | 0.77 |
| RETAIL | sell | 5,713 | 0.44 | 0.43 | 53.5 | 2.37 | 1.53 |

Disaggregated only, propadj basis:

| role | move | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|---|
| TREND | buy | 3,344 | -0.55 | -0.49 | 48.3 | -2.02 | -1.21 |
| TREND | sell | 3,400 | 0.23 | 0.41 | 51.6 | 0.82 | 0.53 |
| VALUE | buy | 3,152 | 0.83 | 0.66 | 52.0 | 2.82 | 1.76 |
| VALUE | sell | 3,119 | 0.14 | 0.47 | 51.4 | 0.49 | 0.30 |
| RETAIL | buy | 3,362 | 0.07 | -0.14 | 49.4 | 0.27 | 0.17 |
| RETAIL | sell | 3,320 | 0.29 | 0.60 | 51.8 | 0.98 | 0.62 |

TFF only, propadj basis:

| role | move | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|---|
| TREND | buy | 2,365 | 0.67 | 0.36 | 54.6 | 3.47 | 2.06 |
| TREND | sell | 2,471 | 0.60 | 0.48 | 57.1 | 3.04 | 1.92 |
| VALUE | buy | 2,471 | 0.19 | 0.35 | 54.6 | 0.97 | 0.63 |
| VALUE | sell | 2,552 | 0.73 | 0.38 | 55.7 | 3.96 | 2.66 |
| RETAIL | buy | 2,382 | 0.40 | 0.36 | 55.0 | 2.09 | 1.47 |
| RETAIL | sell | 2,393 | 0.65 | 0.38 | 55.8 | 3.51 | 2.50 |

Pooled ALL, cache basis (the gold doc's measure):

| role | move | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|---|
| TREND | buy | 5,213 | 0.16 | 0.08 | 50.6 | 0.48 | 0.37 |
| TREND | sell | 5,385 | 1.30 | 0.32 | 53.3 | 3.91 | 2.80 |
| VALUE | buy | 5,185 | 1.10 | 0.32 | 52.6 | 3.02 | 2.15 |
| VALUE | sell | 5,216 | 1.25 | 0.32 | 52.9 | 3.70 | 2.72 |
| RETAIL | buy | 5,252 | 0.24 | 0.15 | 51.4 | 0.74 | 0.54 |
| RETAIL | sell | 5,210 | 1.25 | 0.31 | 52.7 | 3.76 | 2.83 |

Pooled and ratio-adjusted, every row sits within 0.4 percentage points of the
unconditional +0.31% and no HAC t exceeds 1.85 (VALUE buy). On Disaggregated alone the
widest spread is TREND buy at -0.55% (plain t -2.02, HAC t -1.21) against VALUE buy at
+0.83% (plain 2.82, HAC 1.76), around an unconditional +0.07%; the plain t on TREND buy
would pass a naive 2.0 cut and the HAC t does not, which is the overlap correction doing
its job. On TFF every row is between +0.19% and +0.73% around +0.62% unconditional, and
VALUE sell (+0.73%, HAC 2.66) is a drift row, not a signal row: it is above zero because
financials drift, not because asset managers selling predicts anything, and it is within
0.12 points of the unconditional mean. The gold finding that a cohort moving one sigma on
its own predicts nothing about the next quarter holds on 42 markets.

### Per-market VALUE_ACCUM, forward 13 weeks, both price bases

The pooled lean decomposed. `n` differs between bases where cache closes were masked
(HO, RB, OJ, ZM, ZS, HE, CT). `above` is whether the state mean exceeds that market's own
unconditional mean on the same basis.

| symbol | class | report | n (cache) | VALUE_ACCUM mean % | uncond % | above | n (propadj) | VALUE_ACCUM mean % | uncond % | above |
|---|---|---|---|---|---|---|---|---|---|---|
| ZB | Fixed Income | tff | 13 | -2.15 | 0.71 | no | 13 | -2.00 | 0.43 | no |
| ZN | Fixed Income | tff | 9 | 0.12 | 0.60 | no | 9 | 0.19 | 0.41 | no |
| ZF | Fixed Income | tff | 12 | 0.21 | 0.35 | no | 12 | 0.18 | 0.27 | no |
| ZT | Fixed Income | tff | 4 | 0.45 | 0.08 | yes | 4 | 0.44 | 0.07 | yes |
| YM | Equities | tff | 8 | 7.44 | 1.69 | yes | 8 | 7.86 | 1.98 | yes |
| NQ | Equities | tff | 6 | 0.99 | 2.12 | no | 6 | 1.27 | 3.36 | no |
| RTY | Equities | tff | 5 | 5.02 | 1.46 | yes | 5 | 5.84 | 1.76 | yes |
| ES | Equities | tff | 5 | -2.59 | 1.69 | no | 5 | -5.69 | 2.15 | no |
| GF | Live Stock | disagg | 0 |  | 0.78 | no | 0 |  | 0.38 | no |
| HE | Live Stock | disagg | 4 | 40.67 | 0.15 | yes | 5 | 3.11 | -0.05 | yes |
| LE | Live Stock | disagg | 2 | -2.83 | 0.66 | no | 2 | -3.25 | 0.36 | no |
| CT | Softs | disagg | 14 | -0.81 | 3.56 | no | 15 | -1.66 | 0.08 | no |
| CC | Softs | disagg | 11 | 48.73 | 3.39 | yes | 11 | 9.60 | 1.25 | yes |
| KC | Softs | disagg | 8 | 2.72 | -0.56 | yes | 8 | 5.49 | -0.21 | yes |
| LBR | Softs | disagg | 1 | -18.60 | -6.13 | no | 1 | -35.92 | -11.37 | no |
| OJ | Softs | disagg | 3 | 13.22 | 9.15 | yes | 14 | -1.79 | 0.07 | no |
| SB | Softs | disagg | 24 | 0.78 | -0.16 | yes | 24 | 0.20 | -0.83 | yes |
| HG | Metals | disagg | 16 | 0.52 | 0.32 | yes | 16 | 0.36 | 0.27 | yes |
| GC | Metals | disagg | 21 | 2.20 | 1.24 | yes | 21 | 3.29 | 1.77 | yes |
| PA | Metals | disagg | 6 | -3.52 | 0.73 | no | 6 | -2.58 | 1.21 | no |
| PL | Metals | disagg | 8 | -0.62 | -0.03 | no | 8 | -0.39 | -0.15 | no |
| SI | Metals | disagg | 13 | -3.35 | 1.15 | no | 13 | -4.52 | 1.45 | no |
| BTC | Crypto | tff | 0 |  | 2.10 | no | 0 |  | 4.93 | no |
| ETH | Crypto | tff | 1 | -34.88 | -2.73 | no | 1 | -40.43 | -2.55 | no |
| 6A | Currencies | tff | 0 |  | 0.40 | no | 0 |  | 0.24 | no |
| 6B | Currencies | tff | 5 | 0.58 | -0.41 | yes | 5 | 0.58 | -0.43 | yes |
| 6C | Currencies | tff | 2 | 1.14 | -0.30 | yes | 2 | 1.15 | -0.31 | yes |
| 6S | Currencies | tff | 3 | 0.78 | 0.01 | yes | 3 | 1.75 | 0.03 | yes |
| 6E | Currencies | tff | 5 | -0.56 | -0.33 | no | 5 | -0.67 | -0.38 | no |
| 6J | Currencies | tff | 3 | -5.71 | -0.80 | no | 3 | -6.88 | -0.90 | no |
| 6M | Currencies | tff | 4 | -0.15 | 0.54 | no | 4 | -0.15 | 0.51 | no |
| 6N | Currencies | tff | 4 | 6.79 | 0.41 | yes | 4 | 5.70 | 0.25 | yes |
| DX | Currencies | tff | 2 | 2.44 | 0.22 | yes | 2 | 2.29 | 0.19 | yes |
| CL | Energies | disagg | 9 | -4.76 | 1.81 | no | 9 | -3.54 | -1.06 | no |
| NG | Energies | disagg | 27 | -2.08 | -2.57 | yes | 27 | -3.48 | -7.07 | yes |
| RB | Energies | disagg | 11 | 14.65 | 12.90 | yes | 39 | 5.28 | 2.48 | yes |
| HO | Energies | disagg | 7 | 9.19 | 9.04 | yes | 32 | 5.57 | 1.62 | yes |
| ZC | Grains | disagg | 1 | -6.56 | 0.02 | no | 1 | -6.71 | -0.54 | no |
| ZS | Grains | disagg | 8 | -18.20 | 4.76 | no | 9 | 5.78 | 1.68 | yes |
| ZM | Grains | disagg | 6 | 3.91 | 4.94 | no | 12 | 3.82 | 2.58 | yes |
| ZL | Grains | disagg | 22 | -0.05 | -0.97 | yes | 22 | 0.91 | 0.86 | yes |
| ZW | Grains | disagg | 9 | -0.32 | -1.24 | yes | 9 | -2.31 | -2.39 | yes |

Sign count with n >= 5: **13 of 26** markets above their own unconditional mean on the
cache basis, **16 of 28** on the propadj basis. Fourteen markets (sixteen on cache) have
fewer than five VALUE_ACCUM weeks and three (6A, BTC, GF) have none. The dispersion is the
point: the propadj means with n >= 5 run from -5.69% (ES) to +9.60% (CC), and the markets
that carry the pooled lean (CC, RB, HO, KC, YM, ZS) are a different set from the markets
where it is absent or reversed (ES, ZB, SI, CL, PA, CT). GC at +3.29% against +1.77% on
propadj is in the middle of the pack.

### The latest week, 2026-09-22

Every market, z per role on the latest report, state, and the two flags that fired.

| symbol | class | report | z_TREND | z_VALUE | z_RETAIL | z_COUNTERPARTY | z_OTHER | state | flags |
|---|---|---|---|---|---|---|---|---|---|
| ZB | Fixed Income | tff | +1.53 | -1.33 | +0.22 | -0.39 | +0.38 | PARTIAL |  |
| ZF | Fixed Income | tff | +1.34 | -0.79 | +0.25 | -1.36 | +0.30 | PARTIAL |  |
| ZN | Fixed Income | tff | -0.87 | -1.10 | -0.20 | +2.90 | +0.72 | PARTIAL |  |
| ZT | Fixed Income | tff | -0.74 | +0.41 | -0.12 | +0.24 | +0.36 | QUIET |  |
| ES | Equities | tff | -1.65 | +1.07 | +1.04 | +1.49 | -2.49 | MM_SELL_OTHERS_BUY | straddle_RETAIL |
| NQ | Equities | tff | -1.86 | +0.90 | -1.18 | +1.37 | +1.49 | PARTIAL |  |
| RTY | Equities | tff | -0.95 | +0.89 | +1.30 | -0.43 | +0.92 | PARTIAL |  |
| YM | Equities | tff | -0.44 | +1.64 | +1.79 | -1.66 | +2.08 | PARTIAL |  |
| GF | Live Stock | disagg | +0.43 | -1.17 | +1.86 | -1.22 |  | PARTIAL |  |
| HE | Live Stock | disagg | -0.42 | +1.17 | +0.07 | -0.12 |  | PARTIAL |  |
| LE | Live Stock | disagg | +0.20 | -0.65 | +1.21 | -0.37 |  | PARTIAL |  |
| CC | Softs | disagg | -1.92 | -0.53 | -1.85 | +2.19 |  | PARTIAL |  |
| CT | Softs | disagg | -1.75 | +0.41 | +0.52 | +1.16 |  | PARTIAL | derisk_TREND |
| KC | Softs | disagg | -1.25 | -0.22 | -0.52 | +1.21 |  | PARTIAL |  |
| LBR | Softs | disagg | -0.09 | +0.02 | +0.33 | +0.04 |  | QUIET |  |
| OJ | Softs | disagg | -0.47 | -0.12 | -0.30 | +0.64 |  | QUIET |  |
| SB | Softs | disagg | -0.23 | -0.67 | -0.44 | +0.61 |  | QUIET | straddle_RETAIL |
| GC | Metals | disagg | -0.65 | +0.15 | +2.12 | -0.08 |  | PARTIAL |  |
| HG | Metals | disagg | +2.79 | -0.62 | +0.52 | -2.21 |  | PARTIAL |  |
| PA | Metals | disagg | -0.47 | -0.17 | +0.88 | +0.30 |  | QUIET |  |
| PL | Metals | disagg | +0.39 | -0.57 | -0.30 | +0.03 |  | QUIET |  |
| SI | Metals | disagg | +0.06 | -0.03 | +1.44 | -0.77 |  | PARTIAL |  |
| BTC | Crypto | tff | -1.34 | +0.79 | +0.68 | +0.48 | +1.23 | PARTIAL |  |
| ETH | Crypto | tff | -1.12 | +0.56 | +0.92 | +0.85 | +0.33 | PARTIAL |  |
| 6A | Currencies | tff | -0.27 | -1.00 | +0.19 | +0.71 | +0.35 | QUIET | straddle_RETAIL |
| 6B | Currencies | tff | -0.80 | -2.01 | -1.55 | +2.12 | -1.13 | PARTIAL | straddle_RETAIL |
| 6C | Currencies | tff | -0.98 | -0.86 | +1.99 | +0.66 | +0.63 | PARTIAL |  |
| 6E | Currencies | tff | +0.12 | -2.26 | -0.75 | +1.49 | +0.02 | PARTIAL | straddle_RETAIL |
| 6J | Currencies | tff | -0.84 | -0.84 | +0.03 | +1.60 | -3.04 | QUIET | straddle_RETAIL |
| 6M | Currencies | tff | -1.40 | -0.94 | +0.40 | +1.10 | -0.08 | PARTIAL | straddle_RETAIL |
| 6N | Currencies | tff | -0.62 | -2.66 | -1.01 | +3.03 | +1.30 | PARTIAL | straddle_RETAIL |
| 6S | Currencies | tff | -0.80 | +0.15 | -0.44 | +0.40 | +0.00 | QUIET | straddle_RETAIL |
| DX | Currencies | tff | +0.09 | +0.40 | +0.37 | -0.09 | -1.83 | QUIET |  |
| CL | Energies | disagg | -0.29 | +0.65 | -0.03 | -0.25 |  | QUIET | straddle_RETAIL |
| HO | Energies | disagg | -0.54 | +1.35 | -1.32 | +0.43 |  | PARTIAL |  |
| NG | Energies | disagg | +1.50 | -1.62 | -0.50 | -0.25 |  | PARTIAL |  |
| RB | Energies | disagg | +1.61 | -1.83 | +0.27 | -0.81 |  | PARTIAL |  |
| ZC | Grains | disagg | -0.18 | +0.30 | +0.32 | +0.04 |  | QUIET | derisk_TREND |
| ZL | Grains | disagg | -0.61 | -0.93 | -0.37 | +0.91 |  | QUIET |  |
| ZM | Grains | disagg | +0.35 | -1.35 | -0.35 | +0.03 |  | PARTIAL |  |
| ZS | Grains | disagg | +0.73 | -0.38 | -0.42 | -0.64 |  | QUIET |  |
| ZW | Grains | disagg | -0.52 | -0.05 | +0.35 | +0.56 |  | QUIET |  |

Twenty-six markets are PARTIAL, fifteen QUIET, one named: ES is MM_SELL_OTHERS_BUY
(leveraged -1.65, asset manager +1.07, non-reportable +1.04, dealer +1.49, other
reportable -2.49). No divergence state (VALUE_ACCUM or RETAIL_ALONE_BUY) anywhere. The
largest moves are in the dealer and asset manager legs of the currencies (6N asset
manager -2.66 against dealer +3.03, 6B -2.01 against +2.12, 6E -2.26), ZN dealer +2.90,
and HG managed money +2.79 against commercials -2.21. `straddle_RETAIL` fired on ten
markets, eight of them TFF currencies and equities; `derisk_TREND` on CT and ZC. GC's
non-reportable +2.12 is the same figure the gold doc reports for the week.

---

## The handoff's scope

The handoff that asked for this run
([`docs/handoffs/2026-09-26-cot-flow-states-cross-universe.md`](../handoffs/2026-09-26-cot-flow-states-cross-universe.md))
scoped the pooled test to ADR-0005's universe, physical commodities and currencies, with
index futures and Treasuries kept out of the pool because their TFF cohorts have no
interpretable opinion split. The tables above pool all 42 markets. This section re-cuts
the same parquet to that scope (32 markets, 33,885 market-weeks), once with gold in it and
once without (gold is the discovery market), and re-anchors the forward return.
Reproducer: `scripts/analysis/cot_flow_states_scope.py`; every cut is a `tried` entry in
its own search log. The quarterly-expiry mask the handoff suggested for index futures was
not run: equities are outside the scoped pool and their heatmaps here are descriptive.

**The anchor.** The Friday diagnostic above starts at the settlement on report date + 3
days. That settlement prints before the 15:30 ET publication on every exchange in the
universe (COMEX metals settle 13:30 ET, grains 14:20, energies 14:30), and the 13 reports
dated 2025-09-30 to 2025-12-23 were published between 7 and 50 days late. Here the return
starts at the first settlement strictly after the resolved release date, the workspace's
Monday-close convention (`npf/scripts/episode_age_v6.py`, ENTRY_LAG_DAYS = 6), with the
release date taken from cotdata's release schedule where it has one (2,184 market-weeks,
the reports since 2025-09-30) and derived as report date + 3 pushed off a weekend
elsewhere (40,901 market-weeks). On an ordinary week the anchor is the Monday close; on a
late-release week it moves to the session after the actual publication.

Forward 13 weeks by state, ADR-0005 universe with gold, propadj basis. `n` is the
Tuesday-anchored count; the after-release count differs by at most one row per state
(ALL 32,595):

| state | n | Tuesday mean % | hit % | t | t_HAC | after-release mean % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|---|---|---|
| ALL | 32,626 | 0.02 | 50.8 | 0.30 | 0.10 | 0.04 | 51.0 | 0.50 | 0.17 |
| PARTIAL | 16,748 | 0.01 | 50.2 | 0.09 | 0.04 | 0.03 | 50.5 | 0.28 | 0.11 |
| QUIET | 14,320 | 0.02 | 51.6 | 0.20 | 0.08 | 0.02 | 51.5 | 0.19 | 0.08 |
| VALUE_ACCUM | 332 | 1.32 | 53.6 | 1.76 | 1.60 | 1.86 | 56.6 | 2.39 | 2.18 |
| TREND+RETAIL_BUY | 324 | -0.00 | 49.4 | -0.00 | -0.00 | 0.64 | 50.3 | 0.79 | 0.73 |
| MM_SELL_OTHERS_BUY | 269 | 0.78 | 49.8 | 1.13 | 1.02 | 0.60 | 52.6 | 0.83 | 0.73 |
| MM_ALONE_BUY | 264 | -1.65 | 47.3 | -1.97 | -1.57 | -1.41 | 47.3 | -1.78 | -1.36 |
| BROAD_LIQUID | 139 | 1.84 | 57.6 | 1.81 | 2.26 | 0.69 | 50.7 | 0.68 | 0.83 |
| BROAD_ACCUM | 124 | -0.03 | 51.6 | -0.04 | -0.04 | -0.27 | 46.0 | -0.31 | -0.38 |
| RETAIL_ALONE_BUY | 54 | -4.14 | 48.1 | -1.72 | -1.74 | -4.89 | 45.5 | -2.10 | -2.04 |
| INST_BUY_RETAIL_SELL | 52 | 0.55 | 46.2 | 0.17 | 0.28 | 0.45 | 51.9 | 0.15 | 0.23 |

Without gold (31 markets, 32,826 market-weeks), the rows that move:

| state | n | Tuesday mean % | t_HAC | after-release mean % | t_HAC |
|---|---|---|---|---|---|
| ALL | 31,580 | -0.03 | -0.15 | -0.02 | -0.08 |
| VALUE_ACCUM | 311 | 1.18 | 1.36 | 1.75 | 1.94 |
| BROAD_LIQUID | 134 | 1.75 | 2.09 | 0.59 | 0.68 |
| MM_ALONE_BUY | 260 | -1.59 | -1.49 | -1.35 | -1.29 |
| RETAIL_ALONE_BUY | 53 | -4.35 | -1.80 | -5.11 | -2.10 |

At 4 weeks on the Tuesday anchor, VALUE_ACCUM is +1.15% against ALL +0.02% (hit 57.8%
against 50.9%, plain t 2.56, HAC t 2.20) with gold and +1.12% against 0.00% (HAC t 2.03)
without.

Single-cohort rows at 13 weeks on this scope: every buy and sell row sits within 0.55
points of ALL, the largest |HAC t| is 1.57 (TREND buy -0.55% without gold, Tuesday
anchor), and after the release the largest is 1.20. The null holds on the scoped pool.

Per class (Tuesday anchor, 13 weeks), VALUE_ACCUM against the class's own ALL:

| class | n | VALUE_ACCUM mean % | class ALL % | t_HAC |
|---|---|---|---|---|
| Energies | 107 | 2.41 | -1.01 | 1.33 |
| Grains | 53 | 1.71 | 0.44 | 1.37 |
| Softs | 73 | 0.94 | -0.36 | 0.50 |
| Currencies | 28 | 0.47 | -0.09 | 0.43 |
| Live Stock | 7 | 1.29 | 0.23 | 0.60 |
| Metals | 64 | -0.04 | 0.91 | -0.03 |

The metals class, which holds the discovery market, shows nothing pooled: GC's +3.29%
sits beside SI -4.52%, PA -2.58%, PL -0.39% and HG +0.36%. Per market, 14 of 21 with n >= 5
sit above their own unconditional mean (13 of 20 without gold).

Co-firing: VALUE_ACCUM's 338 rows on this scope fall in 262 distinct weeks; 13 weeks
carry three or more markets at once (13.6% of rows), and one week, 2011-08-09, carries
eight. BROAD_LIQUID: 141 rows in 111 weeks, 15.6% in weeks of three or more. The effective
n of a pooled row is nearer the distinct-week count than the row count, and the HAC, which
treats markets as independent, does not see this; a block bootstrap on the calendar grid
would.

Two more facts from this run: on the propadj basis 429 market-weeks of 43,085 have
|fwd13| > 50% (BTC 70, CL 57, HO 47, NG 43, RB 41, ETH 38, CC 20, OJ 20), so about a third
of the cache figure of 1,228 are genuine moves rather than near-zero artefacts; and the
after-release single-cohort rows shrink uniformly toward zero (TREND buy -0.48% to -0.36%,
VALUE buy +0.53% to +0.41%), which is what removing three to four pre-publication sessions
from every window should do.

Reading. On the pre-registered scope VALUE_ACCUM is the same marginal lean it was pooled
over 42 markets, and it is a little stronger, not weaker, once the anchor is moved past
the publication. BROAD_LIQUID is not: its Tuesday-anchored lean was concentrated in the
sessions between the report date and the release, the week's own rebound, which no reader
of the report could have bought. RETAIL_ALONE_BUY (retail buying alone while both
institutional cohorts sell) leans negative on 54 weeks with HAC t near -2 on both anchors
and both scopes, on an n too small to say more. All of it is descriptive; the two search
logs hold 53 looks between them, and any test goes through crucible with that count.

---

## Diagnostics

### Identity residual

The sum of `dNet` over every category the report carries (five on Disaggregated, five on
TFF including other reportable) is 0 contracts on every week of every one of the 42
markets: `identity_max_abs_overall = 0.0`. Every long has a short on both reports.

### Lag-1 autocorrelation of dNet, per market, and flag counts over the full history

| symbol | report | weeks | ac1 TREND | ac1 VALUE | ac1 RETAIL | ac1 COUNTERPARTY | straddle_TREND | straddle_VALUE | straddle_RETAIL | derisk_TREND | cache closes <= 0 | abs(fwd13) > 50% weeks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ZB | tff | 1,059 | 0.05 | 0.01 | -0.18 | -0.06 | 64 | 69 | 71 | 31 | 0 | 0 |
| ZN | tff | 1,059 | -0.07 | 0.00 | -0.22 | -0.10 | 54 | 47 | 75 | 51 | 0 | 0 |
| ZF | tff | 1,059 | 0.01 | 0.02 | -0.20 | -0.09 | 48 | 49 | 64 | 47 | 0 | 0 |
| ZT | tff | 1,059 | 0.12 | 0.13 | -0.34 | -0.11 | 72 | 56 | 73 | 49 | 0 | 0 |
| YM | tff | 1,059 | 0.06 | 0.08 | -0.14 | 0.06 | 53 | 11 | 50 | 41 | 0 | 0 |
| NQ | tff | 1,059 | -0.01 | 0.07 | -0.03 | 0.15 | 50 | 11 | 51 | 35 | 0 | 0 |
| RTY | tff | 1,059 | 0.03 | 0.19 | -0.25 | 0.18 | 55 | 15 | 66 | 48 | 0 | 0 |
| ES | tff | 1,059 | -0.12 | 0.03 | -0.02 | 0.06 | 33 | 17 | 49 | 34 | 0 | 0 |
| GF | disagg | 1,059 | 0.30 | 0.07 | 0.15 | 0.15 | 25 | 65 | 63 | 75 | 0 | 0 |
| HE | disagg | 1,059 | 0.44 | 0.11 | -0.16 | 0.43 | 26 | 54 | 119 | 65 | 151 | 151 |
| LE | disagg | 1,059 | 0.40 | 0.07 | 0.09 | 0.33 | 24 | 46 | 116 | 73 | 0 | 0 |
| CT | disagg | 1,059 | 0.35 | 0.10 | -0.00 | 0.30 | 5 | 36 | 55 | 74 | 65 | 65 |
| CC | disagg | 1,059 | 0.32 | 0.09 | -0.13 | 0.27 | 32 | 25 | 83 | 62 | 11 | 236 |
| KC | disagg | 1,059 | 0.37 | 0.05 | -0.18 | 0.31 | 7 | 29 | 110 | 80 | 59 | 119 |
| LBR | disagg | 1,059 | 0.33 | 0.00 | -0.09 | 0.31 | 6 | 39 | 111 | 57 | 0 | 0 |
| OJ | disagg | 1,059 | 0.39 | 0.20 | -0.03 | 0.29 | 4 | 18 | 82 | 56 | 780 | 116 |
| SB | disagg | 1,059 | 0.37 | 0.22 | 0.00 | 0.29 | 9 | 20 | 77 | 87 | 0 | 28 |
| HG | disagg | 1,059 | 0.22 | 0.10 | -0.16 | 0.22 | 17 | 37 | 79 | 81 | 0 | 0 |
| GC | disagg | 1,059 | 0.17 | -0.03 | -0.15 | 0.20 | 7 | 45 | 79 | 65 | 0 | 0 |
| PA | disagg | 1,059 | 0.27 | 0.01 | -0.05 | 0.27 | 10 | 41 | 61 | 55 | 0 | 0 |
| PL | disagg | 1,059 | 0.20 | 0.02 | -0.17 | 0.23 | 15 | 41 | 57 | 79 | 0 | 3 |
| SI | disagg | 1,059 | 0.26 | -0.07 | -0.19 | 0.28 | 7 | 42 | 70 | 60 | 0 | 6 |
| BTC | tff | 442 | -0.16 | 0.12 | -0.24 | 0.04 | 62 | 1 | 18 | 31 | 0 | 7 |
| ETH | tff | 286 | -0.22 | -0.02 | -0.24 | -0.28 | 20 | 2 | 13 | 18 | 0 | 20 |
| 6A | tff | 1,059 | 0.17 | 0.26 | 0.06 | 0.30 | 35 | 9 | 42 | 45 | 0 | 1 |
| 6B | tff | 1,059 | 0.13 | 0.22 | 0.01 | 0.27 | 49 | 14 | 44 | 45 | 0 | 0 |
| 6C | tff | 1,059 | 0.17 | 0.35 | -0.18 | 0.34 | 50 | 12 | 21 | 42 | 0 | 0 |
| 6S | tff | 1,059 | -0.04 | 0.10 | 0.11 | 0.17 | 32 | 13 | 19 | 33 | 0 | 0 |
| 6E | tff | 1,059 | 0.16 | 0.23 | -0.10 | 0.31 | 42 | 21 | 74 | 39 | 0 | 0 |
| 6J | tff | 1,059 | 0.08 | 0.22 | -0.09 | 0.17 | 44 | 14 | 48 | 42 | 0 | 0 |
| 6M | tff | 1,059 | 0.09 | 0.10 | -0.28 | 0.23 | 37 | 4 | 34 | 35 | 0 | 8 |
| 6N | tff | 1,056 | 0.13 | 0.32 | -0.10 | 0.37 | 37 | 9 | 36 | 43 | 0 | 0 |
| DX | tff | 1,059 | -0.02 | 0.21 | -0.11 | 0.06 | 61 | 4 | 58 | 36 | 0 | 0 |
| CL | disagg | 1,059 | 0.17 | -0.04 | -0.18 | 0.28 | 21 | 36 | 111 | 77 | 20 | 40 |
| NG | disagg | 1,059 | 0.27 | 0.09 | -0.11 | 0.21 | 35 | 4 | 78 | 68 | 0 | 85 |
| RB | disagg | 1,059 | 0.21 | 0.22 | -0.01 | 0.17 | 21 | 22 | 71 | 77 | 835 | 31 |
| HO | disagg | 1,059 | 0.17 | 0.12 | 0.06 | 0.17 | 26 | 21 | 90 | 82 | 952 | 37 |
| ZC | disagg | 1,059 | 0.35 | 0.02 | 0.01 | 0.34 | 5 | 27 | 84 | 79 | 0 | 0 |
| ZS | disagg | 1,059 | 0.29 | 0.04 | 0.02 | 0.26 | 7 | 26 | 86 | 97 | 251 | 82 |
| ZM | disagg | 1,059 | 0.34 | 0.09 | -0.08 | 0.25 | 4 | 30 | 88 | 88 | 492 | 59 |
| ZL | disagg | 1,059 | 0.33 | 0.05 | -0.07 | 0.25 | 5 | 54 | 61 | 93 | 128 | 134 |
| ZW | disagg | 1,059 | 0.17 | 0.06 | -0.20 | 0.08 | 11 | 30 | 97 | 74 | 0 | 0 |

Median lag-1 autocorrelation across the 42 markets: TREND 0.171, VALUE 0.090, RETAIL
-0.105, COUNTERPARTY 0.231. The weekly change is far from the near unit-root behaviour of
the positioning level (`positioning-series-properties.md` reports a median lag-1 of 0.956
on levels), which is the reason to build the primitive on changes. It is not white either.
Disaggregated managed money runs 0.17 to 0.44 (HE 0.44, LE 0.40, OJ 0.39), so a one-sigma
managed-money move on a physical is more likely to be followed by another in the same
direction than not; TFF leveraged funds run -0.22 to 0.17. RETAIL is mildly
mean-reverting on most markets, consistent with the gold doc's reading of GC's
non-reportable sell then buy as a reversal rather than a divergence. Effective sample
sizes for the state tables are correspondingly somewhat smaller than n on physicals.

### Small-OI flag

100 contracts exceeds 0.5 sigma of dNet at the latest date on two markets: LBR (RETAIL
sd 124) and OJ (VALUE sd 172). The next smallest sigma on any role is OJ RETAIL at 225,
then BTC RETAIL at 242. On LBR and OJ a one-sigma "move" is a few dozen contracts and the
state label on those two should be read as noise.

### Price basis on the cache series

The cache `Closing Price` is additively back-adjusted. It is non-positive, and therefore
masked to NaN before the log, on 11 markets: HO 952 of 1,059 weeks, RB 835, OJ 780, ZM 492,
ZS 251, HE 151, ZL 128, CT 65, KC 59, CL 20, CC 11. The surviving closes near zero produce
wild log returns: 1,228 market-weeks have |fwd13| > 50% on the cache basis (CC 236, HE 151,
ZL 134, KC 119, OJ 116, NG 85, ZS 82). This is what makes CC's cache VALUE_ACCUM mean
+48.73% (propadj +9.60%), HE +40.67% (propadj +3.11%), ZS -18.20% (propadj +5.78%), and the
Disaggregated pooled unconditional +1.14% on cache against +0.07% on propadj. GC, and every
TFF market, has zero non-positive closes, which is why the gold doc was unaffected. Zero
masking does not make the two bases agree: an additively back-adjusted close gives a
different percentage return from a ratio-adjusted one wherever the offset is non-zero, not
only where it turns the price negative, and the cache has no 2026-09-22 bar, so each TFF
market loses one 13-week row (pooled TFF 13-week n 18,462 on cache against 18,481 on
propadj). Pooled TFF 13-week means on cache against propadj: ALL +0.49% against +0.62%,
PARTIAL +0.33% against +0.50%, QUIET +0.66% against +0.75%, MM_ALONE_BUY +0.78% against
+1.05%, VALUE_ACCUM +0.43% against +0.26%, TREND+RETAIL_BUY +0.48% against +1.03%,
INST_BUY_RETAIL_SELL +1.35% against +2.62%, BROAD_LIQUID +1.90% (n=80) against +2.03%
(n=81), RETAIL_ALONE_BUY +2.56% (n=26) against +3.11% (n=27); the single-cohort TFF rows
differ by 0.1 to 0.3 points (TREND buy +0.39% against +0.67%), and per market BTC's
unconditional is +2.10% against +4.93%, NQ +2.12% against +3.36%, ES +1.69% against
+2.15% (`pooled.tff.*` against `price_basis_check.pooled.tff.*` in the JSON). The two
bases agree on sign and on which rows lean, not to any decimal. The check is recorded as a
`SearchSpaceLog` entry rather than silently substituted.

### Friday-anchor diagnostic

Ran, 42 of 42 markets covered by the propadj tier, 41,697 market-weeks with a
Friday-anchored 13-week return.

| row | anchor | n | mean % | median % | hit % | t | t_HAC |
|---|---|---|---|---|---|---|---|
| VALUE_ACCUM | friday | 395 | 1.64 | 1.16 | 55.4 | 2.45 | 2.19 |
| ALL | friday | 41,697 | 0.32 | 0.42 | 53.4 | 4.81 | 1.62 |
| VALUE_ACCUM | tuesday_propadj | 395 | 1.13 | 0.86 | 54.4 | 1.72 | 1.56 |
| ALL | tuesday_propadj | 41,696 | 0.31 | 0.40 | 53.2 | 4.74 | 1.60 |
| VALUE_ACCUM | tuesday_cache | 322 | 2.36 | 0.20 | 51.9 | 1.59 | 1.30 |
| ALL | tuesday_cache | 38,211 | 0.83 | 0.31 | 52.8 | 6.67 | 2.71 |

Moving the anchor from the Tuesday report date to the first close on or after the Friday
release raises the pooled VALUE_ACCUM 13-week mean from +1.13% to +1.64% and its HAC t from
1.56 to 2.19, while ALL moves from +0.31% to +0.32%. The objection that the gold design's
return window includes three sessions during which the positions were not public does not
explain the VALUE_ACCUM lean; on this measurement those three sessions were slightly
against it. This is one extra anchor on one state, logged, not a design change.

### Search log

`n_variants = 44`: 42 `tried` entries (one per market at the fixed configuration) plus
two diagnostic entries (`friday_anchored_fwd13`, `price_basis_check`). The reproducer
removes the file before writing, so a re-run reports 44 again rather than accumulating.
The scope script keeps its own ledger (`2026-09-26-cot-flow-states-scope.searchlog.jsonl`,
9 entries: six pooled cuts, two co-firing diagnostics, one per-class table), so the looks
taken across this document total 53.

---

## Variants not tried

The gold list, none of which were run here either, all of which would need to be in a
`SearchSpaceLog` before any claim is made off them:

- activity threshold 0.5 sigma
- 26-week rolling window
- 8-week horizon
- states over two cohorts instead of three
- levels instead of changes

New ones this run makes obvious, equally untried:

- any TFF role mapping other than the one fixed here (asset manager as VALUE is an
  analogy; other reportable is carried as a z column and never entered the state)
- a TFF-native vocabulary over its four reportable cohorts rather than the gold three
- BROAD_LIQUID as a test of its own, at any horizon, on either report type
- the Friday anchor applied to every state and horizon rather than two rows
- a cross-sectional (clustered by week) standard error beside the within-market HAC
- equal-weighting markets rather than market-weeks in the pool, or pooling by asset class
- a pinned marketdata vintage so the propadj figures reproduce against a manifest
- dropping LBR and OJ (small-OI) and the ETH history (286 weeks) from the pool
- the quarterly-expiry mask for index futures the handoff suggested (equities are outside
  the scoped pool, so it was not run)
- the after-release anchor applied to the 4-week horizon and to the per-class tables (only
  the 13-week pooled tables were re-anchored)

If VALUE_ACCUM is worth pursuing, it goes through crucible with the variant count from
both logs, starting at 53, on the ADR-0005 universe without gold, anchored after the
release, and with holdout and walk-forward windows built so that the 13-week overlap is
purged by construction.

---

## Plain-language recap

The picture from gold holds up everywhere. When any one group of traders makes a big move
in a week, that on its own tells you nothing about the next three months, on physical
commodities or on financials: a **genuine null**, now on 42 markets instead of one. The
combinations of three groups moving at once are as rare across the board as they were on
gold (one week in twenty), so the state table stays what the gold doc said it was, a
caption vocabulary for the heatmap and not a signal.

Two combinations looked like leans. The one gold flagged (value money buying while
trend-followers and retail sell) is a **marginal lean** pooled: better next-quarter
returns on the physicals and currencies by one to two points, roughly even odds market by
market, no better than the null on financials, and a little stronger, not weaker, when the
return is measured from the first close after the report was actually published. A second
one gold could not see for lack of cases (everyone selling at once, followed by better
returns) was found by looking at eight states in twelve tables (two horizons, three
pools, two price bases), which is exactly how leans that are not real get found, and on
the properly anchored read it fades to nothing: the better returns sat in the few
sessions between the report date and its publication, which nobody could have traded.
Neither is a result; the first is a hypothesis for crucible, and the decision this
document supports is whether to send it there, not whether to trade it.

One finding is **significant** in the plain sense and is about the plumbing, not the
market: the price series the gold study used cannot be used for a cross-market study
because it goes to zero and below on half the physical commodities. The tables that
matter here are the ones on the ratio-adjusted marketdata prices, and any tooling built
on this design should read those.
