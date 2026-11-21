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
``use_contracts`` (cot-analyzer sets it per request from the viewer's switch), then the
process default.
"""
from __future__ import annotations

import contextvars
import functools
from contextlib import contextmanager

EMINI = "emini"
COMBINED = "combined"
CHOICES = (EMINI, COMBINED)

_default = COMBINED
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


def set_request_contracts(value: str | None) -> None:
    """Set (or with None, clear) the context's choice without a with-block.

    For a web request hook, which has no scope to wrap. A value outside CHOICES clears
    rather than raises: it comes from a cookie, and a bad cookie must not break a page.
    """
    _current.set(value if value in CHOICES else None)


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
