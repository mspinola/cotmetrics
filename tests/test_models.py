"""The named positioning models.

These mostly assert that the bundle cannot be taken apart, because taking it apart is
the defect the module exists to prevent: the Analysis page shaded the OI-normalized
index with the raw 95/5 CLS gate, which is a rule from no book.
"""
import pandas as pd
import pytest

import cotmetrics.constants as const
import cotmetrics.models as models
import cotmetrics.utils as utils

# Live rows, 2026-07-14, as (comm, lrg, sml) on each model's own basis.
CAD_RAW = (100, 0, 0)
ORANGE_JUICE_RAW = (96, 0, 100)   # Small Specs at 100 block the setup, near and full
COCOA_RAW = (0, 100, 80)          # Small Specs short of the gate


# ── the bundle holds together ─────────────────────────────────────────────────

def test_each_basis_belongs_to_exactly_one_model():
    """The property that makes "normalized data, raw gate" unrepresentable."""
    assert len({m.basis for m in models.MODELS}) == len(models.MODELS)
    for m in models.MODELS:
        assert models.for_basis(m.basis) is m


def test_models_are_frozen():
    with pytest.raises(Exception):
        models.RAW_PF.high = 80


def test_keys_are_unique_and_resolve():
    assert len({m.key for m in models.MODELS}) == len(models.MODELS)
    for m in models.MODELS:
        assert models.resolve(m.key) is m


def test_unknown_key_falls_back_rather_than_raising():
    """The key comes from a browser session store, so stale client state is expected."""
    assert models.resolve("no_such_model") is models.DEFAULT_MODEL
    assert models.resolve(None) is models.DEFAULT_MODEL


def test_the_app_default_is_npf():
    """NPF is the deployable book; Raw CLS 95/5 is the baseline it is measured against.

    The app opened on Raw PF while the model plumbing was being built, so that adopting
    the default changed nothing visible. That scaffolding is done.
    """
    assert models.DEFAULT_MODEL is models.NPF


def test_the_app_default_does_not_move_the_data_layer_default():
    """Different questions. get_symbols_data still defaults to raw because npf's
    deployed path calls it positionally, and flipping that would silently restate every
    deployed signal. test_basis pins the other half of this."""
    import inspect as _inspect

    from cotmetrics.CotIndexer import CotIndexer
    sig = _inspect.signature(CotIndexer.get_symbols_data.__wrapped__)
    assert sig.parameters["basis"].default == const.BASIS_RAW
    assert models.DEFAULT_MODEL.basis != const.BASIS_RAW


# ── the two models are the two books ──────────────────────────────────────────

def test_raw_pf_is_raw_cls_95_5():
    m = models.RAW_PF
    assert m.basis == const.BASIS_RAW
    assert m.spec_legs == (models.LEG_LARGE, models.LEG_SMALL)
    assert m.band == (95, 5)
    assert m.title == "Raw CLS 95/5"


def test_npf_is_oi_norm_cs_80_20():
    m = models.NPF
    assert m.basis == const.BASIS_OI_NORM
    assert m.spec_legs == (models.LEG_SMALL,)
    assert m.band == (80, 20)
    assert m.title == "NPF CS 80/20"


def test_titles_match_the_signal_matrix_headers():
    """reports.py builds its column-group headers from these, so a change here is a
    change to the emailed report."""
    assert [m.title for m in models.MODELS] == ["Raw CLS 95/5", "NPF CS 80/20"]


# ── setup_state delegates without changing the answer ─────────────────────────

@pytest.mark.parametrize("legs", [CAD_RAW, ORANGE_JUICE_RAW, COCOA_RAW])
def test_raw_pf_agrees_with_is_setup(legs):
    """is_setup stays the reference for the three-leg 95/5 case."""
    comm, lrg, sml = legs
    bull, bear, near_bull, near_bear = utils.is_setup(False, comm, lrg, sml)
    state = models.RAW_PF.setup_state(comm, lrg, sml)
    expected = (const.SETUP_BULL if bull else const.SETUP_BEAR if bear
                else const.SETUP_NEAR_BULL if near_bull
                else const.SETUP_NEAR_BEAR if near_bear else const.SETUP_NONE)
    assert state == expected


# ── "near" excludes a leg leaning against the setup ───────────────────────────
#
# A near setup used to fire when ANY one spec leg was close to its gate. That flagged
# rows whose full setup was blocked by another leg at the opposite extreme, which reads
# as "approaching" while leaning hard the other way. Now every gated leg must be on the
# setup's side of neutral: a leg past the midpoint against the setup blocks the near
# state, but a leg on the right side that is merely short of its gate does not.

def test_near_bull_excludes_a_leg_leaning_bearish():
    """Orange Juice, 2026-07-14: Comm 96, Large 0, Small 100.

    Comm is through the gate and Large is through it, but Small at 100 is leaning hard
    bearish and would need a 95-point move to support a bull setup. Under the old ANY
    rule this was SETUP_NEAR_BULL on the strength of Large alone. It is not approaching.
    """
    assert models.RAW_PF.setup_state(*ORANGE_JUICE_RAW) == const.SETUP_NONE


def test_near_bear_keeps_a_leg_short_of_its_gate_on_the_right_side():
    """Cocoa, 2026-07-14: Comm 0, Large 100, Small 80.

    Small at 80 is short of the 95 gate but still net high, leaning with a bear setup
    rather than against it. This is genuinely approaching, so it stays SETUP_NEAR_BEAR.
    An all-within-a-nudge rule would have wrongly dropped it.
    """
    assert models.RAW_PF.setup_state(*COCOA_RAW) == const.SETUP_NEAR_BEAR


def test_a_leg_past_the_midpoint_against_the_setup_denies_near():
    """Comm and Large in position for a bull, Small just over neutral -> blocked.

    Large 0 satisfies "some leg near its gate"; Small at 51 leans bearish and denies it.
    """
    assert models.RAW_PF.setup_state(92, lrg_idx=0, sml_idx=51) == const.SETUP_NONE
    # One point back onto neutral's bull side and it is approaching again.
    assert models.RAW_PF.setup_state(92, lrg_idx=0, sml_idx=50) == const.SETUP_NEAR_BULL


def test_near_still_needs_one_leg_within_reach_of_its_gate():
    """The neutral clause is added to the old rule, not a replacement for it. Both specs
    on the setup's side of neutral but neither near its gate is not approaching."""
    # Both specs low-ish (bull side) but neither within 5 of the 5 gate -> not near.
    assert models.RAW_PF.setup_state(92, lrg_idx=40, sml_idx=45) == const.SETUP_NONE
    # Bring one leg to its gate and it becomes near.
    assert models.RAW_PF.setup_state(92, lrg_idx=4, sml_idx=45) == const.SETUP_NEAR_BULL


def test_near_bear_is_symmetric():
    """One leg near the high gate and no leg below neutral is near_bear; a leg below
    neutral denies it."""
    assert models.RAW_PF.setup_state(8, lrg_idx=96, sml_idx=70) == const.SETUP_NEAR_BEAR
    assert models.RAW_PF.setup_state(8, lrg_idx=96, sml_idx=40) == const.SETUP_NONE


def test_npf_single_leg_gate_is_unaffected():
    """The CS gate has one spec leg, so "that leg near its gate" already implies "on the
    setup's side" and the neutral clause adds nothing: NPF verdicts are unchanged.
    """
    assert models.NPF.setup_state(78, sml_idx=22) == const.SETUP_NEAR_BULL
    assert models.NPF.setup_state(78, sml_idx=100) == const.SETUP_NONE
    # A Small between the gate (25) and neutral (50) was not near before and is not now.
    assert models.NPF.setup_state(78, sml_idx=40) == const.SETUP_NONE


def test_npf_ignores_the_large_leg_entirely():
    """The CS gate drops Large Specs, so a leg at the wrong extreme cannot block it.

    Under Raw PF the same row is not a setup, because there the Large leg does gate.
    """
    assert models.NPF.setup_state(10, lrg_idx=0, sml_idx=90) == const.SETUP_BEAR
    assert models.NPF.setup_state(10, lrg_idx=100, sml_idx=90) == const.SETUP_BEAR
    assert models.RAW_PF.setup_state(10, lrg_idx=0, sml_idx=90) != const.SETUP_BEAR


def test_a_leg_the_model_ignores_may_be_omitted():
    """Callers pass a whole row without knowing which model they hold."""
    assert models.NPF.setup_state(10, sml_idx=90) == const.SETUP_BEAR


def test_a_leg_the_model_needs_may_not_be_omitted():
    assert models.RAW_PF.setup_state(100, sml_idx=0) == const.SETUP_NONE


def test_equities_ignore_spec_legs_under_both_models():
    for m in models.MODELS:
        assert m.setup_state(100, lrg_idx=100, sml_idx=100, is_equity=True) == const.SETUP_BULL


# ── the gates genuinely differ ────────────────────────────────────────────────

def test_setup_masks_agrees_with_setup_state_across_a_sweep():
    """The vectorized twin feeds the POS_IDX_SETUP_* feature columns, so it has to give
    the same verdict as the scalar one every renderer styles from."""
    for m in models.MODELS:
        for comm in range(0, 101, 7):
            for lrg in range(0, 101, 11):
                for sml in range(0, 101, 13):
                    bull, bear, near_bull, near_bear = m.setup_masks(comm, lrg, sml)
                    expected = (const.SETUP_BULL if bull else const.SETUP_BEAR if bear
                                else const.SETUP_NEAR_BULL if near_bull
                                else const.SETUP_NEAR_BEAR if near_bear else const.SETUP_NONE)
                    assert m.setup_state(comm, lrg, sml) == expected, (m.key, comm, lrg, sml)


def test_setup_masks_is_vectorized():
    """It is applied to whole columns in get_symbols_data, not row by row."""
    comm = pd.Series([100, 0, 50])
    lrg = pd.Series([0, 100, 50])
    sml = pd.Series([0, 100, 50])
    bull, bear, _, _ = models.RAW_PF.setup_masks(comm, lrg, sml)
    assert list(bull) == [True, False, False]
    assert list(bear) == [False, True, False]


def test_setup_masks_drops_the_large_leg_under_npf():
    """The vectorized path honours the gate, not just the band. Gating normalized data
    with the three-leg CLS rule is the defect this module exists to prevent."""
    comm, lrg, sml = pd.Series([10]), pd.Series([0]), pd.Series([90])
    assert list(models.NPF.setup_masks(comm, lrg, sml)[1]) == [True]
    assert list(models.RAW_PF.setup_masks(comm, lrg, sml)[1]) == [False]


def test_the_band_is_wider_under_npf():
    """A row at 85 is nothing under Raw PF and a setup under NPF. If this ever stops
    being true the two models have collapsed into one."""
    assert models.RAW_PF.setup_state(85, lrg_idx=0, sml_idx=0) == const.SETUP_NONE
    assert models.NPF.setup_state(85, sml_idx=10) == const.SETUP_BULL


# ── each model owns which columns its gate reads ──────────────────────────────
#
# The defect behind these: movers.py assembled "Comm <lookback> Idx" itself and handed
# those values to a normalized model's gate. Both column families sit on every frame,
# and the lookback-named one is always raw, so under NPF the gate read one series while
# the card displayed another. Six markets were badged wrongly before it was found.

def test_each_model_names_its_own_column_family():
    """Raw PF reads the plain columns, NPF the OI-normalized twins."""
    comm, lrg, sml = models.RAW_PF.leg_columns("Custom")
    assert (comm, lrg, sml) == ("Comm Custom Idx", "Lrg Spec Custom Idx",
                                "Sml Spec Custom Idx")

    comm, lrg, sml = models.NPF.leg_columns("Custom")
    assert (comm, lrg, sml) == ("Comm Custom Idx Norm", "Lrg Spec Custom Idx Norm",
                                "Sml Spec Custom Idx Norm")


def test_the_column_family_follows_the_basis_not_the_model_name():
    """A model added later gets the right family from its basis alone."""
    for m in models.MODELS:
        normalized = m.basis == const.BASIS_OI_NORM
        assert all(c.endswith(const.NORMALIZED) == normalized
                   for c in m.leg_columns("Custom"))


def test_the_lookback_travels_into_every_column():
    for lookback in ("Custom", "26", "52"):
        assert all(f" {lookback} " in c for c in models.RAW_PF.leg_columns(lookback))


def test_setup_state_from_reads_the_family_matching_the_basis():
    """The original bug, behaviourally: one row whose two families disagree across the
    band. Reading the wrong one flips the verdict.

    Modelled on US Dollar at 2026-07-14, where the raw Commercial index read 4 and the
    normalized read 16. Here they are pushed either side of each gate so a mix-up cannot
    pass by coincidence.
    """
    row = {
        # raw family: a Raw PF bull setup (comm high, both spec legs low)
        "Comm Custom Idx": 100, "Lrg Spec Custom Idx": 2, "Sml Spec Custom Idx": 3,
        # normalized family: an NPF bear setup (comm low, small high)
        "Comm Custom Idx Norm": 5, "Lrg Spec Custom Idx Norm": 50,
        "Sml Spec Custom Idx Norm": 95,
    }
    assert models.RAW_PF.setup_state_from(row, "Custom") == const.SETUP_BULL
    assert models.NPF.setup_state_from(row, "Custom") == const.SETUP_BEAR


def test_setup_state_from_matches_passing_the_legs_by_hand():
    row = {
        "Comm Custom Idx": 97, "Lrg Spec Custom Idx": 1, "Sml Spec Custom Idx": 4,
        "Comm Custom Idx Norm": 88, "Lrg Spec Custom Idx Norm": 20,
        "Sml Spec Custom Idx Norm": 12,
    }
    for m in models.MODELS:
        comm, lrg, sml = (row[c] for c in m.leg_columns("Custom"))
        assert m.setup_state_from(row, "Custom") == m.setup_state(comm, lrg, sml)


def test_equity_rows_still_ignore_the_speculator_legs():
    """The equity carve-out survives the indirection."""
    row = {"Comm Custom Idx": 100, "Lrg Spec Custom Idx": 99, "Sml Spec Custom Idx": 99,
           "Comm Custom Idx Norm": 100, "Lrg Spec Custom Idx Norm": 99,
           "Sml Spec Custom Idx Norm": 99}
    for m in models.MODELS:
        assert m.setup_state_from(row, "Custom", is_equity=True) == const.SETUP_BULL
        assert m.setup_state_from(row, "Custom", is_equity=False) != const.SETUP_BULL


def test_a_missing_column_does_not_raise():
    """Frames from a partial fetch must degrade to no verdict, not an exception."""
    assert models.NPF.setup_state_from({}, "Custom") == const.SETUP_NONE
