"""The strike ladder: open interest and payout on real strikes, calls and puts apart.

Written beside the curve history since 2026-09-18. The curve keeps only a summed
200-point grid, which cannot recover which side's interest is doing the pulling and
does not keep the strikes themselves; the ladder does both. These pin that the two
files agree by construction, that the split is what it says, and that the ladder
file gets the same append protections as the curve without ever being able to
cost the curve.
"""

import numpy as np
import pandas as pd
import pytest

import cotmetrics.options_data as od


@pytest.fixture
def cache(tmp_path, monkeypatch):
    d = tmp_path / "options"
    d.mkdir()
    monkeypatch.setattr(od, "options_history_dir", lambda: d)
    od._MAX_PAIN_CACHE.clear()
    yield d
    od._MAX_PAIN_CACHE.clear()


def _chain():
    # Calls and puts share the ladder but not the interest: puts crowd the low
    # strikes, calls the high ones, and 100 has both.
    return pd.DataFrame({
        "strike":       [90.0, 95.0, 100.0, 100.0, 105.0, 110.0],
        "openInterest": [40,   30,   10,    10,    30,    40],
        "type":         ["put", "put", "put", "call", "call", "call"],
    })


def test_ladder_has_one_row_per_strike_with_the_interest_split():
    ladder = od.calculate_strike_ladder(_chain()).set_index("Strike")
    assert list(ladder.index) == [90.0, 95.0, 100.0, 105.0, 110.0]
    assert list(ladder["PutOI"]) == [40, 30, 10, 0, 0]
    assert list(ladder["CallOI"]) == [0, 0, 10, 30, 40]


def test_ladder_payouts_are_the_curve_evaluated_at_the_strike():
    chain = _chain()
    ladder = od.calculate_strike_ladder(chain)
    sim_px, total_m, _ = od.calculate_intrinsic_curve(chain, 100.0, points=2001)
    # The curve is piecewise-linear with its kinks at strikes, so the interpolated
    # value at a strike is exact.
    for _, row in ladder.iterrows():
        expected = np.interp(row["Strike"], sim_px, total_m)
        assert row["CallPayout_M"] + row["PutPayout_M"] == pytest.approx(expected)


def test_ladder_split_by_hand():
    ladder = od.calculate_strike_ladder(_chain()).set_index("Strike")
    # Settle at 105: calls at 100 pay 5 x 10 x 100 = 5,000; the 105 and 110 calls
    # pay nothing. Puts at 110... there are none; puts are all at or below 100,
    # all out of the money.
    assert ladder.loc[105.0, "CallPayout_M"] == pytest.approx(0.005)
    assert ladder.loc[105.0, "PutPayout_M"] == 0.0
    # Settle at 90: puts at 95 pay 5 x 30 x 100 and at 100 pay 10 x 10 x 100.
    assert ladder.loc[90.0, "PutPayout_M"] == pytest.approx((15_000 + 10_000) / 1e6)
    assert ladder.loc[90.0, "CallPayout_M"] == 0.0


def _fetch(monkeypatch, quote_date):
    monkeypatch.setitem(od.ETF_PROXIES, "GC", "GLD")
    monkeypatch.setattr(od, "fetch_options_chain",
                        lambda etf: (_chain(), 100.0, "2026-10-16", quote_date))


def test_snapshot_writes_the_ladder_beside_the_curve_in_scaled_units(cache, monkeypatch):
    _fetch(monkeypatch, "2026-09-18")
    od.build_daily_options_snapshot("GC", 2000.0)
    ladder = pd.read_parquet(cache / "GC_options_strikes.parquet")
    assert list(ladder["EtfStrike"]) == [90.0, 95.0, 100.0, 105.0, 110.0]
    # Strike is in the curve file's units (x20 here), EtfStrike keeps the listing.
    assert list(ladder["Strike"]) == [1800.0, 1900.0, 2000.0, 2100.0, 2200.0]
    assert set(ladder["Date"]) == {"2026-09-18"}
    assert set(ladder["Expiry"]) == {"2026-10-16"}
    assert (ladder["UnderlyingPrice"] == 2000.0).all()
    curve = pd.read_parquet(cache / "GC_options_history.parquet")
    assert curve["MaxPainStrike"].iloc[0] in set(ladder["Strike"])


def test_rerunning_a_day_replaces_it_and_days_accumulate(cache, monkeypatch):
    _fetch(monkeypatch, "2026-09-18")
    od.build_daily_options_snapshot("GC", 2000.0)
    od.build_daily_options_snapshot("GC", 2000.0)
    _fetch(monkeypatch, "2026-09-21")
    od.build_daily_options_snapshot("GC", 2000.0)
    ladder = pd.read_parquet(cache / "GC_options_strikes.parquet")
    assert ladder.groupby("Date").size().to_dict() == {"2026-09-18": 5, "2026-09-21": 5}


def test_a_corrupt_ladder_is_set_aside_and_the_curve_is_untouched(cache, monkeypatch):
    _fetch(monkeypatch, "2026-09-18")
    ladder_file = cache / "GC_options_strikes.parquet"
    ladder_file.write_bytes(b"not a parquet file")
    assert od.build_daily_options_snapshot("GC", 2000.0) is not None
    asides = list(cache.glob("GC_options_strikes.parquet.corrupt-*"))
    assert len(asides) == 1 and asides[0].read_bytes() == b"not a parquet file"
    assert len(pd.read_parquet(ladder_file)) == 5
    assert len(pd.read_parquet(cache / "GC_options_history.parquet")) == 200


def test_a_ladder_failure_never_costs_the_curve(cache, monkeypatch):
    _fetch(monkeypatch, "2026-09-18")

    def boom(chain):
        raise RuntimeError("ladder broke")

    monkeypatch.setattr(od, "calculate_strike_ladder", boom)
    assert od.build_daily_options_snapshot("GC", 2000.0) is not None
    assert (cache / "GC_options_history.parquet").exists()
    assert not (cache / "GC_options_strikes.parquet").exists()
