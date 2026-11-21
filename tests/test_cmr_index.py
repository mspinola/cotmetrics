"""The CMR index family: CmrLookbackWeeks, and the E-mini / Micro / Combined equity twins."""
import numpy as np
import pandas as pd
import pytest

import cotmetrics as metrics
import cotmetrics.constants as const
from cotmetrics.CotIndexer import CotIndexer, Instrument

DATES = pd.date_range("2024-01-02", periods=12, freq="7D")


def _frame(comm, lrg, sml, dates=DATES):
    return pd.DataFrame({const.REPORT_DATE_XLS: dates, const.COMM_NET: comm,
                         const.LARGE_NET: lrg, const.SMALL_NET: sml})


def _raw(comm, lrg, sml, dates):
    z = np.zeros(len(dates))
    return pd.DataFrame({"Comm_Positions_Long_All": comm, "Comm_Positions_Short_All": z,
                         "NonComm_Positions_Long_All": lrg, "NonComm_Positions_Short_All": z,
                         "NonRept_Positions_Long_All": sml, "NonRept_Positions_Short_All": z},
                        index=pd.DatetimeIndex(dates))


def test_cmr_lookback_falls_back_to_custom():
    assert Instrument("Metals", "Gold", "GC", "088691", 26).cmr_lookback == 26
    assert Instrument("Metals", "Gold", "GC", "088691", 26, "deploy", 24).cmr_lookback == 24


def test_plain_market_cmr_index_uses_the_cmr_lookback():
    rng = np.random.default_rng(0)
    df = _frame(*(rng.normal(size=len(DATES)).cumsum() for _ in range(3)))
    inst = Instrument("Metals", "Gold", "GC", "088691", 8, "deploy", 4)
    out = CotIndexer.attach_cmr_indexes(inst, df.copy())
    pd.testing.assert_series_equal(out[const.COMM_CMR_IDX],
                                   metrics.rolling_cot_index(df[const.COMM_NET], 4),
                                   check_names=False)
    assert const.COMM_CMR_MICRO_IDX not in out.columns


def test_equity_twins_index_each_listing_over_its_own_history():
    lb = 3
    rng = np.random.default_rng(1)
    mini = [rng.normal(size=len(DATES)).cumsum() for _ in range(3)]
    micro_dates = DATES[5:]                       # the micro lists later
    micro = [rng.normal(size=len(micro_dates)).cumsum() for _ in range(3)]
    combined = [m + 7 for m in mini]
    reads = {"primary": _raw(*mini, DATES), "13874U": _raw(*micro, micro_dates)}

    def read_cot(sym, listing):
        assert sym == "ES"
        return reads[listing]

    inst = Instrument("Equities", "S&P 500", "ES", "13874A", 28, "deploy", lb)
    out = CotIndexer.attach_cmr_indexes(inst, _frame(*combined), read_cot=read_cot)

    want_mini = metrics.rolling_cot_index(pd.Series(mini[0]), lb).to_numpy()
    np.testing.assert_array_equal(out[const.COMM_CMR_IDX].to_numpy(), want_mini)
    want_micro = metrics.rolling_cot_index(pd.Series(micro[2]), lb).to_numpy()
    got_micro = out[const.SMALL_CMR_MICRO_IDX].to_numpy()
    assert np.isnan(got_micro[:5]).all()          # before the micro listed
    np.testing.assert_array_equal(got_micro[5:], want_micro)
    np.testing.assert_array_equal(out[const.LARGE_CMR_COMBINED_IDX].to_numpy(),
                                  metrics.rolling_cot_index(pd.Series(combined[1]), lb).to_numpy())
    np.testing.assert_array_equal(out[const.COMM + const.EMINI_NET].to_numpy(), mini[0])


def test_micro_listings_are_registry_sum_codes():
    cotdata = pytest.importorskip("cotdata")
    for sym, code in const.MICRO_LISTINGS.items():
        listed = {c for c, *_ in cotdata.symbol(sym).sum_codes}
        assert code in listed, f"{sym}: {code} not in the registry's sum_codes {listed}"
