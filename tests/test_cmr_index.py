"""The CMR lookback family, and the E-mini / combined contract frames of equity markets."""
import numpy as np
import pandas as pd
import pytest

import cotmetrics as metrics
import cotmetrics.constants as const
import cotmetrics.contracts as contracts
from cotmetrics.CotIndexer import CotIndexer, Instrument

DATES = pd.date_range("2024-01-02", periods=40, freq="7D")


def _raw(comm, lrg, sml, dates, oi=1000.0):
    z = np.zeros(len(dates))
    return pd.DataFrame({const.COMM_LONG_POS_XLS: comm, const.COMM_SHORT_POS_XLS: z,
                         const.LARGE_LONG_POS_XLS: lrg, const.LARGE_SHORT_POS_XLS: z,
                         const.SMALL_LONG_POS_XLS: sml, const.SMALL_SHORT_POS_XLS: z,
                         const.OPEN_INTEREST_XLS: np.full(len(dates), oi)},
                        index=pd.DatetimeIndex(dates, name=const.REPORT_DATE_XLS))


def _indexer():
    ix = object.__new__(CotIndexer)
    ix.lookbacks = [["26", 26]]
    return ix


def _combined_frame(ix, inst, raw):
    df = raw.reset_index()
    df[const.CONTRACT_CODE_XLS] = inst.code
    df[const.CLOSING_PRICE] = np.linspace(100, 140, len(df))
    return ix._derive_metrics(inst, df)


def _walks(n, seed):
    rng = np.random.default_rng(seed)
    return [rng.normal(size=n).cumsum() * 10 + 500 for _ in range(3)]


def test_cmr_lookback_falls_back_to_custom():
    assert Instrument("Metals", "Gold", "GC", "088691", 26).cmr_lookback == 26
    assert Instrument("Metals", "Gold", "GC", "088691", 26, "deploy", 24).cmr_lookback == 24


def test_cmr_family_is_a_full_lookback_at_the_cmr_weeks():
    inst = Instrument("Metals", "Gold", "GC", "088691", 8, "deploy", 4)
    df = _combined_frame(_indexer(), inst, _raw(*_walks(len(DATES), 0), DATES))
    pd.testing.assert_series_equal(df[const.COMM_CMR_IDX],
                                   metrics.rolling_cot_index(df[const.COMM_NET], 4),
                                   check_names=False)
    assert const.COMM + const.LB_CMR + const.ZSCORE in df.columns


def test_emini_frame_recomputes_on_the_primary_listing_alone():
    ix = _indexer()
    inst = Instrument("Equities", "S&P 500", "ES", "13874A", 6, "deploy", 4)
    mini_dates = DATES[10:]                      # the summed series reaches back further
    mini = _walks(len(mini_dates), 1)
    inst.df = _combined_frame(ix, inst, _raw(*_walks(len(DATES), 2), DATES, oi=5000.0))

    def read_cot(sym, report="legacy", listing=None):
        assert (sym, report, listing) == ("ES", "legacy", "primary")
        return _raw(*mini, mini_dates)

    out = ix._emini_frame(inst, read_cot=read_cot)
    assert list(pd.to_datetime(out[const.REPORT_DATE_XLS])) == list(mini_dates)
    np.testing.assert_array_equal(out[const.COMM_NET].to_numpy(), mini[0])
    np.testing.assert_array_equal(out[const.COMM_CMR_IDX].to_numpy(),
                                  metrics.rolling_cot_index(pd.Series(mini[0]), 4).to_numpy())
    np.testing.assert_array_equal(out[const.OPEN_INTEREST_XLS].to_numpy(), 1000.0)
    # prices carry over from the combined frame, row for row
    np.testing.assert_array_equal(out[const.CLOSING_PRICE].to_numpy(),
                                  inst.df[const.CLOSING_PRICE].to_numpy()[10:])
    assert (out[const.CONTRACT_CODE_XLS] == "13874A").all()


def test_frame_for_follows_the_current_contracts():
    inst = Instrument("Equities", "S&P 500", "ES", "13874A", 6)
    inst.df, inst.emini_df = pd.DataFrame({"x": [1]}), pd.DataFrame({"x": [2]})
    plain = Instrument("Metals", "Gold", "GC", "088691", 26)
    plain.df = pd.DataFrame({"x": [3]})
    assert CotIndexer.frame_for(inst) is inst.df            # package default: combined
    with contracts.use_contracts(contracts.EMINI):
        assert CotIndexer.frame_for(inst) is inst.emini_df
        assert CotIndexer.frame_for(plain) is plain.df      # one frame, choice is a no-op
        assert CotIndexer.listing_for(inst) == "primary"
        assert CotIndexer.listing_for(plain) is None
    assert CotIndexer.frame_for(inst, contracts.EMINI) is inst.emini_df


def test_contracts_cached_keys_on_the_resolved_choice():
    calls = []

    class Thing:
        @contracts.contracts_cached(8)
        def read(self, x):
            calls.append((x, contracts.current_contracts()))
            return contracts.current_contracts()

    t = Thing()
    assert t.read(1) == contracts.COMBINED
    with contracts.use_contracts(contracts.EMINI):
        assert t.read(1) == contracts.EMINI
    assert t.read(1, contracts=contracts.EMINI) == contracts.EMINI
    assert t.read(1) == contracts.COMBINED
    assert calls == [(1, contracts.COMBINED), (1, contracts.EMINI)]
    with pytest.raises(ValueError):
        t.read(1, contracts="micro")


def test_listing_frames_are_the_summed_equity_markets():
    pytest.importorskip("cotdata")
    es = Instrument("Equities", "S&P 500", "ES", "13874A", 26)
    gc = Instrument("Metals", "Gold", "GC", "088691", 26)
    assert CotIndexer.has_listing_frames(es)
    assert not CotIndexer.has_listing_frames(gc)


def _twin_indexer(monkeypatch, enabled):
    pytest.importorskip("cotdata")
    from cotmetrics.CotIndexer import _IndexState
    ix = _indexer()
    ix._state = _IndexState()
    es = Instrument("Equities", "S&P 500", "ES", "13874A", 28, "deploy", 26)
    gc = Instrument("Metals", "Gold", "GC", "088691", 26)
    for inst in (es, gc):
        inst.df = pd.DataFrame({"x": [1]})
        ix.instruments[inst.code] = inst
        ix.supported_instruments.add(inst.code)
        ix.asset_class_map.setdefault(inst.asset_class, set()).add(inst.name)
    monkeypatch.setattr(ix, "_emini_frame", lambda inst: pd.DataFrame({"x": [2]}))
    monkeypatch.setattr(contracts, "_combined_class", enabled)
    ix._attach_contract_frames()
    return ix, es


def test_combined_class_twins_each_equity_market(monkeypatch):
    ix, es = _twin_indexer(monkeypatch, True)
    twin = ix.get_instrument_from_name("S&P 500 (Combined)")
    assert twin is not None and twin.twin_of == "13874A"
    assert twin.asset_class == contracts.COMBINED_CLASS
    assert (twin.symbol, twin.code, twin.npf_lookback, twin.cmr_lookback, twin.role) == \
        ("ES", "13874A", 28, 26, "deploy")
    # The twin reads the combined frame whatever the process default.
    with contracts.use_contracts(contracts.EMINI):
        assert CotIndexer.frame_for(twin) is es.df
        assert CotIndexer.listing_for(twin) is None
        assert CotIndexer.frame_for(es) is es.emini_df
    assert not CotIndexer.has_listing_frames(twin)
    # Lookups that stand for "the market" never return the twin.
    assert ix.get_instrument_from_symbol("ES") is es
    assert ix.get_instrument_code_from_name("S&P 500 (Combined)") == "13874A"
    assert ix.get_instrument_names().count("ES") == 1
    assert ix.is_combined_twin("S&P 500 (Combined)") and not ix.is_combined_twin("S&P 500")
    # Out of the class list unless asked for, so nothing counting over it double counts.
    assert contracts.COMBINED_CLASS not in ix.get_asset_classes()
    assert contracts.COMBINED_CLASS in ix.get_asset_classes(include_combined=True)
    assert ix.get_assets_for_asset_class(contracts.COMBINED_CLASS) == ["S&P 500 (Combined)"]
    # A rebuild replaces the twins rather than stacking them.
    ix._attach_contract_frames()
    assert sum(i.twin_of is not None for i in ix.instruments.values()) == 1


def test_combined_class_is_off_by_default(monkeypatch):
    ix, _ = _twin_indexer(monkeypatch, False)
    assert all(i.twin_of is None for i in ix.instruments.values())
    assert contracts.COMBINED_CLASS not in ix.get_asset_classes(include_combined=True)
