# COT flows: from the gold study to a cotmetrics primitive and a cot-analyzer view

**Living document.** Plan and decision record for the week-over-week cohort flow work
that started in
[`analysis/2026-09-26-cot-flow-states-gold.md`](../analysis/2026-09-26-cot-flow-states-gold.md).
Nothing described under "What to build" exists yet; the two analysis docs and the
scripts under `scripts/analysis/` are the only artefacts. Written 2026-09-26 from a
multi-agent review of the gold study, a 42-market replication, and three competing
integration designs judged from an engineering and a reader's lens. Amend this file as
decisions land; the analysis docs are never amended.

## 1. What exists

| artefact | what it is | status |
|---|---|---|
| `analysis/2026-09-26-cot-flow-states-gold.md` + `scripts/analysis/cot_flow_states.py` | the primitive (dNet / own 52-week sd per cohort), the eight-state vocabulary, the gold read | point in time; the script is still being iterated in a parallel Cowork session (a price-over-heatmap figure and a level x flow addendum landed the same day) |
| `analysis/2026-09-26-cot-flow-states-universe.md` + `scripts/analysis/cot_flow_states_universe.py` | the gold design unchanged on the 42 non-heldout markets, two price bases, HAC t, Friday diagnostic, per-class heatmaps and a cross-asset board PNG | point in time, reproduces bit for bit, 44-entry search log |
| section "The handoff's scope" of the universe doc + `scripts/analysis/cot_flow_states_scope.py` | the same parquet cut to ADR-0005's universe with and without gold, and re-anchored at the first settlement after the resolved release date | point in time, 9-entry search log |
| `scripts/analysis/critique_2026-09-26/` | the reproducers behind the methodology corrections in section 2 (overlap inflation, block bootstrap, Tuesday-to-Friday leg, run lengths, seams, normalisers, basis disagreement), each with its printed output beside it | committed so the figures below can be quoted |
| `analysis/2026-09-26-cot-cohort-roles.md` + `scripts/analysis/cot_cohort_roles.py` + two CSVs | per-(report, symbol) cohort roles from the data: SPEC / COUNTERPARTY / NEUTRAL / inert / RETAIL by same-week price correlation of dNet and gross share, threshold 0.15 fixed in advance; the Prod/Swap same-sign measurement that motivated it | point in time, Cowork session, sandbox paths in the script; measured on the cache close (see the next row); stability over time not measured there |
| `analysis/2026-09-26-cot-cohort-roles-propadj.md` + `scripts/analysis/cot_cohort_roles_propadj.py` + three CSVs (roles, collapse, stability) | the same rule on the ratio-adjusted series, the changes against the cache-close table, and a rolling 156-week stability check with a criterion fixed before the run | point in time; the source of `src/cotmetrics/flow_roles.py` (PR 1) via `scripts/analysis/gen_flow_roles.py` |
| `analysis/2026-09-26-cot-roles-vs-legacy.csv` + `scripts/analysis/cot_roles_vs_legacy.py`, and the `-propadj` pair | weekly-flow correlation of the measured SPEC and COUNTERPARTY groups with Legacy Non-Commercial and Commercial | Cowork (cache roles) and this session (propadj roles); see the Legacy bullet in section 2 |
| `docs/handoffs/2026-09-26-cot-flow-states-cross-universe.md` | the Cowork session's handoff asking for the cross-universe run, with a level x flow addendum and a proposed three-panel view | executed twice on 2026-09-26: descriptively in the main checkout (status update at its end) and as the pre-registered crucible test on the branch below; the branch carries its own copy of this file with an Outcome section, so the two copies must be merged by hand |
| branch `claude/cot-flow-states-cross-universe` (local, unpushed, two commits 12:18 and 12:22): `analysis/2026-09-26-cot-flow-states-cross-universe.md` + `scripts/analysis/cot_flow_states_cross_universe.py` | the pre-registered evaluator pass: VALUE_ACCUM long, 13 weeks, 32-market ADR-0005 scope, non-overlapping vol-normalised drift-removed trades in a crucible TradeLog, holdout at 2019-01-01 with an 8-week embargo, run_gauntlet with a 63-entry log seeded from the descriptive pass | done by a third session; design committed before the run; verdict FAIL 0 of 3 gates, TEST +0.124R on 85 trades with the interval spanning zero |

## Vocabulary

- **Flow.** A cohort's week-over-week change in net futures position, dNet = (long minus
  short).diff(), in contracts. **Flow z** is that change divided by the cohort's own
  trailing 52-week standard deviation of weekly changes, no mean subtracted.
- **Opinion cohorts.** The three whose flow signs make the state: Managed Money, Other
  Reportable and Non-Reportable on Disaggregated; Leveraged Funds, Asset Manager and
  Non-Reportable on TFF. Fixed per report so the eight state names keep one meaning.
- **Counterparty.** The cohort, or set of cohorts, that takes the other side of the opinion
  cohorts' flow: the group whose weekly buying moves against the week's price (same-week
  correlation of dNet with the return at or below -0.15) and whose flow correlates
  negatively with the speculators'. Accounting guarantees someone does: every long has a
  short, so the sum of dNet over all cohorts is exactly zero every week, and a sentence
  naming only the buyers has left the sellers off the page. Which cohort it is is a
  per-market fact, measured, not assumed: Producer/Merchant plus Swap Dealers (the Legacy
  "Commercial") in precious metals, Producer/Merchant alone in most grains, softs and
  livestock (where swap dealers carry the index book and are neutral), Other Reportable
  plus Producer on a few, Dealer/Intermediary in currencies, Leveraged Funds on equity
  index and crypto (their hedge and basis book). The heatmap's composite row is the sum of
  dNet over the counterparty members; it equals minus the opinion cohorts' flow only where
  no neutral or inert cohort sits outside both sets. Contemporaneous by construction:
  "absorbs" says who was on the other side this week, not what happens next.
- **Neutral.** A cohort with a meaningful share of gross open interest whose flow does not
  correlate with price either way (the swap dealers' index book in grains). Kept as its
  own row, never folded into either side.
- **Inert.** Under 5% of gross open interest; its flow is drawn but it plays no role.
- **Retail.** Non-Reportable, by label. On the Cowork measurement (cache close, being
  re-measured on the ratio-adjusted series) its flow chases price on 25 of 41 markets, is
  neutral on 13 and absorbs on 3, so the label is a category, not a behaviour.
- **State.** The sign triple of the opinion cohorts at |z| > 1, named on Disaggregated
  with the gold vocabulary. A caption, not a signal; the pre-registered test failed.

## 2. What the measurements settled

Strength words as npf/AGENTS.md #9 asks. Every figure has a reproducer in the row's
source.

- **The primitive is sound and additive.** Sum of dNet over every category is exactly 0
  on every week of all 42 markets (universe doc, Diagnostics). No existing cotmetrics code
  differences Disaggregated or TFF category contracts week over week; every shift, diff
  or pct_change in `src/cotmetrics` is on the Legacy legs, open interest, price, the 0-100
  index or a daily series (compute reader, verified line by line). So a flows module
  touches nothing.
- **dNet / rolling sd of dNet is the right normaliser, by convention rather than by
  measured superiority.** Any quantity divided by its own rolling sd is comparable across
  markets; (dNet / OI) / its rolling sd is 0.97 to 1.00 correlated with it. Unstandardised
  dNet / OI is not comparable (sd 1.3% on CL to 12.4% on LBR). The rolling sd tracks OI at
  a median log-correlation of 0.71, so "unaffected by OI regime" is false (critique:
  `normaliser.py`).
- **`indicators.calculate_z_score` must not be reused.** It subtracts a rolling mean,
  adds 1e-9 to the sd and fills NaN with 0; its own test pins that a constant series
  yields 0. On DC's 25 empty swap-dealer windows the doc's formula says NaN (no reading)
  and the epsilon idiom says 0.0, which the classifier reads as QUIET. The gold and
  universe scripts also map NaN z to 0, so the first 26 weeks of every market are labelled
  QUIET (1,113 warm-up rows in the universe parquet). A shipped classifier returns None
  there.
- **The single-cohort read is a genuine null** on gold and on the universe (largest
  |HAC t| 1.85 pooled over 42 markets, 1.57 on the ADR-0005 scope, 1.20 after the release
  anchor). A cohort moving one sigma on its own says nothing about the next quarter.
- **The eight-state table is a vocabulary, not a signal.** 4.6% of market-weeks are in a
  named state; RETAIL_ALONE_BUY happens 77 times in twenty years across 42 markets. Named
  states do not repeat: weeks per episode is 1.00 to 1.07 for every state (critique:
  `refute_runs.py`), so the episode property of positioning LEVELS does not apply to
  flows.
- **Gold alone is uninformative on VALUE_ACCUM, not a null.** With the statistics done
  right (excess over the unconditional, Newey-West lag 12, crucible's
  `block_bootstrap_pvalue` at block 13) gold's n=21 gives +0.95% excess, HAC t 0.76,
  p 0.22, 95% CI [-1.7%, +3.3%]; the minimum detectable excess at 80% power is 3.0 to 3.4%
  against +0.95% observed (critique: `alts.py`, `serial.py`). The gold doc's t=1.92 tested
  against zero on overlapping windows; under the null a 13-week overlapping t has sd 3.6
  (`overlap_null.py`).
- **VALUE_ACCUM fails the gate: a marginal lean at most, a genuine null as a signal.**
  Descriptively it survives the two corrections that were supposed to kill it (physicals
  plus currencies without gold, anchored after the resolved release date: +1.75% against
  -0.02%, n=311, HAC t 1.94; universe doc, "The handoff's scope"), but the pre-registered
  crucible test on the branch (32 markets, non-overlapping trades, causal drift removal,
  Friday-settlement entry) reads TEST +0.124R on 85 trades with a 90% interval of
  [-0.070, +0.317], REAL p 0.61 after Sidak over 19 session variants, STRONG and GENERAL
  failed, time-clustered t 1.24, and gold's own pre-2019 half negative. The sign is
  consistent (13 of 19 markets, both halves, commodities only, currencies negative), which
  is what a marginal lean looks like, and nothing here is an npf gate candidate. The only
  pre-registrable next step named there is the same state on data after 2026-09-26. One
  difference between the two reads is worth recording and not re-litigating: the branch
  enters at the report date + 3 settlement, which prints before the 15:30 ET publication;
  the after-release anchor in the universe doc gave a slightly larger lean, and a gauntlet
  fail at 0 of 3 is not going to flip on a one-session shift.
- **BROAD_LIQUID is not a lean.** Its pooled HAC t of 2.92 came from tabulating twelve
  tables, and anchoring after the publication takes it from +1.84% to +0.69% (HAC t
  0.83): the return sat in the sessions between the report date and its release.
- **The cache price series cannot be used for cross-market returns.** cot-analyzer's
  `data_cache` `Closing Price` is additively back-adjusted and goes non-positive on 11 of
  23 physicals; gold's own +2.20% against +1.24% are on that basis and read +3.29% against
  +1.77% on the ratio-adjusted `propadj` tier. Read `marketdata.get_bars(sym, "propadj",
  domain="futures")` for any return.
- **The Tuesday anchor is a look-ahead, small on gold, and the fix is not report date +
  3.** The settlement on report date + 3 prints before the 15:30 ET publication on every
  exchange, and 13 reports of late 2025 were published 7 to 50 days late. Anchor at the
  first settlement strictly after the release date resolved through
  `cotdata.vintage_schedule` (schedule where present, derived elsewhere), the workspace's
  Monday-close convention.
- **Two stitched markets carry phantom flows.** LBR's new code (058644) lacks 2023-02-28
  and 03-07, so `cotdata.get_cot`'s primary-wins stitch alternates two contract
  populations across 2023-02-21 to 03-14 (managed money z -3.68 then +3.32); RTY switches
  code on 2017-08-15 (leveraged z +2.21) and migrated venue across 2008-09-09 to 09-23
  (dealer +71,123, which no per-code differencing cleans). `CFTC_Contract_Market_Code_Quotes`
  survives the stitch on all 42 markets and pinpoints the code switches; cotdata does not
  promise that column. ZO has ten index holes over 8 days (max 294) and 6N one.
- **The counterparty composite is a precious-metals fact, not a Disaggregated fact.**
  Prod/Swap weekly-flow correlation is +0.40 to +0.58 on GC, SI, PL, PA and negative on
  every grain, soft, livestock and energy market (median -0.14; same-sign fraction of net
  levels near zero on ZC, ZS, LE, HE, CT, HO, RB). Corn today: producers -773k, swap
  dealers +299k. Summing them there is the difference of two opposite books. Measured per
  market in `analysis/2026-09-26-cot-cohort-roles.md`: Managed Money is SPEC on 21 of 23
  physicals and Producer/Merchant COUNTERPARTY on 21; Swap Dealer is COUNTERPARTY only on
  GC, SI, PL, PA, HG, HO and NEUTRAL (the index book, 11-16% of gross) in grains and
  softs; Other Reportable is never SPEC. On TFF, Dealer is COUNTERPARTY in all eight
  currencies and ZB with Asset Manager and/or Leveraged as SPEC (the universe run's
  mapping), but on ES, RTY and BTC Asset Manager is SPEC and Leveraged Funds is the
  COUNTERPARTY. CL, ZF and ZT separate nothing at 0.15. Non-Reportable flow chases price
  on 25 of 41 markets, is neutral on 13 and absorbs it on 3 (GF, LE, YM), so "retail" as
  a fixed opinion cohort is an assumption that holds on 25. Significant as description;
  contemporaneous by construction, so no evidence about prediction.
- **Legacy is a faithful proxy for the role pair on physicals and major FX, and not on
  equities or rates.** Weekly-flow correlation of the measured SPEC group with Legacy
  Non-Commercial and of the COUNTERPARTY group with Legacy Commercial
  (`analysis/2026-09-26-cot-roles-vs-legacy.csv`, `scripts/analysis/cot_roles_vs_legacy.py`):
  0.87 to 0.97 and 0.84 to 1.00 on 20 of 23 Disaggregated markets (exact 1.00 where the
  counterparty is Prod + Swap, since that IS Legacy Commercial); the exceptions are the
  energy products HO, NG, RB (0.18 to 0.43) and CL, which has no roles. On TFF the majors
  6A, 6B, 6C, 6E, 6J give 0.79 to 0.89 and 0.85 to 0.92; 6S, DX, 6N are weaker on the
  spec side; ES, ZN, ZB, BTC are zero or negative on both. Consequence: the pre-2006
  Legacy history can back-fill the role groups where the correlation is above about 0.85
  (physicals ex-energy, major FX) and nowhere else, which is ADR-0005's boundary measured
  at the flow level. Amended the same day on the propadj roles
  (`scripts/analysis/cot_roles_vs_legacy_propadj.py`,
  `analysis/2026-09-26-cot-roles-vs-legacy-propadj.csv`): with the price basis fixed, HO
  and RB rejoin the physicals (0.85 / 0.92 and 0.87 / 0.86), CL separates (0.81 / 0.63),
  and the counterparty-side exceptions are NG (0.43) and CL (0.63); on TFF 6S is now 0.92 /
  0.94, 6A 0.88 / 0.92, and equities, rates, BTC and ETH stay at or below 0.6 on the
  counterparty side. The back-fill boundary therefore reads: physicals except NG and CL,
  and the CME currencies except DX; nowhere else.
- **The TFF role mapping is an analogy and the currencies fact is drift from ADR-0005.**
  Measured dNet correlations: in FX, dealers absorb both leveraged (-0.74) and asset
  manager (-0.57) flow and the two barely relate (-0.07); in rates leveraged against asset
  manager is -0.67 with dealers 7% of gross (the basis trade). ADR-0005 Decision 2 names
  asset managers as the counterparty in currencies; the data says dealers. That is a
  finding to surface beside the ADR, not to reconcile silently (critique: `part2.py`).
- **Basis matters for the labels.** z of d(net contracts) and z of d(net % of OI) disagree
  on the named-state label for 14.8% of pooled market-weeks (critique: `state_basis.py`).
  The classifier's basis (contracts) is a fixed, logged choice, not an invariance.
- **Managed-money flow coincides with the week's own price move** (corr +0.55 on gold,
  same week). The heatmap will look like it predicts the price panel above it. Whether a
  state adds anything beyond the concurrent weekly return has not been tested on any
  market (open, section 6).

## 3. What to build, in order

Merged from the two judged designs (the minimal one and the reader-first one; the
cross-asset-board design contributes the copy rules and the later board). Each PR ships
without the next.

### PR 1, cotmetrics 0.15.0: `src/cotmetrics/flows.py`

Pure and store-free, imports only pandas, numpy, `cotmetrics.constants` and
`cotmetrics.categories`. Takes the OUTPUT of `categories.build_category_frame` so the
Swap_/Swap__ resolution, dtype coercion, skipped categories and `present_categories` are
inherited, and returns only new columns on the same index.

- Constants (in `constants.py` beside `NET_POS`): `FLOW = " dNet"`, `FLOW_LONG = " dLong"`,
  `FLOW_SHORT = " dShort"`, `FLOW_Z = " Flow Z"`, `FLOW_THIN = " Flow Thin"`,
  `FLOW_Z_WEEKS = 52`, `FLOW_Z_MIN_PERIODS = 26`, `FLOW_ACTIVE_Z = 1.0`,
  `FLOW_MAX_GAP_DAYS = 8`, `FLOW_MIN_STD_CONTRACTS = 200`. Every one recorded in the
  docstring as fixed before results and unsearched. The window rides in the z column name
  (`"Managed Money Flow Z 52w"`) so it cannot be mistaken for the page-lookback infix that
  `index_col` and `zscore_col` carry: the page lookback is 8 weeks on OJ and 216 on PA and
  must never reach the flow window.
- `weekly_change(series, *, max_gap_days)`: `diff()` masked where the index gap exceeds
  8 days and where the source contract code changes (see discontinuities, section 5).
- `flow_z(series, window=52, min_periods=26)`: `series / sd.where(sd > 0)`. No mean
  subtraction, no epsilon, no fillna. Tested as the inverse of
  `test_z_score_constant_series_is_zero_and_no_nan`.
- `build_flow_frame(category_frame, report, symbol=None)`: per present category dNet,
  dLong, dShort, Flow Z, Flow Thin (rolling sd below 200 contracts: dims, never blanks);
  plus the counterparty composite from a `FlowRoles` table (data, not branches), keyed by
  (report, symbol) with a per-report default, so the precious-metals grouping does not
  leak into grains (section 2, cohort roles). The per-symbol entries live in a generated
  data module (`flow_roles.py`) with the measurement date, the threshold and the source
  doc recorded beside them, and they come from the roles re-measured on the propadj
  series (`analysis/2026-09-26-cot-cohort-roles-propadj.md`; the Cowork measurement read
  the parquet's `close`, which is the cache close, so HO, RB and OJ had a fifth to a third
  of their history and every physical's correlation was attenuated; LBR's 215 weeks are
  the bar history itself, Norgate's LBR series starting 2022-08-08). Only the 21 markets
  whose counterparty set is stable on rolling 156-week windows (criterion fixed before
  the run: the set equals the full-history set in at least 60% of windows over at least
  8 windows) carry measured roles; the other 21 fall back to the per-report default with
  the source recorded as such. Per-report defaults:
  disagg counterparty = producer_merchant + swap, opinion = (managed_money,
  other_reportable, nonreportable); tff counterparty = dealer, opinion = (leveraged,
  asset_manager, nonreportable), residual = other_reportable. The opinion triple that
  feeds the state is the per-report default everywhere (the branch's test and the
  universe run used it, so the vocabulary keeps its meaning); the measured roles change
  only the counterparty composite and the NEUTRAL set. Each entry carries
  `state_eligible`: True on Disaggregated and on TFF currencies, False on equities, rates
  and crypto (ADR-0005 decision 1), so those markets get z cells and no state. Drift alarm
  test: every category of `categories_for(report)` is in exactly one of counterparty,
  opinion, neutral, inert, residual. Identity test: the sum of dNet over every category
  is exactly zero, and the composite equals the sum of its members.
- Classifier: `flow_signs(z_frame, threshold=FLOW_ACTIVE_Z)` returning {-1, 0, 1, <NA>}
  and `flow_state(...)` returning an object Series with None wherever any input is NA
  (never QUIET in the warm-up), styled on `indicators.fomo_zones` / `net_highs_regime`
  (a published cutoff restated, not a verdict). Not in `models.py` (frozen validated
  (basis, gate, band) bundles with book provenance), not in `signals.py` or
  `conditions.py` (they feed the tape bias), no `SETUP_*` constant. The eight disagg names
  ship as the caption vocabulary; TFF renders the sign tuple until a TFF vocabulary is
  proposed, and Fixed Income gets z cells and no state (ADR-0005: the leveraged against
  asset-manager pair is one basis trade).
- Held out of 0.15.0: dGross, straddle, derisk (fixed 2x / 1x multipliers designed on
  gold, untested anywhere; the swap-dealer reading behind derisk holds in six markets and
  not the other seventeen), any forward return, any state name for TFF.
- Exposure: one concat inside `CotIndexer.get_category_data` after `build_category_frame`
  and before the price merge, attrs re-attached. No new lru_cache key, no signature change,
  no parquet cache involvement (the cache is RAM only). Reconciliation tests that are free:
  disagg counterparty dNet equals the Legacy `COMM_NET.diff()` and nonreportable dNet
  equals `SMALL_NET.diff()`, byte-exact on every market probed.
- Tests: `tests/test_flows.py`, store-free, reusing `test_categories._frame`; the list in
  the judged designs is the spec (identity, min_periods NaN count, zero-sd NaN, gap mask,
  seam mask, roles cover every category once, window fixed regardless of lookback, no
  column collision, warm-up state None). `test_categories.py` must not need editing.
- Version 0.14.4 to 0.15.0; not re-exported from `__init__` (categories is not either).
  cot-analyzer's floor moves only in the PR that imports `cotmetrics.flows`; refresh the
  editable install before `scripts/check_dep_floors.py` or it fails against an unchanged
  tree.

### PR 2, cot-analyzer: one panel on /categories

- `category_traces.CATEGORY_SPECS["flow"]`, appended last, `SECONDARY_NEVER`, plus the
  mandatory `_PANEL_COLUMNS` entry (facet `shared_range` KeyErrors without it) and a
  `_FACET_BUILDERS` entry drawing a one-row heatmap per category cell. `DEFAULT_PLOTS`
  stays `["net_pos", "index"]` until a release has been read on the panel.
- One `go.Heatmap`: x = report Tuesdays, y = selected categories in report order PLUS the
  counterparty composite row always (the reader rule that answers the newsletter failure:
  the other side is never off the page), z clipped for display at +/-3, zmid 0, xgap and
  ygap 1, `hoverongaps=False` so warm-up and masked weeks stay blank, no colorbar (the
  stack's 10px right margin clips one; the panel title states the scale). Hover carries
  the week in words: cohort, report Tuesday with "published Friday", net change in
  contracts, longs and shorts, z against the cohort's own 52-week sd. Thin cells dim (alpha
  in the cell, hover says "read the count, not the z") rather than blank.
- Colour: never an identity palette slot (all six slots mean a cohort or a series);
  polarity from the validated `CATEGORY_DIVERGING_UP` / `DOWN` pair. Prototype rendered
  2026-09-26 (section 7) decides between a grey midpoint composited over the background
  and a dead band that paints |z| < 1 as background; the dead band hard-codes the
  unsearched 1.0 threshold into the picture, so the grey midpoint is the default unless
  the render says otherwise.
- Copy rule, held by a test: never the words "mover", "biggest move" or "unusual" beside a
  flow z, and one sentence distinguishing index-point moves of the Legacy Commercial index
  (the Home board) from contract flows of a cohort scaled by its own history.
- Inherits the stack's x window (156 weeks desktop, 52 mobile), rangeselector, x sharing
  and mobile chrome. The lookback control does not move the flow window; the title says
  so.
- Tests: `test_every_panel_draws_a_trace_per_category` gains a heatmap branch (not
  weakened); the new tests in the judged designs (report order, diverging pair and clip,
  warm-up blank, hover names both legs, counterparty row always drawn, one-row facet cell).
  Extend the test `_frame` with the flow builders so a builder reading a missing column
  fails in CI, not in production.
- Browser checks before merge, with the `cot-analyzer` preview on :5001 (no hot reload):
  the heatmap under hovermode `x unified` beside the Scattergl panels, the one-row facet
  cell at `FACET_ROW_HEIGHT` 120, phone width. The prototype in section 7 answers the first
  two for a standalone figure; the in-stack render still has to be looked at.

### PR 3, cot-analyzer: the state strip, the level markers and the caption

After PR 2 has been seen on a real release. Three pieces.

**The state strip.** In facet mode a three-lane strip under the price row (signs coloured
by the diverging pair, zero as `DIM_TEXT`, NA blank), with the divergence states (mixed
signs, as the gold doc asked, not ALL_BUY or ALL_SELL) boxed line-only and captioned "a
vocabulary label, not a signal".

**The level markers**, from the Cowork mockup (`analysis/2026-09-26-cot-view-proposed-gold.png`
and the level x flow addendum in the handoff): a flow cell needs its level. On gold the
same managed-money buying week was worth about half a percent from mid-range and over
three percent from the top of the range (24 cells, no correction, a twenty-year bull
market: a continuation-direction lean and nothing more). The heatmap gets a marker trace:
a triangle in a cell whose flow is active (|z| > 1) and whose cohort's positioning index
in the PRIOR week, the level the flow departs from, was below `FLOW_LEVEL_LOW` = 20
(down-pointing) or above `FLOW_LEVEL_HIGH` = 80 (up-pointing). The two cutoffs are the
mockup's, recorded as unsearched (its legend says decile, its cells used 20 and 80; the
plan takes 20 and 80). The level is the range index the page already carries,
`categories.index_col(spec, lookback_header)`, at the page's tuned per-symbol lookback
rather than the mockup's fixed 156 weeks, so one page never shows two different levels
for one cohort; the caption names the window. cotmetrics side (0.15.x, additive):
`flows.flow_from_level_col(spec)`, the prior week's range index, emitted by
`build_flow_frame` when the index column is present, so the view shifts nothing itself.
Hover on a marked cell adds "from level 87 of the <n>-week range". Copy rule: the markers
are context for reading a cell, and no caption may say what follows a flow from an
extreme; the level x flow cells were descriptive and continuation-direction on gold
alone, and any claim goes through the same ledger and the same judge as the states did.
The mockup's three-panel layout (price with open interest above, the flow heatmap with
markers, the positioning index lines below) is the facet layout with plots set to flow
and index plus the price row, which PR 2 already gives; nothing new is needed for the
third panel.

**The caption.** A store-free `flow_copy.py` that writes the week in words under the
graph: the report Tuesday and publication date, one sentence per opinion cohort with both
legs, the counterparty always (named per market from the roles table, with its members),
the sum-to-zero line, the level a marked flow departed from, and the rates caveat routed
through the role table rather than a class-name string.

### PR 4, both repos: the cross-asset board

`cotmetrics.reports.get_flow_board(report)` beside `get_matrix_data`, feeding a new
/flows page (an AG Grid first, sortable for free; a rows-by-cohorts figure later), Asset
links to `/categories?asset=`, warmed after divergence, `get_category_data`'s lru_cache
raised to 128 in the same PR. Measured cost of the sweep: 0.7 s cold, 0.07 s warm over 42
markets. It does not fit /heatmap (Legacy-leg grid), /strip (0-100 index axis) or the Home
movers (index-point WoW of the Commercial leg, a different quantity). The universe doc's
board PNG is the picture to match.

### The study: run, failed, closed

The pre-registered test was run by a separate session on 2026-09-26 (branch
`claude/cot-flow-states-cross-universe`, design committed before the run) and failed the
gauntlet on all three pillars. Nothing in cotmetrics or cot-analyzer may carry a forward
return or a verdict word beside a state; the heatmap and the vocabulary ship as a picture
of the primitive, which was their justification from the gold doc onward. If anyone
reopens the question, the branch names the one honest next step (the same state,
commodities only, judged on data after 2026-09-26) and every look already taken is in
the two search logs plus the branch's 63-entry log. Generator and evaluator stay in
separate sessions.

## 4. Decisions the human owns

1. Whether the eight state names ship in cotmetrics 0.15.0 as caption vocabulary, or only
   the sign tuple. Recommendation: names, disagg only, documented as vocabulary.
2. The TFF counterparty row: dealer alone (the universe run's mapping, and what the FX
   correlations support) or the identity complement (everyone who is not an opinion
   cohort). Recommendation: dealer, with the ADR-0005 drift written up beside the ADR.
3. Straddle and derisk: hold out of 0.15.0 (recommended) or ship as flagged, untested
   labels.
4. The seam fix: a cotdata stitch rule (primary wins an overlap only inside a continuous
   run; LBR collapses to one seam) versus a cotmetrics-side mask on the Quotes column.
   Recommendation: both, cotdata first, recorded in `docs/design/amendments-cotdata.md`.
5. Whether "uninformative" joins the three strength words in npf/AGENTS.md #9;
   `crowdmon/DEPRECATED.md` already uses it and this plan does too.
6. Whether `FlowRoles` is keyed per symbol from the measured table (recommended: the
   collapse CSV committed as data with threshold and measurement date beside it, NEUTRAL
   kept as its own row and excluded from state classification) or stays per report with
   the precious-metals grouping applied everywhere. A rolling-window stability check on
   the assignments is the prerequisite for the per-symbol option. Done 2026-09-26
   (`analysis/2026-09-26-cot-cohort-roles-propadj.md`): 21 of 42 pass, and PR 1 ships
   measured roles for exactly those. Two things remain the human's: (a) the nine physicals
   that fail (CC, CL, GF, HE, HO, NG, RB, SB, ZW) fall back to Producer/Merchant plus
   Swap Dealers, although the windows say Producer/Merchant alone is the stable
   counterparty on all of them and the swap dealers sit on the 0.15 line; "Producer/Merchant
   alone as the Disaggregated fallback" was not pre-stated and is one CSV edit plus a
   regeneration if chosen; (b) GC passes at exactly 0.60 and LBR on nine windows spanning
   four years, so either could reasonably be moved to the default.
7. Repository hygiene for the untracked artefacts: commit the two analysis docs, the JSONs,
   the search logs, the scripts and the PNGs; do not commit the 4.2 MB universe parquet
   (regenerable in 5 s from the command in the doc; add it to `.gitignore`). The branch
   `claude/cot-flow-states-cross-universe` already commits the gold doc, the gold script,
   an older copy of `cot_flow_states_universe.py` and its own copy of the handoff; merging
   it into main will collide with the untracked copies of those four files in the main
   checkout (the handoff copies differ in substance: addenda here, an Outcome there).
   Resolve by hand before either side is committed further.

## 5. Discontinuities the primitive must refuse

| market | weeks | mechanism | detection today |
|---|---|---|---|
| LBR | 2023-02-21, 02-28, 03-14 | new code 058644 lacks two weeks; `get_cot` keeps the primary where present and the x4-scaled predecessor elsewhere, so the population alternates | `CFTC_Contract_Market_Code_Quotes` changes; OI toggles 7,876 / 1,029 / 9,088 |
| RTY | 2008-09-09 to 09-23 | venue migration CME to ICE, both codes carrying positions; not a seam any differencing cleans | explicit date window |
| RTY | 2017-08-15 | code switch back to CME 239742 after a 3,255-day hole | Quotes column |
| ZO | ten holes over 8 days, max 294 | thin market, missing report weeks | index gap |
| 6N | 2006-07-11 | one 28-day hole at the start | index gap |

To be completed against `marketdata.read_contract_regimes` (multiplier changes) before
PR 1 merges; the LBR x4 scale also corrupts trader counts and pct_oi on predecessor rows
for the existing /categories page today.

## 6. Open hazards, none blocking PR 1

- Point in time: vintages exist only from 2026-07-31 and the frozen-2025 tripwire has
  been blind since 2026-08-01, so a CFTC reclassification restating cohort levels would
  print one spurious flow the current-state store cannot flag. A cotdata item to schedule
  before the next annual reclassification window; add a store-backed test in flows that
  compares the last 8 weeks against the newest vintage observation.
- Concurrent return: corr(z of managed money, same-week return) is +0.55 on gold. Before
  any pre-registration, tabulate VALUE_ACCUM's after-release excess within terciles of the
  concurrent weekly return from the universe parquet (one logged look).
- Basis: emit `dPct` and `z_dPct` from `pct_oi_col` as well, same function on two columns,
  following the page's two-panel convention; the 14.8% label disagreement goes in the help
  fold.
- Multiplicity: the unit of a variant is one (state, horizon, pool, basis, anchor) cell
  tabulated. The two search logs count looks by market and by cut; before a gauntlet,
  backfill a ledger at cell granularity.
- Small OI: LBR and OJ cohorts have 52-week sd under 200 contracts today; the thin flag
  dims them and the board should sort them last.

## 7. Render check, 2026-09-26

A throwaway Plotly page (`.local-state/flow-proto/proto_flow_panel.html` at the workspace
root, served by the `flow-proto` entry in the workspace `.claude/launch.json`; not
committed, no figure quoted from it) drew GC's last 156 weeks as a price line over a
four-row heatmap with the analyzer's dark template and colours, in three configurations:
grey-midpoint scale under hovermode `x unified`, dead-band scale under `x unified`,
grey-midpoint under `closest`, plus a one-row cell at a 120 px plot area. Looked at in
the desktop pane (about 800 px wide) and at the 375 px phone preset.

- **A heatmap works inside `x unified`.** Hovering a cell gives the date header, a colour
  swatch, the cohort name and the template lines; only the hovered row is listed, not all
  four, which is fine. No layout-level change is needed, so the panel can live in the
  /categories stack as a `CATEGORY_SPECS` entry (PR 2 as written). Under `closest` the
  box loses the date header and nothing else.
- **Grey midpoint over the dead band.** With |z| < 1 painted as background the panel
  loses its texture: a run of mild same-sign weeks (the multi-week signature the gold doc
  reads off the heatmap) becomes a few isolated sticks. The grey-composited midpoint
  (`DIM_TEXT` over the background) keeps the runs visible and still lets the 2 to 3 sigma
  cells stand out. Decision: grey midpoint, `zmid` 0, clip +/-3.
- **Phone width needs the 52-week window and no cell gap.** At 375 px with 156 columns
  and `xgap` 1 the cells are two pixels wide and half of each is gap; the panel reads as
  hairlines. The stack already opens phones on 52 weeks (`visible_weeks`), which gives
  about 6 px per cell; set `xgap` to 0 below tablet width and shorten the row labels
  ("Commercials" rather than "Commercials (Prod+Swap)") so the label gutter does not take
  a third of the width.
- **The one-row facet cell reads fine at 120 px.** No change to `FACET_ROW_HEIGHT`.
- **Format the z in the hover from customdata.** The heatmap's `%{z:+.2f}` printed the
  raw float under unified hover in this build (plotly 6.9); carry a pre-rounded z in
  `customdata` beside the contract counts rather than relying on the z format.
- Desktop cell width at 156 weeks in an 800 px pane is about 4 px, which reads; the
  analyzer's wider desktop layout will give more.

## 8. What not to do

- Do not sell the state table as a signal, on any surface, in any caption.
- Do not compute the flow in cot-analyzer to get a panel up quickly.
- Do not route the primitive through `calculate_momentum_index`, `calculate_z_score` or
  `movers.py`.
- Do not let the page lookback reach the flow window.
- Do not put the classifier in `models.py`.
- Do not quote a return off the `data_cache` close for any market but gold, and not for
  gold either once the propadj figures exist.
- Do not amend the gold analysis doc; write forward and link back.
