"""Positioning basis: raw net contracts vs net / open interest.

Every level metric (index, z-score, spearman, index momentum) is computed twice by
`process_lookback` — once from `Comm Net` and once from `Comm Net Norm`. The `basis`
argument to `get_symbols_data` selects which family lands on the generic alias columns
that the UI and the ML dataset read.

These tests are hermetic: the alias wiring is exercised through a synthetic frame and a
stand-in `self`, so no CotIndexer boot (data store) is needed.
"""
import inspect
import types

import pandas as pd
import pytest

import cotmetrics.constants as const
from cotmetrics import CotIndexer as indexer_mod
from cotmetrics.CotIndexer import CotIndexer

# get_symbols_data is wrapped in lru_cache; reach the underlying function so a stand-in
# `self` can be passed and nothing is shared between tests.
_get_symbols_data = CotIndexer.get_symbols_data.__wrapped__

LB = const.LB_CUSTOM  # " Custom"

# Distinct sentinel per (metric, family) so a mis-wired alias can't accidentally pass.
RAW_VALUES = {
    "idx": 20.0, "zscore": -1.0, "spearman": -0.5, "move": -3.0, "wow": -7.0}
NORM_VALUES = {
    "idx": 80.0, "zscore": 1.0, "spearman": 0.5, "move": 3.0, "wow": 7.0}


def _frame(n=4):
    """Minimal instrument frame carrying both the raw and normalized metric families."""
    cols = {}
    for group in (const.COMM, const.LARGE, const.SMALL):
        cols[group + LB + const.IDX] = [RAW_VALUES["idx"]] * n
        cols[group + LB + const.IDX + const.NORMALIZED] = [NORM_VALUES["idx"]] * n
        cols[group + LB + const.ZSCORE] = [RAW_VALUES["zscore"]] * n
        cols[group + LB + const.ZSCORE + const.NORMALIZED] = [NORM_VALUES["zscore"]] * n
        cols[group + LB + const.SPEARMAN] = [RAW_VALUES["spearman"]] * n
        cols[group + LB + const.SPEARMAN + const.NORMALIZED] = [NORM_VALUES["spearman"]] * n
        cols[group + LB + const.MOMENTUM] = [RAW_VALUES["move"]] * n
        cols[group + LB + const.MOMENTUM + const.NORMALIZED] = [NORM_VALUES["move"]] * n
        cols[group + LB + const.WOW_MOVE] = [RAW_VALUES["wow"]] * n
        cols[group + LB + const.WOW_MOVE + const.NORMALIZED] = [NORM_VALUES["wow"]] * n
    cols[const.REPORT_DATE_XLS] = pd.date_range("2020-01-03", periods=n, freq="7D")
    cols[const.COMM_NET] = [100.0] * n
    cols[const.COMM_NET_NORM] = [0.1] * n
    return pd.DataFrame(cols)


@pytest.fixture
def stub_self(monkeypatch):
    """A CotIndexer stand-in wired to a synthetic instrument, with the DB check and the
    signal engine stubbed out so only the alias selection is under test."""
    instrument = types.SimpleNamespace(
        df=_frame(), symbol="XX", custom_lookback=26, asset_class="Test",
    )
    monkeypatch.setattr(indexer_mod.cotDatabase, "latest_update_timestamp", lambda: "t0")
    # Identity signal engine: record the flag it was handed, change nothing.
    seen = {}

    def _append(df, asset_class=None, normalized=False):
        seen["normalized"] = normalized
        return df

    monkeypatch.setattr(indexer_mod.metrics, "append_trading_signals", _append)

    return types.SimpleNamespace(
        last_known_db_time="t0",
        get_instrument_from_name=lambda name: instrument,
        is_equity=lambda name: False,
        estimate_current_gap_positions=lambda *a, **k: None,
        _seen=seen,
    )


# Every generic alias get_symbols_data promises. The ones without a constant of their
# own are named where their source family is defined, which is why this list mixes
# spellings rather than reading from one prefix.
ALIAS_COLUMNS = (
    const.COMMS_IDX, const.LRG_IDX, const.SML_IDX,
    const.COMMS_ZSCORE, const.LRG_ZSCORE, const.SML_ZSCORE,
    const.COMMS_SPEARMAN, const.LRG_SPEARMAN, const.SML_SPEARMAN,
    const.COMM_MOMENTUM, const.LRG_MOMENTUM, const.SML_MOMENTUM,
    const.COMM_WOW, const.LRG_WOW, const.SML_WOW,
    const.WILLCO_ALIAS, const.OI_ZSCORE, const.LSR, const.PHD,
    const.POS_IDX_SETUP_LONG, const.POS_IDX_SETUP_SHORT,
    const.POS_IDX_SETUP_NEAR_LONG, const.POS_IDX_SETUP_NEAR_SHORT,
)


# ── the contract ────────────────────────────────────────────────────────────────
def test_every_promised_alias_is_on_the_frame(stub_self):
    """The guard the constants exist to enable. A consumer that reads a name this
    function never assigns gets a neutral-looking default from `.get`, not an error,
    so the mismatch has to be caught here rather than at read time."""
    out = _get_symbols_data(stub_self, "GC", "Custom")
    assert [a for a in ALIAS_COLUMNS if a not in out.columns] == []


def test_alias_names_are_the_wire_format():
    """npf still reads these frames with string literals, and cached parquet carries
    the names too. The constants are typo safety, not a licence to rename a column:
    changing a value here silently desyncs a repo this suite cannot see."""
    assert const.COMMS_IDX == "comms_idx"
    assert const.LRG_IDX == "lrg_idx"
    assert const.SML_IDX == "sml_idx"
    assert const.COMMS_ZSCORE == "comms_zscore"
    assert const.LRG_ZSCORE == "lrg_zscore"
    assert const.SML_ZSCORE == "sml_zscore"
    assert const.COMMS_SPEARMAN == "comms_spearman"
    assert const.LRG_SPEARMAN == "lrg_spearman"
    assert const.SML_SPEARMAN == "sml_spearman"
    assert const.WILLCO_ALIAS == "willco"
    assert const.OI_ZSCORE == "oi_zscore"
    assert const.LSR == "lsr"
    assert const.PHD == "phd"



def test_basis_choices_are_the_two_supported_families():
    # Display labels and the app-only "both" overlay view live in the app's
    # viz_constants, per this project's data-layer/presentation split.
    assert const.BASIS_CHOICES == (const.BASIS_RAW, const.BASIS_OI_NORM)


def test_raw_is_the_default_basis():
    # npf's deployed path calls get_symbols_data(name, lookback) positionally, so the
    # default must stay raw or every deployed signal silently changes meaning.
    assert inspect.signature(_get_symbols_data).parameters["basis"].default == const.BASIS_RAW


def test_unknown_basis_is_rejected():
    with pytest.raises(ValueError, match="unknown basis"):
        _get_symbols_data(types.SimpleNamespace(), "GC", "Custom", "percent")


# ── alias selection ─────────────────────────────────────────────────────────────
def test_raw_basis_puts_the_raw_family_on_the_aliases(stub_self):
    out = _get_symbols_data(stub_self, "GC", "Custom")
    assert out[const.COMMS_IDX].iloc[-1] == RAW_VALUES["idx"]
    assert out[const.LRG_ZSCORE].iloc[-1] == RAW_VALUES["zscore"]
    assert out[const.SML_SPEARMAN].iloc[-1] == RAW_VALUES["spearman"]
    assert out[const.COMM_MOMENTUM].iloc[-1] == RAW_VALUES["move"]
    assert out[const.COMM_WOW].iloc[-1] == RAW_VALUES["wow"]
    assert out.attrs["basis"] == const.BASIS_RAW


def test_oi_norm_basis_puts_the_normalized_family_on_the_aliases(stub_self):
    out = _get_symbols_data(stub_self, "GC", "Custom", const.BASIS_OI_NORM)
    assert out[const.COMMS_IDX].iloc[-1] == NORM_VALUES["idx"]
    assert out[const.LRG_ZSCORE].iloc[-1] == NORM_VALUES["zscore"]
    assert out[const.SML_SPEARMAN].iloc[-1] == NORM_VALUES["spearman"]
    assert out[const.COMM_MOMENTUM].iloc[-1] == NORM_VALUES["move"]
    assert out[const.COMM_WOW].iloc[-1] == NORM_VALUES["wow"]
    assert out.attrs["basis"] == const.BASIS_OI_NORM


def test_every_alias_moves_together(stub_self):
    """A mixed frame — a normalized index next to a raw z-score — would make the signal
    engine compare two different units inside one condition set."""
    out = _get_symbols_data(stub_self, "GC", "Custom", const.BASIS_OI_NORM)
    aliases = [const.COMMS_IDX, const.LRG_IDX, const.SML_IDX,
               const.COMMS_ZSCORE, const.LRG_ZSCORE, const.SML_ZSCORE,
               const.COMMS_SPEARMAN, const.LRG_SPEARMAN, const.SML_SPEARMAN,
               const.COMM_MOMENTUM, const.LRG_MOMENTUM, const.SML_MOMENTUM,
               const.COMM_WOW, const.LRG_WOW, const.SML_WOW]
    expected = {NORM_VALUES[k] for k in NORM_VALUES}
    assert {out[a].iloc[-1] for a in aliases} == expected


def test_basis_is_threaded_into_the_signal_engine(stub_self):
    _get_symbols_data(stub_self, "GC", "Custom", const.BASIS_OI_NORM)
    assert stub_self._seen["normalized"] is True
    _get_symbols_data(stub_self, "GC", "Custom", const.BASIS_RAW)
    assert stub_self._seen["normalized"] is False


# ── week-over-week twins ────────────────────────────────────────────────────────
# These arrived after the rest of the families. The movers strip ranks on them, so a
# raw delta sitting beside a normalized level would rank one series and badge another.

def test_wow_follows_the_basis_like_every_other_level_metric(stub_self):
    """The WoW delta is a point change *of the index above*, so it cannot stay raw
    while the index it is derived from switches."""
    raw = _get_symbols_data(stub_self, "GC", "Custom", const.BASIS_RAW)
    norm = _get_symbols_data(stub_self, "GC", "Custom", const.BASIS_OI_NORM)
    for alias in (const.COMM_WOW, const.LRG_WOW, const.SML_WOW):
        assert raw[alias].iloc[-1] == RAW_VALUES["wow"]
        assert norm[alias].iloc[-1] == NORM_VALUES["wow"]
        assert raw[alias].iloc[-1] != norm[alias].iloc[-1]


def test_the_cache_guard_probes_both_wow_families():
    """The normalized twin landed after the raw one, so a cache built in between has
    the first and not the second and must still be rejected."""
    assert const.COMM_CUSTOM_WOW_NORM == const.COMM_CUSTOM_WOW + const.NORMALIZED
    src = inspect.getsource(CotIndexer.try_load_from_cache)
    assert "COMM_CUSTOM_WOW" in src and "COMM_CUSTOM_WOW_NORM" in src
