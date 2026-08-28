"""The Home page board: the WoW index delta, the caption built on it, and the two
selectors that read one sweep.

No test here needs a store. The selectors are pure functions over the sweep's output,
so they are tested directly against hand-built rows. get_board itself walks cotIndexer,
which would need a populated COTDATA_STORE, so the last section substitutes a stub
indexer over one hand-built frame -- that covers the row-building half, which is where
the distinctions each field carries actually live. What a real store would add is
coverage of the walk, not of the rows.
"""
import inspect

import pandas as pd
import pytest

import cotmetrics.constants as const
import cotmetrics.models as models
from cotmetrics.indicators import calculate_momentum_index
from cotmetrics.movers import (
    FILTER_BEAR,
    FILTER_BULL,
    UNUSUAL_MIN_HISTORY,
    UNUSUAL_MIN_POINTS,
    UNUSUAL_MULTIPLE,
    _caption,
    _unusual_multiple,
    _wanted_biases,
    get_board,
    get_weekly_movers,
    rank_movers,
    select_setups,
)


def _row(asset, index, setup=const.SETUP_NONE, delta=None):
    """A board row with only the fields the selectors read."""
    return {"asset": asset, "index": index, "setup": setup, "delta": delta}


# ── the metric ────────────────────────────────────────────────────────────────

def test_wow_is_a_one_week_point_change():
    idx = pd.Series([50, 52, 45, 60])
    assert list(calculate_momentum_index(idx, periods=const.WOW_PERIOD)) == [0, 2, -7, 15]


def test_wow_and_the_six_week_move_are_different_metrics():
    """Gold at 2026-07-14 read -8 over six weeks while the week itself was +7.

    That gap is what surfaced the mislabelled "WoW ROC" column, and it is the reason
    the movers list needed its own metric rather than reusing comm_momentum.
    """
    idx = pd.Series([70, 82, 80, 68, 67, 74, 81])
    wow = calculate_momentum_index(idx, periods=1)
    six = calculate_momentum_index(idx, periods=6)
    assert wow.iloc[-1] == 7
    assert six.iloc[-1] == 11
    assert wow.iloc[-1] != six.iloc[-1]


def test_default_period_is_unchanged():
    """The existing 6-week callers must keep their behaviour."""
    idx = pd.Series(range(10))
    assert list(calculate_momentum_index(idx)) == list(
        calculate_momentum_index(idx, periods=const.MOMENTUM_PERIOD)
    )


def test_leading_rows_are_zero_not_nan():
    assert calculate_momentum_index(pd.Series([50, 55]), periods=1).iloc[0] == 0


# ── the caption ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("idx,delta,expected", [
    (97, 12, "Pushed into the top of its range"),
    (2, -12, "Dropped to the bottom of its range"),
    (85, 5, "Pushed into the high end of its range"),
    (12, -5, "Dropped to the low end of its range"),
    (55, 9, "Pushed toward mid-range"),
    (48, -9, "Dropped toward mid-range"),
])
def test_caption_reads_position_and_direction(idx, delta, expected):
    assert _caption(idx, delta) == expected


def test_caption_never_predicts():
    """Position, not direction-of-price. The setup state is a separate field."""
    for idx in range(0, 101, 5):
        for delta in (-30, -1, 1, 30):
            text = _caption(idx, delta).lower()
            for banned in ("bull", "bear", "buy", "sell", "setup"):
                assert banned not in text, f"{text!r} leaked a prediction"


def test_caption_direction_follows_the_delta_not_the_level():
    """A market can drop and still sit high, or push and still sit low."""
    assert _caption(96, -3).startswith("Dropped")
    assert _caption(4, 2).startswith("Pushed")


# ── tape-bias filter ──────────────────────────────────────────────────────────

def test_no_filter_admits_everything():
    for empty in (None, [], ["SOMETHING_ELSE"]):
        assert _wanted_biases(empty) is None


def test_each_chip_maps_to_its_bias():
    assert _wanted_biases([FILTER_BULL]) == {"bullish"}
    assert _wanted_biases([FILTER_BEAR]) == {"bearish"}


def test_both_chips_are_an_or_not_an_and():
    """Matches build_mobile_asset_card: both selected means bullish OR bearish,
    which excludes neutral rather than excluding everything."""
    both = _wanted_biases([FILTER_BULL, FILTER_BEAR])
    assert both == {"bullish", "bearish"}
    assert "neutral" not in both


def test_unknown_tokens_do_not_silently_filter():
    """An unrecognised chip must not narrow the pool to nothing."""
    assert _wanted_biases(["TAPE_BIAS_SIDEWAYS"]) is None
    assert _wanted_biases([FILTER_BULL, "TAPE_BIAS_SIDEWAYS"]) == {"bullish"}


# ── unusual-move flag ─────────────────────────────────────────────────────────

def _hist(typical, n=200):
    """History whose median absolute weekly move is `typical`."""
    return pd.Series([typical, -typical] * (n // 2))


def test_multiple_is_the_move_over_the_markets_own_typical_week():
    assert _unusual_multiple(28, _hist(7)) == pytest.approx(4.0)
    assert _unusual_multiple(-59, _hist(11)) == pytest.approx(59 / 11)


def test_a_quiet_market_needs_a_smaller_move_to_be_unusual():
    """The whole point: 25 points is routine somewhere and extraordinary elsewhere."""
    assert _unusual_multiple(25, _hist(5)) > UNUSUAL_MULTIPLE
    assert _unusual_multiple(25, _hist(20)) < UNUSUAL_MULTIPLE


def test_small_moves_never_flag_however_quiet_the_market():
    """A leg whose typical week is 1 point would turn a 4-point drift into '4x'."""
    assert _unusual_multiple(4, _hist(1)) is None
    assert _unusual_multiple(UNUSUAL_MIN_POINTS - 1, _hist(1)) is None
    assert _unusual_multiple(UNUSUAL_MIN_POINTS, _hist(1)) is not None


def test_thin_history_gives_no_verdict():
    """Too few observations for the median to be a stable baseline."""
    assert _unusual_multiple(50, _hist(5, n=UNUSUAL_MIN_HISTORY - 2)) is None
    assert _unusual_multiple(50, _hist(5, n=UNUSUAL_MIN_HISTORY)) is not None


def test_a_motionless_history_does_not_divide_by_zero():
    assert _unusual_multiple(50, pd.Series([0.0] * 200)) is None


def test_sign_does_not_matter():
    assert _unusual_multiple(30, _hist(6)) == _unusual_multiple(-30, _hist(6))


def test_threshold_is_a_top_decile_week_not_a_common_one():
    """Calibrated on real data: 4x clears 9.7% of all Commercial observations,
    against 16.8% at 3x and 30% at 2x. A badge that fires half the time says nothing."""
    assert UNUSUAL_MULTIPLE >= 3.5


# ── the model parameter ───────────────────────────────────────────────────────
# The strip used to be pinned to Raw PF because the WoW delta existed only on the raw
# basis. Now that process_lookback builds both, the whole read follows one model.

def test_get_weekly_movers_defaults_to_the_app_default_model():
    """A caller that passes no model must not silently change meaning."""
    assert inspect.signature(get_weekly_movers).parameters["model"].default is None


def test_the_model_is_resolved_not_assumed():
    """It accepts a key from a browser store as well as a model object, and a stale key
    falls back rather than raising."""
    src = inspect.getsource(get_board)
    assert "models.resolve(model)" in src


def test_frame_ranking_and_badge_all_come_from_the_one_model():
    """The defect this guards: fetching the frame on one basis while gating the setup
    with another's band. All three references must name the same `model`.

    Pinned to get_board rather than get_weekly_movers because that is where the sweep
    now lives. There is exactly one sweep, which is itself the strongest form of this
    guarantee: two views cannot disagree about a row's setup state if only one of them
    ever computes it.
    """
    src = inspect.getsource(get_board)
    assert "get_symbols_data(asset, lookback, model.basis)" in src
    assert "model.setup_state_from(" in src
    assert "model.leg_columns(" in src
    # Nothing may reach past the parameter to a hardcoded model.
    assert "RAW_PF" not in src and "MOVER_MODEL" not in src


def test_the_sweep_does_not_choose_the_gates_columns_itself():
    """The regression: this function naming the columns it fed to a model's gate.

    "Comm <lookback> Idx" is the raw series whatever basis was fetched, so handing it to
    a normalized model read one series while the card displayed another. Six markets
    were badged wrongly under NPF before it was found, and Raw PF concealed it entirely
    because there the two families coincide.

    The rule now lives on the model (leg_columns / setup_state_from) and is covered
    behaviourally in test_models.py. What this guards is the sweep not going back to
    picking columns for itself, which is the only way it can disagree with reports.py
    again.
    """
    src = inspect.getsource(get_board)
    assert "setup_state_from(" in src, "the gate must delegate to the model"
    assert "model.setup_state(" not in src, (
        "passing legs positionally means this function chose them"
    )
    # The lookback-named index columns must not be reassembled for the gate here.
    assert "const.COMM + " not in src, (
        "building 'Comm <lookback> Idx' here reintroduces the raw-column gate"
    )


def test_neither_view_computes_setup_state_for_itself():
    """Both selectors must read the swept `setup` field rather than re-deriving it."""
    for fn in (rank_movers, select_setups):
        src = inspect.getsource(fn)
        assert "setup_state" not in src and "setup_masks" not in src


# ── the two selectors over one sweep ──────────────────────────────────────────

def test_movers_drops_rows_that_did_not_move():
    """A card whose headline number is 0 explains nothing, so it is not a mover."""
    rows = [_row("A", 50, delta=5), _row("B", 50, delta=None), _row("C", 50, delta=0)]
    assert [r["asset"] for r in rank_movers(rows)] == ["A"]


def test_movers_rank_on_absolute_move_in_either_direction():
    rows = [_row("A", 50, delta=3), _row("B", 50, delta=-9), _row("C", 50, delta=6)]
    assert [r["asset"] for r in rank_movers(rows)] == ["B", "C", "A"]


def test_a_pinned_setup_that_did_not_move_still_reaches_the_setups_view():
    """The regression this guards: the old ranking dropped zero-delta rows during the
    sweep, which would have deleted a market sitting at an extreme with a quiet week --
    the most interesting kind of setup -- from a view that has no delta rule at all."""
    rows = [_row("Quiet", 100, const.SETUP_BULL, delta=None)]
    assert rank_movers(rows) == []
    assert [r["asset"] for r in select_setups(rows)] == ["Quiet"]


def test_setups_put_full_states_ahead_of_near_ones():
    """Tier dominates extremity: NearBear at 7 is further from mid-range than FullBull
    at 97, and still sorts below it."""
    rows = [
        _row("NearBull", 92, const.SETUP_NEAR_BULL),
        _row("FullBear", 2, const.SETUP_BEAR),
        _row("Neutral", 50, const.SETUP_NONE),
        _row("FullBull", 97, const.SETUP_BULL),
        _row("NearBear", 7, const.SETUP_NEAR_BEAR),
    ]
    assert [r["asset"] for r in select_setups(rows)] == [
        "FullBear", "FullBull", "NearBear", "NearBull",
    ]


def test_setups_order_by_extremity_not_by_direction():
    """Distance from mid-range, so a bull near 100 and a bear near 0 interleave on how
    far out they actually are rather than clustering by sign."""
    rows = [
        _row("MildBull", 96, const.SETUP_BULL),
        _row("HardBear", 0, const.SETUP_BEAR),
        _row("HardBull", 100, const.SETUP_BULL),
    ]
    assert [r["asset"] for r in select_setups(rows)] == [
        "HardBear", "HardBull", "MildBull",
    ]


def test_setups_are_uncapped_by_default():
    """Unlike the movers strip, which is a top-N by construction, the setups list is
    however long the board says it is."""
    assert inspect.signature(select_setups).parameters["limit"].default is None
    rows = [_row(f"A{i}", 100, const.SETUP_BULL) for i in range(20)]
    assert len(select_setups(rows)) == 20
    assert len(select_setups(rows, limit=5)) == 5


def test_neutral_rows_never_reach_the_setups_view():
    rows = [_row("A", 50, const.SETUP_NONE), _row("B", 88, const.SETUP_NONE)]
    assert select_setups(rows) == []


def test_the_caption_ladder_stays_fixed_across_models():
    """The caption is a positional description, not a verdict. If it moved with the
    band, one row would report its position differently depending on the gate around
    it while the badge said something else."""
    assert list(inspect.signature(_caption).parameters) == ["idx", "delta"]
    for idx, expected in ((96, "top"), (85, "high end"), (50, "mid-range")):
        assert expected in _caption(idx, 5)


# ── what the sweep reports, over a stub indexer ───────────────────────────────
#
# get_board walks the indexer, which is why the module docstring keeps it out of the
# hermetic suite. Substituting the indexer brings the row-building half of it back in,
# and that half is where the distinction below lives. Nothing here needs a store.

class _StubIndexer:
    """Every indexer call get_board makes, over one hand-built frame."""

    def __init__(self, frame):
        self._frame = frame

    def get_asset_classes(self):
        return ["Testables"]

    def get_assets_for_asset_class(self, asset_class):
        return ["Quiet"]

    def get_symbols_data(self, asset, lookback, basis):
        return self._frame

    def get_instrument_symbol_from_name(self, asset):
        return "QT"

    def is_equity(self, asset):
        return False


def _swept(monkeypatch, comm_wow, lrg_wow=4.0, sml_wow=-6.0, model=None,
           target_date=None):
    """The single board row for a market whose legs moved by the given amounts."""
    model = model or models.resolve(None)
    comm_col, lrg_col, sml_col = model.leg_columns("Custom")
    frame = pd.DataFrame(
        {
            const.COMMS_IDX: [98.0, 100.0],
            comm_col: [98.0, 100.0],
            # Both rows are FULL bull setups under every model's band: the spec legs
            # sit at or under the tightest low (5), so these fixtures do not care
            # which model is the default. They were 10/6 and 9/3 while the default
            # was NPF's 80/20, and flipping the default to Raw PF's 95/5 turned two
            # setup-week tests into near-misses through the Large leg alone.
            lrg_col: [5.0, 4.0],
            sml_col: [5.0, 3.0],
            const.COMM_WOW: [0.0, comm_wow],
            const.LRG_WOW: [0.0, lrg_wow],
            const.SML_WOW: [0.0, sml_wow],
        },
        index=pd.to_datetime(["2026-08-11", "2026-08-18"]),
    )
    monkeypatch.setattr("cotmetrics.movers.get_indexer", lambda: _StubIndexer(frame))
    rows = get_board(model=model, target_date=target_date)
    assert len(rows) == 1
    return rows[0]


def test_a_market_that_did_not_move_carries_zero_rather_than_none(monkeypatch):
    """The regression: a genuinely motionless week arrived identical to a market with
    no prior week to compare against, because the sweep collapsed both to None.

    That was invisible while rank_movers was the only consumer -- it drops 0 and None
    alike on truthiness -- and wrong the moment a view RENDERED the number, which the
    setups cards now do. A blank where a market is pinned at an extreme and quiet reads
    as missing data, and this function's own docstring calls that the most interesting
    kind of setup.
    """
    assert _swept(monkeypatch, 0.0)["delta"] == 0


def test_no_reading_is_still_none(monkeypatch):
    """The other half of the distinction: None now means only "the frame has no value"."""
    assert _swept(monkeypatch, float("nan"))["delta"] is None


def test_a_motionless_week_gets_no_caption(monkeypatch):
    """_caption picks its verb from the sign, so a zero move would read as "Dropped"."""
    assert _swept(monkeypatch, 0.0)["caption"] is None
    assert _swept(monkeypatch, -7.0)["caption"].startswith("Dropped")


def test_zero_and_none_still_rank_alike(monkeypatch):
    """Keeping the two apart in the row must not change either selector. Both filter on
    truthiness, so a motionless market is still not a mover and is still a setup."""
    quiet = _swept(monkeypatch, 0.0)
    assert rank_movers([quiet]) == []
    assert [r["asset"] for r in select_setups([quiet])] == ["Quiet"]


def test_every_leg_carries_its_own_delta(monkeypatch):
    """A card that draws three legs needs three moves. The specs read the same
    basis-independent WoW aliases the Commercial delta does, so all three follow the
    basis together, and they are reported ungated: which legs get drawn is the view's
    decision, exactly as the leg indices above them already work."""
    row = _swept(monkeypatch, 3.0, lrg_wow=4.4, sml_wow=-6.6)
    assert (row["delta"], row["lrg_delta"], row["sml_delta"]) == (3, 4, -7)


def test_a_leg_with_no_reading_does_not_borrow_another(monkeypatch):
    row = _swept(monkeypatch, 3.0, lrg_wow=float("nan"))
    assert row["lrg_delta"] is None and row["sml_delta"] == -6


def test_the_row_carries_how_long_the_market_has_been_at_its_gate(monkeypatch):
    """The setups badge draws this. Both rows of the fixture frame are bull setups, so
    the market has been telling one story for two weeks."""
    row = _swept(monkeypatch, 2.0)
    assert row["setup"] == const.SETUP_BULL
    assert row["setup_weeks"] == 2


def test_a_dated_read_ages_as_of_that_date(monkeypatch):
    """A board asked about a past week must answer as that week. Counting back from the
    frame's last row instead would report a run that had not happened yet."""
    assert _swept(monkeypatch, 2.0, target_date="2026-08-11")["setup_weeks"] == 1
