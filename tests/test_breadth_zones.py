"""The SWG FOMO zones and the M-01 net-highs regime, pinned at their published edges.

Sources: agi/docs/02-RULES.md M-07 (four zones, June 2026 Swing Trading Guide) and M-01
(three consecutive days, Caruso's nasdaq_net_highs.pine). Units are the vendor's percent.
"""

import numpy as np
import pandas as pd
import pytest

from cotmetrics import indicators as ind


# ── fomo_zone: the published edges, inclusive where the source says so ──────────────
@pytest.mark.parametrize("value, zone", [
    (100.0, "exhaustion"),
    (85.0, "exhaustion"),
    (80.0, "exhaustion"),      # "> 80" is read as the edge belonging to exhaustion
    (79.99, None),             # 60-80 is unnamed in the source
    (60.0, "neutral"),
    (48.05, "neutral"),        # the 2026-07-29 EDGE-report reading
    (35.0, "neutral"),
    (34.99, None),             # 25-35 is unnamed in the source
    (25.0, None),
    (24.99, "fear"),
    (12.0, "fear"),
    (0.0, "fear"),
])
def test_fomo_zone_boundaries_match_the_source(value, zone):
    assert ind.fomo_zone(value) == zone


def test_fomo_recovery_is_a_direction_not_a_level():
    assert ind.fomo_zone(30.0) is None                 # no prior: unknowable
    assert ind.fomo_zone(30.0, previous=18.0) == "recovery"   # rising out of fear
    assert ind.fomo_zone(30.0, previous=34.0) is None         # falling toward fear
    assert ind.fomo_zone(22.0, previous=18.0) == "fear"       # rising but still in fear
    assert ind.fomo_zone(85.0, previous=18.0) == "exhaustion"  # level wins at the top
    assert ind.fomo_zone(50.0, previous=18.0) == "recovery"   # recovery, not neutral, off a fear print
    assert ind.fomo_zone(50.0, previous=40.0) == "neutral"    # ordinary neutral drift


def test_fomo_zone_missing_reading_is_none():
    assert ind.fomo_zone(None) is None
    assert ind.fomo_zone(float("nan")) is None
    assert ind.fomo_zone(30.0, previous=float("nan")) is None


@pytest.mark.parametrize("bad", [100.01, -0.01, 150.0])
def test_fomo_zone_refuses_a_value_outside_percent_range(bad):
    with pytest.raises(ValueError, match="percent"):
        ind.fomo_zone(bad)


def test_fomo_zone_accepts_a_genuine_sub_one_percent_reading():
    # 0.5 was the series' printed low; it is 0.5%, not a fraction, and it is fear.
    assert ind.fomo_zone(0.5) == "fear"


# ── fomo_zones: the vectorised form agrees with the scalar one row by row ─────────
def test_fomo_zones_matches_the_scalar_with_the_prior_row_as_previous():
    idx = pd.bdate_range("2026-09-01", periods=10)
    s = pd.Series([42.71, 61.9, 60.77, 43.39, 25.64, 17.79, 34.69, 47.01, 38.9, 32.23], idx)
    got = ind.fomo_zones(s)
    prev = None
    for date, value in s.items():
        assert got[date] == ind.fomo_zone(value, prev), date
        prev = value
    # The one recovery print in that stretch: 34.69 rising off 17.79.
    assert got[idx[6]] == "recovery"
    assert list(got.index) == list(idx)


def test_fomo_zones_nan_rows_are_none_and_break_the_recovery_test():
    s = pd.Series([18.0, np.nan, 30.0, 30.0])
    got = ind.fomo_zones(s)
    assert got.iloc[0] == "fear"
    assert got.iloc[1] is None
    assert got.iloc[2] is None       # previous is NaN, so no direction is known
    assert got.iloc[3] is None       # 30 after 30 sits in the unnamed gap


def test_fomo_zones_refuses_a_series_outside_percent_range():
    with pytest.raises(ValueError, match="percent"):
        ind.fomo_zones(pd.Series([48.0, 52.0, 120.0]))


def test_fomo_zones_cannot_tell_a_fraction_series_from_low_readings():
    # Documented limit of the guard: 0.48 is a legal 0.48% reading, so a series that
    # was divided by 100 by mistake classifies as fear throughout rather than raising.
    # The unit lives in the docstrings and in the store, not in a check.
    assert list(ind.fomo_zones(pd.Series([0.48, 0.52]))) == ["fear", "fear"]


# ── net_highs_regime: three consecutive, rolling, zero breaks a run ───────────────
def test_net_highs_regime_needs_three_consecutive_and_lapses_on_the_fourth():
    net = pd.Series([5, 3, 8, -2, 4, 6, 9, 0, -1, -4, -7])
    got = list(ind.net_highs_regime(net))
    assert got == [None, None, "up", None, None, None, "up", None, None, None, "down"]


def test_net_highs_regime_zero_is_neither_direction():
    net = pd.Series([0, 0, 0, 1, 1, 1])
    assert list(ind.net_highs_regime(net)) == [None, None, None, None, None, "up"]


def test_net_highs_regime_keeps_the_index_and_honours_days():
    idx = pd.bdate_range("2026-09-01", periods=4)
    net = pd.Series([-1, -1, -1, -1], idx)
    got = ind.net_highs_regime(net, days=2)
    assert list(got.index) == list(idx)
    assert list(got) == [None, "down", "down", "down"]


def test_the_zone_names_are_the_four_the_guide_names():
    assert ind.FOMO_ZONES == ("exhaustion", "neutral", "fear", "recovery")
    assert ind.FOMO_EXHAUSTION_MIN == 80.0
    assert ind.FOMO_NEUTRAL == (35.0, 60.0)
    assert ind.FOMO_FEAR_MAX == 25.0
