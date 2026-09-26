"""Unit tests for the week-over-week cohort flow columns.

Store-free by construction, like test_categories: every test pipes the synthetic
CFTC-shaped frame from that module through `categories.build_category_frame` and
asserts on what `flows.build_flow_frame` adds. The one store-backed test at the end
skips itself when the store lacks Gold's Disaggregated file, which is CI's case.
"""

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


def _balanced_frame(report, n=60, seed=0):
    """`_frame` with legs that net to zero across categories, as real reports do.

    Every long is somebody's short, so the CFTC's category longs sum to the category
    shorts each week. The random frame does not respect that. Rebuilding the last
    category's two legs from the others' totals does, which is what the exact
    zero-sum identity below needs.
    """
    df = _frame(report, n=n, seed=seed)
    specs = categories.categories_for(report)
    last = specs[-1]
    others = specs[:-1]
    longs = sum(df[s.long_col] for s in others)
    shorts = sum(df[s.short_col] for s in others)
    df[last.long_col] = shorts + 1_000
    df[last.short_col] = longs + 1_000
    return df


def _cat(report, raw=None, lookback=52, **kw):
    raw = _frame(report) if raw is None else raw
    return categories.build_category_frame(raw, report, lookback, **kw)


def _flow(report, raw=None, symbol=None, lookback=52):
    return flows.build_flow_frame(_cat(report, raw, lookback), report, symbol=symbol)


# --- module boundary ------------------------------------------------------------

def test_importing_flows_pulls_in_no_store_or_indexer():
    """flows and flow_roles are pure. An indexer or cotdata import would drag the
    store (and its raise-on-unset root) into every consumer of a column name.

    Checked in a fresh interpreter: sys.modules is process-wide, and any earlier test
    in the session that touched the indexer would make an in-process check
    meaningless in one direction and flaky in the other.
    """
    code = (
        "import sys; import cotmetrics.flows, cotmetrics.flow_roles; "
        "print(sorted(m for m in sys.modules if m in ('cotmetrics.indexer', "
        "'cotmetrics.CotIndexer') or m == 'cotdata' or m.startswith('cotdata.')))"
    )
    got = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True)
    assert got.stdout.strip() == "[]", got.stdout


# --- the primitive --------------------------------------------------------------

@pytest.mark.parametrize("report", [DISAGG, TFF])
def test_dnet_sums_to_exactly_zero_across_categories(report):
    out = _flow(report, _balanced_frame(report))
    total = sum(out[flows.flow_col(s)] for s in categories.categories_for(report))
    assert pd.isna(total.iloc[0])
    assert (total.iloc[1:] == 0).all(), total.iloc[1:].abs().max()


def test_flow_z_subtracts_no_mean_and_is_series_over_rolling_sd():
    rng = np.random.default_rng(3)
    s = pd.Series(rng.normal(0, 100, 120)).diff() + 500      # a steady offset
    z = flows.flow_z(s)
    sd = s.rolling(52, min_periods=26).std()
    finite = z.notna()
    assert z[finite].mean() > 0, "a rolling mean was subtracted"
    pd.testing.assert_series_equal(z[finite], (s / sd)[finite])


def test_min_periods_leaves_exactly_26_nan_then_finite():
    out = _flow(DISAGG, _frame(DISAGG, n=40))
    for spec in categories.categories_for(DISAGG):
        z = out[flows.flow_z_col(spec)]
        assert z.iloc[:26].isna().all(), spec.key
        assert z.iloc[26:].notna().all(), spec.key


def test_constant_category_gives_nan_z_never_zero_or_inf():
    """The inverse of test_indicators.test_z_score_constant_series_is_zero_and_no_nan:
    a zero-sd window is no reading, and 0 would be read as QUIET."""
    raw = _frame(DISAGG, n=60)
    mm = _spec(DISAGG, "managed_money")
    raw[mm.long_col] = 40_000
    raw[mm.short_col] = 10_000
    out = _flow(DISAGG, raw)
    z = out[flows.flow_z_col(mm)]
    assert z.isna().all()
    assert not np.isinf(z.fillna(0)).any()


def test_gap_mask_blanks_the_first_row_after_a_hole():
    raw = _frame(DISAGG, n=60)
    idx = raw.index.to_list()
    hole_at = 30
    idx = idx[:hole_at] + [d + pd.Timedelta(days=294) for d in idx[hole_at:]]
    raw.index = pd.DatetimeIndex(idx)
    cat = _cat(DISAGG, raw)
    mm = _spec(DISAGG, "managed_money")
    net = cat[categories.net_col(mm)]

    masked = flows.weekly_change(net)
    assert pd.isna(masked.iloc[hole_at])
    assert masked.iloc[hole_at + 1:].notna().all()
    assert masked.iloc[1:hole_at].notna().all()

    unmasked = flows.weekly_change(net, max_gap_days=None)
    assert unmasked.iloc[1:].notna().all()

    out = flows.build_flow_frame(cat, DISAGG)
    assert pd.isna(out[flows.flow_col(mm)].iloc[hole_at])
    assert pd.isna(out[flows.flow_z_col(mm)].iloc[hole_at])


def test_seam_mask_blanks_every_code_change():
    codes = list("AABAABB")
    s = pd.Series(range(7), dtype=float, index=pd.date_range("2023-01-03", periods=7,
                                                              freq="7D"))
    out = flows.weekly_change(s, source_code=pd.Series(codes, index=s.index))
    expect_nan = [True, False, True, True, False, True, False]
    assert out.isna().tolist() == expect_nan


def test_seam_mask_reaches_build_flow_frame_through_source_code():
    raw = _frame(DISAGG, n=12)
    raw["CFTC_Contract_Market_Code_Quotes"] = ["058643"] * 6 + ["058644"] * 6
    out = _flow(DISAGG, raw)
    for spec in categories.categories_for(DISAGG):
        assert pd.isna(out[flows.flow_col(spec)].iloc[6]), spec.key
        assert pd.isna(out[flows.flow_long_col(spec)].iloc[6]), spec.key
        assert out[flows.flow_col(spec)].iloc[1:6].notna().all(), spec.key
        assert out[flows.flow_col(spec)].iloc[7:].notna().all(), spec.key


def test_missing_category_yields_no_flow_columns_and_no_error():
    raw = _frame(TFF).drop(columns=["Dealer_Positions_Long_All"])
    out = _flow(TFF, raw)
    dealer = _spec(TFF, "dealer")
    assert not any(c.startswith(dealer.prefix) for c in out.columns)
    # Spreadless categories (no spread leg) still get the full flow family.
    nonrep = _spec(TFF, "nonreportable")
    for col in (flows.flow_col, flows.flow_long_col, flows.flow_short_col,
                flows.flow_z_col, flows.flow_thin_col):
        assert col(nonrep) in out.columns


def test_swap_underscore_spellings_give_identical_flows():
    raw = _frame(DISAGG)
    swap = _spec(DISAGG, "swap")
    single = raw.rename(columns={swap.short_col: swap.short_col.replace("__", "_"),
                                 swap.spread_col: swap.spread_col.replace("__", "_")})
    pd.testing.assert_frame_equal(_flow(DISAGG, raw), _flow(DISAGG, single))


def test_window_is_fixed_regardless_of_page_lookback():
    """OJ's Custom lookback is 8 weeks and PA's is 216, and neither may reach the z."""
    raw = _frame(DISAGG, n=80)
    a = _flow(DISAGG, raw, lookback=8)
    b = _flow(DISAGG, raw, lookback=216)
    pd.testing.assert_frame_equal(a, b)
    z_cols = [c for c in a.columns if const.FLOW_Z in c]
    assert z_cols and all(c.endswith("Flow Z 52w") for c in z_cols)
    assert a.attrs["flow_window"] == 52
    assert a.attrs["flow_min_periods"] == 26


def test_no_flow_column_collides_with_a_category_column():
    for report in (DISAGG, TFF):
        cat = _cat(report)
        out = flows.build_flow_frame(cat, report)
        assert not set(out.columns) & set(cat.columns)


# --- the classifier -------------------------------------------------------------

def test_flow_signs_are_strict_and_na_preserving():
    z = pd.Series([np.nan, 1.0, 1.01, -1.0, -1.01, 0.0])
    got = flows.flow_signs(z)
    assert got.dtype == "Int64"
    assert pd.isna(got.iloc[0])
    assert got.iloc[1:].tolist() == [0, 1, 0, -1, 0]
    assert const.FLOW_ACTIVE_Z == 1.0
    assert flows.flow_signs(pd.Series([1.5]), threshold=2.0).iloc[0] == 0


def test_flow_state_vocabulary():
    def state(a, b, c, report=DISAGG):
        s = flows.flow_state(pd.Series([a], dtype="Int64"), pd.Series([b], dtype="Int64"),
                             pd.Series([c], dtype="Int64"), report)
        return s.iloc[0]

    assert state(-1, 1, -1) == "VALUE_ACCUM"
    assert state(1, 1, 1) == "BROAD_ACCUM"
    assert state(0, 0, 0) == "QUIET"
    assert state(1, 0, 0) == "PARTIAL"
    assert state(pd.NA, 1, 1) is None
    assert state(1, pd.NA, 1) is None
    assert state(-1, 1, 0, report=TFF) == "PARTIAL"
    assert state(-1, 1, 1, report=TFF) == "-,+,+"
    assert state(0, 0, 0, report=TFF) == "QUIET"


def test_warm_up_rows_are_none_never_quiet():
    out = _flow(DISAGG, _frame(DISAGG, n=40), symbol="GC")
    state = out[const.FLOW_STATE]
    assert all(v is None for v in state.iloc[:26])
    assert state.iloc[26:].notna().all()
    assert out[const.FLOW_N_ACTIVE].iloc[:26].isna().all()
    assert out[const.FLOW_N_ACTIVE].iloc[26:].notna().all()


def test_active_count_is_the_number_of_nonzero_opinion_signs():
    out = _flow(DISAGG, _frame(DISAGG, n=80), symbol="GC")
    opinion = flow_roles.roles_for(DISAGG, "GC").opinion
    signs = pd.concat([out[flows.flow_sign_col(_spec(DISAGG, k))] for k in opinion],
                      axis=1)
    expect = (signs != 0).sum(axis=1).astype("Int64").mask(signs.isna().any(axis=1),
                                                            pd.NA)
    pd.testing.assert_series_equal(out[const.FLOW_N_ACTIVE], expect, check_names=False)
    counts = out[const.FLOW_N_ACTIVE].dropna()
    assert set(counts.unique()) <= {0, 1, 2, 3}
    assert counts.nunique() > 1, "the random frame should reach more than one count"


def test_one_unreadable_opinion_cohort_blanks_count_and_state_on_every_row():
    """A cohort with no reading (constant legs, zero-sd window) is NA, and NA is
    contagious: the count and the state are NA / None on every row, never QUIET or
    PARTIAL on the two cohorts that do read."""
    raw = _frame(DISAGG, n=80)
    other = _spec(DISAGG, "other_reportable")
    raw[other.long_col] = 0
    raw[other.short_col] = 0
    out = _flow(DISAGG, raw, symbol="GC")
    assert out[flows.flow_z_col(other)].isna().all()
    assert out[flows.flow_sign_col(other)].isna().all()
    assert out[const.FLOW_N_ACTIVE].isna().all()
    assert const.FLOW_STATE in out.columns
    assert all(v is None for v in out[const.FLOW_STATE])


# --- roles ----------------------------------------------------------------------

def _every_entry():
    yield from flow_roles.DEFAULTS.values()
    yield from flow_roles.MEASURED.values()


def test_roles_cover_every_category_once_with_the_opinion_overlap():
    """Drift alarm: a regenerated table must still partition the categories.

    Each key is in the opinion triple, or in exactly one of counterparty / neutral /
    inert / residual, or both (the documented overlap where a measured counterparty
    is other_reportable). Never in two of the four.
    """
    for roles in _every_entry():
        keys = {s.key for s in categories.categories_for(roles.report)}
        four = (roles.counterparty, roles.neutral, roles.inert, roles.residual)
        flat = [k for bucket in four for k in bucket]
        assert len(flat) == len(set(flat)), roles
        assert set(flat) | set(roles.opinion) == keys, roles
        assert len(roles.opinion) == 3, roles


def test_measured_table_matches_the_recommendation():
    """21 measured, 21 refused, and the opinion triple is the default everywhere."""
    measured = {k for k, r in flow_roles.MEASURED.items() if r.source == "measured"}
    assert measured == {
        (DISAGG, s) for s in "CT GC HG KC LBR LE OJ PA PL SI ZC ZL ZM ZS".split()
    } | {(TFF, s) for s in "6A 6B 6E 6J 6M 6N RTY".split()}
    for (report, _), roles in flow_roles.MEASURED.items():
        assert roles.opinion == flow_roles.DEFAULTS[report].opinion
        if roles.source != "measured":
            assert roles.source == flow_roles.SOURCE_UNSTABLE
            assert roles.counterparty == flow_roles.DEFAULTS[report].counterparty


def test_roles_for_unknown_symbol_returns_the_default():
    assert flow_roles.roles_for(DISAGG, "NOPE") is flow_roles.DEFAULTS[DISAGG]
    assert flow_roles.roles_for(TFF) is flow_roles.DEFAULTS[TFF]
    assert flow_roles.roles_for(TFF, "EMD").state_eligible is False
    with pytest.raises(ValueError, match="disagg"):
        flow_roles.roles_for("disaggregated", "GC")


def test_state_eligibility_follows_adr_0005():
    for sym in "ES NQ RTY YM ZB ZN ZF ZT BTC ETH".split():
        assert flow_roles.roles_for(TFF, sym).state_eligible is False, sym
    for sym in "6A 6B 6C 6E 6J 6M 6N 6S DX".split():
        assert flow_roles.roles_for(TFF, sym).state_eligible is True, sym
    for (report, _), roles in flow_roles.MEASURED.items():
        if report == DISAGG:
            assert roles.state_eligible is True


def test_ineligible_market_gets_z_cells_and_no_state():
    out = _flow(TFF, symbol="ES")
    assert flows.flow_z_col(_spec(TFF, "leveraged")) in out.columns
    assert const.FLOW_N_ACTIVE in out.columns
    assert const.FLOW_STATE not in out.columns
    assert out.attrs["flow_roles"]["state_eligible"] is False
    eligible = _flow(TFF, symbol="6E")
    assert const.FLOW_STATE in eligible.columns


def test_measured_counterparty_composite_is_the_sum_of_exactly_its_members():
    """HG's measured counterparty is Prod + Swap + Other, not the default Prod alone."""
    roles = flow_roles.roles_for(DISAGG, "HG")
    assert roles.source == "measured"
    assert set(roles.counterparty) == {"producer_merchant", "swap", "other_reportable"}
    raw = _balanced_frame(DISAGG)
    out = _flow(DISAGG, raw, symbol="HG")
    members = sum(out[flows.flow_col(_spec(DISAGG, k))] for k in roles.counterparty)
    pd.testing.assert_series_equal(out[flows.counterparty_flow_col()], members,
                                   check_names=False)
    assert out.attrs["flow_roles"]["counterparty"] == roles.counterparty

    # The Disaggregated default is Producer/Merchant alone with the swap dealers neutral
    # (docs/design/cot-flows.md, decision 6): a fallback is the conservative core.
    assert flow_roles.DEFAULTS[DISAGG].counterparty == ("producer_merchant",)
    assert flow_roles.DEFAULTS[DISAGG].neutral == ("swap",)
    default = _flow(DISAGG, raw)
    prod = out[flows.flow_col(_spec(DISAGG, "producer_merchant"))]
    pd.testing.assert_series_equal(default[flows.counterparty_flow_col()], prod,
                                   check_names=False)
    assert not default[flows.counterparty_flow_col()].equals(out[flows.counterparty_flow_col()])


def test_composite_absent_when_no_member_is_present():
    raw = _frame(TFF).drop(columns=["Dealer_Positions_Long_All"])
    out = _flow(TFF, raw, symbol="6E")
    assert flows.counterparty_flow_col() not in out.columns
    assert flows.counterparty_flow_z_col() not in out.columns


# --- thin, empty ----------------------------------------------------------------

def test_thin_flags_small_cohorts_and_is_na_in_the_warm_up():
    raw = _frame(DISAGG, n=60)
    rng = np.random.default_rng(1)
    swap = _spec(DISAGG, "swap")
    raw[swap.long_col] = 500 + rng.integers(-3, 4, 60)
    raw[swap.short_col] = 400 + rng.integers(-3, 4, 60)
    out = _flow(DISAGG, raw)
    thin = out[flows.flow_thin_col(swap)]
    assert thin.dtype == "boolean"
    assert thin.iloc[:26].isna().all()
    assert thin.iloc[26:].all()
    big = out[flows.flow_thin_col(_spec(DISAGG, "managed_money"))]
    assert not big.iloc[26:].any()


def test_empty_input_returns_empty_frame():
    assert flows.build_flow_frame(pd.DataFrame(), DISAGG).empty
    assert flows.build_flow_frame(None, TFF).empty
    assert flows.build_flow_frame(
        categories.build_category_frame(pd.DataFrame(), DISAGG, 52), DISAGG).empty


# --- the CotIndexer wiring ------------------------------------------------------

def test_get_category_data_concat_path_runs_store_free(monkeypatch):
    """The concat, the attrs merge and the price merge that runs AFTER it, with
    get_cot replaced by the synthetic frame so CI's empty store executes the lines.
    The GC test below is the live-store confirmation of the same path."""
    import cotdata

    from cotmetrics.CotIndexer import CotIndexer, Instrument, _IndexState

    raw = _frame(DISAGG, n=60)
    raw.index.name = const.REPORT_DATE_XLS       # get_cot names its index this way
    monkeypatch.setattr(cotdata, "get_cot", lambda code, report=None, **kw: raw)
    monkeypatch.setattr(CotIndexer, "available_reports_for",
                        lambda self, name: (DISAGG,))

    inst = Instrument("Metals", "Gold", "GC", "088691", 26)
    inst.df = pd.DataFrame({const.REPORT_DATE_XLS: raw.index.to_numpy(),
                            const.CLOSING_PRICE: np.arange(60, dtype=float)})
    ix = CotIndexer.__new__(CotIndexer)
    ix._state = _IndexState()
    ix._state.instruments = {"088691": inst}
    ix.lookbacks = [["6-months", 26], ["1-years", 52]]
    frame = CotIndexer.get_category_data(ix, "Gold", DISAGG, lookback="52",
                                         with_price=True)

    mm = _spec(DISAGG, "managed_money")
    assert flows.flow_z_col(mm) in frame.columns
    assert flows.counterparty_flow_col() in frame.columns
    assert const.FLOW_STATE in frame.columns
    assert const.FLOW_N_ACTIVE in frame.columns
    assert frame[const.CLOSING_PRICE].notna().all(), "the price merge lost rows"
    assert frame.index.name == const.DATE
    assert len(frame) == 60
    assert frame.attrs["lookback_header"] == " 52"
    assert frame.attrs["flow_window"] == 52
    assert frame.attrs["flow_min_periods"] == 26
    assert frame.attrs["flow_roles"]["symbol"] == "GC"
    assert frame.attrs["report"] == DISAGG
    assert frame[flows.flow_z_col(mm)].iloc[26:].notna().all()


# --- store-backed ---------------------------------------------------------------

def test_get_category_data_carries_the_flow_family_on_gold():
    """One end-to-end read. Skips itself where the store lacks GC's Disaggregated
    file, which is CI's empty store. Run with -rs to see which it was."""
    try:
        import cotdata.config as cfg
        have = (cfg.cot_disagg_dir() / "GC_088691.parquet").exists()
    except Exception:
        have = False
    if not have:
        pytest.skip("no GC disagg file in this COTDATA_STORE")

    from cotmetrics.CotIndexer import CotIndexer, Instrument, _IndexState

    # Built through __new__ like test_store_freshness's spy: the real __init__ loads
    # every market's cache and rebuilds on a miss, and only one market is under test.
    ix = CotIndexer.__new__(CotIndexer)
    ix._state = _IndexState()
    ix._state.instruments = {"088691": Instrument("Metals", "Gold", "GC", "088691", 26)}
    ix.lookbacks = [["6-months", 26], ["1-years", 52]]
    frame = CotIndexer.get_category_data(ix, "Gold", DISAGG, lookback="52",
                                         with_price=False)

    mm = _spec(DISAGG, "managed_money")
    assert flows.flow_z_col(mm) == "Managed Money Flow Z 52w"
    assert flows.flow_z_col(mm) in frame.columns
    assert frame.attrs["lookback_header"] == " 52"
    assert frame.attrs["flow_window"] == 52
    assert frame.attrs["flow_roles"]["symbol"] == "GC"
    total = sum(frame[flows.flow_col(s)]
                for s in categories.present_categories(frame, DISAGG))
    assert (total.dropna() == 0).all()
    assert len(total.dropna()) > 1000
