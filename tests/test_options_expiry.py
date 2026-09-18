"""Which expiry the max-pain snapshot is taken on.

Max pain is a statement about the open interest that will be forced to settle, so
the chain has to be one that carries some. The old rule (first listed expiry more
than three days out) landed on a thin weekly for every proxy with daily or weekly
listings. These pin the replacement: the nearest standard monthly still open,
stepping forward one month only when it is a listing rather than a chain.

Network-free: the listings below are yfinance's for 2026-09-18, and open interest
is supplied by a stub.
"""

import pandas as pd
import pytest

import cotmetrics.options_data as od

# SPY's listing on 2026-09-18: dailies, weeklies, month-ends and two monthlies.
SPY = ["2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24",
       "2026-09-25", "2026-09-30", "2026-10-02", "2026-10-09", "2026-10-16",
       "2026-10-23", "2026-10-30", "2026-11-20"]
# CORN lists monthlies only, and October is a listing rather than a chain.
CORN = ["2026-09-18", "2026-10-16", "2026-11-20", "2027-02-19", "2027-03-19"]
CORN_OI = {"2026-09-18": 3923, "2026-10-16": 1804, "2026-11-20": 110609,
           "2027-02-19": 10246, "2027-03-19": 4663}


def _no_oi(expiry):
    raise AssertionError(f"open interest should not have been needed for {expiry}")


@pytest.mark.parametrize("expiry,monthly", [
    ("2026-09-18", True), ("2026-10-16", True), ("2026-11-20", True),
    ("2026-09-25", False), ("2026-09-30", False), ("2026-10-09", False),
])
def test_standard_monthly_is_the_third_friday(expiry, monthly):
    assert od.is_standard_monthly(expiry, SPY) is monthly


def test_a_holiday_monthly_trades_on_the_thursday_before():
    # 2027-04-16 is the third Friday of April and Good Friday is 2027-03-26, so
    # this is a synthetic holiday: the Friday is absent from the listing.
    listed = ["2027-04-09", "2027-04-15", "2027-05-21"]
    assert od.is_standard_monthly("2027-04-15", listed)
    # The same Thursday with the Friday listed is a plain weekly.
    assert not od.is_standard_monthly("2027-04-15", listed + ["2027-04-16"])


def test_the_nearest_open_monthly_beats_every_weekly_in_front_of_it():
    oi = {"2026-10-16": 2_223_783, "2026-11-20": 1_500_000}
    assert od.select_expiry(SPY, "2026-09-21", oi.__getitem__) == "2026-10-16"


def test_the_monthly_expiring_today_is_not_open():
    # The snapshot job runs after the close, when today's chain has settled.
    oi = {"2026-09-18": 5_174_789, "2026-10-16": 2_223_783, "2026-11-20": 1_500_000}
    assert od.select_expiry(SPY, "2026-09-18", oi.__getitem__) == "2026-10-16"
    assert od.select_expiry(SPY, "2026-09-17", oi.__getitem__) == "2026-09-18"


def test_an_empty_nearest_monthly_steps_forward_one_month():
    assert od.select_expiry(CORN, "2026-09-18", CORN_OI.__getitem__) == "2026-11-20"


def test_the_step_is_one_month_at_most():
    # October is empty so the pick steps to November; February is never consulted,
    # however much it holds.
    oi = dict(CORN_OI, **{"2027-02-19": 10_000_000})
    assert od.select_expiry(CORN, "2026-09-18", oi.__getitem__) == "2026-11-20"


def test_a_thinner_but_not_empty_nearest_monthly_is_kept():
    # TLT 2026-10-17: November 767k against December 1.28M is 60%, well above the
    # step ratio, and the nearer chain is the one settling first.
    tlt = ["2026-10-23", "2026-11-20", "2026-12-18"]
    oi = {"2026-11-20": 766_790, "2026-12-18": 1_283_543}
    assert od.select_expiry(tlt, "2026-10-17", oi.__getitem__) == "2026-11-20"


def test_a_single_open_monthly_needs_no_open_interest():
    assert od.select_expiry(["2026-09-25", "2026-10-16"], "2026-09-18", _no_oi) == "2026-10-16"


def test_no_monthly_listed_falls_back_to_the_old_rule():
    weeklies = ["2026-09-21", "2026-09-22", "2026-09-25", "2026-10-02"]
    assert od.select_expiry(weeklies, "2026-09-18", _no_oi) == "2026-09-22"
    assert od.select_expiry(["2026-09-19"], "2026-09-18", _no_oi) == "2026-09-19"


def test_today_may_be_a_timestamp_with_a_time_of_day():
    oi = {"2026-10-16": 1, "2026-11-20": 1}
    now = pd.Timestamp("2026-09-18 19:30")
    assert od.select_expiry(SPY, now, oi.__getitem__) == "2026-10-16"
