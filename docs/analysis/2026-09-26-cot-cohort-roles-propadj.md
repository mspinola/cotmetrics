# Per-market cohort roles on the ratio-adjusted series, and whether they hold on rolling windows

Point-in-time analysis, 2026-09-26. Never amended: if a later measurement contradicts
this, write a new document and link back.

Reproducer:
[`scripts/analysis/cot_cohort_roles_propadj.py`](../../scripts/analysis/cot_cohort_roles_propadj.py),
run against `COTDATA_STORE=~/code/cotdata_store` (Disaggregated and TFF through
`cotdata.get_cot`, newest COT week 2026-09-22), the 42 non-heldout markets of
`cotmetrics-config/params.yaml`, and the ratio-adjusted `propadj` futures tier of
`MARKETDATA_STORE=~/code/marketdata_store` through `marketdata.get_bars`. Per-cohort
measurements in `2026-09-26-cot-cohort-roles-propadj.csv`, the collapse in
`2026-09-26-cot-cohort-collapse-propadj.csv` (the origin's columns, then the same sets as
`cotmetrics.categories` keys, then the usable week counts on both bases), the rolling
check in `2026-09-26-cot-cohort-roles-stability.csv`. Runs in 2.5 s.

```bash
cd cotmetrics && COTDATA_STORE=~/code/cotdata_store MARKETDATA_STORE=~/code/marketdata_store \
  ../npf/.venv/bin/python scripts/analysis/cot_cohort_roles_propadj.py \
    --params ../cotmetrics-config/params.yaml \
    --universe docs/analysis/2026-09-26-cot-flow-states-universe.parquet \
    --cowork-collapse docs/analysis/2026-09-26-cot-cohort-collapse.csv \
    --out docs/analysis
```

## Origin

[`2026-09-26-cot-cohort-roles.md`](2026-09-26-cot-cohort-roles.md) proposed the rule
(same-week correlation of a cohort's weekly net change with the price return, threshold
0.15, inert below 5% of gross, Non-Reportable always RETAIL) and measured it once over the
full history. Its script read the `close` column of
`2026-09-26-cot-flow-states-universe.parquet`, which is cot-analyzer's cache close and
not, as that doc says, the propadj series. The cache close is additively back-adjusted and
goes non-positive on long commodity histories, so a log return existed on only 229 of
1,058 weeks for HO, 239 for RB, 387 for OJ, 689 for ZM, 901 for HE, 925 for ZL, 929 for
ZS, 987 for KC and 989 for CT (the `usable_cache` column of the collapse CSV, counted as
weeks where the return and every cohort's dNet are defined). On propadj every one of those
markets has 1,058. LBR is the exception that is not a basis fact: Norgate's continuous LBR
begins 2022-08-08 (the contract itself is that young; nothing stitches the retired LBS
series to it), so it has 215 usable weeks on both bases and both measurements of LBR rest
on four years.

The second cost of the cache basis was not visible from the week counts. Where the
additive series sits near zero a log return of a positive week is enormous, and those
weeks dominate a correlation. On propadj the Managed Money and Producer/Merchant
correlations on the grain and soft markets are roughly double the cache figures (ZS MM
+0.16 to +0.55, Prod -0.21 to -0.59; ZM, ZL, CT, KC the same shape; CL MM +0.13 to +0.40),
while every TFF market moved by 0.03 or less (17 of 42 markets have every cohort within
0.03, all of them TFF). The origin doc's reading that CL and HO "have no separable
speculator/hedger axis" was the price basis, not the market.

The rule is the origin's, unchanged, and was fixed before this run. Two things differ in
the plumbing and are recorded rather than hidden: positions come from `cotdata.get_cot`
(the stitched frame, so RTY carries its 2008 venue migration and LBR its 2023 code seam
inside the correlation; the origin read one parquet per code) and the legs resolve
through `cotmetrics.categories` rather than re-spelled CFTC column names. ETH is included
(286 weeks); the origin dropped it under a 300-week floor.

## Results

Threshold 0.15, inert below 5% of gross, full history. "merge ok" is the origin's check
that cohorts sharing a role have non-negative pairwise dNet correlation. The last three
columns are from the stability section below.

| report | sym | SPEC | COUNTERPARTY | NEUTRAL | inert | merge ok | retail behaves | buckets | weeks propadj / cache | cp set stab | windows | stable |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| disagg | CC | MM | Prod+Other | Swap | - | yes | spec-like | 4 | 1058 / 1041 | 0.27 | 70 | no |
| disagg | CL | MM | Swap+Other | Prod | - | cp fails | cp-like | 4 | 1058 / 1033 | 0.09 | 70 | no |
| disagg | CT | MM | Prod | Swap+Other | - | yes | spec-like | 4 | 1058 / 989 | 0.84 | 70 | yes |
| disagg | GC | MM | Prod+Swap | Other | - | yes | spec-like | 4 | 1058 / 1057 | 0.60 | 70 | yes |
| disagg | GF | MM | Prod | Swap+Other | - | yes | cp-like | 4 | 1058 / 1057 | 0.57 | 70 | no |
| disagg | HE | Swap+MM | Prod+Other | - | - | yes | neutral | 3 | 1058 / 901 | 0.39 | 70 | no |
| disagg | HG | MM | Prod+Swap+Other | - | - | yes | neutral | 3 | 1058 / 1057 | 0.63 | 70 | yes |
| disagg | HO | MM | Prod+Swap+Other | - | - | yes | spec-like | 3 | 1058 / 229 | 0.41 | 70 | no |
| disagg | KC | MM | Prod | Swap+Other | - | yes | neutral | 4 | 1058 / 987 | 0.69 | 70 | yes |
| disagg | LBR | MM+Other | Prod | Swap | - | spec fails | neutral | 4 | 215 / 214 | 1.00 | 9 | yes |
| disagg | LE | MM | Prod | Swap+Other | - | yes | cp-like | 4 | 1058 / 1057 | 0.80 | 70 | yes |
| disagg | NG | MM | Prod+Other | Swap | - | yes | neutral | 4 | 1058 / 1057 | 0.53 | 70 | no |
| disagg | OJ | MM | Prod+Other | - | Swap | yes | spec-like | 3 | 1058 / 387 | 0.97 | 70 | yes |
| disagg | PA | MM | Prod+Swap | Other | - | yes | spec-like | 4 | 1058 / 1057 | 0.83 | 70 | yes |
| disagg | PL | MM | Prod+Swap | Other | - | yes | neutral | 4 | 1058 / 1057 | 0.77 | 70 | yes |
| disagg | RB | MM | Prod+Other | Swap | - | yes | spec-like | 4 | 1058 / 239 | 0.37 | 70 | no |
| disagg | SB | MM | Prod+Swap+Other | - | - | cp fails | spec-like | 3 | 1058 / 1057 | 0.31 | 70 | no |
| disagg | SI | MM | Prod+Swap+Other | - | - | yes | spec-like | 3 | 1058 / 1057 | 0.87 | 70 | yes |
| disagg | ZC | MM | Prod | Swap+Other | - | yes | neutral | 4 | 1058 / 1057 | 0.91 | 70 | yes |
| disagg | ZL | MM | Prod | Swap+Other | - | yes | spec-like | 4 | 1058 / 925 | 0.80 | 70 | yes |
| disagg | ZM | MM | Prod | Swap+Other | - | yes | spec-like | 4 | 1058 / 689 | 0.79 | 70 | yes |
| disagg | ZS | MM | Prod | Swap+Other | - | yes | spec-like | 4 | 1058 / 929 | 0.61 | 70 | yes |
| disagg | ZW | MM | Prod+Other | Swap | - | yes | neutral | 4 | 1058 / 1057 | 0.47 | 70 | no |
| tff | 6A | AssetMgr+LevFund | Dealer | - | Other | spec fails | spec-like | 3 | 1058 / 1057 | 0.66 | 70 | yes |
| tff | 6B | AssetMgr+LevFund | Dealer | - | Other | spec fails | spec-like | 3 | 1058 / 1057 | 0.74 | 70 | yes |
| tff | 6C | AssetMgr+LevFund | Dealer | - | Other | yes | spec-like | 3 | 1058 / 1057 | 0.49 | 70 | no |
| tff | 6E | AssetMgr+LevFund | Dealer | - | Other | yes | spec-like | 3 | 1058 / 1057 | 0.97 | 70 | yes |
| tff | 6J | AssetMgr+LevFund | Dealer | Other | - | yes | spec-like | 4 | 1058 / 1057 | 0.94 | 70 | yes |
| tff | 6M | LevFund | Dealer | AssetMgr+Other | - | yes | spec-like | 4 | 1058 / 1057 | 0.71 | 70 | yes |
| tff | 6N | AssetMgr | Dealer | LevFund | Other | yes | spec-like | 4 | 1055 / 1054 | 0.77 | 70 | yes |
| tff | 6S | AssetMgr+LevFund | Dealer | - | Other | spec fails | spec-like | 3 | 1058 / 1057 | 0.57 | 70 | no |
| tff | BTC | AssetMgr | LevFund | Dealer+Other | - | yes | spec-like | 4 | 441 / 440 | 0.39 | 23 | no |
| tff | DX | AssetMgr | Dealer | LevFund+Other | - | yes | spec-like | 4 | 1058 / 1057 | 0.36 | 70 | no |
| tff | ES | AssetMgr | LevFund | Dealer | Other | yes | neutral | 4 | 1058 / 1057 | 0.34 | 70 | no |
| tff | ETH | Dealer+AssetMgr | LevFund | - | Other | yes | spec-like | 3 | 285 / 284 | 0.27 | 11 | no |
| tff | NQ | AssetMgr | Dealer | LevFund | Other | yes | neutral | 4 | 1058 / 1057 | 0.47 | 70 | no |
| tff | RTY | AssetMgr | Dealer | LevFund | Other | yes | neutral | 4 | 1058 / 1057 | 0.66 | 70 | yes |
| tff | YM | AssetMgr | - | Dealer+LevFund | Other | yes | cp-like | 3 | 1058 / 1057 | 0.46 | 70 | no |
| tff | ZB | AssetMgr | Dealer | LevFund+Other | - | yes | spec-like | 4 | 1058 / 1057 | 0.41 | 70 | no |
| tff | ZF | AssetMgr | Dealer | LevFund | Other | yes | spec-like | 4 | 1058 / 1057 | 0.33 | 70 | no |
| tff | ZN | AssetMgr | Other | Dealer+LevFund | - | yes | spec-like | 4 | 1058 / 1057 | 0.17 | 70 | no |
| tff | ZT | - | - | Dealer+AssetMgr+LevFund+Other | - | yes | neutral | 2 | 1058 / 1057 | 0.17 | 70 | no |

Buckets: 4 on 28 markets, 3 on 13, 2 on 1 (ZT; the origin had three two-bucket markets).
Retail flow is spec-like on 26 markets, neutral on 12, counterparty-like on 4 (GF, LE, YM,
and now CL).

### What changed against the cache-close measurement

Ten of the 41 markets in the origin table moved at least one cohort between buckets, and
ETH is new. Old to new:

| market | change | why |
|---|---|---|
| disagg CL | SPEC none to MM; COUNTERPARTY none to Swap+Other; NEUTRAL MM+Other+Prod+Swap to Prod | MM +0.13 to +0.40, Swap -0.12 to -0.23, Other -0.02 to -0.19; Prod -0.14 stays a hair inside the band. Crude has a speculator/hedger axis after all |
| disagg HE | SPEC MM to Swap+MM; COUNTERPARTY Prod to Prod+Other; NEUTRAL Other+Swap to none | Swap +0.06 to +0.16, Other -0.05 to -0.18, both just across the line |
| disagg HO | SPEC none to MM; COUNTERPARTY Other+Swap to Prod+Swap+Other; NEUTRAL MM+Prod to none | 229 weeks became 1,058; MM +0.09 to +0.38, Prod -0.03 to -0.37 |
| disagg LBR | SPEC MM to MM+Other; COUNTERPARTY Other+Prod to Prod; NEUTRAL none to Swap; inert Swap to none | same 215 weeks, different returns and the stitched frame; Other flips sign (-0.29 to +0.23) and Swap's gross share crosses 5%. Four years of data; read nothing into either version |
| disagg RB | COUNTERPARTY Other to Prod+Other; NEUTRAL Prod+Swap to Swap | 239 weeks became 1,058; Prod -0.13 to -0.34 |
| tff 6A | SPEC LevFund to AssetMgr+LevFund; NEUTRAL AssetMgr to none | AssetMgr +0.13 to +0.16, a boundary case on identical weeks |
| tff 6S | SPEC AssetMgr to AssetMgr+LevFund; NEUTRAL LevFund to none | LevFund +0.13 to +0.16, same |
| tff NQ | COUNTERPARTY none to Dealer; NEUTRAL Dealer+LevFund to LevFund | Dealer -0.09 to -0.16 |
| tff RTY | COUNTERPARTY Dealer+LevFund to Dealer; NEUTRAL none to LevFund | LevFund -0.17 to -0.12 |
| tff ZF | SPEC none to AssetMgr; COUNTERPARTY none to Dealer; NEUTRAL Dealer+AssetMgr+LevFund to LevFund | AssetMgr +0.13 to +0.16, Dealer -0.14 to -0.16; the 5-year now separates by 0.01 on each side |

The TFF changes are all cohorts within 0.04 of the threshold on the same weeks, which is
the first sign that a hard 0.15 cut is going to move around; the stability section
measures that directly. The physicals changes are the price basis doing what the origin's
week counts predicted.

What survives the basis change, and is stronger on it: Managed Money is SPEC on 23 of 23
physicals (the origin had 21) and Producer/Merchant is COUNTERPARTY on 22 (CL's -0.14 is
the one miss). Other Reportable is now SPEC once (LBR, four years) and COUNTERPARTY on 11
physicals. Swap Dealer is COUNTERPARTY on the four precious metals plus HG, CL, HO, SB,
SPEC on HE, and NEUTRAL or inert elsewhere. On TFF, Dealer is COUNTERPARTY on all nine
currencies, ZB, ZF, NQ and RTY; Leveraged Funds is the COUNTERPARTY on ES, BTC and ETH;
Asset Manager is SPEC on 17 of 19 (not 6M, not ZT). ZT still separates nothing.

## Stability

Fixed before the run and written into the script docstring: 156-week windows stepping 13
weeks (70 windows on a full-history market, 23 on BTC, 11 on ETH, 9 on LBR), a window
counted only when at least 104 of its weeks carry a return and every cohort's dNet;
inside each window px_corr and gross_share (the window's own last 52 weeks) are
recomputed and the same thresholds applied. Two readings per market: the fraction of
windows in which each cohort's role equals its full-history role (`agree_frac`), and the
fraction of windows in which the COUNTERPARTY set equals the full-history COUNTERPARTY set
(`counterparty_set_stability`), with the SPEC set beside it.

**Criterion, stated before looking:** a market's measured roles are committed as data when
`counterparty_set_stability >= 0.6` over at least 8 windows. The counterparty set is the
criterion because it is the only role `flows.py` reads per symbol (the opinion triple stays
the per-report default everywhere, per `docs/design/cot-flows.md` section 3). A market
that fails falls back to the per-report default (disagg producer_merchant + swap, tff
dealer).

Result: median `counterparty_set_stability` 0.585, median `spec_set_stability` 0.615,
median per-cohort `agree_frac` 0.943. **21 of 42 markets fail the criterion**:

- disagg (9 of 23): CC 0.27, CL 0.09, GF 0.57, HE 0.39, HO 0.41, NG 0.53, RB 0.37,
  SB 0.31, ZW 0.47.
- tff (12 of 19): 6C 0.49, 6S 0.57, BTC 0.39 (23 windows), DX 0.36, ES 0.34, ETH 0.27
  (11 windows), NQ 0.47, YM 0.46, ZB 0.41, ZF 0.33, ZN 0.17, ZT 0.17.

Passing (21): CT, GC, HG, KC, LBR, LE, OJ, PA, PL, SI, ZC, ZL, ZM, ZS; 6A, 6B, 6E, 6J,
6M, 6N, RTY. GC passes at exactly 0.60 and LBR passes on 9 windows spanning four years, so
both sit on the criterion's edge, from opposite sides.

The gap between a 0.94 median per-cohort agreement and a 0.59 median set stability is the
finding. The core of every market is fixed and the edges are not:

- On every Disaggregated market Managed Money is SPEC on at least 94% of windows (HO the
  lowest at 66 of 70) and Producer/Merchant is COUNTERPARTY on at least 66% (CL 46 of 70,
  GF 50, NG 57, the other twenty at 63 or more). Those two roles never flip in any window
  on 17 of the 23 markets.
- The instability is Swap Dealer and Other Reportable sitting on the 0.15 line. The 54
  cohorts with `agree_frac` below 0.6 (full list in the stability CSV, `window_roles`
  column) are, on disagg, Swap or Other on every row but one (CL Prod, which is
  COUNTERPARTY on 46 windows and NEUTRAL over the full history). CC Swap splits 28 / 28 /
  14 across NEUTRAL, SPEC and COUNTERPARTY; ZC Swap 36 / 34 between NEUTRAL and SPEC;
  ZS Swap 30 / 28 / 12 between SPEC, NEUTRAL and COUNTERPARTY. The index book is not on a
  side, and on a three-year window it is on whichever side the index flow happened to be.
- On TFF the Dealer is COUNTERPARTY on at least 82% of windows in every currency except
  DX (28 of 70), so the eight CME currencies keep the mapping and the dollar index does
  not. The rates and equities that fail do so on Dealer and Leveraged Funds shifting
  between COUNTERPARTY and NEUTRAL (ZN Dealer 38 / 20 / 12, ZT Dealer 47 / 23, ES Dealer
  30 / 24 / 16 across SPEC, NEUTRAL and COUNTERPARTY), which is ADR-0005's basis-trade
  observation seen through the classifier: the leveraged / asset-manager pair is one trade,
  and who is on the other side of it depends on the window. ES's Other Reportable is
  inert over the full history and COUNTERPARTY on 30 windows.
- The four lowest SPEC-set stabilities (6C and 6S at 0.00, 6A 0.09, 6B 0.26) are the
  AssetMgr+LevFund pairing: each is SPEC over the full history and the two are rarely both
  across 0.15 in the same window. That is why `spec_merge_ok`
  fails on 6A, 6B and 6S (asset managers and leveraged funds flow against each other at
  -0.07 to -0.3), and it is the origin doc's point 3 with the window added.

Of the 21 failures, 12 are state-eligible under ADR-0005 (nine physicals and 6C, 6S, DX);
the other nine (BTC, ETH, ES, NQ, YM, ZB, ZF, ZN, ZT) get z cells and no state regardless,
so the fallback there changes only which cohort the counterparty row draws, and the default
(dealer) is what their full-history table says on ZB, ZF and NQ anyway.

## Variants not tried

A threshold other than 0.15, or a band (say 0.10 to 0.20) that would hold a cohort's
role until it crosses the far edge; a window other than 156 weeks or a step other than
13; masking dNet at the LBR and RTY seams before correlating (`docs/design/cot-flows.md`
section 5); a soft stability that asks whether the full-history set is a subset of the
window's rather than equal to it (it would pass more markets and was not pre-stated, so
it is not reported); correlation with the next week's return (a predictor, needs the
search log); the net-of-OI basis; the 0.5 or 0.7 cut-offs the criterion could have used
instead of 0.6. One look, one criterion.

## Plain-language recap

Measured on the right price series, the picture gets cleaner and stronger, not weaker:
on every physical commodity the managed-money funds chase price and the producers and
merchants absorb it, including crude and heating oil where the cache-based run saw
nothing. Ten markets changed a bucket, mostly cohorts that were within a few hundredths of
the line, and the TFF picture barely moved. **Significant** as a description of the two
cohorts that carry each market.

The stability test then says the edges of that picture are not data to commit. Whether a
swap dealer or an "other reportable" book is a counterparty, a bystander or a follower
changes from one three-year window to the next on about half the markets, and under the
criterion fixed in advance 21 of 42 markets fail. Rather than lowering the bar after the
fact, the recommendation is to commit measured counterparty sets only for the 21 that
pass (14 physicals and the eight CME currencies less 6C and 6S, plus RTY) and to leave the
rest on the per-report default, with the per-cohort table beside it so the reader can see
which cohorts are fixed and which are not. **Marginal lean** on the per-symbol table as a
whole; the two-cohort core of each market is significant, and the third and fourth cohorts
are noise around a threshold.
