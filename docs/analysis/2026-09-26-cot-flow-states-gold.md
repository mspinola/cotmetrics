# COT flow states for gold: week-over-week cohort moves, and whether their combinations carry information

Point-in-time analysis, 2026-09-26. Never amended: if a later measurement contradicts
this, write a new document and link back.

Reproducer: [`scripts/analysis/cot_flow_states.py`](../../scripts/analysis/cot_flow_states.py),
run against `COTDATA_STORE=~/code/cotdata_store` (disaggregated, newest COT week
2026-09-22, 1,059 weekly rows from 2006-06-13) and weekly closes from
`cot-analyzer/data_cache/GC.parquet` (`Closing Price` on report date). Figures and the
per-week state frame are written beside this file with the same date prefix.

Origin: a review of a third-party gold newsletter whose COT commentary reads one week's
change-in-positions bar chart in isolation and names only one side of each transfer.
Three questions were posed: how to show week-over-week context, whether cross-cohort
combinations form a usable signal table, and what of that belongs in this codebase.

---

## Bottom line

1. **The per-cohort week-over-week net change, normalised to its own 52-week volatility,
   is the right primitive and it is not in `cotmetrics` today.** `categories.py` owns
   net, percent-of-OI, range index, z-score of the LEVEL, and momentum. It does not own
   the weekly CHANGE, its normalisation, or the cross-cohort composites. Adding them is
   additive and touches no existing column.

2. **The heatmap of that primitive (cohort x week) is the view the static bar chart
   cannot give.** Both 2026 gold tops appear as multi-week signatures: Managed Money and
   Other Reportable at -2 to -3 sigma for two consecutive weeks with Commercials at +2 to
   +3, in late January 2026 and in milder form in October 2025. A single week's bar
   chart shows one column of this and cannot distinguish a top from noise.

3. **A three-cohort truth table is over-specified at a 1-sigma activity threshold.**
   Of 1,059 weeks, 457 have no active cohort and 547 have one or two. The eight
   fully-populated states together cover **55 weeks in twenty years**. The state the
   newsletter's prose implied this week (retail buying while trend-followers sell,
   "RETAIL_ALONE_BUY") has occurred **once**.

4. **Single-cohort weekly moves carry no forward information at 13 weeks.** Managed
   Money buying weeks return +1.13% versus selling weeks +1.65%; Other Reportable
   +1.87% versus +1.44%; Non-Reportable +1.21% versus +1.22%; unconditional +1.24%.
   That is a genuine null, and it is the most useful number in this document: a cohort
   moving one sigma in a week, on its own, predicts nothing about the next quarter.

5. **One state shows a marginal lean and nothing more.** VALUE_ACCUM (Managed Money
   selling, Other Reportable buying, Non-Reportable selling) has n=21, 13-week mean
   +2.20% against +1.24% unconditional, hit rate 71% against 58%, t=1.92. Eight states
   were tabulated, so a t of 1.9 on n=21 is not remarkable. It is a hypothesis for
   crucible, not a result.

6. **Two flags reproduce known events.** The `derisk_MM` flag (spread up more than one
   sigma while outright net falls) fired on 2026-09-01, the exact week the newsletter
   described Managed Money shifting 11k contracts from outright long into spreads. The
   `straddle_NonRep` flag (gross up more than two sigma with little net change) fired on
   2026-08-04, one week after the newsletter's "front-running" week. Neither has been
   tested for forward information; they are diagnostic labels.

No parameter search was run. One configuration was fixed before any result was seen
(52-week rolling std, 26-week minimum, activity at |z| > 1.0, horizons 4 and 13
weeks). The variants an honest search would have to log are listed at the end; none were
tried.

---

## What was built

For each cohort c in {Managed Money, Other Reportable, Non-Reportable, Producer/Merchant,
Swap Dealers}, from the disaggregated futures-only frame:

```
dNet_c    = (Long_c - Short_c).diff()
dGross_c  = |Long_c.diff()| + |Short_c.diff()|
z_c       = dNet_c / rolling_std(dNet_c, 52w, min_periods=26)
dSpread_c = Spread_c.diff()                       (where the cohort reports a spread leg)
Comm      = Prod + Swap                            (the structural counterparty, combined)
OI_less_spread = OI - sum(Spread_c)
```

Identity check: the sum of `dNet_c` over all five cohorts is zero in every one of the
1,059 weeks (max absolute residual 0 contracts). Every long has a short; a sentence that
names only the buyers is always leaving a seller off the page.

State per week, over the three cohorts that hold an opinion (Managed Money, Other
Reportable, Non-Reportable):

```
sign_c = +1 if z_c > 1.0, -1 if z_c < -1.0, else 0
state  = (sign_MM, sign_Other, sign_NonRep)
```

The eight all-active combinations are named; anything with a zero is PARTIAL, and
(0,0,0) is QUIET.

| state | (MM, Other, NonRep) | reading |
|---|---|---|
| BROAD_ACCUM | (+,+,+) | everyone buying; commercials distributing |
| INST_BUY_RETAIL_SELL | (+,+,-) | institutions buying from retail |
| TREND+RETAIL_BUY | (+,-,+) | trend and retail buying, value money selling |
| MM_ALONE_BUY | (+,-,-) | trend-followers chasing, no one else joins |
| MM_SELL_OTHERS_BUY | (-,+,+) | trend-followers reducing into value and retail |
| VALUE_ACCUM | (-,+,-) | value money buying from both trend and retail |
| RETAIL_ALONE_BUY | (-,-,+) | retail buying while both institutional cohorts sell |
| BROAD_LIQUID | (-,-,-) | everyone selling; commercials covering |

Two diagnostic flags:

```
straddle_c = dGross_c > 2 * rolling_std(dGross_c)  and  |dNet_c| < 0.25 * dGross_c
derisk_MM  = dSpread_MM > 1 * rolling_std(dSpread_MM)  and  dNet_MM < 0
```

---

## Results

### State frequency, 2006-06 to 2026-09

| state | weeks |
|---|---|
| PARTIAL | 547 |
| QUIET | 457 |
| VALUE_ACCUM | 21 |
| TREND+RETAIL_BUY | 10 |
| MM_SELL_OTHERS_BUY | 6 |
| BROAD_LIQUID | 5 |
| INST_BUY_RETAIL_SELL | 5 |
| MM_ALONE_BUY | 4 |
| BROAD_ACCUM | 3 |
| RETAIL_ALONE_BUY | 1 |

### Forward 13-week log return by state (percent)

| state | n | mean | median | hit % | t |
|---|---|---|---|---|---|
| ALL | 1045 | 1.24 | 1.15 | 58.4 | |
| PARTIAL | 541 | 1.22 | 1.20 | 58.0 | 5.59 |
| QUIET | 449 | 1.17 | 0.98 | 57.7 | 4.15 |
| VALUE_ACCUM | 21 | 2.20 | 3.15 | 71.4 | 1.92 |
| TREND+RETAIL_BUY | 10 | 1.80 | 3.55 | 70.0 | 1.36 |
| MM_SELL_OTHERS_BUY | 6 | 1.68 | 1.76 | 66.7 | 0.69 |
| BROAD_LIQUID | 5 | 2.27 | 3.43 | 80.0 | 1.58 |
| INST_BUY_RETAIL_SELL | 5 | 7.22 | 9.38 | 80.0 | 1.93 |
| MM_ALONE_BUY | 4 | -2.72 | -4.71 | 25.0 | -0.72 |
| BROAD_ACCUM | 3 | -0.33 | -1.45 | 33.3 | -0.12 |
| RETAIL_ALONE_BUY | 1 | 5.58 | 5.58 | 100.0 | |

The 4-week table is in the script output and adds nothing: every named state has
|t| < 1.6.

### Single-cohort baseline, forward 13 weeks

| cohort | move | n | mean % | hit % |
|---|---|---|---|---|
| MM | buy | 155 | 1.13 | 59.4 |
| MM | sell | 145 | 1.65 | 64.1 |
| Other | buy | 144 | 1.87 | 63.9 |
| Other | sell | 143 | 1.44 | 61.5 |
| NonRep | buy | 154 | 1.21 | 58.4 |
| NonRep | sell | 153 | 1.22 | 56.2 |

None of the six is distinguishable from the unconditional +1.24% / 58.4%. If anything,
Managed Money selling weeks have been slightly better than buying weeks, which is the
contrarian reading and is also inside noise.

### The current week

| report date | close | z_MM | z_Other | z_NonRep | z_Comm | state |
|---|---|---|---|---|---|---|
| 2026-09-15 | 4,332.80 | -0.21 | 0.03 | **-2.64** | 0.58 | PARTIAL |
| 2026-09-22 | | -0.65 | 0.15 | **+2.12** | -0.08 | PARTIAL |

Non-Reportable sold 2.6 sigma and then bought 2.1 sigma the following week. Managed
Money's reduction this week is -0.65 sigma, not active. The newsletter's characterisation
of the week as "retail adding while trend-followers reduce" is correct in sign and does
not reach the activity threshold on the institutional side; in sequence it reads as retail
reversing its own prior-week dump rather than as a divergence.

---

## What belongs where

The dependency direction is `cotdata <- cotmetrics <- cot-analyzer`, and cot-analyzer
computes no metrics. So:

**cotmetrics** (additive; nothing existing changes):

- A `flows.py` module, or an extension of `build_category_frame`, that emits per cohort
  `dNet`, `dGross`, `dSpread`, `z_dNet`, and the two flags, plus `dNet_Comm`, `z_Comm`
  and `OI_less_spread`. The cohort specs and column resolvers in `categories.py` already
  exist and should be reused rather than duplicated (the reproducer reads the parquet
  directly only so that it runs without an install).
- The state classifier as a function of the three z columns, returning the string label.
  Keep the threshold a parameter with 1.0 as the default and document that it was not
  searched.

**cot-analyzer** (rendering only):

- The cohort x week heatmap of `z_dNet`, 52 weeks by default, with the divergence states
  boxed. This is the one view that answers "what happened in the weeks before this one".
- A state strip under the price chart, as in the second figure.
- On the existing change-in-positions bar chart: render both the long and the short leg
  for every cohort, always. The chart already does; the failure mode is in prose that
  reads only one leg.

**Not recommended:** surfacing the eight-state table as a signal. Five percent
occupancy over twenty years and one marginal lean is not a signal table; it is a
diagnostic vocabulary. The heatmap carries the information; the labels are captions.

---

## Variants not tried

Rule 2 requires the denominator to be a measurement. One configuration was run. The
obvious variants, none of which were tried and all of which would need to be logged in a
`SearchSpaceLog` before any claim is made off them:

- activity threshold 0.5 sigma (would populate the named states at the cost of meaning)
- 26-week rolling window
- 8-week horizon
- states over two cohorts instead of three (MM x NonRep alone)
- levels instead of changes (the existing range index and z-score of net already cover
  this and have their own history in `positioning-series-properties.md`)

If the VALUE_ACCUM lean is worth pursuing, it goes through crucible with the variant
count from that log, not through a re-run of this script with a friendlier threshold.

---

## Plain-language recap

The chart that shows each group's weekly move as a colour, week after week, is worth
building: it makes the two big gold tops of the last year visible as a pattern that lasts
several weeks, and it makes this week's "retail buying" look like what it is, retail
undoing last week's selling. That is a **significant** improvement in what the page can
show, at zero risk, because it is a different picture of numbers already in the store.

The idea of a lookup table that turns three groups' moves into a buy or sell reading does
not survive contact with the data. The combinations almost never all happen in the same
week, one of them happened exactly once in twenty years, and any single group moving on
its own tells you nothing about the next three months. That is a **genuine null** on the
table as a signal. One combination shows a **marginal lean** (value money buying while
everyone else sells, followed by slightly better quarters), which is worth a proper test
and is not worth acting on from this document.
