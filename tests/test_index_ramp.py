"""Signal Matrix index colouring, driven by the row's setup state.

A positioning index only means something in the company of the other legs, so these
tests are mostly about rows rather than cells. Several encode failures found in review:

  - colouring a cell on its own level lit blocking legs (Feeder Cattle, Orange Juice)
  - grading the wash by depth made one real setup look weaker than another (NZD vs CAD)
  - a ramp anchored to neutral coloured 78% of the grid
"""
import pytest

import cotmetrics.constants as const
import cotmetrics.utils as utils
from cotmetrics.report_styles import (
    _BEAR,
    _BG,
    _BULL,
    _DIM,
    _YELLOW,
    _blend,
    _cell_style,
    _leg_agrees,
    _setup_cell_style,
)

RAW = (const.INDEX_HIGH_THRESHOLD, const.INDEX_LOW_THRESHOLD)             # 95 / 5
NORM = (const.INDEX_NORM_HIGH_THRESHOLD, const.INDEX_NORM_LOW_THRESHOLD)  # 80 / 20

# Live rows, 2026-07-14. Legs are (comm, lrg, sml) for CLS, (comm, sml) for NPF CS.
CAD = (100, 0, 0)            # setup
NZD = (97, 3, 5)             # setup, only just
FEEDER_CATTLE = (100, 0, 100)  # small specs blocking
ORANGE_JUICE = (96, 0, 100)    # two legs through, small specs at the opposite extreme
COCOA = (0, 100, 80)         # near bear, small specs short of the gate
COFFEE = (0, 100, 88)        # near bear on CLS
LUMBER = (35, 62, 79)        # nothing


def _wash(style):
    return "background-color" in style


def _is_dim(style):
    return _DIM in style


def _cls(legs, is_equity=False):
    comm, lrg, sml = legs
    return utils.setup_state(comm, [lrg, sml], is_equity, *reversed(RAW))


# ── setup_state agrees with is_setup ──────────────────────────────────────────

def test_setup_state_matches_is_setup_across_a_sweep():
    """is_setup is the reference. setup_state only generalizes it."""
    for comm in range(0, 101, 7):
        for lrg in range(0, 101, 11):
            for sml in range(0, 101, 13):
                bull, bear, near_bull, near_bear = utils.is_setup(False, comm, lrg, sml)
                state = _cls((comm, lrg, sml))
                if bull:
                    assert state == const.SETUP_BULL, (comm, lrg, sml)
                elif bear:
                    assert state == const.SETUP_BEAR, (comm, lrg, sml)
                elif near_bull:
                    assert state == const.SETUP_NEAR_BULL, (comm, lrg, sml)
                elif near_bear:
                    assert state == const.SETUP_NEAR_BEAR, (comm, lrg, sml)
                else:
                    assert state == const.SETUP_NONE, (comm, lrg, sml)


def test_full_setup_wins_over_near():
    assert _cls(CAD) == const.SETUP_BULL


def test_equities_ignore_the_spec_legs():
    """is_setup applies its spec filters only `if not is_equity`."""
    blocked = FEEDER_CATTLE                      # comm 100, sml 100
    assert _cls(blocked) != const.SETUP_BULL
    assert _cls(blocked, is_equity=True) == const.SETUP_BULL


def test_cs_gate_drops_the_large_spec_leg():
    """The NPF CS gate is Commercials plus Small only, at 80/20."""
    assert utils.setup_state(0, [90], False, *reversed(NORM)) == const.SETUP_BEAR
    assert utils.setup_state(0, [79], False, *reversed(NORM)) == const.SETUP_NEAR_BEAR


# ── a setup is a setup ────────────────────────────────────────────────────────

def test_two_real_setups_render_identically():
    """NZD (97, 3, 5) and CAD (100, 0, 0) are both setups. No lesser setups."""
    for legs in (CAD, NZD):
        assert _cls(legs) == const.SETUP_BULL
    roles = ("comm", "spec", "spec")
    for i, role in enumerate(roles):
        a = _setup_cell_style(CAD[i], const.SETUP_BULL, role, *RAW)
        b = _setup_cell_style(NZD[i], const.SETUP_BULL, role, *RAW)
        assert a == b, f"leg {i} rendered differently"


def test_a_full_setup_washes_every_leg():
    for i, role in enumerate(("comm", "spec", "spec")):
        assert _wash(_setup_cell_style(NZD[i], const.SETUP_BULL, role, *RAW))


def test_value_does_not_grade_within_a_setup():
    """Once the row is a setup, how deep a leg sits is irrelevant."""
    seen = {_setup_cell_style(v, const.SETUP_BULL, "comm", *RAW) for v in range(95, 101)}
    assert len(seen) == 1


# ── incomplete setups do not get the full highlight ───────────────────────────

def test_orange_juice_is_neutral():
    """(96, 0, 100): Commercials and Large Specs are through, but Small Specs at 100 are
    leaning hard bearish, against a bull setup.

    This used to render as near_bull (and, scored per cell, as two fully-washed green
    cells) on the strength of Large alone. A near setup now excludes any leg past neutral
    on the wrong side, so Small at 100 makes the whole row neutral. Nothing washes, and
    every cell is dim, exactly like any other quiet row.
    """
    state = _cls(ORANGE_JUICE)
    assert state == const.SETUP_NONE
    for i, role in enumerate(("comm", "spec", "spec")):
        style = _setup_cell_style(ORANGE_JUICE[i], state, role, *RAW)
        assert not _wash(style)
        assert _is_dim(style)


def test_feeder_cattle_does_not_wash():
    state = _cls(FEEDER_CATTLE)
    assert state != const.SETUP_BULL
    for i, role in enumerate(("comm", "spec", "spec")):
        assert not _wash(_setup_cell_style(FEEDER_CATTLE[i], state, role, *RAW))


@pytest.mark.parametrize("legs", [COCOA, COFFEE])
def test_near_bear_rows_tint_without_washing(legs):
    state = _cls(legs)
    assert state == const.SETUP_NEAR_BEAR
    styles = [_setup_cell_style(v, state, r, *RAW)
              for v, r in zip(legs, ("comm", "spec", "spec"))]
    assert not any(_wash(s) for s in styles), "a near setup must never wash"
    assert not all(_is_dim(s) for s in styles), "a near setup must stay visible"


def test_the_blocking_leg_stays_neutral():
    """Cocoa (0, 100, 80): Commercials and Large Specs are close, Small Specs are not.

    The dim cell is the reason the setup has not fired, which is worth reading.
    """
    state = _cls(COCOA)
    assert not _is_dim(_setup_cell_style(COCOA[0], state, "comm", *RAW))
    assert not _is_dim(_setup_cell_style(COCOA[1], state, "spec", *RAW))
    assert _is_dim(_setup_cell_style(COCOA[2], state, "spec", *RAW))


def test_a_quiet_row_is_entirely_neutral():
    state = _cls(LUMBER)
    assert state == const.SETUP_NONE
    for i, role in enumerate(("comm", "spec", "spec")):
        assert _is_dim(_setup_cell_style(LUMBER[i], state, role, *RAW))


# ── equities ──────────────────────────────────────────────────────────────────

def test_equity_setup_washes_the_band_except_legs_that_disagree():
    """Spec legs do not gate an equity setup, so lighting Commercials alone would
    understate it -- but a leg pointing the other way must not be washed either.

    Feeder Cattle as an equity is a bull setup on Commercials alone (100), with Large
    Specs washed out at 0 agreeing and Small Specs crowded long at 100 disagreeing.
    """
    state = _cls(FEEDER_CATTLE, is_equity=True)
    assert state == const.SETUP_BULL
    assert _wash(_setup_cell_style(FEEDER_CATTLE[0], state, "comm", *RAW, is_equity=True))
    assert _wash(_setup_cell_style(FEEDER_CATTLE[1], state, "spec", *RAW, is_equity=True))
    assert _is_dim(_setup_cell_style(FEEDER_CATTLE[2], state, "spec", *RAW, is_equity=True))


def test_equity_spec_legs_never_tint_on_a_near_state():
    style = _setup_cell_style(3, const.SETUP_NEAR_BULL, "spec", *RAW, is_equity=True)
    assert _is_dim(style)


# ── colour stays rare ─────────────────────────────────────────────────────────

def test_colour_requires_a_setup_state():
    """Regression guard on the 78%-coloured grid. No state, no colour, at any level."""
    for v in (0, 3, 50, 88, 97, 100):
        assert _is_dim(_setup_cell_style(v, const.SETUP_NONE, "comm", *RAW))
        assert _is_dim(_setup_cell_style(v, const.SETUP_NONE, "spec", *RAW))


def test_cell_style_routes_index_columns_through_the_row_state():
    row = {const.SETUP_CLS_COL: const.SETUP_BULL, const.IS_EQUITY_COL: False}
    assert _wash(_cell_style("Lrg Index", 0, row))
    row[const.SETUP_CLS_COL] = const.SETUP_NONE
    assert _is_dim(_cell_style("Lrg Index", 0, row))


def test_cell_style_without_a_row_is_neutral():
    assert _is_dim(_cell_style("Comm Index", 100, None))


# ── email specifics ───────────────────────────────────────────────────────────

def test_blend_endpoints():
    assert _blend(_BULL, _BG, 0.0).lower() == _BULL.lower()
    assert _blend(_BULL, _BG, 1.0).lower() == _BG.lower()


def test_email_never_emits_rgba_text():
    """Outlook mishandles rgba on text; backgrounds are fine."""
    for state in (const.SETUP_BULL, const.SETUP_NEAR_BULL, const.SETUP_BEAR,
                  const.SETUP_NEAR_BEAR, const.SETUP_NONE):
        for v in range(0, 101, 5):
            style = _setup_cell_style(v, state, "comm", *RAW)
            assert "rgba" not in style.split("background-color")[0]


# ── equity spec legs must not be coloured against their own value ─────────────

DOW = (0, 100, 64)     # equity bear setup; Small Specs sit mid-range
SP500 = (0, 98, 91)    # equity bear setup; both spec legs plainly on the bear side


def test_equity_setup_skips_a_spec_leg_that_disagrees():
    """DOW is a bear setup on Commercials alone, but its Small Specs are at 64.

    Washing that cell red reads as "small specs are at a bearish extreme", which is
    false. The row is still legible as a setup through Commercials and Large Specs.
    """
    state = _cls(DOW, is_equity=True)
    assert state == const.SETUP_BEAR
    assert _wash(_setup_cell_style(DOW[0], state, "comm", *RAW, is_equity=True))
    assert _wash(_setup_cell_style(DOW[1], state, "spec", *RAW, is_equity=True))
    assert _is_dim(_setup_cell_style(DOW[2], state, "spec", *RAW, is_equity=True))


def test_equity_setup_still_washes_legs_that_agree():
    """S&P 500's Small Specs at 91 are short of the 95 gate but plainly bearish."""
    state = _cls(SP500, is_equity=True)
    assert state == const.SETUP_BEAR
    for i, role in enumerate(("comm", "spec", "spec")):
        assert _wash(_setup_cell_style(SP500[i], state, role, *RAW, is_equity=True))


def test_commodity_setups_are_unaffected():
    """A non-equity full state already required every leg through its gate, so the
    agreement check can never subtract from one."""
    for legs in (CAD, NZD):
        state = _cls(legs)
        assert state == const.SETUP_BULL
        for i, role in enumerate(("comm", "spec", "spec")):
            assert _wash(_setup_cell_style(legs[i], state, role, *RAW))


def test_agreement_uses_the_near_width_not_the_gate():
    """91 is short of the 95 gate but within the near width, so it agrees."""
    assert _leg_agrees(91, const.SETUP_BEAR, *RAW)
    assert not _leg_agrees(64, const.SETUP_BEAR, *RAW)
    assert _leg_agrees(9, const.SETUP_BULL, *RAW)
    assert not _leg_agrees(40, const.SETUP_BULL, *RAW)


# ── the non-index columns read their gate from cotmetrics ──────────────────────
# These four branches had no coverage while they hardcoded their numbers, which is
# how the emailed HTML drifted from the Dash grid: heatmap.py styled WILLCO from
# const.WILLCO_MAX_THRESHOLD while this module used a literal 80.

# (column, gate constant, colour at the gate, colour past the opposite gate)
_GATED_COLS = [
    ("Comm Z", const.ZSCORE_MAX_THRESHOLD, const.ZSCORE_MIN_THRESHOLD, _BULL, _BEAR),
    ("WILLCO", const.WILLCO_MAX_THRESHOLD, const.WILLCO_MIN_THRESHOLD, _BULL, _BEAR),
    # Sentiment is inverted: a crowded speculator reading is the bearish one.
    ("Inst Sentiment", const.LW_LRG_SENTIMENT_MIN_THRESHOLD,
     const.LW_LRG_SENTIMENT_MAX_THRESHOLD, _BULL, _BEAR),
]


@pytest.mark.parametrize("col,bull_gate,bear_gate,bull,bear", _GATED_COLS)
def test_gated_columns_flip_exactly_at_their_constant(col, bull_gate, bear_gate, bull, bear):
    step = 0.1 if isinstance(bull_gate, float) else 1
    inward = step if bull_gate < bear_gate else -step

    assert bull in _cell_style(col, bull_gate)
    assert _is_dim(_cell_style(col, bull_gate + inward))
    assert bear in _cell_style(col, bear_gate)
    assert _is_dim(_cell_style(col, bear_gate - inward))


def test_oi_z_highlights_at_its_own_threshold():
    gate = const.OI_ZSCORE_HIGHLIGHT_THRESHOLD
    assert _YELLOW in _cell_style("OI Z", gate)
    assert _YELLOW in _cell_style("OI Z", -gate)
    assert _is_dim(_cell_style("OI Z", gate - 0.1))
    assert _is_dim(_cell_style("OI Z", -gate + 0.1))


def test_the_constant_is_the_source_not_a_matching_literal(monkeypatch):
    """The guard that a passing suite above cannot give on its own.

    Boundary tests still pass if the module hardcodes a number equal to the constant.
    Moving the constant and requiring the behaviour to follow is what actually proves
    where the gate comes from.
    """
    monkeypatch.setattr(const, "WILLCO_MAX_THRESHOLD", 90)
    assert _is_dim(_cell_style("WILLCO", 85)), "85 must go dim once the gate moves to 90"
    assert _BULL in _cell_style("WILLCO", 90)

    monkeypatch.setattr(const, "OI_ZSCORE_HIGHLIGHT_THRESHOLD", 3.0)
    assert _is_dim(_cell_style("OI Z", 2.0))
    assert _YELLOW in _cell_style("OI Z", 3.0)
