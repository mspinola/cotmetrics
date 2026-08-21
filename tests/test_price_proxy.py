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


@pytest.mark.parametrize("symbol, etf", sorted(PROXIED.items()))
def test_the_proxy_is_a_symbol_marketdata_knows(symbol, etf):
    """Half the seed: a map pointing at a ticker the registry has never heard of
    resolves to nothing, and the market is exactly as priceless as before.

    This is a property of the INSTALLED marketdata, not of a version pin, which is
    why it is asserted rather than assumed. The siblings are editable installs, so
    what is on disk is whatever that checkout is sitting at.
    """
    marketdata = pytest.importorskip("marketdata")

    if not hasattr(marketdata, "all_symbols"):
        pytest.skip("this marketdata checkout predates all_symbols()")
    known = [s.internal for s in marketdata.all_symbols()]
    if etf not in known:
        pytest.skip(
            f"{etf} is not in this marketdata checkout's registry, so {symbol} "
            f"cannot be priced here. Pull the sibling past "
            f"'Register EFA and EEM' (marketdata #17).")
    assert marketdata.domain_for(etf) == "equities"


@pytest.mark.parametrize("symbol, etf", sorted(PROXIED.items()))
def test_the_proxy_has_bars_where_a_store_is_populated(symbol, etf):
    """The other half, and it is a DEPLOYMENT fact rather than a code one.

    CI points MARKETDATA_STORE at an empty /tmp directory, so this can only ever be
    checked on a machine with a real store. Skipping keeps that honest instead of
    either failing CI forever or quietly asserting nothing: run with `-rs` and the
    skip says which it was. The bars themselves are seeded by
    `marketdata-update --bars --domain equities --symbols EEM EFA`.
    """
    marketdata = pytest.importorskip("marketdata")

    if etf not in [s.internal for s in marketdata.all_symbols()]:
        pytest.skip(f"{etf} not in this marketdata checkout's registry")
    df = marketdata.get_bars(etf)
    if df.empty:
        pytest.skip(
            f"no {etf} bars in this store, so {symbol} has no price here. Seed with "
            f"marketdata-update --bars --domain equities --symbols EEM EFA")
    assert len(df) > 1000, f"{etf} has only {len(df)} bars, which is not a history"
