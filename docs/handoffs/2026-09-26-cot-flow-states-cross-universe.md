# Handoff: cross-universe run of the COT flow-state study

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
