"""Golden tests for utils.is_setup — the positioning-index (COT-index) setup
detector that defines setup long / setup short (also consumed as a pardo ML
feature). Returns (bullish, bearish, close_bullish, close_bearish).
"""
import pandas as pd

from cotmetrics import utils


# ── Equity: only the commercial index matters ───────────────────────────────
def test_equity_bullish_extreme_is_setup_long():
    bull, bear, _, _ = utils.is_setup(True, comms_idx=96, lrg_idx=50, sml_idx=50)
    assert bull and not bear


def test_equity_bearish_extreme_is_setup_short():
    bull, bear, _, _ = utils.is_setup(True, comms_idx=3, lrg_idx=50, sml_idx=50)
    assert bear and not bull


def test_equity_neutral_has_no_setup():
    bull, bear, cbull, cbear = utils.is_setup(True, comms_idx=50, lrg_idx=50, sml_idx=50)
    assert not any([bull, bear, cbull, cbear])


def test_equity_ignores_spec_indices():
    # Specs at the same extreme as commercials must not veto an equity setup.
    bull, _, _, _ = utils.is_setup(True, comms_idx=96, lrg_idx=96, sml_idx=96)
    assert bull


def test_equity_close_bullish_threshold():
    # comm 91 is within 5 of the max (95) -> close, but not a full setup.
    bull, _, cbull, _ = utils.is_setup(True, comms_idx=91, lrg_idx=50, sml_idx=50)
    assert not bull
    assert cbull


def test_equity_close_bearish_threshold():
    # comm 9 is within 5 of the min (5) -> near, but not a full bearish setup.
    _, bear, _, cbear = utils.is_setup(True, comms_idx=9, lrg_idx=50, sml_idx=50)
    assert not bear
    assert cbear


# ── Non-equity: specs must confirm at the opposite extreme ───────────────────
def test_nonequity_requires_spec_confirmation():
    # Commercials extreme but specs neutral -> no full setup.
    bull, _, _, _ = utils.is_setup(False, comms_idx=96, lrg_idx=50, sml_idx=50)
    assert not bull


def test_nonequity_setup_with_spec_confirmation():
    bull, _, _, _ = utils.is_setup(False, comms_idx=96, lrg_idx=4, sml_idx=4)
    assert bull


def test_nonequity_bearish_setup_with_spec_confirmation():
    _, bear, _, _ = utils.is_setup(False, comms_idx=3, lrg_idx=96, sml_idx=96)
    assert bear


# ── Vectorized over Series (how pardo consumes it) ──────────────────────────
def test_is_setup_vectorized_over_series():
    comm = pd.Series([96, 50, 3])
    neutral = pd.Series([50, 50, 50])
    bull, bear, _, _ = utils.is_setup(True, comm, neutral, neutral)
    assert list(bull) == [True, False, False]
    assert list(bear) == [False, False, True]
