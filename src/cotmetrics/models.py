"""
cotmetrics/models.py

The named positioning models, as bundles rather than loose knobs.

A positioning setup is defined by three things at once: which net-position basis the
index is built from, which speculator legs have to agree, and how far into the tail
counts as an extreme. Those three are *not* independently chosen. Each combination that
means anything comes from a book in docs/npf/surviving_books.md:

    Raw PF        raw net contracts   Commercials + Large + Small   95/5
    NPF           net / open interest Commercials + Small           80/20
    NPF CLS 95/5  net / open interest Commercials + Large + Small   95/5

Mixing across the rows produces a rule nobody validated. That was not a hypothetical:
the Analysis page drew the OI-normalized index and shaded it with the raw 95/5 CLS gate,
and get_symbols_data(basis=BASIS_OI_NORM) built its POS_IDX_SETUP_* columns the same
way. Both read as "this is a setup" under a rule that was calibrated on the other basis.

Binding the three together in one object is what stops that recurring. Callers pick a
model, never a threshold, and `basis` comes along with the gate instead of being chosen
separately somewhere else in the call stack.

The Signal Matrix is the deliberate exception: it renders both models side by side,
because comparing them is its whole job. It iterates MODELS rather than escaping the
abstraction.
"""
from dataclasses import dataclass

import cotmetrics.constants as const
import cotmetrics.utils as utils

# Speculator legs a gate can require. The names match the `lrg_idx` / `sml_idx` aliases
# get_symbols_data lands on the frame, so a model can be applied to a row by name.
LEG_LARGE = "lrg"
LEG_SMALL = "sml"


@dataclass(frozen=True)
class PositioningModel:
    """One validated (basis, gate, band) combination.

    Frozen because these are definitions, not settings. Anything that wants a different
    band wants a different model, and adding one here forces a name and a provenance for
    it rather than letting a bare number appear at a call site.
    """

    key: str            # stable id for stores, URLs and round-tripping
    label: str          # short form for column headers ("Raw", "NPF")
    gate: str           # which legs, in the books' notation ("CLS", "CS")
    basis: str          # const.BASIS_RAW or const.BASIS_OI_NORM
    spec_legs: tuple    # LEG_* required to agree, empty for a Commercials-only gate
    high: int           # upper extreme, e.g. 95
    low: int            # lower extreme, e.g. 5

    @property
    def band(self):
        """(high, low), the order report_styles and the heatmap take their bands in."""
        return (self.high, self.low)

    @property
    def title(self):
        """Full display name, e.g. "Raw CLS 95/5"."""
        return f"{self.label} {self.gate} {self.high}/{self.low}"

    def setup_state(self, comm_idx, lrg_idx=None, sml_idx=None, is_equity=False):
        """This model's verdict on one row, as a const.SETUP_* state.

        Takes all three legs and drops the ones its gate does not use, so callers can
        pass a whole row without knowing which model they hold. A leg this model ignores
        may be None.
        """
        return utils.setup_state(comm_idx, self._legs(lrg_idx, sml_idx),
                                 is_equity, self.low, self.high)

    def setup_masks(self, comm_idx, lrg_idx=None, sml_idx=None, is_equity=False):
        """Vectorized twin of setup_state, for whole columns.

        Returns (bullish, bearish, close_bullish, close_bearish) the way utils.is_setup
        always has, so the feature columns keep their four-flag shape.
        """
        return utils.is_setup(is_equity, comm_idx, lrg_idx, sml_idx,
                              min_idx=self.low, max_idx=self.high,
                              spec_idxs=self._legs(lrg_idx, sml_idx))

    def leg_columns(self, lookback):
        """The frame columns this model's gate reads, as (comm, lrg, sml).

        get_symbols_data lands BOTH the raw and the OI-normalized families on every
        frame whatever basis it was asked for, and only the generic aliases follow the
        basis. So a caller holding any frame can gate any model, but only if it names
        the right family, and a caller holding a frame fetched on one basis cannot use
        the aliases to gate a model on the other.

        That is why this lives here. Two call sites were independently deciding which
        columns a model gates on: movers.py read the lookback-named columns, which are
        raw whatever the basis, and it shipped a real defect for it. reports.py names
        the normalized twins explicitly and was correct, but by its own separate
        reasoning. One expression of the rule, next to the basis it follows.

        Returns all three legs even for gates that ignore one. setup_state drops the
        ones spec_legs does not name, so callers do not have to.
        """
        stem = " " + lookback + const.IDX
        suffix = const.NORMALIZED if self.basis == const.BASIS_OI_NORM else ""
        return (const.COMM + stem + suffix,
                const.LARGE + stem + suffix,
                const.SMALL + stem + suffix)

    def setup_state_from(self, row, lookback, is_equity=False):
        """This model's verdict on a frame row, reading its own columns off it.

        The pairing of leg_columns with setup_state, so a caller cannot get one right
        and the other wrong.
        """
        comm, lrg, sml = (row.get(c) for c in self.leg_columns(lookback))
        return self.setup_state(comm, lrg, sml, is_equity)

    def setup_age_from(self, frame, lookback, is_equity=False,
                       cap=const.SETUP_AGE_CAP):
        """How many consecutive weeks the last row of `frame` has held its story.

        0 when that row is not at or approaching a gate. Otherwise the count of weeks,
        walking back, that stayed in the SAME DIRECTION at THIS TIER OR STRONGER. So a
        market that spent five weeks approaching a bull gate and fired this week reads
        1, because its setup is one week old; a market that fired eight weeks ago and
        has since relaxed to approaching reads 9, because it has been telling the same
        story throughout. The badge already says which tier it is in now, and this says
        how long it has been there or better.

        The alternative -- counting any non-neutral week, so NEAR and SETUP are one run
        -- was rejected because it makes a setup that fired this week read as six weeks
        old, and "is this new" is the question the number exists to answer.

        `cap` bounds the walk rather than the answer, and a capped count is returned as
        the cap, so a view displaying the number reads `const.SETUP_AGE_CAP` as "at
        least". See that constant for why it sits where it does.
        """
        if frame is None or len(frame) == 0:
            return 0
        state = self.setup_state_from(frame.iloc[-1], lookback, is_equity)
        if state == const.SETUP_NONE:
            return 0
        bullish = state in (const.SETUP_BULL, const.SETUP_NEAR_BULL)
        same_direction = ((const.SETUP_BULL, const.SETUP_NEAR_BULL) if bullish
                          else (const.SETUP_BEAR, const.SETUP_NEAR_BEAR))
        # A full state also counts for a near row, which is the "or stronger" half.
        wanted = (same_direction if state in const.SETUP_NEAR_STATES
                  else (same_direction[0],))
        weeks = 0
        for i in range(len(frame) - 1, -1, -1):
            if self.setup_state_from(frame.iloc[i], lookback, is_equity) not in wanted:
                break
            weeks += 1
            if weeks >= cap:
                break
        return weeks

    def _legs(self, lrg_idx, sml_idx):
        """The legs this model's gate actually uses, in a fixed order."""
        available = {LEG_LARGE: lrg_idx, LEG_SMALL: sml_idx}
        return [available[leg] for leg in self.spec_legs]


# The Raw PF baseline: net contracts, all three legs, 95/5. What every surface in the
# app spoke before the models existed, and what the npf research calls the baseline the
# deployable book is measured against. Still reachable everywhere, no longer the default.
RAW_PF = PositioningModel(
    key="raw_pf", label="Raw", gate="CLS", basis=const.BASIS_RAW,
    spec_legs=(LEG_LARGE, LEG_SMALL),
    high=const.INDEX_HIGH_THRESHOLD, low=const.INDEX_LOW_THRESHOLD,
)

# NPF, the deployable headline. Dividing net by open interest strips the secular growth
# in contract size, so the normalized series spends far less time pinned at the ends of
# its own range and 95/5 would almost never fire. The CS gate drops the Large Spec leg.
NPF = PositioningModel(
    key="npf", label="NPF", gate="CS", basis=const.BASIS_OI_NORM,
    spec_legs=(LEG_SMALL,),
    high=const.INDEX_NORM_HIGH_THRESHOLD, low=const.INDEX_NORM_LOW_THRESHOLD,
)

# NPF CLS 95/5, the tight-band OI-normalized book from the same table in
# surviving_books.md: highest per-trade expectancy and the shallowest drawdowns of the
# family, but too few forward-test trades to deploy standalone, which is why NPF CS
# 80/20 stayed the headline. It is here so the app can draw its verdicts beside the
# other two, not because its status changed. Because the band is 95/5 on a series that
# rarely pins its own extremes, expect it to fire far less often than either neighbour.
NPF_CLS_95_5 = PositioningModel(
    key="npf_cls_95_5", label="NPF", gate="CLS", basis=const.BASIS_OI_NORM,
    spec_legs=(LEG_LARGE, LEG_SMALL),
    high=const.INDEX_HIGH_THRESHOLD, low=const.INDEX_LOW_THRESHOLD,
)

MODELS = (RAW_PF, NPF, NPF_CLS_95_5)
_BY_KEY = {m.key: m for m in MODELS}
# Basis OWNERSHIP, not mere membership, and explicit now that two models share the
# OI-normalized basis. for_basis answers for callers whose basis is already fixed by
# something else (the data layer's POS_IDX_SETUP_* columns, the Analysis page's shading,
# the Both overlay's fallback), and those callers must keep getting the book that was
# always behind that basis: NPF for OI-normalized, because it is the deployable headline
# and handing them the CLS variant would silently restate every derived setup column.
_BY_BASIS = {RAW_PF.basis: RAW_PF, NPF.basis: NPF}

# NPF is the default the app opens on, because it is the book that is actually
# deployable: Raw CLS 95/5 is the baseline NPF is measured *against*, not the thing to
# trade. On the board at the time of the switch it fired on 7 of 42 markets against Raw
# PF's 4, and contained all 4, so nothing the old default surfaced was lost.
#
# This is the app's reading default only. It is deliberately NOT the data layer's:
# get_symbols_data still defaults to BASIS_RAW, because npf's deployed path calls it
# positionally and changing that would silently restate every deployed signal. The two
# defaults answer different questions and are pinned by separate tests.
DEFAULT_MODEL = NPF


def resolve(key):
    """Model for a key, falling back to the default rather than raising.

    The key arrives from a browser session store, so an unknown one means stale client
    state, not a bug worth taking the page down over.
    """
    return _BY_KEY.get(key, DEFAULT_MODEL)


def for_basis(basis):
    """The model that OWNS a basis, which since NPF CLS 95/5 is no longer the only
    model on it.

    Used where the basis is already fixed by something else, such as a chart panel the
    user picked a basis for, and the answer is pinned to the book that has always
    governed that basis (see _BY_BASIS). A caller who means a specific model resolves
    it by key instead.
    """
    return _BY_BASIS.get(basis, DEFAULT_MODEL)
