"""Unit tests for the speculator and retail series and the weekly flow z.

Store-free by construction, like test_categories: every test pipes the synthetic
CFTC-shaped frame from that module through `categories.build_category_frame` and
asserts on `cotmetrics.flows`. The one store-backed test at the end skips itself when
the store lacks Gold's Disaggregated file, which is CI's case.
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
import cotmetrics.indicators as indicators
from tests.test_categories import _frame

DISAGG = categories.REPORT_DISAGG
TFF = categories.REPORT_TFF
SPEC = const.SPECULATOR


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


# --- the resolvers ------------------------------------------------------------------

def test_speculator_net_sums_exactly_the_measured_members():
    cat = _cat(TFF)
    got = flows.speculator_net(cat, TFF, "6E")
    want = _net(cat, TFF, "asset_manager") + _net(cat, TFF, "leveraged")
    pd.testing.assert_series_equal(got, want, check_names=False)
    gc = _cat(DISAGG)
    pd.testing.assert_series_equal(flows.speculator_net(gc, DISAGG, "GC"),
                                   _net(gc, DISAGG, "managed_money"), check_names=False)


def test_no_speculator_role_and_a_missing_member_both_give_none():
    assert flows.speculator_net(_cat(TFF), TFF, "ZT") is None
    raw = _frame(TFF).drop(columns=["Lev_Money_Positions_Long_All"])
    assert flows.speculator_net(_cat(TFF, raw), TFF, "6E") is None


def test_retail_net_is_non_reportable_on_both_reports():
    for report in (DISAGG, TFF):
        cat = _cat(report)
        pd.testing.assert_series_equal(flows.retail_net(cat, report),
                                       _net(cat, report, "nonreportable"),
                                       check_names=False)


# --- the frame the panel reads ---------------------------------------------------------

def test_speculator_frame_columns_and_attrs():
    cat = _cat(DISAGG, _frame(DISAGG, n=120), lookback=26)
    out = flows.speculator_frame(cat, DISAGG, "GC")
    header = cat.attrs["lookback_header"]
    net = _net(cat, DISAGG, "managed_money")
    pd.testing.assert_series_equal(out[flows.net_col(SPEC)], net, check_names=False)
    want_idx = indicators.calculate_range_index(net, window=27, min_periods=27)
    pd.testing.assert_series_equal(out[flows.index_col(SPEC, header)], want_idx,
                                   check_names=False)
    want_z = flows.flow_z(flows.weekly_change(net))
    pd.testing.assert_series_equal(out[flows.flow_z_col(SPEC)], want_z,
                                   check_names=False)
    assert flows.flow_z_col(SPEC) == "Speculator Flow Z 52w"
    assert flows.net_col(const.RETAIL) in out.columns
    assert out.attrs["speculator_label"] == "Managed Money"
    assert out.attrs["flow_roles"]["retail_behaves"] == "spec-like"
    assert out.attrs["lookback_weeks"] == 26


def test_speculator_frame_without_a_speculator_keeps_retail_only():
    out = flows.speculator_frame(_cat(TFF), TFF, "ZT")
    assert list(out.columns) == [flows.net_col(const.RETAIL)]
    assert out.attrs["speculator_label"] is None


def test_flow_window_is_fixed_whatever_the_page_lookback():
    raw = _frame(TFF, n=120)
    a = flows.speculator_frame(_cat(TFF, raw, lookback=8), TFF, "6E")
    b = flows.speculator_frame(_cat(TFF, raw, lookback=216), TFF, "6E")
    pd.testing.assert_series_equal(a[flows.flow_z_col(SPEC)], b[flows.flow_z_col(SPEC)])


def test_seam_in_the_report_reaches_the_speculator_z():
    raw = _frame(DISAGG, n=80)
    raw["CFTC_Contract_Market_Code_Quotes"] = ["058643"] * 40 + ["058644"] * 40
    out = flows.speculator_frame(_cat(DISAGG, raw), DISAGG, "GC")
    assert pd.isna(out[flows.flow_col(SPEC)].iloc[40])
    assert pd.isna(out[flows.flow_z_col(SPEC)].iloc[40])
    assert out[flows.flow_col(SPEC)].iloc[41:].notna().all()


def test_get_speculator_data_runs_store_free(monkeypatch):
    """get_cot replaced by the synthetic frame so CI's empty store executes the path."""
    import cotdata

    from cotmetrics.CotIndexer import CotIndexer, Instrument, _IndexState

    raw = _frame(TFF, n=80)
    raw.index.name = const.REPORT_DATE_XLS
    monkeypatch.setattr(cotdata, "get_cot", lambda code, report=None, **kw: raw)
    monkeypatch.setattr(CotIndexer, "available_reports_for", lambda self, name: (TFF,))
    inst = Instrument("Currencies", "Euro", "6E", "099741", 90)
    inst.df = pd.DataFrame({const.REPORT_DATE_XLS: raw.index.to_numpy()})
    ix = CotIndexer.__new__(CotIndexer)
    ix._state = _IndexState()
    ix._state.instruments = {"099741": inst}
    ix.lookbacks = [["6-months", 26], ["1-years", 52]]
    out = CotIndexer.get_speculator_data(ix, "Euro", "52")
    assert out.index.name == const.DATE and len(out) == 80
    assert flows.index_col(SPEC, " 52") in out.columns
    assert out.attrs["speculator_label"] == "Asset Manager + Leveraged Funds"
    assert out.attrs["flow_roles"]["symbol"] == "6E"


# --- store-backed ---------------------------------------------------------------

def test_gold_speculator_is_managed_money_on_the_live_store():
    try:
        import cotdata.config as cfg
        have = (cfg.cot_disagg_dir() / "GC_088691.parquet").exists()
    except Exception:
        have = False
    if not have:
        pytest.skip("no GC disagg file in this COTDATA_STORE")

    from cotmetrics.CotIndexer import CotIndexer, Instrument, _IndexState

    ix = CotIndexer.__new__(CotIndexer)
    ix._state = _IndexState()
    ix._state.instruments = {"088691": Instrument("Metals", "Gold", "GC", "088691", 26)}
    ix.lookbacks = [["6-months", 26], ["1-years", 52]]
    out = CotIndexer.get_speculator_data(ix, "Gold", "52")
    cat = CotIndexer.get_category_data(ix, "Gold", DISAGG, "52", with_price=False)
    mm = cat[categories.net_col(_spec(DISAGG, "managed_money"))]
    pd.testing.assert_series_equal(out[flows.net_col(SPEC)], mm, check_names=False)
    assert out[flows.flow_z_col(SPEC)].iloc[-100:].notna().all()
