"""Options cache location and the NaN guards on both sides of it.

All three failures these cover were live at once, and together they emptied Max Pain
for 22 of 24 symbols on the exact date the Signal Matrix asks for:

  - snapshots were written to a package-anchored directory and read from a
    cwd-relative one, so writes landed where nothing read them
  - a NaN underlying price passed `is None or == 0` and was persisted permanently
  - reading that row raised KeyError('nan') via idxmin on an all-NA series, logged
    as "Error retrieving max pain for GC: nan"
"""
import warnings

import numpy as np
import pandas as pd
import pytest

import cotmetrics.constants as const
import cotmetrics.options_data as od


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Point both sides of the module at a scratch directory."""
    d = tmp_path / "options"
    d.mkdir()
    monkeypatch.setattr(od, "_options_cache_dir", lambda: d)
    od._MAX_PAIN_CACHE.clear()
    yield d
    od._MAX_PAIN_CACHE.clear()


def _snapshot(date, underlying, n=5):
    return pd.DataFrame({
        "Date": [date] * n,
        "Expiry": ["2026-08-21"] * n,
        "UnderlyingPrice": [underlying] * n,
        "SimulatedStrike": np.linspace(90.0, 110.0, n),
        "IntrinsicValue_M": np.linspace(5.0, 1.0, n),
        "MaxPainStrike": [100.0] * n,
        "ETF_Proxy": ["GLD"] * n,
    })


# ── one directory, resolved the same way on both sides ────────────────────────

def test_cache_dir_lives_under_the_shared_cache_root(monkeypatch, tmp_path):
    """Not anchored to the package: constants.py says an installed package cannot
    assume a repo root, and the writer used to do exactly that."""
    monkeypatch.setattr(const, "CACHE_DIR", str(tmp_path))
    assert od._options_cache_dir() == tmp_path / "options"


def test_cache_dir_does_not_depend_on_cwd(monkeypatch, tmp_path):
    """The reader used to use a relative path, so from any other directory it reported
    "no options data" instead of failing -- a silent wrong answer."""
    monkeypatch.setattr(const, "CACHE_DIR", str(tmp_path))
    before = od._options_cache_dir()
    monkeypatch.chdir(tmp_path)
    assert od._options_cache_dir() == before
    assert od._options_cache_dir().is_absolute()


# ── the read guard ────────────────────────────────────────────────────────────

def test_a_nan_price_snapshot_returns_none_rather_than_raising(cache):
    """This raised KeyError('nan'), which surfaced as a log line naming neither the
    date nor the real problem."""
    _snapshot("2026-07-14", np.nan).to_parquet(cache / "GC_options_history.parquet")
    assert od.get_max_pain_for_symbol("GC", "2026-07-14") is None


def test_the_nan_path_emits_no_pandas_futurewarning(cache):
    """idxmin over an all-NA series is deprecated and becomes a ValueError. The guard
    has to run before it, not catch it afterwards."""
    _snapshot("2026-07-14", np.nan).to_parquet(cache / "GC_options_history.parquet")
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        assert od.get_max_pain_for_symbol("GC", "2026-07-14") is None


def test_a_zero_price_snapshot_is_also_refused(cache):
    _snapshot("2026-07-14", 0.0).to_parquet(cache / "GC_options_history.parquet")
    assert od.get_max_pain_for_symbol("GC", "2026-07-14") is None


def test_a_good_snapshot_still_resolves(cache):
    _snapshot("2026-07-14", 100.0).to_parquet(cache / "GC_options_history.parquet")
    res = od.get_max_pain_for_symbol("GC", "2026-07-14")
    assert res is not None
    assert res["current_price"] == 100.0


def test_a_neighbouring_date_is_used_once_the_poison_is_gone(cache):
    """The repair drops all-NaN dates rather than leaving them in place, so the
    +/-14 day search falls through to a usable date instead of locking onto a hole."""
    good = _snapshot("2026-07-13", 100.0)
    good.to_parquet(cache / "GC_options_history.parquet")
    res = od.get_max_pain_for_symbol("GC", "2026-07-14")
    assert res is not None and res["current_price"] == 100.0


# ── the write guard ───────────────────────────────────────────────────────────

def test_a_nan_underlying_is_never_persisted(cache, monkeypatch):
    """NaN is neither None nor 0, so it used to pass the guard. The snapshot is
    appended to a permanent parquet and nothing repairs it, so one bad quote day
    poisoned that date forever."""
    monkeypatch.setitem(od.ETF_PROXIES, "GC", "GLD")
    monkeypatch.setattr(od, "fetch_options_chain",
                        lambda etf: (pd.DataFrame({"strike": [100.0], "openInterest": [1],
                                                   "type": ["c"]}), np.nan, "2026-08-21",
                                     "2026-07-14"))
    assert od.build_daily_options_snapshot("GC", 2000.0) is None
    assert not (cache / "GC_options_history.parquet").exists()
