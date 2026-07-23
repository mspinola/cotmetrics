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
import time

import cotmetrics.utils as utils
from cotmetrics.CotIndexer import CotIndexer

_indexer: CotIndexer | None = None


def get_indexer() -> CotIndexer:
    """The process-wide indexer, constructed on first call and cached thereafter."""
    global _indexer
    if _indexer is None:
        utils.get_cot_logger().debug("Loading COT Data... (this might take a moment)")
        start_time = time.time()
        _indexer = CotIndexer()
        utils.get_cot_logger().debug(f"Loading COT data took: {time.time() - start_time:.2f}s")
    return _indexer


def reset_indexer() -> None:
    """Drop the cached singleton so the next :func:`get_indexer` rebuilds it.

    For tests that need a fresh indexer against changed config or a changed store.
    """
    global _indexer
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
