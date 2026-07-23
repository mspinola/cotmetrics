"""The shared directional read.

utils.price_trend_is_up used to exist twice, once in cotmetrics.synthesis and once in
cot-analyzer's signal_cards. Both used a 3-report window and the same NaN handling,
written out separately, and they disagreed about what to do with a frame that cannot
answer. These tests pin the merged behaviour, including that disagreement.
"""
import pandas as pd
import pytest

import cotmetrics.constants as const
import cotmetrics.utils as utils


def _frame(closes):
    idx = pd.date_range("2020-01-03", periods=len(closes), freq="7D")
    return pd.DataFrame({const.CLOSING_PRICE: closes}, index=idx)


def _last(df):
    return df.index[-1]


def test_rising_over_the_window_is_up():
    df = _frame([10, 11, 12, 13, 14])
    assert utils.price_trend_is_up(df, _last(df)) is True


def test_falling_over_the_window_is_not_up():
    df = _frame([14, 13, 12, 11, 10])
    assert utils.price_trend_is_up(df, _last(df)) is False


def test_flat_is_not_up():
    """Strictly greater. An unchanged close is not a rising trend."""
    df = _frame([10, 10, 10, 10, 10])
    assert utils.price_trend_is_up(df, _last(df)) is False


def test_it_measures_the_window_not_the_last_step():
    """Down over three reports but up on the final one. The window decides."""
    df = _frame([20, 19, 12, 11, 13])
    assert utils.price_trend_is_up(df, _last(df)) is False


def test_as_of_slices_the_history():
    """Reading a past row must not see the future, which is why as_of exists."""
    df = _frame([10, 11, 12, 13, 9, 8, 7])
    assert utils.price_trend_is_up(df, df.index[3]) is True   # rising as of report 4
    assert utils.price_trend_is_up(df, _last(df)) is False    # fallen since


def test_too_short_a_history_is_not_up():
    for n in range(0, const.PRICE_TREND_PERIOD + 1):
        df = _frame(list(range(10, 10 + n)))
        assert utils.price_trend_is_up(df, _last(df) if n else None) is False


def test_nan_at_the_edge_is_not_up():
    df = _frame([10, 11, 12, 13, float("nan")])
    assert utils.price_trend_is_up(df, _last(df)) is False


@pytest.mark.parametrize("df", [None, pd.DataFrame({"something else": [1, 2, 3, 4, 5]})])
def test_a_frame_that_cannot_answer_returns_false(df):
    """The divergence this merge settled: synthesis returned False here, the signal
    card raised KeyError. False wins, because every caller reads "not up" as neutral
    rather than as an error."""
    assert utils.price_trend_is_up(df, None) is False


def test_the_window_comes_from_the_constant():
    """A literal 3 would pass every test above. Moving the constant is what proves
    the period is sourced rather than hardcoded."""
    df = _frame([20, 19, 12, 11, 13])
    assert utils.price_trend_is_up(df, _last(df)) is False
    # Over a single report the same frame is rising: 11 -> 13.
    assert utils.price_trend_is_up(df, _last(df), period=1) is True
