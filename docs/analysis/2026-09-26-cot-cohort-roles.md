# Per-market cohort roles: can Disaggregated and TFF collapse to speculators / counterparty / retail?

Point-in-time analysis, 2026-09-26. Never amended.

Reproducer: [`scripts/analysis/cot_cohort_roles.py`](../../scripts/analysis/cot_cohort_roles.py)
against `COTDATA_STORE=~/code/cotdata_store` (Disaggregated 23 markets, TFF 18, RTY on its
current code only) and the propadj closes carried in
`2026-09-26-cot-flow-states-universe.parquet`. Per-cohort measurements in
`2026-09-26-cot-cohort-roles.csv`, the resulting collapse in `2026-09-26-cot-cohort-collapse.csv`.
Sandbox paths are hard-coded in the script; fix before running.

Origin: the flow-state work grouped Producer/Merchant with Swap Dealer as "Commercials" for
gold. Measured across the Disaggregated universe that grouping holds only in precious metals
(Prod/Swap weekly-flow correlation +0.40 to +0.58 in GC, SI, PL, PA; negative in every grain,
soft, livestock and energy market, same-sign fraction near zero). The question here is whether
a per-market rule can assign roles from the data instead of from category names.

## Rule (fixed before the run, one configuration, no search)

For each market and cohort, over the full history:

```
px_corr     = corr(dNet_c, same-week log return)
gross_share = mean over last 52 weeks of (long_c + short_c) / total gross
role        = RETAIL          if cohort is Non-Reportable
            = inert           if gross_share < 0.05
            = SPEC            if px_corr >= +0.15
            = COUNTERPARTY    if px_corr <= -0.15
            = NEUTRAL         otherwise
merge check = cohorts sharing a role must have non-negative pairwise flow correlation
```

`px_corr` is contemporaneous by design: a cohort whose weekly flow moves with the week's price
is chasing or being chased; one whose flow moves against it is absorbing. This is the same
same-week coincidence `docs/design/cot-flows.md` flags as making the heatmap "look like it
predicts"; here it is used as the classifier, not as evidence of prediction.

## Result

| report | sym | SPEC | COUNTERPARTY | NEUTRAL | inert | retail behaves | buckets |
|---|---|---|---|---|---|---|---|
| disagg | CC | MM | Other+Prod | Swap | - | spec-like | 4 |
| disagg | CL | - | - | MM+Other+Prod+Swap | - | neutral | 2 |
| disagg | CT | MM | Prod | Other+Swap | - | spec-like | 4 |
| disagg | GC | MM | Prod+Swap | Other | - | spec-like | 4 |
| disagg | GF | MM | Prod | Other+Swap | - | cp-like | 4 |
| disagg | HE | MM | Prod | Other+Swap | - | neutral | 4 |
| disagg | HG | MM | Other+Prod+Swap | - | - | neutral | 3 |
| disagg | HO | - | Other+Swap | MM+Prod | - | spec-like | 3 |
| disagg | KC | MM | Prod | Other+Swap | - | neutral | 4 |
| disagg | LBR | MM | Other+Prod | - | Swap | neutral | 3 |
| disagg | LE | MM | Prod | Other+Swap | - | cp-like | 4 |
| disagg | NG | MM | Other+Prod | Swap | - | neutral | 4 |
| disagg | OJ | MM | Other+Prod | - | Swap | spec-like | 3 |
| disagg | PA | MM | Prod+Swap | Other | - | spec-like | 4 |
| disagg | PL | MM | Prod+Swap | Other | - | neutral | 4 |
| disagg | RB | MM | Other | Prod+Swap | - | spec-like | 4 |
| disagg | SB | MM | Other+Prod+Swap | - | - | spec-like | 3 |
| disagg | SI | MM | Other+Prod+Swap | - | - | spec-like | 3 |
| disagg | ZC | MM | Prod | Other+Swap | - | neutral | 4 |
| disagg | ZL | MM | Prod | Other+Swap | - | spec-like | 4 |
| disagg | ZM | MM | Prod | Other+Swap | - | spec-like | 4 |
| disagg | ZS | MM | Prod | Other+Swap | - | spec-like | 4 |
| disagg | ZW | MM | Other+Prod | Swap | - | neutral | 4 |
| tff | 6A | LevFund | Dealer | AssetMgr | Other | spec-like | 4 |
| tff | 6B | AssetMgr+LevFund | Dealer | - | Other | spec-like | 3 |
| tff | 6C | AssetMgr+LevFund | Dealer | - | Other | spec-like | 3 |
| tff | 6E | AssetMgr+LevFund | Dealer | - | Other | spec-like | 3 |
| tff | 6J | AssetMgr+LevFund | Dealer | Other | - | spec-like | 4 |
| tff | 6M | LevFund | Dealer | AssetMgr+Other | - | spec-like | 4 |
| tff | 6N | AssetMgr | Dealer | LevFund | Other | spec-like | 4 |
| tff | 6S | AssetMgr | Dealer | LevFund | Other | spec-like | 4 |
| tff | BTC | AssetMgr | LevFund | Dealer+Other | - | spec-like | 4 |
| tff | DX | AssetMgr | Dealer | LevFund+Other | - | spec-like | 4 |
| tff | ES | AssetMgr | LevFund | Dealer | Other | neutral | 4 |
| tff | NQ | AssetMgr | - | Dealer+LevFund | Other | neutral | 3 |
| tff | RTY | AssetMgr | Dealer+LevFund | - | Other | neutral | 3 |
| tff | YM | AssetMgr | - | Dealer+LevFund | Other | cp-like | 3 |
| tff | ZB | AssetMgr | Dealer | LevFund+Other | - | spec-like | 4 |
| tff | ZF | - | - | Dealer+AssetMgr+LevFund | Other | spec-like | 2 |
| tff | ZN | AssetMgr | Other | Dealer+LevFund | - | spec-like | 4 |
| tff | ZT | - | - | Dealer+AssetMgr+LevFund+Other | - | neutral | 2 |

Buckets: 4 on 26 markets, 3 on 12, 2 on 3. Retail flow is spec-like on 25 markets, neutral on
13, counterparty-like on 3 (GF, LE, YM).

## Reading

1. **Managed Money is SPEC on 21 of 23 physicals; Producer/Merchant is COUNTERPARTY on 21.**
   The two exceptions are CL and HO, where no cohort's flow correlates with price above 0.15:
   the crude complex has no separable speculator/hedger axis on this measure. Swap Dealer is
   COUNTERPARTY only in GC, SI, PL, PA, HG, HO (and merges with Prod cleanly except where the
   merge check fails: SB, LBR); elsewhere it is NEUTRAL, which is the index-flow book.
2. **Other Reportable is NEUTRAL on 14 physicals and COUNTERPARTY on 9.** It is never SPEC. The
   "value money" caption from the gold doc is the counterparty-or-neutral behaviour, and on
   gold specifically it is NEUTRAL (px_corr -0.05), so the Jan 2026 read of Other Reportable as
   the stretched cohort was a level fact, not a flow-role fact.
3. **TFF: Dealer is COUNTERPARTY in all eight currencies and ZB; Asset Manager and/or Leveraged
   Funds are SPEC.** The universe run's mapping (dealer = counterparty, asset manager +
   leveraged = opinion) is what the data gives for FX. In equity indices the picture flips:
   Asset Manager is SPEC and Leveraged Funds is COUNTERPARTY on ES, RTY, BTC, with Dealer
   neutral. In Treasuries (ZF, ZT, ZN) nothing separates, which is ADR-0005's conclusion
   reached from the other side.
4. **A universal two-bucket collapse (speculators vs commercials) exists on 26 markets and
   fails on 15**, and the failures are not noise: crude, the 2-year and 5-year, and the
   markets where a cohort is NEUTRAL with a large gross share (Swap in grains at 11-16%).
   Dropping a neutral cohort into either bucket adds a book that does not respond to price.
   The honest collapse is three buckets plus retail, with NEUTRAL kept as its own row or
   excluded from state classification, per market.
5. **"Retail" is a label, not a behaviour.** Non-Reportable flow chases price in FX and softs
   (SB 0.58, 6S 0.53) and absorbs it in feeder and live cattle. A state table that fixes
   NonRep as the third opinion cohort is assuming a behaviour that holds on 25 of 41 markets.

## What this supports

A `FlowRoles` table keyed by (report, symbol) rather than by report alone, generated by this
script and committed as data, with the threshold and the date of the measurement recorded
beside it. Stability of the assignment over time was not measured (one full-history
correlation per cell); a rolling version is the obvious next check before the table is relied
on.

## Variants not tried

Threshold other than 0.15; rolling rather than full-history correlation; correlation with the
NEXT week's return (which would turn the classifier into a predictor and needs the search log);
net-of-OI basis; per-regime assignments.

## Plain-language recap

Yes, a per-market rule can be built from the data, and the same one fits both reports: a
group whose weekly buying moves with price is a speculator, one whose buying moves against it
is the counterparty, and the rest are neutral. On most markets that gives the familiar
speculators-versus-hedgers picture with the right names filled in per market. It does not give
a universal two-way split: on crude, the short Treasuries, and the grains where the swap
dealers carry index money, one large group is simply not on either side, and forcing it into a
bucket buries the signal. **Significant** as a description of who is who; nothing here is
evidence that any of it predicts.
