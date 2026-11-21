"""Which contracts an equity index market is read on: the E-mini alone, or combined.

cotdata sums an equity index future's parallel listings (full-size, micro) into the
E-mini's units by default (`registry.yaml` `sum_codes`), which is one definition of
"the whole market" across the series and what the NPF research and the livebook paper
book were validated on. CMR's published index, and most people reading COT, use the
E-mini alone. CotIndexer builds both frames for those markets and serves one per call:

- ``COMBINED`` (the package default): the summed series, unchanged from before this
  module existed. A process that never calls ``set_default_contracts`` sees nothing new,
  which is what keeps npf and livebook on their validated inputs.
- ``EMINI``: the E-mini listing alone (``cotdata.get_cot(sym, listing="primary")``).

Only equity index markets with ``sum_codes`` have two frames. Every other market has one,
and the choice is a no-op there.

Resolution order for a call: an explicit ``contracts=`` argument, then the context set by
``use_contracts``, then the process default.

**The Combined class.** A process on the EMINI default can still show the summed series,
as its own asset class rather than a switch: ``enable_combined_class()`` before the indexer
is built, and CotIndexer adds a twin of each equity market under ``COMBINED_CLASS``, named
with ``COMBINED_SUFFIX``, always read on the combined frame. Off by default, and
``CotIndexer.get_asset_classes`` leaves the class out unless asked (``include_combined``),
so a universe built from the class list (npf's ``resolve_universe``, the movers, the
setups email) never counts a market twice. Only cot-analyzer turns it on.
"""
from __future__ import annotations

import contextvars
import functools
from contextlib import contextmanager

EMINI = "emini"
COMBINED = "combined"
CHOICES = (EMINI, COMBINED)

COMBINED_CLASS = "Equities Combined"
COMBINED_SUFFIX = " (Combined)"

_default = COMBINED
_combined_class = False
_current: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cotmetrics_equity_contracts", default=None)


def _check(value):
    if value not in CHOICES:
        raise ValueError(f"unknown contracts {value!r}, expected one of {CHOICES}")
    return value


def set_default_contracts(value: str) -> None:
    """The process default. cot-analyzer sets EMINI at boot; npf never calls this."""
    global _default
    _default = _check(value)


def default_contracts() -> str:
    return _default


def current_contracts() -> str:
    return _current.get() or _default


def enable_combined_class(on: bool = True) -> None:
    """Add the Combined equity twins as their own asset class. Set before the indexer
    is built; cot-analyzer does, npf never does."""
    global _combined_class
    _combined_class = bool(on)


def combined_class_enabled() -> bool:
    return _combined_class


@contextmanager
def use_contracts(value: str | None):
    token = _current.set(_check(value) if value is not None else None)
    try:
        yield
    finally:
        _current.reset(token)


def contracts_cached(maxsize):
    """lru_cache keyed on the resolved contracts as well as the arguments.

    The resolved value is part of the key, and the body runs inside ``use_contracts``
    for that value, so nested calls (get_commercial_flow_data -> get_category_data)
    agree with the outer one. ``cache_clear`` is exposed so ``_clear_memoized`` finds it.
    """
    def deco(fn):
        @functools.lru_cache(maxsize=maxsize)
        def cached(self, contracts, *args, **kwargs):
            with use_contracts(contracts):
                return fn(self, *args, **kwargs)

        @functools.wraps(fn)
        def wrapper(self, *args, contracts=None, **kwargs):
            resolved = _check(contracts) if contracts is not None else current_contracts()
            return cached(self, resolved, *args, **kwargs)

        wrapper.cache_clear = cached.cache_clear
        wrapper.cache_info = cached.cache_info
        return wrapper
    return deco
