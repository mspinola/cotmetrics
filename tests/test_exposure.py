"""Contracts into dollars, and dollars into risk.

Every test here injects its own weekly frame and monkeypatches the two price series, so
none of it needs a store. That is deliberate: the arithmetic and the guards are the
interesting part, and the I/O is not.
"""
import numpy as np
import pandas as pd
import pytest

import cotmetrics.constants as const
import cotmetrics.exposure as ex


def weekly(dates, comm=None, large=None, small=None):
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    n = len(idx)
    return pd.DataFrame({
        const.COMM_NET: comm if comm is not None else [0.0] * n,
        const.LARGE_NET: large if large is not None else [0.0] * n,
        const.SMALL_NET: small if small is not None else [0.0] * n,
    }, index=idx)


def daily(start, values):
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series([float(v) for v in values], index=idx)


@pytest.fixture
def priced(monkeypatch):
    """A market called TEST: multiplier 50, price 100, daily vol 2%."""
    monkeypatch.setattr(ex, "point_values", lambda: {"TEST": 50.0})
    monkeypatch.setattr(ex, "price_levels", lambda s, *a, **k: daily("2026-01-01", [100.0] * 40))
    monkeypatch.setattr(ex, "sigma_series", lambda s, **k: daily("2026-01-01", [0.02] * 40))


# ── the arithmetic ────────────────────────────────────────────────────────────

def test_notional_is_contracts_times_multiplier_times_price(priced):
    frame = weekly(["2026-01-06", "2026-01-13"], comm=[-1000.0, -2000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="TEST")
    assert list(out["notional_usd"]) == [-1000 * 50 * 100, -2000 * 50 * 100]


def test_risk_MULTIPLIES_by_volatility(priced):
    """A vol targeter sizes at target/sigma, so its notional is inversely proportional
    to sigma and the PRODUCT is what stays constant while it sits at target. Dividing
    would describe nothing anybody does, and would move the wrong way when vol spikes."""
    frame = weekly(["2026-01-06"], comm=[-1000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="TEST")
    notional = out["notional_usd"].iloc[0]
    assert out["risk_usd"].iloc[0] == pytest.approx(notional * 0.02)
    assert out["risk_usd"].iloc[0] != pytest.approx(notional / 0.02)


def test_the_spec_leg_is_the_sum_of_two_legs_not_the_negation_of_commercials(priced):
    """The three Legacy legs sum to zero, so the mirror of Commercial net is Large PLUS
    Small. Computing it as a negation would agree only where the report balances exactly
    and would hide which series was actually read."""
    frame = weekly(["2026-01-06"], comm=[-1000.0], large=[700.0], small=[250.0])
    out = ex.market_exposure("t", leg=ex.LEG_SPEC, frame=frame, symbol="TEST")
    assert out["net_contracts"].iloc[0] == 950.0
    assert out["net_contracts"].iloc[0] != 1000.0


def test_a_market_with_no_multiplier_yields_no_dollars_rather_than_raising(monkeypatch):
    """MFS and MME are ICE MSCI futures priced off ETFs, and an ETF share is not a
    contract. Saying so in a column beats raising and taking the other 45 markets with
    it."""
    monkeypatch.setattr(ex, "point_values", lambda: {})
    frame = weekly(["2026-01-06"], comm=[-1000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="MFS")
    assert out["net_contracts"].iloc[0] == -1000.0
    assert np.isnan(out["notional_usd"].iloc[0])


# ── the two price series are not interchangeable ──────────────────────────────

def test_notional_refuses_anything_but_unadjusted_levels():
    """get_bars DEFAULTS to backadj for futures, and the `Closing Price` column already
    on every CotIndexer frame is that default, so the wrong series is the one nearest to
    hand. Additive adjustment restates history on every roll."""
    with pytest.raises(ex.ExposureError, match="tradeable price levels"):
        ex.price_levels("ES", "backadj")


def test_volatility_refuses_anything_but_ratio_adjusted_returns():
    with pytest.raises(ex.ExposureError, match="percentage returns"):
        ex.sigma_series("ES", adjustment="backadj")
    with pytest.raises(ex.ExposureError, match="percentage returns"):
        ex.sigma_series("ES", adjustment="unadj")


def test_the_two_series_ask_for_different_adjustments():
    """Stated as a pin because the whole module rests on it: one product, two price
    series, neither substituting for the other."""
    assert ex.LEVEL_ADJUSTMENT == "unadj"
    assert ex.RISK_ADJUSTMENT == "propadj"
    assert ex.LEVEL_ADJUSTMENT != ex.RISK_ADJUSTMENT


# ── staleness ─────────────────────────────────────────────────────────────────

def test_a_holiday_tuesday_takes_the_last_known_price(priced, monkeypatch):
    """A plain reindex would drop every COT date that was not a trading day."""
    px = daily("2026-01-01", [100.0] * 5).drop(pd.Timestamp("2026-01-05"))
    monkeypatch.setattr(ex, "price_levels", lambda s, *a, **k: px)
    out = ex.market_exposure("t", leg=ex.LEG_COMM,
                             frame=weekly(["2026-01-05"], comm=[-10.0]), symbol="TEST")
    assert out["price"].iloc[0] == 100.0


def test_a_price_older_than_the_staleness_bound_is_not_carried(priced, monkeypatch):
    """An unbounded fill would value a delisted market at whatever it last printed,
    forever, which is the silence this bound exists for."""
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 2))
    out = ex.market_exposure("t", leg=ex.LEG_COMM,
                             frame=weekly(["2026-03-01"], comm=[-10.0]), symbol="TEST")
    assert np.isnan(out["price"].iloc[0])
    assert np.isnan(out["notional_usd"].iloc[0])


# ── the aggregate states its set ──────────────────────────────────────────────

def _two_market_frames():
    return {
        "A": {"frame": weekly(["2026-01-06", "2026-01-13"], comm=[-100.0, -200.0]),
              "symbol": "TEST"},
        "B": {"frame": weekly(["2026-01-06", "2026-01-13"], comm=[-300.0, -400.0]),
              "symbol": "TEST"},
    }


def test_the_total_sums_only_weeks_every_member_can_price(priced):
    """A total that silently changes constituents is a different series each week, and
    the seam lands where a market's history starts or stops, which is exactly where a
    reader would read a level change as news."""
    frames = _two_market_frames()
    frames["B"]["frame"] = weekly(["2026-01-13"], comm=[-400.0])
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=frames)
    assert list(agg.frame.index) == [pd.Timestamp("2026-01-13")]
    assert agg.frame["notional_usd"].iloc[0] == (-200 - 400) * 50 * 100
    assert agg.weeks_lost == 1


def test_the_member_that_truncates_the_total_is_named(priced):
    """The live case this exists for: NKD's COT history ends 2026-03-03, so a strict
    six-market equity total ends there while the other five run to the current week, and
    nothing about the chart would say so."""
    frames = _two_market_frames()
    frames["B"]["frame"] = weekly(["2026-01-06"], comm=[-300.0])
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=frames)
    assert agg.bounded_by["end"] == "B"
    assert "start" not in agg.bounded_by


def test_a_member_with_no_multiplier_is_dropped_by_name_not_silently(monkeypatch):
    monkeypatch.setattr(ex, "point_values", lambda: {"TEST": 50.0})
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 40))
    monkeypatch.setattr(ex, "sigma_series", lambda s, **k: daily("2026-01-01", [0.02] * 40))
    frames = _two_market_frames()
    frames["B"]["symbol"] = "NOPE"
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=frames)
    assert "B" in agg.dropped
    assert "multiplier" in agg.dropped["B"]
    assert agg.frame["n_markets"].iloc[0] == 1


def test_the_total_carries_no_contracts_column_because_contracts_do_not_add(priced):
    """Summing ES contracts and corn contracts gives a number in no unit, and the frame
    that adds is the worst place to offer it: beside two columns that ARE summable and
    named alike, it reads as a third of the same kind. It stays on each member, where
    one market's contract count means something."""
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    assert "net_contracts" not in agg.frame.columns
    assert set(agg.frame.columns) == {"notional_usd", "risk_usd", "n_markets",
                                      "sigma_weighted", "notional_pct_rank",
                                      "risk_pct_rank"}
    assert all("net_contracts" in m.columns for m in agg.members.values())


def test_the_empty_total_carries_the_same_columns_as_a_real_one(monkeypatch):
    """An empty frame with a different column list is a second schema nothing tests, and
    a caller that handles the empty case first would be written against it."""
    monkeypatch.setattr(ex, "point_values", lambda: {})
    real = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM,
                                 frames=_two_market_frames())
    assert real.frame.empty
    monkeypatch.setattr(ex, "point_values", lambda: {"TEST": 50.0})
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 40))
    monkeypatch.setattr(ex, "sigma_series",
                        lambda s, **k: daily("2026-01-01", [0.02] * 40))
    populated = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM,
                                      frames=_two_market_frames())
    assert list(real.frame.columns) == list(populated.frame.columns)


def test_an_unbounded_total_names_no_bound(priced):
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    assert agg.bounded_by == {}
    assert agg.weeks_lost == 0
    assert len(agg.frame) == 2


# ── the percentile ────────────────────────────────────────────────────────────

def test_the_percentile_is_expanding_so_it_carries_no_look_ahead():
    """A full-sample rank tells 2010 where it sat in a distribution half of which had
    not happened, which is the kind of number that makes a backtest look prescient."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    rank = ex.expanding_pct_rank(s, min_periods=1)
    # Each value is the largest SO FAR, so every week is the 100th percentile of its own
    # history. Under a full-sample rank the first would be the 25th.
    assert list(rank) == [100.0, 100.0, 100.0, 100.0]


def test_the_percentile_says_nothing_until_it_has_enough_history():
    """Below min_periods a percentile is mostly a statement about how few observations
    there are."""
    rank = ex.expanding_pct_rank(pd.Series([1.0, 2.0, 3.0]), min_periods=3)
    assert list(rank.isna()) == [True, True, False]


def test_the_percentile_ranks_a_low_value_low():
    rank = ex.expanding_pct_rank(pd.Series([10.0, 20.0, 30.0, 5.0]), min_periods=1)
    assert rank.iloc[-1] == pytest.approx(25.0)


# ── the legs ──────────────────────────────────────────────────────────────────

def test_an_unknown_leg_is_refused(priced):
    with pytest.raises(ex.ExposureError, match="unknown leg"):
        ex.market_exposure("t", leg="middle",
                           frame=weekly(["2026-01-06"]), symbol="TEST")


def test_every_leg_has_a_label_and_a_column_set():
    assert set(ex.LEG_COLUMNS) == set(ex.LEG_LABELS)


# ── the reference index and the extreme bands ─────────────────────────────────

def test_the_composite_is_the_same_set_the_total_sums(monkeypatch):
    """The printed reference this view came from puts the S&P 500 alone above a total
    of four markets, so its reference is not its subject. Equal-weight of the set, each
    member rebased to its own first observation, needs no defending."""
    monkeypatch.setattr(ex, "point_values", lambda: {"A": 1.0, "B": 1.0})
    prices = {"A": daily("2026-01-01", [100.0, 110.0, 120.0]),
              "B": daily("2026-01-01", [50.0, 50.0, 100.0])}
    monkeypatch.setattr(ex, "price_levels", lambda s, *a, **k: prices[s])
    idx = ex.composite_price_index(
        ["A", "B"], frames={"A": {"symbol": "A"}, "B": {"symbol": "B"}})
    # A: 100 -> 110 -> 120.  B: 100 -> 100 -> 200.  Mean: 100, 105, 160.
    assert list(idx) == [100.0, 105.0, 160.0]


def test_a_member_with_no_multiplier_is_out_of_the_composite_too(monkeypatch):
    """It is out of the total, so including it here would put a market in the reference
    that is not in the subject, which is the defect this whole function exists to
    avoid."""
    monkeypatch.setattr(ex, "point_values", lambda: {"A": 1.0})
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0, 200.0]))
    idx = ex.composite_price_index(
        ["A", "B"], frames={"A": {"symbol": "A"}, "B": {"symbol": "MFS"}})
    assert list(idx) == [100.0, 200.0]


def test_the_extreme_band_is_expanding_like_the_percentile():
    """A static threshold from the whole sample marks 2010 extreme using 2026's
    distribution."""
    s = pd.Series([1.0, 2.0, 3.0, 100.0])
    band = ex.expanding_quantile(s, 0.9, min_periods=2)
    assert np.isnan(band.iloc[0])
    assert band.iloc[-1] > band.iloc[1]
    assert band.iloc[-1] < 100.0


# ── the total carries its own composition ─────────────────────────────────────

def test_the_members_sum_to_the_total_exactly(priced):
    """Returned rather than discarded because a total conceals its composition, and on
    the real equity complex one market is 59.5% of the gross speculator total."""
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    stacked = sum(m["notional_usd"] for m in agg.members.values())
    assert list(stacked) == list(agg.frame["notional_usd"])


def test_members_are_trimmed_to_the_weeks_the_total_covers(priced):
    """Otherwise a member would carry weeks the total does not, and the two would stop
    adding up exactly where a reader was checking them against each other."""
    frames = _two_market_frames()
    frames["B"]["frame"] = weekly(["2026-01-13"], comm=[-400.0])
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=frames)
    assert list(agg.members["A"].index) == list(agg.frame.index)
    assert len(agg.members["A"]) == 1


def test_a_dropped_member_is_not_in_the_membership(monkeypatch):
    monkeypatch.setattr(ex, "point_values", lambda: {"TEST": 50.0})
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 40))
    monkeypatch.setattr(ex, "sigma_series", lambda s, **k: daily("2026-01-01", [0.02] * 40))
    frames = _two_market_frames()
    frames["B"]["symbol"] = "NOPE"
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=frames)
    assert set(agg.members) == {"A"}


# ── agreement ─────────────────────────────────────────────────────────────────

def test_agreement_is_one_when_every_contributor_points_the_same_way():
    assert ex.agreement([3.0, 1.0, 6.0]) == pytest.approx(1.0)
    assert ex.agreement([-3.0, -1.0, -6.0]) == pytest.approx(1.0)


def test_agreement_falls_as_contributors_cancel():
    """The number that says whether a total is a crowd or an argument. Measured on one
    real week: 1.00 for Small Traders, unanimous, and 0.63 for Large Speculators, split,
    on the same markets on the same day."""
    assert ex.agreement([10.0, -4.0]) == pytest.approx(6 / 14)
    assert ex.agreement([5.0, -5.0]) == pytest.approx(0.0)


def test_agreement_is_undefined_rather_than_perfect_on_nothing():
    import math
    assert math.isnan(ex.agreement([]))
    assert math.isnan(ex.agreement([0.0, 0.0]))


# ── contributions ─────────────────────────────────────────────────────────────

def test_contributions_lead_with_what_is_driving_the_total(priced):
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    got = ex.contributions(agg.members, "notional_usd")
    # B is -400 contracts against A's -200 in the last week, so B leads on magnitude.
    assert list(got.index) == ["B", "A"]
    assert got.iloc[0] == -400 * 50 * 100


def test_contributions_can_be_asked_for_an_earlier_week(priced):
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    got = ex.contributions(agg.members, "notional_usd", when=pd.Timestamp("2026-01-06"))
    assert got["A"] == -100 * 50 * 100


def test_contributions_of_nothing_is_empty_rather_than_an_error():
    assert ex.contributions({}, "notional_usd").empty


# ── the contribution table ────────────────────────────────────────────────────

def test_the_table_carries_both_units_whichever_one_is_drawn(priced):
    """They are not substitutes: on the Energies complex their percentiles correlate
    0.802, with a median gap of 9.6 percentile points and a worst gap of 69."""
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    table = ex.contribution_table(agg.members, min_rank_periods=1)
    assert set(table.columns) == {"notional_usd", "risk_usd",
                                  "notional_pct_rank", "risk_pct_rank"}


def test_each_member_is_ranked_against_its_own_history(priced):
    """A market at its own 99th percentile inside a total sitting at its 40th is the
    kind of thing a sum cannot show."""
    frames = {
        "steady": {"frame": weekly(["2026-01-06", "2026-01-13", "2026-01-20"],
                                   comm=[-100.0, -100.0, -100.0]), "symbol": "TEST"},
        "extreme": {"frame": weekly(["2026-01-06", "2026-01-13", "2026-01-20"],
                                    comm=[-10.0, -50.0, -900.0]), "symbol": "TEST"},
    }
    agg = ex.aggregate_exposure(["steady", "extreme"], leg=ex.LEG_COMM, frames=frames)
    table = ex.contribution_table(agg.members, min_rank_periods=1)
    # "extreme" is at its own most negative week, so it ranks at the BOTTOM of its own
    # history; "steady" has never moved, so every week ties and it ranks at the top.
    assert table.loc["extreme", "notional_pct_rank"] == pytest.approx(100 / 3)
    assert table.loc["steady", "notional_pct_rank"] == pytest.approx(100.0)


def test_the_market_driving_the_total_leads_the_table(priced):
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    table = ex.contribution_table(agg.members, min_rank_periods=1)
    assert list(table.index) == ["B", "A"]


def test_the_table_can_be_asked_for_an_earlier_week(priced):
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    table = ex.contribution_table(agg.members, when=pd.Timestamp("2026-01-06"),
                                  min_rank_periods=1)
    assert table.loc["A", "notional_usd"] == -100 * 50 * 100


def test_a_table_of_nothing_still_has_its_columns():
    """So a caller can build column definitions from it without branching."""
    table = ex.contribution_table({})
    assert table.empty
    assert "risk_usd" in table.columns
    assert "risk_pct_rank" in table.columns


def test_the_table_names_its_percentile_columns_the_way_the_frame_does(priced):
    """They did not, for one commit: the frame said `notional_pct_rank` while the table
    said `notional_usd_pct_rank`, which is the kind of near-miss a caller resolves by
    writing whichever one their fixture happened to have."""
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM, frames=_two_market_frames())
    table = ex.contribution_table(agg.members, min_rank_periods=1)
    for column in ("notional_pct_rank", "risk_pct_rank"):
        assert column in agg.frame.columns
        assert column in table.columns
    assert ex.rank_column("risk_usd") == "risk_pct_rank"


# ── the numeraire ─────────────────────────────────────────────────────────────

def test_gold_divides_the_dollars_and_leaves_the_contracts_alone(monkeypatch, priced):
    """Contracts are contracts under any numeraire. Read on the members, because the
    total has no contracts column to read it on."""
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 40)
                        if s != "GC" else daily("2026-01-01", [2000.0] * 40))
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM,
                                numeraire=ex.NUMERAIRE_GOLD,
                                frames=_two_market_frames())
    usd = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM,
                                frames=_two_market_frames())
    assert agg.numeraire == ex.NUMERAIRE_GOLD
    assert (list(agg.members["A"]["net_contracts"])
            == list(usd.members["A"]["net_contracts"]))
    assert agg.frame["notional_usd"].iloc[-1] == pytest.approx(
        usd.frame["notional_usd"].iloc[-1] / 2000.0)


def test_the_numeraire_applies_before_the_percentile_is_computed(monkeypatch):
    """Applying it later would leave a percentile computed on a dollar series describing
    a gold one, which is the kind of mismatch nothing on screen would reveal. Against the
    real store the two genuinely differ: US equity speculators sat at the 98th percentile
    in USD and the 67th in ounces of gold on the same week."""
    monkeypatch.setattr(ex, "point_values", lambda: {"TEST": 50.0})
    monkeypatch.setattr(ex, "sigma_series", lambda s, **k: daily("2026-01-01", [0.02] * 40))
    # Flat position, rising gold: in dollars every week ties, in gold each is lower than
    # the last, so the last week ranks top in one and bottom in the other.
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 40)
                        if s != "GC" else daily("2026-01-01", list(range(100, 140))))
    frame = weekly(["2026-01-06", "2026-01-13", "2026-01-20"], comm=[100.0] * 3)
    frames = {"A": {"frame": frame, "symbol": "TEST"}}
    in_usd = ex.aggregate_exposure(["A"], leg=ex.LEG_COMM, min_rank_periods=1,
                                   frames=frames)
    in_gold = ex.aggregate_exposure(["A"], leg=ex.LEG_COMM, min_rank_periods=1,
                                    numeraire=ex.NUMERAIRE_GOLD, frames=frames)
    assert in_usd.frame["notional_pct_rank"].iloc[-1] == pytest.approx(100.0)
    assert in_gold.frame["notional_pct_rank"].iloc[-1] < 100.0


def test_the_members_are_deflated_too_so_they_still_sum_to_the_total(monkeypatch, priced):
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [100.0] * 40)
                        if s != "GC" else daily("2026-01-01", [2000.0] * 40))
    agg = ex.aggregate_exposure(["A", "B"], leg=ex.LEG_COMM,
                                numeraire=ex.NUMERAIRE_GOLD,
                                frames=_two_market_frames())
    stacked = sum(m["notional_usd"] for m in agg.members.values())
    assert list(stacked) == list(agg.frame["notional_usd"])


def test_dollars_need_no_divisor():
    assert ex.numeraire_series(ex.NUMERAIRE_USD,
                               pd.date_range("2026-01-06", periods=3)) is None


def test_an_unknown_numeraire_is_refused():
    with pytest.raises(ex.ExposureError, match="unknown numeraire"):
        ex.numeraire_series("silver", pd.date_range("2026-01-06", periods=3))


def test_a_non_positive_gold_price_is_masked_rather_than_divided_by(monkeypatch):
    """Not a market event, a broken read. Dividing by it would produce an infinity that
    looks like a record position."""
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [2000.0, 0.0, 2000.0]))
    got = ex.numeraire_series(ex.NUMERAIRE_GOLD,
                              pd.DatetimeIndex(["2026-01-01", "2026-01-02",
                                                "2026-01-03"]))
    assert got.iloc[0] == 2000.0
    assert pd.isna(got.iloc[1])


def test_both_numeraires_are_labelled():
    assert set(ex.NUMERAIRE_LABELS) == {ex.NUMERAIRE_USD, ex.NUMERAIRE_GOLD}


def test_the_composite_follows_the_numeraire_so_it_stays_the_subjects_reference(monkeypatch):
    """A price panel above an exposure panel is a reference for it, and a reference in a
    different unit from its subject is the same defect as the printed source's
    S&P-over-four-markets.

    Under gold this is Larry Williams' WillVal applied to a complex: an asset measured
    against a hard-money benchmark rather than a currency. Since August 2002 the US
    equity composite is up 13.88x in dollars and 0.99x in gold.
    """
    monkeypatch.setattr(ex, "point_values", lambda: {"A": 1.0})
    prices = {"A": daily("2026-01-01", [100.0, 200.0, 400.0]),
              "GC": daily("2026-01-01", [1000.0, 1000.0, 4000.0])}
    monkeypatch.setattr(ex, "price_levels", lambda s, *a, **k: prices[s])
    frames = {"A": {"symbol": "A"}}
    in_usd = ex.composite_price_index(["A"], frames=frames)
    in_gold = ex.composite_price_index(["A"], numeraire=ex.NUMERAIRE_GOLD,
                                       frames=frames)
    assert list(in_usd) == [100.0, 200.0, 400.0]
    # Price 4x, gold 4x: unchanged in gold, which is the whole point of the view.
    assert list(in_gold) == [100.0, 200.0, 100.0]


def test_the_gold_composite_still_starts_at_the_base(monkeypatch):
    monkeypatch.setattr(ex, "point_values", lambda: {"A": 1.0})
    prices = {"A": daily("2026-01-01", [37.0, 40.0]),
              "GC": daily("2026-01-01", [1234.0, 1300.0])}
    monkeypatch.setattr(ex, "price_levels", lambda s, *a, **k: prices[s])
    got = ex.composite_price_index(["A"], numeraire=ex.NUMERAIRE_GOLD,
                                   frames={"A": {"symbol": "A"}})
    assert got.iloc[0] == pytest.approx(100.0)


# ── effective-dated multipliers ───────────────────────────────────────────────
#
# `point_values` reads contract_specs, one row per symbol with no effective date. It
# answers "can this market be priced". `point_value_series` answers "what was it worth
# that week", which differs wherever an exchange re-denominated a contract. The live
# case is RTY: ICE cut the Russell multiplier from $100 to $50 on 2016-12-05 with no
# CFTC rename to mark it, so 740 of its 1,247 priced weeks sit on the old contract.
#
# marketdata owns the regime data. These tests inject it rather than reading the
# packaged file, so they pin THIS package's behaviour (per-week multiply, refusal,
# fallback) and not marketdata's table, which has its own tests.


@pytest.fixture
def regimed(monkeypatch):
    """Fake a marketdata whose only declared symbol is TEST: 200 before 2026-01-10,
    50 from it. Same shape as the real Russell change, an order of magnitude smaller."""
    def read_contract_regimes(symbol):
        if symbol != "TEST":
            return pd.DataFrame()
        return pd.DataFrame({"Symbol": ["TEST", "TEST"],
                             "Valid_From": pd.to_datetime([None, "2026-01-10"]),
                             "Point_Value": [200.0, 50.0]})

    def point_value_asof(symbol, dates):
        idx = pd.DatetimeIndex(pd.to_datetime(dates))
        return pd.Series(np.where(idx < pd.Timestamp("2026-01-10"), 200.0, 50.0),
                         index=idx, dtype="float64")

    fake = type("M", (), {"read_contract_regimes": staticmethod(read_contract_regimes),
                          "point_value_asof": staticmethod(point_value_asof)})
    monkeypatch.setitem(__import__("sys").modules, "marketdata", fake)
    return fake


def test_a_re_denominated_contract_uses_the_multiplier_of_its_own_week(priced, regimed):
    frame = weekly(["2026-01-06", "2026-01-13"], comm=[-1000.0, -1000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="TEST")
    assert list(out["point_value"]) == [200.0, 50.0]
    # Same contract count, same price, four times the dollars before the change.
    assert list(out["notional_usd"]) == [-1000 * 200 * 100, -1000 * 50 * 100]


def test_the_point_value_column_reports_the_week_not_today(priced, regimed):
    """A reader checking why an old week is large must be able to see the multiplier
    that produced it. A column carrying today's value would explain nothing."""
    frame = weekly(["2026-01-06", "2026-01-13"], comm=[0.0, 0.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="TEST")
    assert out["point_value"].nunique() == 2


def test_risk_inherits_the_correction(priced, regimed):
    """risk_usd is notional x sigma, so it must move with the multiplier, not beside it."""
    frame = weekly(["2026-01-06"], comm=[-1000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="TEST")
    assert out["risk_usd"].iloc[0] == pytest.approx(-1000 * 200 * 100 * 0.02)


def test_an_undeclared_symbol_keeps_one_multiplier_for_its_whole_history(priced, monkeypatch):
    """The common case, and it must stay a flat series: nothing established a
    re-denomination for these markets, which is a claim, not a shrug."""
    fake = type("M", (), {
        "read_contract_regimes": staticmethod(lambda s: pd.DataFrame()),
        "point_value_asof": staticmethod(lambda s, d: pytest.fail(
            "an undeclared symbol must not need a regime lookup"))})
    monkeypatch.setitem(__import__("sys").modules, "marketdata", fake)
    dates = pd.to_datetime(["2026-01-06", "2026-01-13"])
    assert list(ex.point_value_series("TEST", dates)) == [50.0, 50.0]


def test_an_unestablished_multiplier_gives_no_dollars_rather_than_a_guess(priced, monkeypatch):
    """marketdata returns NaN where a regime was never established (LBR before 1995).
    The dollars must go with it: a gap is visible on a chart and a guess is not."""
    def point_value_asof(symbol, dates):
        idx = pd.DatetimeIndex(pd.to_datetime(dates))
        return pd.Series([np.nan, 50.0], index=idx, dtype="float64")

    fake = type("M", (), {
        "read_contract_regimes": staticmethod(lambda s: pd.DataFrame({"Symbol": ["TEST"]})),
        "point_value_asof": staticmethod(point_value_asof)})
    monkeypatch.setitem(__import__("sys").modules, "marketdata", fake)

    frame = weekly(["2026-01-06", "2026-01-13"], comm=[-1000.0, -1000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="TEST")
    assert np.isnan(out["notional_usd"].iloc[0])
    assert np.isnan(out["risk_usd"].iloc[0])
    assert out["notional_usd"].iloc[1] == -1000 * 50 * 100


def test_a_marketdata_without_regimes_is_refused_not_silently_flattened(priced, monkeypatch):
    """The failure this whole change exists to prevent. Falling back to the flat series
    would return a plausible number that is wrong by 2x on RTY, and nothing downstream
    could tell. Refuse loudly and name the version."""
    fake = type("M", (), {})           # marketdata < 0.2.0: no regime API at all
    monkeypatch.setitem(__import__("sys").modules, "marketdata", fake)
    with pytest.raises(ex.ExposureError, match="0.2.0"):
        ex.point_value_series("TEST", pd.to_datetime(["2026-01-06"]))


def test_membership_still_comes_from_the_current_spec(priced, regimed):
    """A market absent from contract_specs has no dollars at all, and that check must
    stay on the CURRENT table: a regime table cannot say a market is unpriceable."""
    frame = weekly(["2026-01-06"], comm=[-1000.0])
    out = ex.market_exposure("t", leg=ex.LEG_COMM, frame=frame, symbol="ABSENT")
    assert np.isnan(out["notional_usd"].iloc[0])
    assert np.isnan(out["point_value"].iloc[0])


def test_weeks_with_no_multiplier_drop_out_of_the_aggregate(monkeypatch):
    """An unestablished multiplier must not quietly become a zero in a sum."""
    monkeypatch.setattr(ex, "point_values", lambda: {"A": 1.0, "B": 1.0})
    monkeypatch.setattr(ex, "price_levels", lambda s, *a, **k: daily("2026-01-01", [10.0] * 40))
    monkeypatch.setattr(ex, "sigma_series", lambda s, **k: daily("2026-01-01", [0.01] * 40))

    def point_value_asof(symbol, dates):
        idx = pd.DatetimeIndex(pd.to_datetime(dates))
        vals = [np.nan, 1.0] if symbol == "A" else [1.0, 1.0]
        return pd.Series(vals, index=idx, dtype="float64")

    fake = type("M", (), {
        "read_contract_regimes": staticmethod(lambda s: pd.DataFrame({"Symbol": [s]})),
        "point_value_asof": staticmethod(point_value_asof)})
    monkeypatch.setitem(__import__("sys").modules, "marketdata", fake)

    dates = ["2026-01-06", "2026-01-13"]
    frames = {"a": {"frame": weekly(dates, comm=[-100.0, -100.0]), "symbol": "A"},
              "b": {"frame": weekly(dates, comm=[-100.0, -100.0]), "symbol": "B"}}
    agg = ex.aggregate_exposure(["a", "b"], frames=frames)
    # Week 1 is incomplete for A, so the total starts at week 2 rather than counting B alone.
    assert list(agg.frame.index) == [pd.Timestamp("2026-01-13")]
    assert agg.frame["notional_usd"].iloc[0] == -100 * 1.0 * 10 * 2


# ── the set's volatility ──────────────────────────────────────────────────────

def _sized_frames():
    """Two markets, one ten times the other's size, on the same two weeks."""
    return {
        "Big": {"frame": weekly(["2026-01-06", "2026-01-13"], comm=[1000.0, 1000.0]),
                "symbol": "BIG"},
        "Small": {"frame": weekly(["2026-01-06", "2026-01-13"], comm=[100.0, 100.0]),
                  "symbol": "SMALL"},
    }


@pytest.fixture
def two_vols(monkeypatch):
    """BIG at 2% daily, SMALL at 12%, both priced at 100 with a multiplier of 50."""
    monkeypatch.setattr(ex, "point_values", lambda: {"BIG": 50.0, "SMALL": 50.0,
                                                     "GC": 100.0})
    monkeypatch.setattr(ex, "price_levels",
                        lambda s, *a, **k: daily("2026-01-01", [2000.0] * 40)
                        if s == "GC" else daily("2026-01-01", [100.0] * 40))
    monkeypatch.setattr(ex, "sigma_series",
                        lambda s, **k: daily("2026-01-01",
                                             [0.12 if s == "SMALL" else 0.02] * 40))


def test_a_single_market_total_reports_that_markets_own_volatility(priced):
    """The weighted mean of one thing is that thing, so a caller drawing this has one
    code path rather than a single-market special case."""
    agg = ex.aggregate_exposure(["A"], leg=ex.LEG_COMM, frames={
        "A": {"frame": weekly(["2026-01-06", "2026-01-13"], comm=[-100.0, -200.0]),
              "symbol": "TEST"}})
    assert agg.frame["sigma_weighted"].round(10).eq(0.02).all()


def test_the_sets_volatility_is_weighted_by_how_much_is_held(two_vols):
    """(10 x 0.02 + 1 x 0.12) / 11 = 0.0291. The big position is most of the answer,
    which is the only weighting that describes what a holder is exposed to."""
    agg = ex.aggregate_exposure(["Big", "Small"], leg=ex.LEG_COMM,
                                frames=_sized_frames())
    assert agg.frame["sigma_weighted"].round(4).eq(0.0291).all()


def test_the_weights_are_GROSS_so_opposed_members_cannot_blow_it_up(two_vols):
    """The obvious weighting is signed, which is exactly `risk_usd / notional_usd`, and
    it is wrong: on a set whose members lean opposite ways the denominator passes
    through zero, so the volatility goes to infinity and changes sign on a week where
    nothing about any member's volatility happened."""
    frames = _sized_frames()
    frames["Small"]["frame"] = weekly(["2026-01-06", "2026-01-13"],
                                      comm=[-1000.0, -1000.0])
    agg = ex.aggregate_exposure(["Big", "Small"], leg=ex.LEG_COMM, frames=frames)
    signed = agg.frame["risk_usd"] / agg.frame["notional_usd"]
    assert not np.isfinite(signed).all()
    assert agg.frame["sigma_weighted"].round(10).eq(0.07).all()


def test_a_week_holding_nothing_has_no_holdings_to_weight_by(priced):
    """NaN, not zero. Zero would claim the set holds something with no volatility."""
    agg = ex.aggregate_exposure(["A"], leg=ex.LEG_COMM, frames={
        "A": {"frame": weekly(["2026-01-06", "2026-01-13"], comm=[0.0, 0.0]),
              "symbol": "TEST"}})
    assert agg.frame["sigma_weighted"].isna().all()


def test_the_sets_volatility_does_not_move_when_the_numeraire_does(two_vols):
    """Sigma is a fraction and the gold divisor hits every notional equally, so the
    weights are unchanged. A volatility that moved with the numeraire would be
    describing the numeraire."""
    usd = ex.aggregate_exposure(["Big", "Small"], leg=ex.LEG_COMM,
                                frames=_sized_frames())
    gold = ex.aggregate_exposure(["Big", "Small"], leg=ex.LEG_COMM,
                                 numeraire=ex.NUMERAIRE_GOLD, frames=_sized_frames())
    pd.testing.assert_series_equal(usd.frame["sigma_weighted"],
                                   gold.frame["sigma_weighted"])
