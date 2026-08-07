# Two properties of positioning series that break naive statistics on them

**Living document.** Both properties below have the same root cause: **COT positioning is
slow-moving.** A weekly net position is close to last week's, so a positioning series behaves
much more like a random walk than like a sequence of draws. Two standard procedures break on
that, in ways that look like results rather than like errors:

1. **Counting exceedances as if they were independent** (§1). A percentile threshold is
   crossed in episodes, not in isolated weeks, so an exceedance count is not a sample size.
2. **Correlating two positioning series in levels** (§2). Two near-unit-root series correlate
   strongly by chance, so a level correlation is not weak evidence of a relationship, it is
   no evidence.

Neither is a defect in this package. Both are properties of the data this package computes on,
and both have cost real time in packages downstream.

---

## 1. Percentile exceedances arrive in episodes, so a count of them is not a sample size

Measured over **117,940 scored market-weeks**, 27 markets, 2006 to 2026:

| | measured | nominal |
|---|---|---|
| share above the 95th percentile | **10.11%** | 5% |
| share below the 5th percentile | **8.90%** | 5% |

Twice the nominal rate, because the readings are serially dependent. Counting consecutive-week
episodes above the 95th percentile, per market-category:

| | |
|---|---|
| episodes | 2,477 |
| mean run length | **4.8 weeks** |
| median | 3 weeks |
| 90th percentile | 12 weeks |
| longest | 42 weeks |
| share of hot weeks inside runs of 8 or more | **57.6%** |

**A 95th-percentile positioning reading is not a one-in-twenty event. It is the middle of an
episode.**

### The consequence, which belongs to whoever is counting

**Anything treating "weeks above the 95th percentile" as a sample size has an effective sample
roughly a fifth of its nominal one.** A study with 400 exceedance weeks does not have 400
independent observations, it has something closer to 80 episodes, and any standard error,
confidence interval or p-value computed from the raw count is too tight by roughly the square
root of that ratio.

This bites hardest in validation work, where an exceedance count is a natural denominator.
The practical remedy is the one already standard in `crucible`: block-resample over calendar
time rather than over rows, with a block long enough to contain a typical episode. The
measurements above say that block wants to be at least 8 weeks and preferably longer, not the
1 to 2 that a "weekly data" framing suggests.

**This section is the single statement of the fact.** Consumers should cite it rather than
restate it: a fact and its consequence living in two repos is how one of them goes stale.

### Scope, stated because it limits the transfer

These figures were measured on a **z-score percentile panel over Managed Money positioning**,
not on this package's own COT index. The underlying cause, that positioning is slow-moving
(§2 measures a median lag-1 autocorrelation of 0.956), is a property of the same series this
package reads, so the qualitative conclusion transfers directly: **this package's index will
show episodes too.** The specific rates have not been re-measured on it.

That re-measurement is cheap and worth doing before anyone quotes 10.11% or 57.6% of a
`cotmetrics` index rather than of the panel they were measured on.

---

## 2. Correlating positioning levels is spurious

### The series is near unit-root

Lag-1 autocorrelation of Managed Money net positioning, over 25 covered markets:

| | median | min | max |
|---|---|---|---|
| levels | **0.956** | 0.784 | 0.981 |
| first differences | 0.211 | | |

A correlation between two such series is the Granger-Newbold spurious-regression problem in
textbook form.

### Measured, three ways

| test | levels | first differences |
|---|---|---|
| cross-complex pairs (n=251, true `r` should be ~0), median \|r\| | **0.395** | 0.095 |
| the same, p90 / max | 0.705 / 0.878 | 0.229 / 0.392 |
| the same, share above 0.5 | **33.5%** | **0.0%** |
| max \|r\| scanning all 25 against an INDEPENDENT random walk, median | **0.773** | 0.237 |
| the same, p95 | 0.905 | 0.333 |

**A series with no relationship to anything scores a maximum level correlation of 0.773 half
the time.**

### What it looked like in practice

The measurement was prompted by pairings that were economically absurd rather than by
suspicion of the method: Malaysian palm oil against lean hogs at **0.741**, non-fat dry milk
against palladium at **-0.666**, butter against NY Harbour ULSD at **0.693**. Those are not
anomalies needing an explanation. **They are the expected output of the procedure.**

### The rule

> **Test positioning correlation on FIRST DIFFERENCES, against a noise band computed from the
> same panel.** A level correlation is not weak evidence of a shared relationship. It is no
> evidence.

The noise band matters as much as the differencing. On differences, the cross-complex null
band has median 0.095 and p90 0.229, so a difference correlation of 0.2 is unremarkable and
one of 0.5 is not. Without the band there is no way to know which.

### Why this is stated so firmly

The analysis that produced it had led with level correlations, bolding values from -0.224 to
-0.643 as striking evidence. Those numbers were noise. Its conclusion survived only because it
had also printed the first-difference statistic, which was genuinely consistent with
independence. **That is luck rather than method**: had the level correlations come back
strongly positive by chance, a correct recommendation would have been withdrawn on the
strength of nothing.

---

## 3. An open check in this package, which is a check and not a defect report

`src/cotmetrics/indicators.py::calculate_spearman_correlation` and its vectorised twin
correlate **price levels against positioning levels**. `CotIndexer` emits **six columns per
lookback**, commercial / large / small in both raw and OI-normalised form, at each configured
lookback (`Custom`, `26`, `52`). `signals.py::_append_spearman_regime_shift_signal` reads the
commercial series at a 13-week window and thresholds its velocity.

That is the same statistical structure as §2, and **three differences mean nothing should be
concluded without measuring**:

- it asks a **within-market** question, price against positioning, not §2's cross-market
  positioning-against-positioning one;
- the windows are short, 13 to 52 points, not a full sample;
- the signal built on it thresholds *velocity* against a rolling baseline, which absorbs some
  of the level effect. The published columns carry no such treatment.

**The window length cuts the wrong way as it grows.** A longer window gives a
spurious-regression problem more room, not less, so the 52-week columns are the ones most
exposed, and they are exactly the ones a reader is most likely to treat as the reliable
version. That ordering should be checked before it is assumed either way.

**What is missing is the null.** This statistic's noise band has never been measured on this
data, while §2 has now measured a very wide band for a close relative. Until it is, there is
no way to say whether a `comms_spearman` of -0.6 is informative or ordinary.

**The settling check**, cheap and self-contained: run §2's procedure against a synthetic
independent series at each of the configured lookbacks, and report the null distribution of
the statistic per lookback. If the bands are narrow, the indicators are fine as they stand and
this section becomes a footnote. If they are wide, each column needs its band published beside
it.

**Stakes, so this is not over-read.** `npf` does not consume any of these columns; its only
`spearman` is `wfc_gate.correlation_method`, which correlates in-sample against out-of-sample
performance and touches no positioning level. These are displayed indicators in `cotmetrics`
and `cot-analyzer`, **not traded inputs**.

---

## Provenance

Both properties were measured in `crowdmon`, which is being deprecated, and are restated here
because `cotmetrics` owns the series they describe. Restated, never moved: those files are
point-in-time records under that repo's doc lifecycle and are not edited by the harvest.

| section | source | reproducer |
|---|---|---|
| §1 | `crowdmon/docs/design/amendments-2026-08-01.md` §A11 | in that section |
| §2 | `crowdmon/docs/design/amendments-2026-08-03.md` §C16 | `crowdmon/docs/analysis/reproduce.py::positioning_levels_are_spurious` |

§3 is new here: it was found while checking whether anything live does what §2 forbids.

`crowdmon/docs/HARVEST.md` is the full map of what was ported out of that package, what was
already resolved upstream, and what was parked with its hypothesis.
