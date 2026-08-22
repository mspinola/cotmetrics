# Effective-dated contract multipliers: what is actually broken, and what it costs to fix

Point-in-time analysis, 2026-08-22. Never amended: if a later measurement contradicts
this, write a new document and link back.

Reproducer: [`scripts/analysis/audit_contract_regimes.py`](../../scripts/analysis/audit_contract_regimes.py),
run against `COTDATA_STORE=~/code/cotdata_store` (newest COT week 2026-08-18),
`MARKETDATA_STORE=~/code/marketdata_store`, and the real universe
(`COTMETRICS_PARAMS=cotmetrics-config/params.yaml`, 47 markets across 9 asset classes).

---

## Bottom line

`marketdata.store.read_metadata()` carries one `Point Value` per symbol with no
effective date, and `cotmetrics.exposure.point_values()` applies it to a market's entire
COT history. The concern is right. The two conclusions below are not the ones the
concern predicted.

1. **Lumber is not broken.** cotdata already carries a scale factor for it, and it is
   already applied. The premise that its pre-2023 weeks are understated 4x does not
   reproduce.
2. **The Russell is broken, by exactly 2x, over 740 of its 1,247 priced weeks.** ICE
   halved the Russell multiplier on 2016-12-05 and converted every open lot into two.
   The CFTC name did not change that week, so a name-based audit cannot see it at all.

One market in 47 is affected, and one date and one ratio fix it. The prerequisite for
promoting the dollar-risk percentile is **cheap**, and the recommended change is
**additive, so it needs no deprecation path** despite marketdata being public and on
PyPI.

---

## 1. The inventory

Full per-market table in the reproducer's section 1. Headline shape:

| | |
|---|---|
| markets in the real universe | 47 |
| markets with a `Point Value` | 45 (MFS and MME have none, by design) |
| priced market-weeks in total | 73,343 |
| distinct `Market_and_Exchange_Names` boundaries | 85 |

A name change **before** a market's first priced week is harmless, because those weeks
carry no dollars. That rule does real work here. The Euro is the canonical case: its COT
history starts 1986-01-15 as `EUROPEAN CURRENCY UNIT`, its price starts 1999-01-05, and
the 10 ECU weeks in between carry no notional at all. Same for New Zealand Dollar (COT
1999, priced 2005) and for Lumber's first 143 weeks.

### The name column is a poor signal, and this is measurable

**61 of the 85 boundaries (72%) sit on a date shared by three or more markets.** Those
are CFTC-wide relabels and exchange reorganisations, not contract events:

| date | markets | what it was |
|---|---|---|
| 2022-02-08 | 18 | CFTC shortened market names across the board |
| 2000-08-29 | 10 | IMM folded into CHICAGO MERCANTILE EXCHANGE |
| 1999-12-21, 2005-01-04, 2007-09-04 | 6 each | CSCE/NYBOT/ICE consolidation |
| 1993-01-26 | 5 | CBOT note and bond relabels |
| 2002-04-30, 2000-01-11, 2003-02-25 | 3-4 each | exchange renames |

Of the 24 idiosyncratic boundaries, 16 sit inside a priced window. Reading them one by
one, **every one but Lumber's is cosmetic**: punctuation (`CRUDE OIL, LIGHT 'SWEET'` ->
`CRUDE OIL, LIGHT SWEET`), pluralisation (`AUSTRALIAN DOLLARS` -> `AUSTRALIAN DOLLAR`),
disambiguation after CME acquired KCBT (`WHEAT` -> `WHEAT-SRW` / `WHEAT-HRW`, both still
5,000 bu), a product respecification that left the contract size alone (`NO. 2 HEATING
OIL` -> `ULSD`, 42,000 gallons throughout), or a one-week labelling slip on a contract's
first COT print (NQ 1999-06-29, YM 2002-06-04).

**And the column misses the one real event.** More on that in section 3.

## 2. Lumber: the reported defect does not reproduce

The premise was that the CFTC kept market code 058644 across the 2023 redesign, so 31
pre-rename weeks multiply 110,000-board-foot contract counts by the 27,500-board-foot
point value. Measured, that is not what the store holds.

The CFTC used **two** codes, and cotdata carries both:

```
cot_legacy/LBR_058643.parquet   1,428 wk  1995-09-26 .. 2023-04-18   RANDOM LENGTH LUMBER
cot_legacy/LBR_058644.parquet     181 wk  2023-02-21 .. 2026-08-18   LUMBER
```

`cotdata/src/cotdata/registry.yaml` already declares the bridge, and it already carries
the ratio:

```yaml
LBR:
  cftc_code: "058644"          # CME Lumber (physical), listed 2022-08
  hist_codes:
    - ["058643", 4.0]
```

`cotdata.cot.get_cot` multiplies every numeric column of the predecessor by that scale
(`cot.py:59-61`), so predecessor counts arrive denominated in the CURRENT contract.
Verified on 2022-11-15:

| | Open Interest | Comm long | Comm short |
|---|---|---|---|
| raw `LBR_058643` | 2,387 | 1,174 | 63 |
| `get_cot("LBR")` | 9,548 | 4,696 | 252 |

Exactly 4x. And 4.0 is the right ratio: 110,000 / 27,500 board feet. The single name
column reads as one continuous code only because the stitcher rewrites
`CFTC_Contract_Market_Code` to the primary when it presents predecessor rows
(`cot.py:62-63`). That presentational choice is what makes the defect look present when
it is not.

**So the mechanism this audit was asked to propose already exists in the stack.** That
matters for section 5: the proposal is an extension of a working precedent, not a new
concept.

### What IS wrong with Lumber, and it is small

`LBR_058644` has no rows for **2023-02-28 and 2023-03-07**. The stitcher's
de-duplication keeps the primary where it exists and otherwise falls through to the
predecessor, so those two weeks inside the new contract's own era are served by the
superseded Random Length contract, scaled 4x:

```
2023-02-21   net_contracts   -646   notional  -$8.7m     <- 058644, new contract
2023-02-28   net_contracts  +2,240  notional +$31.4m     <- 058643 x4, superseded
2023-03-07   net_contracts  +3,268  notional +$41.3m     <- 058643 x4, superseded
2023-03-14   net_contracts    -884  notional -$10.7m     <- 058644, new contract
```

A spurious sign flip and a ~$40m round trip on a market whose typical notional is tens
of millions. This is a data-completeness bug in the fall-through rule, not a multiplier
bug: "primary wins where present" is correct, but "fall back to a contract the primary
has already superseded" is not. It affects 2 of Lumber's 211 priced weeks.

A related latent item, stated because it is unestablished rather than because it bites:
058643's own history contains `RANDOM LENGTH LUMBER-NEW` from 1995-12-12 and
`RANDOM LENGTH LUMBER-80/110000` from 1999-12-21, which suggest the Random Length
contract was itself resized before settling at 110,000 board feet. **I could not
establish those sizes or their dates from exchange records**, so the constant 4.0 may be
wrong for 058643's first weeks. It costs nothing today: Lumber's first priced week is
2022-08-09, so every affected week carries no dollars.

## 3. The Russell: a 2x error, invisible to the name column

### What happened

ICE Futures U.S. changed the price multiplier on all Russell index futures **from $100
to $50 per index point, effective with the start of trading on Monday 2016-12-05**, and
converted each open lot into two lots. The reporting threshold was deliberately left at
200 lots. From the exchange's own FAQ, dated 2016-10-31:

> ...the price multiplier for all Russell Index futures and option contracts will change
> to $50 per index point, from the current $100 multiplier.

The CFTC did not rename the market that week. The name change in the store is
**2017-08-15**, eight months later, and it records something else entirely: the migration
of the contract from ICE back to CME.

### Confirmed in the store

Open interest under the ICE code `RTY_23977A`:

```
2016-11-22    352,668
2016-11-29    355,514        <- last week at $100
2016-12-06    691,904        <- first week at $50
2016-12-13    759,944
```

Ratio on the adjacent weeks 1.946; on 13-week medians 334,389 -> 649,786, ratio 1.943.
Column by column at 2016-12-06:

| column | ratio |
|---|---|
| Open Interest | 1.946 |
| NonComm long / short | 1.874 / 2.269 |
| Comm long / short | 2.049 / 1.925 |
| **NonRept long / short** | **1.283 / 1.222** |

The reportable buckets double. The non-reportable buckets do not, and that is the FAQ's
200-lot clause showing up in the data: the threshold is a lot count, so it does not
scale with the contract, and traders who held 100-200 lots crossed it when their lots
were rewritten. Trader counts jumped 277 -> 359 for the same reason. **This is why the
detector in section 4 uses reportable columns only.**

### The two neighbouring boundaries are NOT multiplier changes

- **2008-09-23, CME -> ICE.** 13-week median OI 581,480 -> 499,775, ratio 0.859, and no
  uniform one-week step anywhere in the span. Positions transferred about 1:1, so the
  CME contract that ran 2002-2008 was also $100.
- **2017-08-15, ICE -> CME.** 13-week ratio 0.946, again roughly 1:1, both venues at $50
  by then.

So the Russell has exactly one multiplier regime boundary in its priced history, and it
is 2016-12-05 (COT report date 2016-12-06).

### What it costs

`cotmetrics.exposure` applies today's $50 to the whole series.

| | |
|---|---|
| RTY priced weeks | 1,247 (2002-08-13 .. 2026-08-18) |
| **weeks on the wrong multiplier** | **740 (59.3%)**, every week before 2016-12-06 |
| direction | notional and risk **understated by exactly 2x** |
| median \|notional\| as computed, wrong side | $1.33bn (true $2.66bn) |
| median \|notional\|, right side | $2.99bn |
| median \|risk_usd\|, wrong side | $15.0m (true $30.0m) |
| share of all priced market-weeks in the universe | 1.01% |

Aggregate effects, over the 732 weeks where all six priced Equities members are present:

| | as computed | corrected |
|---|---|---|
| Russell share of Equities \|notional\| | 11.9% | **21.2%** |
| Equities class total, pre-2016-12-06 | - | **understated 11.9%** |

The percentile consequence is the one that matters for the promotion question. Because
`aggregate_exposure` ranks each week against an expanding window of its own history, an
under-scaled first half does not just shift the level: it compresses the historical
reference distribution, so **every post-2016 Russell reading ranks as more extreme than
it is**, and the Equities composite inherits a discontinuity at 2016-12-06 that no
column on screen explains.

### A second consumer has the same defect, smaller

`npf/src/npf/validation/costs.py` reads the same table and applies today's `Point Value`
and `Tick Value` to historical trades:
`cost_R = (commission + 2 x slip x tick_value) / (risk_pts x point_value)`. For pre-2017
Russell trades both `tick_value` and `point_value` are half their true values, so the
slippage term cancels exactly and only the fixed commission term is wrong, by 2x. On a
30-point stop that is roughly 0.33% of R charged instead of 0.17%. Real, systematic, one
directional, and an order of magnitude smaller than the exposure error. Worth fixing
second, not first.

## 4. How I looked for the silent cases, and how well it works

A name-change audit cannot find a re-denomination that came with no rename, which is the
whole Russell story. So the reproducer also runs a detector for the signature a
re-denomination actually leaves: **in one week, every reportable position column scales
by the same factor**, because the clearing house rewrites open lots.

Screen: all five reportable columns move by a common factor >= 1.5x or <= 1/1.5, spread
between the largest and smallest column ratio under 30%, prior week at least 200 lots.
Two independent tests then separate the survivors.

Across 47 markets and ~73,000 market-weeks the screen returns **16 events**:

- **14 sit within 5 days of a quarterly third Friday.** Index and currency open interest
  collapses uniformly across buckets at quarterly expiry and then rebuilds, which looks
  exactly like a re-denomination for one week.
- **13 had reverted 26 weeks later.** This is the principled test, and it is the one to
  trust: a re-denomination rewrites open lots and never reverts.

**Exactly one event survives both: RTY 2016-12-06, k = 1.946, still 1.838 half a year
later.** Lumber does not appear, correctly, because its change was a code replacement
rather than a re-denomination and cotdata already handles it.

Two honest limits on this detector, both measured:

- **A looser screen is useless.** An 8-week median step at >= 1.6x, which is the obvious
  first thing to write, returns **169 episodes** dominated by 2008, March 2020, and
  ordinary currency open-interest cycles. It confirms a known event; it cannot discover
  one. The tight single-week uniform-scaling form is what made this work.
- **It only sees instantaneous conversions.** A multiplier change handled by listing a
  new contract alongside the old and letting positions migrate over months produces no
  step and would be missed.

### What this audit structurally cannot see

The store holds only the CFTC codes the registry names, so **this audit's coverage of
the code-change class is exactly the registry's coverage**, and the registry names
predecessors for 2 of 51 symbols (`RTY -> 23977A` at scale 1.0, `LBR -> 058643` at 4.0).
A market whose predecessor code was never registered does not appear as a name change or
as a step; it appears as a COT history that starts later than it should. Six markets in
the universe start well after 1986 (`6M` 1995, `KE`/`ZW`/`ZC`/`ZS` 1998, `RB` 2006), and
I did not investigate whether any of those is a truncation rather than a listing date.

Separately, I verified that today's `Point Value` is sane for all 45 priced markets by
computing current notional per contract: the range runs $15.8k (Lumber) to $588k (NQ),
with no outlier suggesting a stale or wrong current value.

## 5. Proposal

### Ranked candidates

| rank | market | weeks on the suspect side | multiplier error | established? |
|---|---|---|---|---|
| 1 | **RTY** | **740 of 1,247 priced (59.3%)** | **exactly 2x understated** | **yes** - ICE FAQ 2016-10-31, confirmed by a 1.946x uniform step in the store |
| 2 | LBR | 2 of 211 priced | none; wrong contract, not wrong multiplier | yes - `058644` has no rows those weeks |
| 3 | LBR pre-1995-12-12 | 0 priced | unknown | **no** - could not establish the Random Length sizes or dates |
| - | all other 44 markets | 0 | none found | name audit plus uniform-step detector both clean |

### The three options

**(a) Effective-dated `contract_specs` in marketdata.** Adding a `Valid_From` column is
harmless; adding **rows** is not. Every consumer today assumes one row per symbol, and
npf does `specs.loc[sym]` at `costs.py:357`, which silently returns a DataFrame instead
of a Series once a symbol has two rows. That is a wrong-answer break rather than a loud
one, in the repo whose numbers feed a gate verdict. This is the expensive option the
brief anticipated, and it is expensive for the reason the brief gave.

**(b) A per-market override map in cotmetrics.** Cheapest to write, roughly one dict and
20 lines. But it leaves npf wrong, and it puts a fact about an ICE contract inside a
positioning-metrics package, where the next consumer will not find it.

**(c) Refuse to price weeks before the current definition took effect.** This loses 740
of Russell's 1,247 weeks, and the loss falls exactly where it hurts most: the expanding
percentile that `aggregate_exposure` reports needs a long history, and truncating RTY to
2016 makes its percentile incommensurable with the S&P's 1997 base. It is also not
conservatism. We know this multiplier to the digit and have the exchange notice; discarding
a known number is throwing away information, not being careful about it.

### What I would do: (a), restructured to be additive

Ship the effective-dated data in **marketdata**, where both consumers can reach it, but
as a **sibling table rather than a change to `contract_specs`**:

- a new `metadata/contract_regimes.parquet`, one row per `(symbol, valid_from,
  point_value, tick_value)`, seeded with three rows: RTY $100 from its listing and $50
  from 2016-12-05, plus Lumber's two regimes for completeness
- a new `read_contract_regimes()` and a `point_value_asof(symbol, dates)` helper
- `read_metadata()` and `contract_specs` **completely unchanged**, still one current row
  per symbol

Nothing existing changes shape, so **there is no breaking change and no deprecation path
is needed**, which is the objection that made option (a) look costly. marketdata takes a
minor version bump. The regime table is the same idea as cotdata's `hist_codes` scale,
which already works in production, generalised from "across a code change" to "at a
date", which is the case that code cannot express.

Then in cotmetrics, `point_values()` becomes a per-date lookup. `market_exposure`
already emits a `point_value` column, so the output shape does not change; the scalar
multiply becomes elementwise, and the `lru_cache` on `point_values` needs to move.

### Cost

| | |
|---|---|
| marketdata: table, reader, `point_value_asof`, tests | ~200-250 lines, additive, minor bump |
| cotmetrics: `exposure.point_values` -> per-date, tests | ~40-60 lines |
| npf `costs.py`: resolve per trade date | follow-up, smaller payoff |
| data to enter | **3 rows** |

**Cheap.** The prerequisite for promoting the dollar-risk percentile is not a schema
migration across a public package; it is one additive table with three rows in it, and
one market's history to correct.

One thing to do regardless of which option is chosen: whatever holds the regimes should
require a source citation per row, because the 2016 Russell change was findable only in
an exchange notice and would otherwise be an unexplained constant.

---

## Recap in plain language

The worry behind this audit is legitimate, and the specific case it named turned out to
be already handled. Lumber is fine: cotdata carries a 4x bridge between the two CFTC
codes and applies it, so the reported 4x understatement is not there. What IS there is a
different market and a bigger break. The Russell's contract was cut in half on 5 December
2016 with no CFTC rename to mark it, so **59% of the Russell's priced history is
understated by exactly a factor of two** in both dollar notional and dollar risk, which
also distorts the equity composite and every percentile computed from it. That is one
market out of 47, one date, one number.

Two smaller things came out of it: Lumber loses two weeks in early 2023 to a stitching
fall-through that reads as a spurious sign flip, and npf's cost model carries the same
Russell error at about a tenth the severity.

Strength of the finding: the Russell result is **confirmed**, not a lean. It rests on the
exchange's own notice giving the date and the ratio, and independently on a 1.946x
one-week step in the stored positions that persists half a year later, with the
non-reportable buckets behaving exactly as that notice's unchanged 200-lot threshold
predicts. The recommendation is **cheap**: an additive table in marketdata with three
rows, no breaking change, no deprecation path.
