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


def test_request_contracts_ignores_a_bad_value():
    contracts.set_request_contracts("bogus")
    assert contracts.current_contracts() == contracts.default_contracts()
    contracts.set_request_contracts(contracts.EMINI)
    assert contracts.current_contracts() == contracts.EMINI
    contracts.set_request_contracts(None)
    assert contracts.current_contracts() == contracts.default_contracts()


def test_listing_frames_are_the_summed_equity_markets():
    pytest.importorskip("cotdata")
    es = Instrument("Equities", "S&P 500", "ES", "13874A", 26)
    gc = Instrument("Metals", "Gold", "GC", "088691", 26)
    assert CotIndexer.has_listing_frames(es)
    assert not CotIndexer.has_listing_frames(gc)
