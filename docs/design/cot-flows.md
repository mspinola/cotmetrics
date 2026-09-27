# COT flows: from the gold study to a cotmetrics primitive and a cot-analyzer view

**Living document.** Plan and decision record for the week-over-week cohort flow work
that started in
[`analysis/2026-09-26-cot-flow-states-gold.md`](../analysis/2026-09-26-cot-flow-states-gold.md).
Amend this file as decisions land; the analysis docs are never amended.

**Where it ended (2026-09-27).** One strip on the existing Positioning Index panel of
/analysis: the Legacy **Commercial** leg's net change each week over its own 52-week
standard deviation of weekly changes, blue buying and red selling, with that week's
flow in the Commercial line's hover and a one-line note where the market needs one
(equity setups read Commercials only; how retail behaves). Built as cotmetrics #52, #53
and the cleanup PR, and cot-analyzer #142 and #144 (section 3).

It got there in three steps. v1 and the plan before it designed per-cohort displays
(heatmap rows, a counterparty row, state names, level markers, a caption, a three-panel
Flow view, a cross-asset board); each was built or specified, looked at on the running
page and withdrawn. "Scope, restated v2" (top of
`docs/handoffs/2026-09-26-cot-flow-states-cross-universe.md`) cut the display to one
speculator series per market, and that shipped (#142). On review the same night the
Speculator line went too: its weekly flow tracks Legacy Non-Commercial at 0.81 to 0.96
on physicals and major currencies, so it repeated a line already drawn, and where it
differed (equity index, Treasuries) the gap described composition, which a sentence says
better. The strip moved to the Commercial leg because every setup in the app is triggered
by the Commercial index at an extreme, and on equities it is the only leg the gate
reads. Section 3 keeps the record; full specs are in this file's git history. Section
2's measurements stand unchanged.

## 1. What exists

| artefact | what it is | status |
|---|---|---|
| `analysis/2026-09-26-cot-flow-states-gold.md` + `scripts/analysis/cot_flow_states.py` | the primitive (dNet / own 52-week sd per cohort), the eight-state vocabulary, the gold read | point in time; the script is still being iterated in a parallel Cowork session (a price-over-heatmap figure and a level x flow addendum landed the same day) |
| `analysis/2026-09-26-cot-flow-states-universe.md` + `scripts/analysis/cot_flow_states_universe.py` | the gold design unchanged on the 42 non-heldout markets, two price bases, HAC t, Friday diagnostic, per-class heatmaps and a cross-asset board PNG | point in time, reproduces bit for bit, 44-entry search log |
| section "The handoff's scope" of the universe doc + `scripts/analysis/cot_flow_states_scope.py` | the same parquet cut to ADR-0005's universe with and without gold, and re-anchored at the first settlement after the resolved release date | point in time, 9-entry search log |
| `scripts/analysis/critique_2026-09-26/` | the reproducers behind the methodology corrections in section 2 (overlap inflation, block bootstrap, Tuesday-to-Friday leg, run lengths, seams, normalisers, basis disagreement), each with its printed output beside it | committed so the figures below can be quoted |
| `analysis/2026-09-26-cot-cohort-roles.md` + `scripts/analysis/cot_cohort_roles.py` + two CSVs | per-(report, symbol) cohort roles from the data: SPEC / COUNTERPARTY / NEUTRAL / inert / RETAIL by same-week price correlation of dNet and gross share, threshold 0.15 fixed in advance; the Prod/Swap same-sign measurement that motivated it | point in time, Cowork session, sandbox paths in the script; measured on the cache close (see the next row); stability over time not measured there |
| `analysis/2026-09-26-cot-cohort-roles-propadj.md` + `scripts/analysis/cot_cohort_roles_propadj.py` + three CSVs (roles, collapse, stability) | the same rule on the ratio-adjusted series, the changes against the cache-close table, and a rolling 156-week stability check with a criterion fixed before the run | point in time; the source of `src/cotmetrics/flow_roles.py` (cotmetrics #52) via `scripts/analysis/gen_flow_roles.py` |
| `analysis/2026-09-26-cot-roles-vs-legacy.csv` + `scripts/analysis/cot_roles_vs_legacy.py`, and the `-propadj` pair | weekly-flow correlation of the measured SPEC and COUNTERPARTY groups with Legacy Non-Commercial and Commercial | Cowork (cache roles) and this session (propadj roles); see the Legacy bullet in section 2 |
| `analysis/2026-09-26-cot-one-role-view.png` + `scripts/analysis/cot_one_role_view.py` | the v2 sketch: per market, price with open interest, the speculator net's index with a thin retail line, and one speculator flow-z strip, on GC, ZC, 6E and ES | Cowork session, sandbox paths in the script; draws from the cache-close collapse table and a fixed 3-year index, where the built view uses the propadj table and the page lookback (section 3; decision 2, section 4) |
| `docs/handoffs/2026-09-26-cot-flow-states-cross-universe.md` | the Cowork session's handoff asking for the cross-universe run, with a level x flow addendum and a proposed three-panel view | executed twice on 2026-09-26: descriptively in the main checkout (status update at its end) and as the pre-registered crucible test on the branch below; the branch carries its own copy of this file with an Outcome section, so the two copies must be merged by hand |
| branch `claude/cot-flow-states-cross-universe` (local, unpushed, two commits 12:18 and 12:22): `analysis/2026-09-26-cot-flow-states-cross-universe.md` + `scripts/analysis/cot_flow_states_cross_universe.py` | the pre-registered evaluator pass: VALUE_ACCUM long, 13 weeks, 32-market ADR-0005 scope, non-overlapping vol-normalised drift-removed trades in a crucible TradeLog, holdout at 2019-01-01 with an 8-week embargo, run_gauntlet with a 63-entry log seeded from the descriptive pass | done by a third session; design committed before the run; verdict FAIL 0 of 3 gates, TEST +0.124R on 85 trades with the interval spanning zero |

## Vocabulary

- **Flow.** A cohort's week-over-week change in net futures position, dNet = (long minus
  short).diff(), in contracts. **Flow z** is that change divided by the cohort's own
  trailing 52-week standard deviation of weekly changes, no mean subtracted.
  What ships is the flow z of the Legacy Commercial leg.
- **Speculator.** The cohort, or set of cohorts, whose weekly buying moves WITH the
  week's price (same-week correlation of dNet with the return above 0.15, gross share over
  5%), measured per market on the ratio-adjusted series: Managed Money on 21 of the 23
  Disaggregated markets (Swap Dealers plus Managed Money on HE, Managed Money plus Other
  Reportable on LBR); Asset Manager alone on 10 TFF markets, Asset Manager plus Leveraged
  Funds on 6 (the major currencies), Leveraged Funds on 6M, Dealer plus Asset Manager on
  ETH; none on ZT. The one series the display draws. Source:
  `analysis/2026-09-26-cot-cohort-collapse-propadj.csv`, committed as
  `cotmetrics.flow_roles`. A measurement, drawn nowhere since 2026-09-27 (section 3).
- **Opinion cohorts.** (Withdrawn with the state display.) The three whose flow signs made
  the state: Managed Money, Other Reportable and Non-Reportable on Disaggregated;
  Leveraged Funds, Asset Manager and Non-Reportable on TFF.
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
  index and crypto (their hedge and basis book). Recorded in `flow_roles` and drawn
  nowhere since v2: the counterparty's net is the speculator's mirror plus the neutral
  residual, so a counterparty series repeats the speculator series. Contemporaneous by
  construction:
  "absorbs" says who was on the other side this week, not what happens next.
- **Neutral.** A cohort with a meaningful share of gross open interest whose flow does not
  correlate with price either way (the swap dealers' index book in grains). Kept as its
  own row, never folded into either side.
- **Inert.** Under 5% of gross open interest; its flow is drawn but it plays no role.
- **Retail.** Non-Reportable, by label. On the propadj measurement its flow moves with
  price on 26 of 42 markets, is neutral on 12 and moves against price on 4, so the label
  is a category, not a behaviour; the display names the behaviour per market. On
  /analysis it is the Legacy Non-Reportable line already drawn, the same data, and the
  panel's note names its behaviour.
- **State.** The sign triple of the opinion cohorts at |z| > 1, named on Disaggregated
  with the gold vocabulary. Its pre-registered test failed; since v2 it appears on no
  surface and cotmetrics no longer computes it.

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
  same week). The flow strip (the heatmap before v2) will look like it predicts the price
  it is drawn against. Whether a
  state adds anything beyond the concurrent weekly return has not been tested on any
  market (open, section 6).

## 3. What is built

### cotmetrics: the flow primitive, the roles table, the Commercial leg's flow

Merged as #52 (0.15.0), #53 (0.15.1) and the cleanup PR; untagged, so not on PyPI. Nothing
in `signals`, `conditions`, `models`, `movers` or `synthesis` reads any of it.

- **`cotmetrics.flows`**: `weekly_change` (dNet, NaN across an index gap over 8 days and
  across a change in the per-row `_Quotes` contract code; section 5), `flow_z` (dNet over
  its own rolling 52-week sd, min 26, no mean subtracted, NaN rather than 0 under
  min_periods and on a zero sd; not `indicators.calculate_z_score`, which mean-subtracts
  and fills 0), and `leg_flow_frame`, which puts "<leg> dNet" and "<leg> Flow Z 52w" on a
  net series. The window is fixed and rides in the column name; the page lookback never
  reaches it.
- **`CotIndexer.get_commercial_flow_data(name)`**: the Legacy Commercial leg's frame,
  indexed by Date, with `is_equity` and the market's roles entry in attrs. The Legacy
  report carries no per-row `_Quotes` code, so the seam mask takes it from the market's
  Disaggregated or TFF frame (same report weeks from 2006; every known seam, RTY 2008 and
  2017 and LBR 2023, is later), back-filled so pre-2006 rows read as one population;
  verified on the live store that LBR's three 2023 seam rows come out blank.
  `build_category_frame` carries that code as `Source Code`.
- **`cotmetrics.flow_roles`**, generated by `scripts/analysis/gen_flow_roles.py` from
  `analysis/2026-09-26-cot-cohort-collapse-propadj.csv` (threshold 0.15, gross-share
  floor 0.05, measured 2026-09-26): a frozen `FlowRoles` per (report, symbol) with a
  per-report default; `--check` fails if the committed module differs from a
  regeneration. Read today only for how retail behaves on a market; the speculator,
  counterparty, neutral and inert sets are the measurement, kept as data.
- Removed by the cleanup PR, never released: `speculator_net`, `retail_net`,
  `speculator_frame` and `CotIndexer.get_speculator_data` (#52's v2 resolvers, which lost
  their only caller in #144).

### cot-analyzer: the Positioning Index panel on /analysis

Merged as #142 (the speculator version) and #144 (the Commercial strip that replaced it).
On the raw-basis panel of the single-market stack:

- **One strip** inside the panel, below its zero (the index axis widens to -17, ticks stay
  on 0 to 100 plus a "flow z" tick at the strip): the Commercial leg's weekly flow z, a
  true diverging scale with zero barely lifted off the panel background, one sd a muted
  blue or red and three sd saturated, clipped at 3, opacity 1. Its hover gives the z and
  the net contracts.
- **The Commercial line's hover** carries the same week's flow beside its index
  ("Commercial : 96 · flow z +0.94 (net +13,537 contracts)"), because under hovermode
  "x unified" a heatmap cell reports only when the cursor is on the strip.
- **A one-line note** only where the market needs one: "Equities: setups read Commercial
  only", and how retail (Non-Reportable) behaves there, from `flow_roles`.
- The page asks cotmetrics for the frame only when a raw index panel is drawn; the % of
  OI and Raw vs %OI variants and the market grid view are unchanged. The clientside
  autoscale leaves any axis carrying a heatmap alone, so the index panel keeps 0 to 100
  on zoom.

### Why the Commercial leg, and not the speculator the v2 block named

- The speculator line repeated Legacy Non-Commercial on about 30 of 42 markets (weekly
  flow correlation 0.81 to 0.96, `analysis/2026-09-26-cot-roles-vs-legacy-propadj.csv`).
- Where it differed (equity index, Treasuries, BTC, DX: -0.41 to +0.30) the gap said
  that Non-Commercial there is largely Leveraged Funds' hedge and basis book, which is
  composition, and ADR-0005 (Proposed) argues no group carries a directional read in index
  futures or Treasuries.
- The Commercial index is the trigger of every setup in the app, and on equities the only
  leg the gate reads, so a Commercial strip shows the move behind the leg the setups are
  judged on, one rule on every market.
- The three Legacy nets sum to zero, so on commodities the Commercial flow is roughly the
  Non-Commercial flow reversed; the choice mostly flips blue and red there and matters on
  equities.

### Withdrawn on review, 2026-09-26 and 27 (record)

Each was built or specified, looked at on the running page, and withdrawn by the user.
Full specs, render findings and review fixes are in this file's history on the #51 branch.

- **Per-cohort flow columns on /categories and the Weekly Flow heatmap panel** (first
  cut of #52 and cot-analyzer #140): one heatmap row per category plus a counterparty
  composite row, a grey-midpoint diverging scale. The composite repeated a category row
  on every one-member market (DOW's Dealer row twice), and a muted scale with no anchor
  at zero hid the moves the panel existed for.
- **State strip, level markers, week-in-words caption** (cot-analyzer #141, closed): the
  eight state names on screen, triangles at 20/80 of the prior week's index, sentences per
  cohort. On review the scope was cut back to the panel alone; a caption that counted a
  cohort on both sides (Other Reportable on SI, HG, OJ) was among the review findings.
- **The three-panel Flow view** (#140 rebuilt): price, a collapsed-row heatmap (one
  Commercials row on GC, SI, PL, PA) with the mockup's decile markers, the rows' index
  lines. Withdrawn by v2: the rows collapsed nothing, and four index lines read as random.
- **The cross-asset board** (never built).
- **The Speculator line and its strip** (cot-analyzer #142, replaced by #144 the same
  night; #143, its hover follow-up, closed): the v2 display. Withdrawn for the reasons
  above.

### The study: run, failed, closed

The pre-registered test was run by a separate session on 2026-09-26 (branch
`claude/cot-flow-states-cross-universe`, design committed before the run) and failed the
gauntlet on all three pillars. Nothing in cotmetrics or cot-analyzer may carry a forward
return or a verdict word; the speculator line and its flow strip are a picture of
the data, which was the justification for the display from the gold doc onward. If anyone
reopens the question, the branch names the one honest next step (the same state,
commodities only, judged on data after 2026-09-26) and every look already taken is in
the two search logs plus the branch's 63-entry log. Generator and evaluator stay in
separate sessions.

## 4. Decisions the human owns

Taken:

1. **One strip on the existing panel**: the Legacy Commercial leg's weekly flow z on the
   /analysis Positioning Index panel, no fourth line (2026-09-27, replacing v2's
   speculator series of 2026-09-26). This closes the earlier questions about the eight
   state names (they appear nowhere), the TFF counterparty row, straddle and derisk (none
   shipped), and the Legacy back-fill of a speculator series (there is no such series).
2. **The panel is the /analysis one**, the Legacy page's Positioning Index, rather than
   the /categories index panel (2026-09-26).
3. **The roles table is the propadj measurement**, keyed per (report, symbol), generated,
   never typed (2026-09-26); the cache-close table named in v2 truncated HO, RB and OJ and
   attenuated every physical's correlation.
4. **Treasuries stay out of the COT-gated books.** Asked whether NPF should read
   Commercials only on Treasuries, as it does on equities: no. The deployed NPF book
   already drops Fixed Income (+1.81R in sample, -1.94R out of sample, dropping it raised
   the out-of-sample floor from +0.29 to +0.47; `npf/config/npf/cmr_cs_oinorm_liquid.yaml`),
   and a Commercials-only Treasury gate would be a fresh, un-registered variant on a class
   that failed once.

Open:

5. **The seam fix upstream**: a cotdata stitch rule (primary wins an overlap only inside
   a continuous run; LBR collapses to one seam), and carrying the `_Quotes` code in the
   Legacy report so the Commercial flow need not borrow it. Recommendation: both, cotdata
   first, recorded in `docs/design/amendments-cotdata.md`.
6. **"Uninformative"** as a fourth strength word in npf/AGENTS.md #9;
   `crowdmon/DEPRECATED.md` already uses it and this plan does too.
7. **A speculator-level test**, if ever wanted: whether a speculator-index condition adds
   to the frozen NPF CS book out of sample, pre-registered, physicals and currencies only,
   2006 on, judged in a separate session. Expected: a marginal lean at best, since the
   three Legacy nets sum to zero and the speculator tracks Non-Commercial on those
   markets.

## 5. Discontinuities the primitive must refuse

| market | weeks | mechanism | detection today |
|---|---|---|---|
| LBR | 2023-02-21, 02-28, 03-14 | new code 058644 lacks two weeks; `get_cot` keeps the primary where present and the x4-scaled predecessor elsewhere, so the population alternates | `CFTC_Contract_Market_Code_Quotes` changes; OI toggles 7,876 / 1,029 / 9,088 |
| RTY | 2008-09-23 | venue migration CME to ICE; measured, the whole cross-population jump lands on the one row where the code switches (dealer net 129,063 on 09-09 and 113,046 on 09-16 under 239742, 184,169 on 09-23 under 23977A; the 09-09 and 09-16 diffs are ordinary weeks at z -0.70 and -0.81) | Quotes column; no date window needed |
| RTY | 2017-08-15 | code switch back to CME 239742 after a 3,255-day hole | Quotes column |
| ZO | ten holes over 8 days, max 294 | thin market, missing report weeks | index gap |
| 6N | 2006-07-11 | one 28-day hole at the start | index gap |

To be completed against `marketdata.read_contract_regimes` (multiplier changes); the LBR
x4 scale also corrupts trader counts and pct_oi on predecessor rows for the existing
/categories page today. Verified on the first PR 1 build (2026-09-26, per-cohort z through the same
`weekly_change` the speculator z now uses): the seam mask fires on
exactly LBR 2023-02-21, 02-28, 03-14 and RTY 2008-09-23, 2017-08-15, the gap mask on
exactly 6N 2006-07-11, and nowhere else across the 42 markets; parity of the flow z
against the universe parquet is exact (max difference 0.0) on the other 40 markets, and
on those three it differs only on the masked rows and the 52 rows after each.

## 6. Open hazards, none blocking the build

- Point in time: vintages exist only from 2026-07-31 and the frozen-2025 tripwire has
  been blind since 2026-08-01, so a CFTC reclassification restating cohort levels would
  print one spurious flow the current-state store cannot flag. A cotdata item to schedule
  before the next annual reclassification window; add a store-backed test in flows that
  compares the last 8 weeks against the newest vintage observation.
- Concurrent return: corr(z of managed money, same-week return) is +0.55 on gold. Before
  any pre-registration, tabulate VALUE_ACCUM's after-release excess within terciles of the
  concurrent weekly return from the universe parquet (one logged look).
- Basis: the Commercial flow is contracts-basis and is drawn on the raw index panel
  only; a % of OI version (the same function on the normalised net) would be needed
  before it can sit on the OI-normalised panel.
- Multiplicity: the unit of a variant is one (state, horizon, pool, basis, anchor) cell
  tabulated. The two search logs count looks by market and by cut; before a gauntlet,
  backfill a ledger at cell granularity.
- Small OI: LBR's and OJ's cohorts have a 52-week sd of weekly changes under 200
  contracts, so a z there is large on small counts. The v1 thin flag was withdrawn with
  the heatmap; the strip's hover and the Commercial line's hover print the contracts
  beside the z.

## 7. Render checks, 2026-09-26

**The Commercial strip (2026-09-27).** Looked at on /analysis on Gold (hover "Commercial :
96 · flow z +0.94 (net +13,537 contracts)"; note "retail (Non-Reportable) moves with
price here") and S&P 500 (note "Equities: setups read Commercial only, retail
(Non-Reportable) does not move with price here").

**v2, the speculator panel (record).** Looked at on /analysis (desktop pane, single-market stack) on
Gold, Corn and Euro. The Speculator line reads against the three Legacy lines; on Gold it
tracks Non-Commercial closely, as the Legacy correlation for Managed Money predicts. The
strip reads as runs of blue and red with near-zero weeks close to the background. Two
fixes came from looking: the first panel note ran off the panel and sat over the lines,
so it was shortened to one clause each for the speculator and retail and the strip was
named by a "flow z" tick at its own height; and the zoom autoscale cut the strip off,
fixed by leaving heatmap axes alone.

**v1, the withdrawn heatmap (record).** A throwaway Plotly page (`.local-state/flow-proto/proto_flow_panel.html` at the workspace
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

- Do not sell the flow strip, or any state, as a signal, on any surface, in any caption.
- Do not compute the flow or the roles in cot-analyzer; it reads
  `CotIndexer.get_commercial_flow_data`.
- Do not route the primitive through `calculate_momentum_index`, `calculate_z_score` or
  `movers.py`.
- Do not let the page lookback reach the flow window.
- Do not type a role into `flow_roles.py` by hand; re-measure and regenerate.
- Do not add a Retail line on /analysis: the Legacy Non-Reportable line is the same data.
- Do not bring back a multi-row heatmap, a counterparty row or a Speculator line without
  a new review: each was built and withdrawn (section 3).
- Do not quote a return off the `data_cache` close for any market.
- Do not amend the gold analysis doc; write forward and link back.
