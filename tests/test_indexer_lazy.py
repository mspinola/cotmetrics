"""The indexer module must stay free of import-time construction.

Building a CotIndexer loads the Parquet cache, needs COTDATA_STORE, and on a cache miss
rebuilds the index and rewrites the CSV exports. When that ran at import, `import
cotmetrics.indexer` was a heavyweight operation that failed outright on a machine without
the store, which turned a clear runtime error into a collection error and forced consumers
to defer their imports into function bodies. These tests pin the property that fixed it.
"""
import subprocess
import sys
import threading
import time

import pytest

import cotmetrics.indexer as indexer


def teardown_function():
    indexer.reset_indexer()


def test_importing_the_module_constructs_nothing():
    """The singleton stays unbuilt until something asks for it."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import cotmetrics.indexer as ix; print(ix._indexer is None)"],
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("True"), out.stdout


def test_import_succeeds_without_the_data_store(monkeypatch):
    """No COTDATA_STORE is not an import-time error. It is a use-time one."""
    env = {k: v for k, v in __import__("os").environ.items() if k != "COTDATA_STORE"}
    out = subprocess.run(
        [sys.executable, "-c", "import cotmetrics.indexer; print('imported')"],
        capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "imported" in out.stdout


def test_indexer_consumers_import_without_the_data_store():
    """The modules that consume the indexer must import free too, not just `indexer`.

    `reports`, `movers` and the ETL scheduler all reach for the indexer. While it was built
    at import, importing any of them required a populated store, so `movers` pushed its
    import into a function body and `reports` was excluded from the test suite entirely.
    Both now import at module scope and both must stay importable with no store, or that
    workaround grows back.
    """
    env = {k: v for k, v in __import__("os").environ.items() if k != "COTDATA_STORE"}
    out = subprocess.run(
        [sys.executable, "-c",
         "import cotmetrics.reports, cotmetrics.movers;"
         " import cotmetrics.indexer as ix; print('built' if ix._indexer else 'unbuilt')"],
        capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "unbuilt" in out.stdout, out.stdout


def test_get_indexer_caches_the_singleton(monkeypatch):
    """Two calls build once. The load is slow, so this is the whole point of a singleton."""
    built = []

    class FakeIndexer:
        def __init__(self):
            built.append(1)

    monkeypatch.setattr(indexer, "CotIndexer", FakeIndexer)
    indexer.reset_indexer()

    first, second = indexer.get_indexer(), indexer.get_indexer()
    assert first is second
    assert len(built) == 1


def test_concurrent_callers_build_exactly_one_indexer(monkeypatch):
    """The build is serialized, so a thundering herd on a cold start builds once.

    The single-threaded test above passes even with a completely unguarded
    `if _indexer is None`, because nothing interleaves. This is the one that would
    have failed before the lock: the fake sleeps inside __init__, which is where the
    real one spends ~90 seconds, so every thread reaches the None check before any
    assignment lands. Without the lock this builds once per thread.
    """
    built = []
    barrier = threading.Barrier(8)

    class SlowIndexer:
        def __init__(self):
            built.append(1)
            time.sleep(0.2)   # the window an unguarded check leaves wide open

    monkeypatch.setattr(indexer, "CotIndexer", SlowIndexer)
    indexer.reset_indexer()

    got = []

    def call():
        barrier.wait()        # release all threads at the same instant
        got.append(indexer.get_indexer())

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "a caller never returned (deadlock?)"
    assert len(built) == 1, f"built {len(built)} indexers, expected 1"
    assert len(got) == 8
    assert all(g is got[0] for g in got), "callers got different indexer objects"


def test_reset_during_a_build_does_not_resurrect_the_old_indexer(monkeypatch):
    """A reset that overlaps a build waits for it, then clears it.

    Otherwise the reset lands mid-build and the completing assignment undoes it, and
    the next caller is handed the object the reset was supposed to discard.
    """
    monkeypatch.setattr(indexer, "CotIndexer", lambda: object())
    indexer.reset_indexer()

    started = threading.Event()

    class SlowIndexer:
        def __init__(self):
            started.set()
            time.sleep(0.3)

    monkeypatch.setattr(indexer, "CotIndexer", SlowIndexer)
    builder = threading.Thread(target=indexer.get_indexer)
    builder.start()
    started.wait(timeout=5)
    indexer.reset_indexer()      # blocks until the build finishes, then clears
    builder.join(timeout=30)

    assert indexer._indexer is None, "reset was undone by the completing build"


def test_legacy_cotIndexer_name_still_resolves(monkeypatch):
    """`from cotmetrics.indexer import cotIndexer` keeps working for existing call sites."""
    sentinel = object()
    monkeypatch.setattr(indexer, "CotIndexer", lambda: sentinel)
    indexer.reset_indexer()

    assert indexer.cotIndexer is sentinel


def test_unknown_attribute_still_raises_attribute_error():
    """The PEP 562 hook must not swallow genuine typos."""
    with pytest.raises(AttributeError, match="no attribute 'cotIndexerr'"):
        indexer.cotIndexerr
