"""Per-market cohort roles for the flow composite. GENERATED, do not edit by hand.

Regenerate with `python scripts/analysis/gen_flow_roles.py` (that script documents the
inputs and the rule). Generated 2026-09-26 from the measurement of 2026-09-26 in
`docs/analysis/2026-09-26-cot-cohort-roles-propadj.md`.

Why this is data and not a branch on the report type: the Producer/Merchant plus Swap
Dealer grouping the gold study called "Commercials" holds on precious metals only.
Measured Prod/Swap weekly-flow correlation is +0.40 to +0.58 on GC, SI, PL, PA and
negative on every grain, soft, livestock and energy market (docs/design/cot-flows.md,
section 2), so summing the two on corn is the difference of two opposite books. Each
market therefore names its own counterparty set, from the data, with the measurement
that produced it recorded beside it.

The measurement (`scripts/analysis/cot_cohort_roles_propadj.py`, unchanged from the
origin rule in `docs/analysis/2026-09-26-cot-cohort-roles.md`):

    px_corr      = corr(dNet_c, same-week log return of the propadj tier), full history
    gross_share  = mean over the last 52 weeks of (long_c + short_c) / total gross
    role         = RETAIL        if the cohort is nonreportable
                 = inert         if gross_share < 0.05
                 = SPEC          if px_corr >= +0.15
                 = COUNTERPARTY  if px_corr <= -0.15
                 = NEUTRAL       otherwise

Stability, fixed before the run: 156-week windows stepping 13 weeks, roles recomputed
inside each window, and `counterparty_set_stability` is the fraction of windows whose
COUNTERPARTY set equals the full-history one. Criterion, stated before any result was
read: a market's measured roles are committed when that fraction is >= 0.6 over
at least 8 windows. Otherwise the market falls back to the per-report default
below with source "default (unstable)". 21 of 42 markets pass on the
committed table. The bar is not lowered after the fact, because a softer criterion
was not pre-stated, and the generator refuses a CSV whose stable_enough flag
disagrees with this criterion.

Passes a reader may reasonably disagree with, named rather than hidden: GC passes at
exactly 0.60, the threshold itself; LBR passes at 1.00 on only 9 windows. A human may
choose the default for any of them despite the pass (one CSV edit plus a regeneration);
this module records what the criterion said, and the reasons are in the source doc.

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

On the committed table the overlap occurs for `other_reportable` on HG, OJ, SI.

Held-out symbols (EMD, NKD, MME, MFS, KE) are not measured and resolve to the
per-report default with source "default". `roles_for` never raises on an unknown
symbol for the same reason `categories._resolve` returns None: this is a read path
feeding a chart.
"""

from dataclasses import dataclass

import cotmetrics.categories as categories

MEASUREMENT_DATE = '2026-09-26'
PX_CORR_THRESHOLD = 0.15
INERT_GROSS_SHARE = 0.05
PRICE_BASIS = 'propadj'
STABILITY_MIN = 0.6
STABILITY_MIN_WINDOWS = 8
SOURCE_DOC = 'docs/analysis/2026-09-26-cot-cohort-roles-propadj.md'

SOURCE_MEASURED = "measured"
SOURCE_DEFAULT = "default"
SOURCE_UNSTABLE = "default (unstable)"

# ADR-0005 decision 1: COT-gated readings apply to physical commodities and currencies
# only. Every Disaggregated market is a physical, and on TFF only these are currencies.
TFF_CURRENCIES = frozenset(('6A', '6B', '6C', '6E', '6J', '6M', '6N', '6S', 'DX'))


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
        keys = {s.key for s in categories.categories_for(self.report)}
        buckets = (self.counterparty, self.neutral, self.inert, self.residual)
        seen = set()
        for bucket in buckets:
            for key in bucket:
                if key not in keys:
                    raise ValueError(f"{key!r} is not a {self.report} category key")
                if key in seen:
                    raise ValueError(f"{key!r} sits in two non-opinion role tuples")
                seen.add(key)
        for key in self.opinion:
            if key not in keys:
                raise ValueError(f"{key!r} is not a {self.report} category key")
        missing = keys - seen - set(self.opinion)
        if missing:
            raise ValueError(f"roles for {self.report} do not cover {sorted(missing)}")


DEFAULTS = {
    'disagg': FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_DEFAULT,
    ),
    'tff': FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_DEFAULT,
    ),
}

# One entry per non-heldout market of cotmetrics-config/params.yaml. The comment on
# each line is counterparty_set_stability over n windows and, for a fallback, the
# counterparty set the full-history measurement gave, so a reader can see what the
# criterion refused.
MEASURED = {
    # 0.27 over 70 windows, refused (full history said producer_merchant+other_reportable)
    ('disagg', 'CC'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.09 over 70 windows, refused (full history said swap+other_reportable)
    ('disagg', 'CL'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.84 over 70 windows
    ('disagg', 'CT'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant',),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('swap', 'other_reportable'),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.60 over 70 windows
    ('disagg', 'GC'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('other_reportable',),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.57 over 70 windows, refused (full history said producer_merchant)
    ('disagg', 'GF'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.39 over 70 windows, refused (full history said producer_merchant+other_reportable)
    ('disagg', 'HE'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.63 over 70 windows
    ('disagg', 'HG'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap', 'other_reportable'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.41 over 70 windows, refused (full history said producer_merchant+swap+other_reportable)
    ('disagg', 'HO'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.69 over 70 windows
    ('disagg', 'KC'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant',),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('swap', 'other_reportable'),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 1.00 over 9 windows
    ('disagg', 'LBR'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant',),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('swap',),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.80 over 70 windows
    ('disagg', 'LE'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant',),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('swap', 'other_reportable'),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.53 over 70 windows, refused (full history said producer_merchant+other_reportable)
    ('disagg', 'NG'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.97 over 70 windows
    ('disagg', 'OJ'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'other_reportable'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=('swap',),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.83 over 70 windows
    ('disagg', 'PA'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('other_reportable',),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.77 over 70 windows
    ('disagg', 'PL'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('other_reportable',),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.37 over 70 windows, refused (full history said producer_merchant+other_reportable)
    ('disagg', 'RB'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.31 over 70 windows, refused (full history said producer_merchant+swap+other_reportable)
    ('disagg', 'SB'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.87 over 70 windows
    ('disagg', 'SI'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap', 'other_reportable'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.91 over 70 windows
    ('disagg', 'ZC'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant',),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('swap', 'other_reportable'),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.80 over 70 windows
    ('disagg', 'ZL'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant',),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('swap', 'other_reportable'),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.79 over 70 windows
    ('disagg', 'ZM'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant',),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('swap', 'other_reportable'),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.61 over 70 windows
    ('disagg', 'ZS'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant',),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=('swap', 'other_reportable'),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.47 over 70 windows, refused (full history said producer_merchant+other_reportable)
    ('disagg', 'ZW'): FlowRoles(
        report='disagg',
        counterparty=('producer_merchant', 'swap'),
        opinion=('managed_money', 'other_reportable', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.66 over 70 windows
    ('tff', '6A'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=('other_reportable',),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.74 over 70 windows
    ('tff', '6B'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=('other_reportable',),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.49 over 70 windows, refused (full history said dealer)
    ('tff', '6C'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.97 over 70 windows
    ('tff', '6E'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=('other_reportable',),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.94 over 70 windows
    ('tff', '6J'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=('other_reportable',),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.71 over 70 windows
    ('tff', '6M'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=('asset_manager', 'other_reportable'),
        inert=(),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.77 over 70 windows
    ('tff', '6N'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=('leveraged',),
        inert=('other_reportable',),
        residual=(),
        state_eligible=True,
        source=SOURCE_MEASURED,
    ),
    # 0.57 over 70 windows, refused (full history said dealer)
    ('tff', '6S'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.39 over 23 windows, refused (full history said leveraged)
    ('tff', 'BTC'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
    # 0.36 over 70 windows, refused (full history said dealer)
    ('tff', 'DX'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=True,
        source=SOURCE_UNSTABLE,
    ),
    # 0.34 over 70 windows, refused (full history said leveraged)
    ('tff', 'ES'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
    # 0.27 over 11 windows, refused (full history said leveraged)
    ('tff', 'ETH'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
    # 0.47 over 70 windows, refused (full history said dealer)
    ('tff', 'NQ'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
    # 0.66 over 70 windows
    ('tff', 'RTY'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=('leveraged',),
        inert=('other_reportable',),
        residual=(),
        state_eligible=False,
        source=SOURCE_MEASURED,
    ),
    # 0.46 over 70 windows, refused (full history said none)
    ('tff', 'YM'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
    # 0.41 over 70 windows, refused (full history said dealer)
    ('tff', 'ZB'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
    # 0.33 over 70 windows, refused (full history said dealer)
    ('tff', 'ZF'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
    # 0.17 over 70 windows, refused (full history said other_reportable)
    ('tff', 'ZN'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
    # 0.17 over 70 windows, refused (full history said none)
    ('tff', 'ZT'): FlowRoles(
        report='tff',
        counterparty=('dealer',),
        opinion=('leveraged', 'asset_manager', 'nonreportable'),
        neutral=(),
        inert=(),
        residual=('other_reportable',),
        state_eligible=False,
        source=SOURCE_UNSTABLE,
    ),
}


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
