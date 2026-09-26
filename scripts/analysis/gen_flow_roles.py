"""Regenerate `src/cotmetrics/flow_roles.py` from the propadj cohort-role measurement.

The module it writes is data: which cohorts form the counterparty composite on each
market, which are neutral, which are inert, and whether the market may carry a flow
state under ADR-0005. Nothing in it is typed by hand, so that a re-measurement (a new
year of data, a different threshold decided in advance) is one command and one diff
rather than 42 edits with a typo in one of them.

Inputs, both written by `scripts/analysis/cot_cohort_roles_propadj.py`:

    docs/analysis/2026-09-26-cot-cohort-collapse-propadj.csv
        one row per (report, symbol): COUNTERPARTY_keys, NEUTRAL_keys, inert_keys, ...
    docs/analysis/2026-09-26-cot-cohort-roles-stability.csv
        one row per (report, symbol, cohort): counterparty_set_stability, n_windows,
        stable_enough (the pre-stated criterion, applied by that script)

Rule applied here, and only here (the design in docs/design/cot-flows.md section 3):
a market whose `stable_enough` is True gets its measured counterparty, neutral and
inert sets. A market that fails falls back to the per-report default with source
"default (unstable)". The opinion triple is the per-report default on every market so
the state vocabulary keeps its meaning. `residual` is whatever key is in none of the
other four, which on the committed table is always empty but is computed rather than
assumed. `state_eligible` is True on every Disaggregated market and on the TFF
currencies, False on equities, rates and crypto (ADR-0005 decision 1).

Usage (from the cotmetrics checkout):

    python scripts/analysis/gen_flow_roles.py

writes the module in place and prints one line per entry.
"""

import argparse
import os
import textwrap
from datetime import date

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

COLLAPSE_CSV = os.path.join(ROOT, "docs", "analysis",
                            "2026-09-26-cot-cohort-collapse-propadj.csv")
STABILITY_CSV = os.path.join(ROOT, "docs", "analysis",
                             "2026-09-26-cot-cohort-roles-stability.csv")
SOURCE_DOC = "docs/analysis/2026-09-26-cot-cohort-roles-propadj.md"
OUT = os.path.join(ROOT, "src", "cotmetrics", "flow_roles.py")

MEASUREMENT_DATE = "2026-09-26"
PX_CORR_THRESHOLD = 0.15
INERT_GROSS_SHARE = 0.05
PRICE_BASIS = "propadj"
STABILITY_MIN = 0.6
STABILITY_MIN_WINDOWS = 8

# ADR-0005 decision 1: COT-gated readings apply to physical commodities and currencies.
# Every Disaggregated market is a physical, and on TFF only these are currencies.
TFF_CURRENCIES = ("6A", "6B", "6C", "6E", "6J", "6M", "6N", "6S", "DX")

# The per-report defaults from docs/design/cot-flows.md section 3, in category KEY
# vocabulary (cotmetrics.categories). The opinion triple's ORDER is the state triple's
# order: (managed_money, other_reportable, nonreportable) is the gold script's
# (MM, Other, NonRep).
DEFAULTS = {
    "disagg": dict(counterparty=("producer_merchant", "swap"),
                   opinion=("managed_money", "other_reportable", "nonreportable"),
                   neutral=(), inert=(), residual=()),
    "tff": dict(counterparty=("dealer",),
                opinion=("leveraged", "asset_manager", "nonreportable"),
                neutral=(), inert=(), residual=("other_reportable",)),
}

ALL_KEYS = {
    "disagg": ("producer_merchant", "swap", "managed_money", "other_reportable",
               "nonreportable"),
    "tff": ("dealer", "asset_manager", "leveraged", "other_reportable", "nonreportable"),
}


def _keys(cell):
    if pd.isna(cell) or str(cell).strip() in ("", "-"):
        return ()
    return tuple(str(cell).split("+"))


def _fmt(t):
    return "(" + "".join(f"{k!r}, " for k in t).rstrip(", ") + ("," if len(t) == 1 else "") + ")"


def build_entries(collapse, stability):
    stab = (stability.groupby(["report", "sym"])
            .agg(n_windows=("n_windows", "first"),
                 cp_stability=("counterparty_set_stability", "first"),
                 stable=("stable_enough", "first"))
            .reset_index())
    merged = collapse.merge(stab, on=["report", "sym"], how="left", validate="1:1")
    entries = []
    for row in merged.sort_values(["report", "sym"]).itertuples(index=False):
        report, sym = row.report, row.sym
        default = DEFAULTS[report]
        eligible = report == "disagg" or sym in TFF_CURRENCIES
        # The CSV's stable_enough flag was computed by the measurement script. Re-apply
        # the criterion recorded in this module's header and refuse a disagreement, so
        # the header can never describe a bar the table was not built under.
        stable = (float(row.cp_stability) >= STABILITY_MIN
                  and int(row.n_windows) >= STABILITY_MIN_WINDOWS)
        if bool(row.stable) != stable:
            raise ValueError(
                f"{report} {sym}: stable_enough={row.stable} in the CSV disagrees with "
                f"the recorded criterion (>= {STABILITY_MIN} over >= "
                f"{STABILITY_MIN_WINDOWS} windows) at {row.cp_stability} over "
                f"{row.n_windows} windows")
        if stable:
            counterparty = _keys(row.COUNTERPARTY_keys)
            neutral = _keys(row.NEUTRAL_keys)
            inert = _keys(row.inert_keys)
            opinion = default["opinion"]
            taken = set(counterparty) | set(neutral) | set(inert) | set(opinion)
            residual = tuple(k for k in ALL_KEYS[report] if k not in taken)
            source = "measured"
        else:
            counterparty, neutral, inert = (default["counterparty"], default["neutral"],
                                            default["inert"])
            opinion, residual = default["opinion"], default["residual"]
            source = "default (unstable)"
        entries.append(dict(
            report=report, symbol=sym, counterparty=counterparty, opinion=opinion,
            neutral=neutral, inert=inert, residual=residual, state_eligible=eligible,
            source=source, cp_stability=float(row.cp_stability),
            n_windows=int(row.n_windows), measured_counterparty=_keys(row.COUNTERPARTY_keys),
        ))
    return entries


HEADER = '''"""Per-market cohort roles for the flow composite. GENERATED, do not edit by hand.

Regenerate with `python scripts/analysis/gen_flow_roles.py` (that script documents the
inputs and the rule). Generated {today} from the measurement of {measured} in
`{source_doc}`.

Why this is data and not a branch on the report type: the Producer/Merchant plus Swap
Dealer grouping the gold study called "Commercials" holds on precious metals only.
Measured Prod/Swap weekly-flow correlation is +0.40 to +0.58 on GC, SI, PL, PA and
negative on every grain, soft, livestock and energy market (docs/design/cot-flows.md,
section 2), so summing the two on corn is the difference of two opposite books. Each
market therefore names its own counterparty set, from the data, with the measurement
that produced it recorded beside it.

The measurement (`scripts/analysis/cot_cohort_roles_propadj.py`, unchanged from the
origin rule in `docs/analysis/2026-09-26-cot-cohort-roles.md`):

    px_corr      = corr(dNet_c, same-week log return of the {basis} tier), full history
    gross_share  = mean over the last 52 weeks of (long_c + short_c) / total gross
    role         = RETAIL        if the cohort is nonreportable
                 = inert         if gross_share < {inert}
                 = SPEC          if px_corr >= +{thr}
                 = COUNTERPARTY  if px_corr <= -{thr}
                 = NEUTRAL       otherwise

Stability, fixed before the run: 156-week windows stepping 13 weeks, roles recomputed
inside each window, and `counterparty_set_stability` is the fraction of windows whose
COUNTERPARTY set equals the full-history one. Criterion, stated before any result was
read: a market's measured roles are committed when that fraction is >= {stab_min} over
at least {stab_n} windows. Otherwise the market falls back to the per-report default
below with source "default (unstable)". {n_pass} of {n_total} markets pass on the
committed table. The bar is not lowered after the fact, because a softer criterion
was not pre-stated, and the generator refuses a CSV whose stable_enough flag
disagrees with this criterion.

{edge_paragraph}

What the flow module reads from an entry: `counterparty` (the composite's members)
and `state_eligible`. The `opinion` triple is the per-report default on EVERY entry,
measured or not, because the eight-state vocabulary was defined and tested on it
(the universe run and the pre-registered branch both used it) and a per-market
triple would silently change what a state name means. `neutral`, `inert` and
`residual` are recorded so the table covers every category and a reader can see
where a cohort went. Nothing computes on them yet.

Invariant, pinned by tests/test_flows.py: counterparty, neutral, inert and residual
partition the category keys that are not opinion cohorts, and every key is in the
opinion triple or in exactly one of those four, or both. The overlap is by design:
where a measured counterparty includes an opinion cohort, that cohort is BOTH a
member of the composite AND one of the three opinion cohorts, because the vocabulary
keeps its meaning while the composite follows the market. A key never sits in two of
the four non-opinion tuples.

{overlap_paragraph}

Held-out symbols (EMD, NKD, MME, MFS, KE) are not measured and resolve to the
per-report default with source "default". `roles_for` never raises on an unknown
symbol for the same reason `categories._resolve` returns None: this is a read path
feeding a chart.
"""

from dataclasses import dataclass

import cotmetrics.categories as categories

MEASUREMENT_DATE = {measured!r}
PX_CORR_THRESHOLD = {thr}
INERT_GROSS_SHARE = {inert}
PRICE_BASIS = {basis!r}
STABILITY_MIN = {stab_min}
STABILITY_MIN_WINDOWS = {stab_n}
SOURCE_DOC = {source_doc!r}

SOURCE_MEASURED = "measured"
SOURCE_DEFAULT = "default"
SOURCE_UNSTABLE = "default (unstable)"

# ADR-0005 decision 1: COT-gated readings apply to physical commodities and currencies
# only. Every Disaggregated market is a physical, and on TFF only these are currencies.
TFF_CURRENCIES = frozenset({currencies!r})


@dataclass(frozen=True)
class FlowRoles:
    """Which category keys play which role on one market.

    Keys are `cotmetrics.categories` CategorySpec keys (producer_merchant, swap,
    managed_money, other_reportable, nonreportable on Disaggregated, and dealer,
    asset_manager, leveraged, other_reportable, nonreportable on TFF). `opinion` is
    ordered: it is the state triple's order. `source` says where the entry came from:
    SOURCE_MEASURED, SOURCE_DEFAULT or SOURCE_UNSTABLE.
    """

    report: str
    counterparty: tuple
    opinion: tuple
    neutral: tuple
    inert: tuple
    residual: tuple
    state_eligible: bool
    source: str

    def __post_init__(self):
        # Fail at import rather than at the first chart: a regenerated table with a
        # key in two buckets would otherwise double-count a cohort in the composite.
        keys = {{s.key for s in categories.categories_for(self.report)}}
        buckets = (self.counterparty, self.neutral, self.inert, self.residual)
        seen = set()
        for bucket in buckets:
            for key in bucket:
                if key not in keys:
                    raise ValueError(f"{{key!r}} is not a {{self.report}} category key")
                if key in seen:
                    raise ValueError(f"{{key!r}} sits in two non-opinion role tuples")
                seen.add(key)
        for key in self.opinion:
            if key not in keys:
                raise ValueError(f"{{key!r}} is not a {{self.report}} category key")
        missing = keys - seen - set(self.opinion)
        if missing:
            raise ValueError(f"roles for {{self.report}} do not cover {{sorted(missing)}}")


DEFAULTS = {{
{defaults}}}

# One entry per non-heldout market of cotmetrics-config/params.yaml. The comment on
# each line is counterparty_set_stability over n windows and, for a fallback, the
# counterparty set the full-history measurement gave, so a reader can see what the
# criterion refused.
MEASURED = {{
{measured_entries}}}


def roles_for(report, symbol=None):
    """The roles for one market, or the per-report default when it is not measured.

    Never raises on an unknown symbol: a held-out or newly registered market gets the
    default composite and the caller's chart still draws.
    """
    if symbol is not None:
        entry = MEASURED.get((report, symbol))
        if entry is not None:
            return entry
    categories.categories_for(report)  # raises ValueError naming REPORT_CHOICES
    return DEFAULTS[report]
'''


# A measured pass resting on fewer windows than this is named in the header so a
# reader sees how short its history is (LBR's propadj bars start 2022-08-08).
FEW_WINDOWS = 20


def _wrap(text):
    return textwrap.fill(text, width=88)


def _edge_paragraph(entries):
    """The passes a reader may reasonably disagree with, computed, never typed."""
    measured = [e for e in entries if e["source"] == "measured"]
    items = []
    for e in measured:
        if e["cp_stability"] == STABILITY_MIN:
            items.append(f"{e['symbol']} passes at exactly {e['cp_stability']:.2f}, the "
                         f"threshold itself")
    for e in measured:
        if e["n_windows"] < FEW_WINDOWS:
            items.append(f"{e['symbol']} passes at {e['cp_stability']:.2f} on only "
                         f"{e['n_windows']} windows")
    if not items:
        return _wrap("No measured entry sits on the threshold or rests on fewer than "
                     f"{FEW_WINDOWS} windows.")
    return _wrap("Passes a reader may reasonably disagree with, named rather than hidden: "
                 + "; ".join(items) + ". A human may choose the default for any of them "
                 "despite the pass (one CSV edit plus a regeneration); this module records "
                 "what the criterion said, and the reasons are in the source doc.")


def _overlap_paragraph(entries):
    """Which measured counterparties include an opinion cohort, on this table."""
    by_key = {}
    for e in entries:
        if e["source"] != "measured":
            continue
        for key in e["counterparty"]:
            if key in e["opinion"]:
                by_key.setdefault(key, []).append(e["symbol"])
    if not by_key:
        return _wrap("On the committed table no measured counterparty includes an opinion "
                     "cohort, so the overlap is allowed but unused.")
    parts = [f"`{key}` on {', '.join(syms)}" for key, syms in sorted(by_key.items())]
    return _wrap("On the committed table the overlap occurs for " + "; ".join(parts) + ".")


def render(entries):
    defaults = ""
    for report, d in DEFAULTS.items():
        eligible = report == "disagg"
        defaults += (
            f"    {report!r}: FlowRoles(\n"
            f"        report={report!r},\n"
            f"        counterparty={_fmt(d['counterparty'])},\n"
            f"        opinion={_fmt(d['opinion'])},\n"
            f"        neutral={_fmt(d['neutral'])},\n"
            f"        inert={_fmt(d['inert'])},\n"
            f"        residual={_fmt(d['residual'])},\n"
            f"        state_eligible={eligible},\n"
            f"        source=SOURCE_DEFAULT,\n"
            f"    ),\n"
        )
    body = ""
    for e in entries:
        src = "SOURCE_MEASURED" if e["source"] == "measured" else "SOURCE_UNSTABLE"
        note = f"{e['cp_stability']:.2f} over {e['n_windows']} windows"
        if e["source"] != "measured":
            mc = "+".join(e["measured_counterparty"]) or "none"
            note += f", refused (full history said {mc})"
        body += (
            f"    # {note}\n"
            f"    ({e['report']!r}, {e['symbol']!r}): FlowRoles(\n"
            f"        report={e['report']!r},\n"
            f"        counterparty={_fmt(e['counterparty'])},\n"
            f"        opinion={_fmt(e['opinion'])},\n"
            f"        neutral={_fmt(e['neutral'])},\n"
            f"        inert={_fmt(e['inert'])},\n"
            f"        residual={_fmt(e['residual'])},\n"
            f"        state_eligible={e['state_eligible']},\n"
            f"        source={src},\n"
            f"    ),\n"
        )
    return HEADER.format(
        today=date.today().isoformat(), measured=MEASUREMENT_DATE, source_doc=SOURCE_DOC,
        basis=PRICE_BASIS, inert=INERT_GROSS_SHARE, thr=PX_CORR_THRESHOLD,
        stab_min=STABILITY_MIN, stab_n=STABILITY_MIN_WINDOWS,
        n_pass=sum(e["source"] == "measured" for e in entries), n_total=len(entries),
        edge_paragraph=_edge_paragraph(entries),
        overlap_paragraph=_overlap_paragraph(entries),
        currencies=tuple(sorted(TFF_CURRENCIES)),
        defaults=defaults, measured_entries=body,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--collapse", default=COLLAPSE_CSV)
    ap.add_argument("--stability", default=STABILITY_CSV)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    collapse = pd.read_csv(args.collapse)
    stability = pd.read_csv(args.stability)
    entries = build_entries(collapse, stability)
    with open(args.out, "w") as f:
        f.write(render(entries))
    for e in entries:
        print(f"{e['report']:6s} {e['symbol']:4s} {e['source']:20s} "
              f"counterparty={'+'.join(e['counterparty'])} "
              f"state_eligible={e['state_eligible']}")
    print(f"wrote {args.out} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
