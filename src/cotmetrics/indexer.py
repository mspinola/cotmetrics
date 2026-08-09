"""The process-wide CotIndexer singleton, built lazily on first use.

Constructing a CotIndexer is expensive and requires COTDATA_STORE: it loads the Parquet
cache, and on a cache miss it rebuilds the whole index and rewrites the CSV exports.
Doing that at import time made ``import cotmetrics.indexer`` a heavyweight, failure-prone
operation. Any consumer that merely wanted to introspect a module paid the full load, and
a machine without the store got a collection error instead of a clear runtime message.
That is the same reasoning that already keeps the options fetch out of ``__init__`` (see
:func:`boot_options_update`) and that keeps ``cotmetrics/__init__.py`` free of this module.

Call :func:`get_indexer` at the point of use, inside the function that needs it. The
module-level name ``cotIndexer`` still resolves through PEP 562 ``__getattr__`` so existing
call sites keep working unchanged, but be aware that a module-scope
``from cotmetrics.indexer import cotIndexer`` reintroduces the eager cost for that module.
New code should import ``get_indexer`` instead.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import cotmetrics.utils as utils
from cotmetrics.CotIndexer import CotIndexer

_indexer: CotIndexer | None = None

# Guards construction, not use. A built indexer is read concurrently all day without
# this; what needs serializing is the one-time build. See get_indexer.
#
# A plain Lock rather than an RLock, deliberately. The build must never call back into
# get_indexer, and today it cannot: CotIndexer imports neither cotmetrics.reports nor
# cotmetrics.movers, which are the only modules that call it. If that ever changes, a
# Lock deadlocks loudly at the reentrant call, while an RLock would quietly recurse,
# see _indexer still None, and build forever. The louder failure is the better one.
_indexer_lock = threading.Lock()


def get_indexer() -> CotIndexer:
    """The process-wide indexer, constructed on first call and cached thereafter.

    Construction is serialized. It was not, and the check was the classic unguarded
    ``if _indexer is None: _indexer = CotIndexer()``: two threads could both see None
    and both build. That is ~90 seconds and ~100MB of instrument frames each on the
    full universe, with one of the two silently discarded. Worse than the waste,
    whichever caller lost the race went on holding a different object than everyone
    else, so a later refresh_if_stale would faithfully update an index nobody reads.

    Dash serves on multiple threads, so this was always reachable on a cold start with
    simultaneous first requests. cot-analyzer's store poller made it easier to reach by
    adding a second kind of caller, on a timer rather than on traffic.

    The fast path stays lock-free: once built, this is a plain read, which is what
    nearly every call is. Only the cold path takes the lock, and a caller arriving
    mid-build now waits for the winner instead of starting a second build. Waiting is
    the better trade, since the duplicate was never usable anyway.
    """
    global _indexer
    # Read once into a local. Testing the global and then returning it would be two
    # separate reads, and reset_indexer could land between them and hand back None.
    indexer = _indexer
    if indexer is not None:
        return indexer

    with _indexer_lock:
        # Re-check: another thread may have finished building while this one queued.
        if _indexer is None:
            utils.get_cot_logger().debug("Loading COT Data... (this might take a moment)")
            start_time = time.time()
            _indexer = CotIndexer()
            utils.get_cot_logger().debug(f"Loading COT data took: {time.time() - start_time:.2f}s")
        return _indexer


def reset_indexer() -> None:
    """Drop the cached singleton so the next :func:`get_indexer` rebuilds it.

    For tests that need a fresh indexer against changed config or a changed store.

    Takes the same lock, so a reset overlapping a build waits for it and then clears the
    result. Without that the reset could land mid-build and be undone moments later by
    the assignment completing, leaving the caller holding the very indexer it asked to
    be rid of.
    """
    global _indexer
    with _indexer_lock:
        _indexer = None


def __getattr__(name: str):
    """Back-compat for ``from cotmetrics.indexer import cotIndexer``.

    Resolves the old module-level name to the lazily built singleton. Note this fires at
    the ``from ... import`` statement, so a module-scope import still constructs eagerly
    for that importer — prefer :func:`get_indexer` called at the use site.
    """
    if name == "cotIndexer":
        return get_indexer()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def boot_options_update():
    """Run the daily options snapshot refresh on startup.

    Kept out of CotIndexer.__init__ so that importing the indexer never triggers
    live network I/O. Skipped under --fast or when COT_SKIP_BOOT_FETCH is set
    (e.g. tests). Call this explicitly from the app entrypoint.
    """
    if "--fast" in sys.argv or os.environ.get("COT_SKIP_BOOT_FETCH"):
        return
    print("\n-----------------------CotIndexer daily options update-----------------------------")
    from cotmetrics.options_data import update_all_daily_options
    update_all_daily_options()
    # Prices come from the cotdata store (Norgate producer); no Databento price update here.
