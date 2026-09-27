"""Unit tests for the weekly flow primitive, the roles table and the Commercial leg's flow.

Store-free by construction: synthetic series and frames, with CotIndexer's store reads
monkeypatched. The one store-backed test at the end skips itself when the store lacks
Lumber's Legacy file, which is CI's case.
"""

import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

import cotmetrics.categories as categories
import cotmetrics.constants as const
import cotmetrics.flow_roles as flow_roles
import cotmetrics.flows as flows
from tests.test_categories import _frame

DISAGG = categories.REPORT_DISAGG
TFF = categories.REPORT_TFF


def _spec(report, key):
    return next(s for s in categories.categories_for(report) if s.key == key)


def _cat(report, raw=None, lookback=52):
    raw = _frame(report) if raw is None else raw
    return categories.build_category_frame(raw, report, lookback)


def _net(cat, report, key):
    return cat[categories.net_col(_spec(report, key))]


# --- module boundary ------------------------------------------------------------

def test_importing_flows_pulls_in_no_store_or_indexer():
    code = ("import sys, cotmetrics.flows; "
            "bad = [m for m in sys.modules if m.startswith(('cotdata', 'cotmetrics.CotIndexer', "
            "'cotmetrics.indexer'))]; print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**os.environ})
    assert r.returncode == 0, r.stdout + r.stderr


# --- the primitive ----------------------------------------------------------------

def test_flow_z_subtracts_no_mean_and_is_series_over_rolling_sd():
    s = pd.Series(np.arange(1.0, 81.0))
    z = flows.flow_z(s)
    sd = s.rolling(52, min_periods=26).std()
    pd.testing.assert_series_equal(z, s / sd)
    # A steady accumulation stays positive; a mean-subtracted z would sit near zero.
    assert (z.dropna() > 0).all()


def test_min_periods_leaves_exactly_25_nan_after_the_diff():
    dnet = flows.weekly_change(pd.Series(np.random.default_rng(1).normal(0, 1, 80)))
    z = flows.flow_z(dnet)
    assert z.iloc[:26].isna().all()      # row 0 is the diff's NaN, then 25 short rows
    assert z.iloc[26:].notna().all()


def test_zero_sd_window_is_nan_never_zero_or_inf():
    z = flows.flow_z(pd.Series([0.0] * 60))
    assert z.isna().all()


def test_gap_mask_blanks_the_first_row_after_a_hole():
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-09", "2024-02-06", "2024-02-13"])
    got = flows.weekly_change(pd.Series([1.0, 2.0, 5.0, 7.0], index=idx))
    assert pd.isna(got.iloc[2]) and got.iloc[3] == 2.0
    kept = flows.weekly_change(pd.Series([1.0, 2.0, 5.0, 7.0], index=idx),
                               max_gap_days=None)
    assert kept.iloc[2] == 3.0


def test_seam_mask_blanks_every_code_change():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    code = pd.Series(["A", "A", "B", "A", "A"])
    got = flows.weekly_change(s, source_code=code)
    assert got.isna().tolist() == [True, False, True, True, False]


# --- the roles table ------------------------------------------------------------------

def test_every_table_key_is_a_category_of_its_report_and_roles_are_disjoint():
    for (report, sym), r in flow_roles.MEASURED.items():
        keys = {s.key for s in categories.categories_for(report)}
        groups = [r.speculator, r.counterparty, r.neutral, r.inert]
        for g in groups:
            assert set(g) <= keys, (report, sym, g)
        flat = [k for g in groups for k in g]
        assert len(flat) == len(set(flat)), (report, sym)
        assert r.source == flow_roles.SOURCE_MEASURED
        assert r.retail_behaves in ("spec-like", "neutral", "cp-like"), (report, sym)
    assert flow_roles.PX_CORR_THRESHOLD == 0.15
    assert flow_roles.PRICE_BASIS == "propadj"


def test_table_names_the_measured_speculators():
    assert flow_roles.roles_for(DISAGG, "GC").speculator == ("managed_money",)
    assert flow_roles.roles_for(DISAGG, "ZC").retail_behaves == "neutral"
    assert flow_roles.roles_for(TFF, "6E").speculator == ("asset_manager", "leveraged")
    assert flow_roles.roles_for(TFF, "ZT").speculator == ()


def test_unknown_or_missing_symbol_gets_the_report_default():
    for sym in (None, "KE", "NOPE"):
        r = flow_roles.roles_for(DISAGG, sym)
        assert r.speculator == ("managed_money",)
        assert r.source == flow_roles.SOURCE_DEFAULT and r.retail_behaves is None
    assert flow_roles.roles_for(TFF, "EMD").speculator == ("leveraged",)


def test_committed_table_is_what_the_generator_writes():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv = os.path.join(root, "docs", "analysis",
                       "2026-09-26-cot-cohort-collapse-propadj.csv")
    if not os.path.exists(csv):
        pytest.skip("the propadj collapse CSV is not in this checkout")
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "analysis",
                                                     "gen_flow_roles.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# --- the Legacy Commercial leg's flow (the /analysis strip) ------------------------------

def test_leg_flow_frame_is_weekly_change_then_flow_z():
    idx = pd.date_range("2020-01-07", periods=80, freq="7D")
    net = pd.Series(np.random.default_rng(2).normal(0, 1e4, 80).cumsum(), index=idx)
    code = pd.Series(["A"] * 50 + ["B"] * 30, index=idx)
    out = flows.leg_flow_frame(net, const.COMM, source_code=code)
    assert list(out.columns) == ["Comm dNet", "Comm Flow Z 52w"]
    want = flows.weekly_change(net, source_code=code)
    pd.testing.assert_series_equal(out["Comm dNet"], want, check_names=False)
    pd.testing.assert_series_equal(out["Comm Flow Z 52w"], flows.flow_z(want),
                                   check_names=False)
    assert pd.isna(out["Comm dNet"].iloc[50])


def _legacy_indexer(monkeypatch, n=80, codes=None, reports=(DISAGG,)):
    from cotmetrics.CotIndexer import CotIndexer, Instrument, _IndexState

    dates = pd.date_range("2020-01-07", periods=n, freq="7D")
    inst = Instrument("Metals", "Gold", "GC", "088691", 26)
    inst.df = pd.DataFrame({
        const.REPORT_DATE_XLS: dates,
        const.COMM_NET: np.random.default_rng(3).normal(0, 1e4, n).cumsum(),
    })
    cat = pd.DataFrame(index=dates)
    if codes is not None:
        cat[const.SOURCE_CODE] = codes
    monkeypatch.setattr(CotIndexer, "available_reports_for", lambda self, name: reports)
    monkeypatch.setattr(CotIndexer, "get_category_data",
                        lambda self, name, report, lookback="Custom", with_price=True: cat)
    monkeypatch.setattr(CotIndexer, "is_equity", lambda self, name: False)
    ix = CotIndexer.__new__(CotIndexer)
    ix._state = _IndexState()
    ix._state.instruments = {"088691": inst}
    return ix, inst, dates


def test_get_commercial_flow_data_runs_store_free(monkeypatch):
    from cotmetrics.CotIndexer import CotIndexer

    ix, inst, dates = _legacy_indexer(monkeypatch, codes=["088691"] * 80)
    out = CotIndexer.get_commercial_flow_data(ix, "Gold")
    assert out.index.name == const.DATE and list(out.index) == list(dates)
    net = pd.Series(inst.df[const.COMM_NET].to_numpy(), index=dates)
    pd.testing.assert_series_equal(out["Comm Flow Z 52w"],
                                   flows.flow_z(flows.weekly_change(net)),
                                   check_names=False, check_freq=False)
    assert out.attrs["flow_leg"] == "Commercial"
    assert out.attrs["is_equity"] is False
    assert out.attrs["flow_roles"]["retail_behaves"] == "spec-like"


def test_commercial_seam_mask_comes_from_the_category_frames_code(monkeypatch):
    from cotmetrics.CotIndexer import CotIndexer

    # The category frame starts later than Legacy (2006 against 1986): back-filled,
    # so the early rows are one population and only the real switch is masked.
    codes = [None] * 20 + ["058643"] * 40 + ["058644"] * 20
    ix, inst, dates = _legacy_indexer(monkeypatch, codes=codes)
    out = CotIndexer.get_commercial_flow_data(ix, "Gold")
    masked = out["Comm dNet"].isna()
    assert masked.iloc[0] and masked.iloc[60]
    assert not masked.iloc[1:60].any() and not masked.iloc[61:].any()


def test_commercial_flow_without_a_category_report_still_draws(monkeypatch):
    from cotmetrics.CotIndexer import CotIndexer

    ix, inst, dates = _legacy_indexer(monkeypatch, reports=())
    out = CotIndexer.get_commercial_flow_data(ix, "Gold")
    assert out["Comm Flow Z 52w"].iloc[26:].notna().all()
    assert out.attrs["flow_roles"] is None


def test_lumber_commercial_flow_masks_the_2023_seam_on_the_live_store():
    try:
        import cotdata.config as cfg
        have = (cfg.cot_legacy_dir() / "LBR_058644.parquet").exists()
    except Exception:
        have = False
    if not have:
        pytest.skip("no LBR legacy file in this COTDATA_STORE")
    from cotmetrics.indexer import get_indexer

    out = get_indexer().get_commercial_flow_data("Lumber")
    for day in ("2023-02-21", "2023-02-28", "2023-03-14"):
        assert pd.isna(out.loc[pd.Timestamp(day), "Comm dNet"]), day
