"""Two COT markets are priced off an ETF, and only those two.

MFS and MME are ICE MSCI futures that Norgate carries no continuous series for, so
there is no futures price to read. cotdata still holds their COT, which is why they
are in the universe at all. Until EFA/EEM were seeded into the equities half they had
no prices whatsoever, and every price-derived column for them was empty.

The dangerous failure here is not "no price". It is the WRONG price, silently, on a
market that has a perfectly good one of its own. That is one careless dict entry away,
so most of this file guards the blast radius rather than the feature.
"""
import pytest

from cotmetrics.market_data import PRICE_PROXIES, price_symbol

PROXIED = {"MFS": "EFA", "MME": "EEM"}


def test_the_map_is_exactly_the_two_markets_without_their_own_series():
    """A deliberately exact assertion. Growing this map is a modelling decision about
    what a price MEANS for that market, not a config tweak, so it should fail here and
    be argued for rather than pass quietly."""
    assert PRICE_PROXIES == PROXIED


@pytest.mark.parametrize("symbol, expected", sorted(PROXIED.items()))
def test_a_proxied_market_resolves_to_its_etf(symbol, expected):
    assert price_symbol(symbol) == expected


@pytest.mark.parametrize("symbol", ["ES", "GC", "CL", "ZB", "6E", "BTC", "RTY", "NQ"])
def test_a_market_with_its_own_series_is_never_proxied(symbol):
    """The catastrophe this file exists to prevent.

    options_data.ETF_PROXIES maps ES to SPY, GC to GLD and so on, because a futures
    OPTIONS chain is illiquid. Reusing that map for prices would replace S&P futures
    with an ETF across the whole book, and the result would look plausible.
    """
    assert price_symbol(symbol) == symbol


def test_the_price_map_shares_no_keys_with_the_options_map():
    """They answer different questions and must not converge. An overlap means some
    market both has its own price and is being priced off something else."""
    from cotmetrics.options_data import ETF_PROXIES

    assert not (set(PRICE_PROXIES) & set(ETF_PROXIES))


def test_an_unknown_symbol_passes_through():
    assert price_symbol("ZZZ") == "ZZZ"


def test_the_proxies_are_actually_readable():
    """The seed half. Without EFA/EEM in the store this map resolves to nothing and
    the markets are exactly as priceless as before."""
    marketdata = pytest.importorskip("marketdata")

    for symbol, etf in PROXIED.items():
        assert etf in [s.internal for s in marketdata.all_symbols()], (
            f"{etf} is not in marketdata's registry, so {symbol} cannot be priced")
        df = marketdata.get_bars(etf)
        assert not df.empty, f"{etf} has no bars, so {symbol} still has no price"
