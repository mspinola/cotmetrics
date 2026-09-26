# Handoff: cross-universe run of the COT flow-state study

Status: OPEN. Written 2026-09-26 in a Cowork session without the npf venv; to be executed in
Claude Code from `npf/.venv`.

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
