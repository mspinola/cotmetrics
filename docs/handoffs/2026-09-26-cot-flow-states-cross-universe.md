# Handoff: cross-universe run of the COT flow-state study

## Scope, restated v2 (2026-09-26, evening; SUPERSEDES the v1 block and the PR 2-4 plan)

The user reviewed the four-row heatmap panel and rejected it: it drew every cohort the
collapse table named, so it collapsed nothing, and four positioning-index lines read as
random. Decision: scrap the multi-row heatmap, the multi-line index panel and the eight
state names. Keep the measurements and reduce the display to ONE role series per market.

### The view (sketch: `docs/analysis/2026-09-26-cot-one-role-view.png`, reproducer `scripts/analysis/cot_one_role_view.py`)

Identical on every market and every report type:

1. Price with open interest (existing panel).
2. Positioning index of the **speculator net** (the SPEC group from
   `2026-09-26-cot-cohort-collapse.csv`: MM on most physicals, AssetMgr+LevFund in FX,
   AssetMgr on ES/RTY), on `CotIndexer`'s per-symbol lookback, 20/80 bands. One thin
   secondary line for **retail net** (Non-Reportable), labelled with how it behaves on
   that market (spec-like / neutral / cp-like from the same CSV).
3. One strip: the speculator net's weekly flow z (dNet / own rolling 52w sd, min 26),
   diverging scale centred at zero, clipped at +-3.

Why one series: by the sum-to-zero identity the counterparty net is the mirror of the
speculator net plus the neutral residual, so a counterparty row repeats the speculator
row; NEUTRAL cohorts do not respond to price by construction of the role rule, so they
are noise on a chart about price. Markets with no separable roles (CL, ZF, ZT) get the
panel with the label "no speculator role on this market" and Legacy Non-Commercial as
the fallback series, dimmed.

### What the port is now

- **cotmetrics** (additive): `speculator_net(symbol)` and `retail_net(symbol)` resolvers
  driven by a committed `FlowRoles` table keyed by (report, symbol) with per-report
  defaults, generated from the collapse CSV with threshold 0.15 and the measurement date
  beside it; `flow_z(series)` for the strip. Legacy back-fill of the speculator series
  before 2006 only where `2026-09-26-cot-roles-vs-legacy.csv` clears ~0.85.
- **cot-analyzer**: the existing Positioning Index panel gains a "Speculator" series
  from the resolver (and "Retail"), and one flow-z strip is added under it. No new
  panel type, no heatmap grid, no state strip, no cross-asset board.

### Closed

Signal work (VALUE_ACCUM gauntlet FAIL 0/3, single-cohort null on 42 markets): closed.
PR 2, 3, 4 of `docs/design/cot-flows.md` as written: withdrawn. The critique folder,
render prototype and crucible branch need no further work; merge the branch's copy of
this file by hand and commit the Cowork files separately.

Order of work: FlowRoles table + resolvers + flow_z in cotmetrics, then the two
additions to the existing panel, then stop and show one market from each report type.

### Status of v2 (2026-09-26, Claude Code session)

Built as cotmetrics #52 (`FlowRoles`, `speculator_net`, `retail_net`, `flow_z`,
`CotIndexer.get_speculator_data`) and cot-analyzer #142 (the Speculator series and one
flow-z strip on the /analysis Positioning Index panel); cot-analyzer #140 and #141,
built to v1 and the earlier plan, are closed. Departures from the block, each the
user's call or forced by the data, are recorded in `docs/design/cot-flows.md` section 3:
the propadj roles table rather than `2026-09-26-cot-cohort-collapse.csv` (on it only ZT
has no speculator role; CL and ZF do), retail as a label rather than a line (Legacy
Non-Reportable on that panel is the same data), no 20/80 bands, and the Legacy back-fill
before 2006 not yet built.

---

## Scope, restated v1 (2026-09-26, end of day; SUPERSEDED by v2 above)

Kept as the record. v1 was written over by v2 in the main checkout's copy of this file;
the text below was recovered verbatim from the session that read it before the rewrite.

The user's request was three things. Everything below this block exists to serve them and
nothing else.

1. **Show week-over-week COT context instead of one static bar chart.** ANSWERED. The
   deliverable is the three-panel view in `docs/analysis/2026-09-26-cot-view-proposed-gold.png`:
   price with open interest on top; the cohort flow heatmap in the middle (each cohort's
   weekly net change divided by its own 52-week standard deviation, blue buying, red
   selling, with a marker on the cell when that cohort's positioning index is in the bottom
   or top decile); the positioning index below. Shared x-axis, 52 to 104 weeks.
2. **Is a cross-cohort truth table a signal?** CLOSED, genuine null. Single-cohort moves
   predict nothing at 4 or 13 weeks on 42 markets; the eight named states cover about 5% of
   weeks; the one lean (VALUE_ACCUM) failed the crucible gauntlet 0 of 3 on the branch
   `claude/cot-flow-states-cross-universe`. The state names survive only as the hover
   caption on a heatmap cell. No further signal work.
3. **Port to cot-analyzer.** OPEN, and it is the only open item. What ships is item 1.

Inputs the port needs, all measured, all in `docs/analysis/`:

- **Rows per market** come from `2026-09-26-cot-cohort-collapse.csv`, not from category
  names. "Commercials" as one row (Prod + Swap) is right on GC, SI, PL, PA only; elsewhere
  Producer/Merchant and Swap Dealer are separate rows, and Swap is NEUTRAL (the index
  book) on grains and softs. On TFF the counterparty is Dealer in FX and Leveraged Funds
  on ES/RTY/BTC. CL, ZF, ZT have no separable roles; draw all cohorts, no composite.
- **Level** comes from `CotIndexer`'s existing per-symbol tuned lookback, not the fixed
  156 weeks the prototype used.
- **History depth**: Legacy (from 1986) may back-fill a row only where
  `2026-09-26-cot-roles-vs-legacy.csv` clears ~0.85 (physicals ex-energy, major FX).
  Elsewhere the rows start where Disaggregated/TFF starts (2006).
- **Primitive** (cotmetrics, additive): per category dNet and z = dNet / rolling 52w sd
  (min 26), `FlowRoles` keyed by (report, symbol) with a per-report default. That is
  `docs/design/cot-flows.md` PR 1 as amended; PR 2 is the panel. PRs 3 and 4 (state strip,
  cross-asset board) are not in scope. The critique folder, the render prototype and the
  crucible branch are done and need no further work; merge the branch's copy of this file
  by hand and commit the Cowork files separately.

Order of work for the Claude Code session: PR 1, then PR 2, then stop and show the panel.

---

Status: DONE 2026-09-26. Executed twice the same day: the pre-registered crucible test
(Outcome below, merged as PR #50) and a descriptive 42-market run (Status update below).
Written 2026-09-26 in a Cowork session without the npf venv; executed in Claude Code from
`npf/.venv`. This copy merges the two divergent copies of the file (the branch's Outcome and
the main checkout's addenda) on 2026-09-26.

## What exists

- Reproducer: `cotmetrics/scripts/analysis/cot_flow_states.py` (untracked). Reads the
  disaggregated parquet directly, one symbol (GC), emits a per-week frame of `dNet`, `dGross`,
  `z_dNet` per cohort, the 3-cohort state label, two flags, and four figures.
- Findings: `cotmetrics/docs/analysis/2026-09-26-cot-flow-states-gold.md`. Single-cohort
  weekly moves: genuine null at 13w. Eight named states cover 55 of 1,059 weeks. VALUE_ACCUM
  (MM sell, Other buy, NonRep sell) n=21, 13w mean +2.20% vs +1.24%, t=1.92: marginal lean,
  eight states tabulated, no search run.

## The question

Does the VALUE_ACCUM lean, or any state, survive on markets other than gold with the SAME
fixed configuration (52w std, 26w min, |z| > 1.0, horizons 4 and 13)? Gold gives n=21; the
pooled universe gives on the order of a thousand state-weeks. If the lean is gold-only it was
a gold artifact and the study closes as a genuine null with a bigger denominator.

## Scope, per ADR-0005

`npf/docs/adr/ADR-0005-cot-group-semantics-by-market.md`: COT-gated readings apply to
physical commodities and currencies; index futures and Treasuries have no interpretable
commercial/speculative split. So:

1. Primary run: the physical-commodity and currency members of `cotmetrics-config/params.yaml`
   (Disaggregated cohorts for commodities; for currencies use the TFF-or-Legacy mapping the
   ADR names, not the Disaggregated names). Pool per asset class and overall.
2. Equities and rates: NOT part of the pooled test. If run at all, run separately as a
   descriptive heatmap only, with quarterly expiry weeks masked (ES median OI change in expiry
   weeks 17.7%; Leveraged Funds |z| > 1 in 48% of expiry weeks vs 24% otherwise).

## Rules that bind

- One configuration, fixed before the run. Any variant (threshold, window, horizon, expiry
  treatment, class pooling choice) goes into a `crucible.validation.SearchSpaceLog` and its
  count feeds the denominator. The "Variants not tried" list in the gold doc is the menu.
- Forward returns via `holdout` / `walk_forward` if anything is to be claimed, not the naive
  fwd4/fwd13 columns the reproducer attaches (those are for description only).
- Prices from `MARKETDATA_STORE` (`get_bars`), not from `cot-analyzer/data_cache`.
- Output is a new dated file under `cotmetrics/docs/analysis/`; the gold doc is not amended.
- Plain-language recap with a strength word at the end.

## Suggested shape

```
for sym in universe:
    frame = derive(load(sym, report_for(sym)))      # reuse categories_for(report) resolvers
    frame["sym"] = sym
pooled = concat(frames)
tables: state frequency and fwd-13 by state, per class and pooled; single-cohort baseline
figure: one heatmap per class for the last 104 weeks with price above (plot_heatmap_with_price)
```

If a state clears crucible's bar on the pooled set it becomes a candidate gate for npf,
which is a separate session (generator and evaluator stay apart).

## Related

The commercial row of the heatmap is short-covering at tops (Jan 27 2026: +480 longs,
-40,924 shorts) and is the accounting mirror of the Managed Money row, so it is not an
independent cohort for the state table. The CMR/PF gate reads the commercial LEVEL (WILLCO
range index); the flow is the level unwinding, i.e. the same information one step later.

## Outcome (2026-09-26)

Executed in Claude Code from `npf/.venv`, branch `claude/cot-flow-states-cross-universe`.
Findings: `docs/analysis/2026-09-26-cot-flow-states-cross-universe.md` (design committed
before the run). VALUE_ACCUM long 13w, 32-market ADR-0005 scope: TEST +0.124R on 85 trades,
CI spans zero, FRAGILE; gauntlet FAIL 0/3. Sign holds in commodities in both halves,
currencies negative, gold's own TRAIN half negative on the non-overlapping construction.
Marginal lean at most, genuine null as a signal. No npf gate candidate. Equities and rates
not run.

## Addendum (same day): level x flow on gold

`scripts/analysis/cot_level_x_flow.py` (paths hard-coded to the Cowork sandbox; fix before
running) produced `docs/analysis/2026-09-26-cot-level-x-flow-gold.png` and
`2026-09-26-cot-view-proposed-gold.png`. Per cohort, 6 cells (buy/sell at |z| > 1, from level
< 20 / 20-80 / > 80 on a 156w range index), 24 cells in all, no correction, fwd13 naive.
Unconditional +1.30%, hit 59%, n=994.

Cells that stand out, all in the CONTINUATION direction, none contrarian:
Comm sell from < 20: n=31, +3.5%, hit 77%. MM buy from > 80: n=35, +3.3%, 74%.
Other sell from < 20: n=33, +2.9%, 76%. Contrarian cells (any cohort selling from > 80,
commercials buying from < 20) are n=11-18 and sit at or below unconditional.

Reading: on gold 2007-2026 a flow that EXTENDS an extreme has been followed by better
quarters than one that unwinds it. That is what a 20-year bull market with near-unit-root
positioning would produce whether or not anything is there, so it is a marginal lean at
most and the pooled run is the test. The design point stands regardless: the same MM buy
is +0.5% from mid-range and +3.3% from the top decile, so a flow cell needs its level.

## Status update (2026-09-26, Claude Code session)

Executed. Output: `docs/analysis/2026-09-26-cot-flow-states-universe.md` (reproducers
`scripts/analysis/cot_flow_states_universe.py` and `cot_flow_states_scope.py`, search logs
beside it, 53 looks in total). Two departures from the scope above, both logged and both
reported separately rather than merged:

1. The universe script pooled all 42 non-heldout markets (equities and rates included, no
   expiry mask, gold included) on two price bases. The section "The handoff's scope" then
   re-cuts the same parquet to the scope this handoff asked for (physicals plus
   currencies; with and without gold) and is the pre-registered read. The equities and
   rates heatmaps are descriptive only, as asked; the quarterly-expiry mask was not run.
2. Prices: the universe doc reports the `data_cache` close only to show the gold row
   reproduces; every table that matters is on `marketdata` propadj, as this handoff
   required. The cache series goes non-positive on 11 of 23 physicals.

Answer to the question posed: VALUE_ACCUM is a marginal lean on the scoped pool (without
gold, anchored at the first settlement after the resolved release date: +1.75% against
-0.02%, n=311, HAC t 1.94), not gold-only and not a genuine null; the single-cohort null
holds everywhere; BROAD_LIQUID, which looked stronger on the naive anchor, fades to nothing
after the publication. Neither is a result. The plan for what happens next is
`docs/design/cot-flows.md`. The level x flow addendum was not re-run here.

## Addendum 2 (same day): cohort roles per market

Pertinent to the run's pooled read, not to its execution. The universe run pooled with
Comm = Prod + Swap on Disaggregated and dealer-as-counterparty on TFF. Measured in
`docs/analysis/2026-09-26-cot-cohort-roles.md`: the Prod + Swap grouping is right on
precious metals only, and on ES/RTY/BTC the counterparty is Leveraged Funds, not Dealer.
The three opinion cohorts the state classifier uses are unaffected on Disaggregated (MM,
Other, NonRep are the same columns), so the pooled VALUE_ACCUM read stands; the
`z_COUNTERPARTY` column of the universe parquet is a residual outside precious metals and
should not be read on grains, softs or energy. Design consequence recorded in
`docs/design/cot-flows.md` (section 2 bullet, PR 1 `FlowRoles` keyed per symbol, decision 6).

## Note (later the same day)

The pre-registered crucible test above was run on the branch
`claude/cot-flow-states-cross-universe` and merged as PR #50 at 13:30. Until this merge
the file existed in two copies (the branch's, with the Outcome; the main checkout's, with
the addenda); they were combined here and nothing was dropped from either.

## Addendum 3 (same day, Cowork session): Legacy equivalence per market

Measured whether the per-market role groups from Addendum 2 coincide with Legacy.
`scripts/analysis/cot_roles_vs_legacy.py` -> `docs/analysis/2026-09-26-cot-roles-vs-legacy.csv`:
weekly-flow correlation of the measured SPEC group with Legacy Non-Commercial and of the
COUNTERPARTY group with Legacy Commercial.

- Disaggregated: 0.87-0.97 and 0.84-1.00 on 20 of 23 markets (1.00 where the counterparty
  is Prod + Swap, which IS Legacy Commercial). Exceptions: HO, NG, RB (0.18-0.43) and CL
  (no roles).
- TFF: majors 6A, 6B, 6C, 6E, 6J at 0.79-0.89 / 0.85-0.92; 6S, DX, 6N weak on the spec
  side; ES, ZN, ZB, BTC zero or negative on both.

Consequence for PR 1 and the board: Legacy history (from 1986) may back-fill the role groups
only where the correlation clears ~0.85 (physicals ex-energy, major FX). Elsewhere the two
are different partitions and must not be stitched. This is ADR-0005's boundary measured at
the flow level. Recorded in `docs/design/cot-flows.md` section 2 (new bullet after the
cohort-roles bullet). Files touched by this session today, all untracked, all under
cotmetrics: `docs/analysis/2026-09-26-cot-{cohort-roles.md,cohort-roles.csv,cohort-collapse.csv,roles-vs-legacy.csv,level-x-flow-gold.png,view-proposed-gold.png,flow-heatmap-price-gold.png}`,
`scripts/analysis/cot_{cohort_roles,roles_vs_legacy,level_x_flow}.py`, edits to
`scripts/analysis/cot_flow_states.py` (plot_heatmap_with_price), `docs/design/cot-flows.md`,
and this file. Commit separately from the Claude Code branch's work.
