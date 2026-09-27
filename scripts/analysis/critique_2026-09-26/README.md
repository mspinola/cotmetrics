# Reproducers for the 2026-09-26 critique of the gold COT flow-states study

These scripts back the figures quoted in `docs/design/cot-flows.md` section 2 and in the
verification of `docs/analysis/2026-09-26-cot-flow-states-gold.md`. They were written by
verification agents during the 2026-09-26 review session and are kept as they ran, with
each script's printed output beside it (`<name>.out.txt`), so every number quoted from
them has a file to point at. Paths to the store, the price cache and the gold reproducer
are absolute workspace paths; `coverage.py` writes `coverage.json` beside itself.

Run from this directory with the npf venv and the store variables set:

```bash
cd cotmetrics/scripts/analysis/critique_2026-09-26 && COTDATA_STORE=~/code/cotdata_store \
  MARKETDATA_STORE=~/code/marketdata_store COTMETRICS_PARAMS=../../../../cotmetrics-config/params.yaml \
  ../../../../npf/.venv/bin/python <script>.py
```

| script | what it measures | headline in its output |
|---|---|---|
| `overlap_null.py` | the naive t of an h-week overlapping forward return under an iid null (seed 0, 4,000 sims) | sd 3.63 at h=13 and 2.01 at h=4; P(abs t > 1.96) 59% and 34% |
| `alts.py` | gold VALUE_ACCUM restated: excess over the unconditional, Newey-West lag 12, thinned non-overlapping n, crucible `block_bootstrap_pvalue` and `block_bootstrap_ci` at block 13 (seed 0) | excess +0.95%, HAC t 0.76, thinned n=16, p 0.22, CI [-1.69, +3.29]% |
| `serial.py` | inter-firing gaps and autocorrelation on gold | 6 of 20 VALUE_ACCUM gaps shorter than 13 weeks |
| `anchor.py` | the Tuesday-to-Friday leg on gold from the marketdata daily bars, and its share of forward-return variance | leg mean +0.07%, 17% of the 4-week variance, 5.6% of the 13-week |
| `refute_runs.py` | weeks against episodes for every named state over 42 markets | weeks per episode 1.00 to 1.07; the states do not run |
| `coverage.py` | per-market coverage, stitching seams, the identity, small-OI sigmas, lag-1 autocorrelation of dNet | LBR and RTY seams; identity exact on 42 of 42 |
| `part2.py` | LBR and RTY gap detail, the supplemental report's basis, cross-cohort dNet correlations, vintage revisions | FX dealers absorb both leveraged and asset-manager flow; rates leveraged against asset manager -0.67 |
| `normaliser.py` | four normalisers compared across the 23 physicals | dNet / rolling sd comparable by construction; rolling sd tracks OI at log-corr 0.71 |
| `state_basis.py` | state labels on contracts against percent-of-OI | labels differ on 14.8% of market-weeks |
| `refute_consequence.py` | which sub-cohort of Commercials absorbs managed-money flow, per market | swap dealers in six markets (GC, PA, PL, SI, CL, NG), producer/merchant elsewhere |
| `window_check.py` | flow z under the fixed 52/26 window against the page's per-market lookback | how many one-sigma signs differ when the lookback reaches the window |

None of these is a search: each is one descriptive look, and the plan doc counts them
toward the denominator of any later gauntlet. cotmetrics does not lint `scripts/`, and
these keep the single-letter style they were written in.
