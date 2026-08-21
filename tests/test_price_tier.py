"""cotmetrics must not name a price tier. The domain decides it.

`marketdata.get_bars(symbol, adjustment)` treats the domain as a registry fact and
resolves the tier from it when none is given: 'backadj' for futures, 'split' for
equities. Naming 'backadj' therefore works for 46 of the 47 configured markets and
raises on the ones priced off ETF proxies:

    adjustment 'backadj' is not valid for domain 'equities'
    ('backadj' is a futures adjustment). Valid: ('split', 'raw', 'total')

Observed on every boot and every index rebuild, for MFS and MME: no prices, no Max
Pain snapshot, and a red line in the log that had been there long enough to read as
furniture. Three call sites had made the same assumption independently.
"""
import pathlib

import pytest

import cotmetrics.signals as signals

# The two configured markets that are not futures. They exist because
# cotdata.registry hard-requires a cftc_code and these are priced off ETF proxies.
EQUITY_PROXIES = ("MFS", "MME")

FUTURES_TIERS = ("backadj", "unadj", "propadj")


def test_the_proxies_really_are_a_different_domain():
    """The premise. If these ever become futures, the rest of this file is moot."""
    marketdata = pytest.importorskip("marketdata")

    for symbol in EQUITY_PROXIES:
        assert marketdata.domain_for(symbol) == "equities"
    assert marketdata.domain_for("ES") == "futures"


def test_the_rejection_scores_read_does_not_pin_a_tier(monkeypatch):
    """The behavioural half: whatever this asks for must be valid for an equity."""
    import pandas as pd

    seen = {}

    def spy(symbol, adjustment=None, **kwargs):
        seen["symbol"], seen["adjustment"] = symbol, adjustment
        return pd.DataFrame()

    monkeypatch.setattr(signals.marketdata, "get_bars", spy)
    signals.compute_weekly_rejection_scores("MFS", pd.DatetimeIndex([]))

    assert seen["symbol"] == "MFS"
    assert seen["adjustment"] not in FUTURES_TIERS, (
        f"asked for {seen['adjustment']!r}, which raises on an equities symbol")


@pytest.mark.parametrize("module", ["CotIndexer", "options_data", "signals"])
def test_no_call_site_pins_a_futures_tier(module):
    """The tripwire, and it earns its brittleness.

    The bug was not one mistake, it was the same assumption made three times in
    three files, each reasonable in isolation because this package began as a
    futures-only consumer. A behavioural test on one call site would have left the
    other two free to regress, and the failure they produce is a logged error rather
    than a crash, so nothing else would notice.
    """
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "cotmetrics"
    for i, line in enumerate((src / f"{module}.py").read_text().splitlines(), 1):
        if "get_bars(" in line and any(t in line for t in FUTURES_TIERS):
            pytest.fail(
                f"{module}.py:{i} pins a futures tier: {line.strip()}\n"
                f"Omit the tier and let the domain decide, or this raises on "
                f"{', '.join(EQUITY_PROXIES)}.")
