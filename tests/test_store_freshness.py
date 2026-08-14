"""A store read that fails must not read as a new COT week.

The producer writes status.json atomically, so these cases cannot arise there. They
arise on a REPLICA: the Mac and the VPS receive that file through robocopy and rsync,
neither of which replaces it atomically, so a consumer polling mid-sync can read a
truncated file or none at all.

Measured, not hypothesised. On 2026-08-14 the 2026-08-11 week landed at 15:34 and the
sync was still running at 15:35:56, when json.load raised "Expecting value: line 1
column 1 (char 0)". latest_update_timestamp answered "Unknown", refresh_if_stale saw a
string that differed from the last known week, and rebuilt the whole index for the
second of three times in five minutes.
"""
import json
import threading

import pytest

import cotmetrics.CotIndexer as indexer_mod
from cotmetrics.CotDatabase import CotDatabase
from cotmetrics.CotIndexer import CotIndexer, _IndexState, _no_new_week

# --------------------------------------------------------------------------- #
# The predicate
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("current, last_known, expected", [
    ("2026-08-11", "2026-08-11", True),    # same week, nothing to do
    ("2026-08-11", "2026-08-04", False),   # a genuine new week
    (None, "2026-08-04", True),            # unreadable: no answer, not an answer
    (None, None, True),                    # unreadable, and never read: still no answer
    ("2026-08-11", None, False),           # first readable answer since construction
])
def test_no_new_week(current, last_known, expected):
    assert _no_new_week(current, last_known) is expected


# --------------------------------------------------------------------------- #
# Reading the signal
# --------------------------------------------------------------------------- #

@pytest.fixture
def store(tmp_path, monkeypatch):
    """A store root latest_update_timestamp will read, with no real store involved."""
    import cotdata.config as cfg
    monkeypatch.setattr(cfg, "store_root", lambda: tmp_path)
    return tmp_path


def _db():
    """A CotDatabase whose SQLite half is irrelevant here; only the store read is."""
    return CotDatabase()


def test_reads_the_week_from_a_whole_file(store):
    (store / "status.json").write_text(json.dumps(
        {"domains": {"cot_legacy": {"newest_data": "2026-08-11"}}}))
    assert _db().latest_update_timestamp() == "2026-08-11"


def test_a_truncated_file_reads_as_no_answer(store):
    """The exact 2026-08-14 failure: a zero-length file mid-sync."""
    (store / "status.json").write_text("")
    assert _db().latest_update_timestamp() is None


def test_a_half_written_file_reads_as_no_answer(store):
    (store / "status.json").write_text('{"domains": {"cot_legacy": {"newest_')
    assert _db().latest_update_timestamp() is None


def test_an_absent_file_reads_as_no_answer(store):
    assert _db().latest_update_timestamp() is None


def test_a_store_with_no_cot_run_reads_as_no_answer(store):
    """Present, valid, and carrying no week. Not a signal either."""
    (store / "status.json").write_text(json.dumps(
        {"domains": {"cot_legacy": {"newest_data": None}}}))
    assert _db().latest_update_timestamp() is None


# --------------------------------------------------------------------------- #
# Acting on the signal
# --------------------------------------------------------------------------- #

@pytest.fixture
def spy_indexer(monkeypatch):
    """A CotIndexer with only the refresh machinery on it.

    Constructed through __new__ deliberately: the real __init__ loads the Parquet
    cache and, on a miss, rebuilds the index for ~90 seconds. What is under test is
    which reads reach _build_state, so everything else is left off.
    """
    ix = CotIndexer.__new__(CotIndexer)
    ix.last_known_db_time = "2026-08-04"
    ix._refresh_lock = threading.RLock()
    ix._state = _IndexState()

    builds = []

    def fake_build():
        builds.append(1)
        return _IndexState()

    monkeypatch.setattr(ix, "_build_state", fake_build)
    return ix, builds


def _reads(monkeypatch, *values):
    """Feed latest_update_timestamp a fixed sequence, one per call.

    refresh_if_stale reads twice on the path that rebuilds (once outside the lock,
    once under it), so a sequence rather than a constant is what lets a test say
    which read saw what. The last value repeats once the sequence is spent.
    """
    seq = list(values)
    monkeypatch.setattr(indexer_mod.cotDatabase, "latest_update_timestamp",
                        lambda: seq.pop(0) if len(seq) > 1 else seq[0])


def test_an_unreadable_store_does_not_rebuild(spy_indexer, monkeypatch):
    """The regression. This is what cost two ~90 second rebuilds on 2026-08-14."""
    ix, builds = spy_indexer
    _reads(monkeypatch, None)

    assert ix.refresh_if_stale() is False
    assert builds == []
    assert ix.last_known_db_time == "2026-08-04", "an unreadable read overwrote the stamp"


def test_a_new_week_still_rebuilds(spy_indexer, monkeypatch):
    ix, builds = spy_indexer
    _reads(monkeypatch, "2026-08-11")

    assert ix.refresh_if_stale() is True
    assert len(builds) == 1
    assert ix.last_known_db_time == "2026-08-11"


def test_the_same_week_does_not_rebuild(spy_indexer, monkeypatch):
    ix, builds = spy_indexer
    _reads(monkeypatch, "2026-08-04")

    assert ix.refresh_if_stale() is False
    assert builds == []


def test_a_sync_window_costs_one_rebuild_not_three(spy_indexer, monkeypatch):
    """The whole 2026-08-14 sequence, replayed as one test.

    New week, then a torn read while the sync is still running, then the week again.
    Before the fix this rebuilt three times, because "Unknown" differed from
    2026-08-11 and then 2026-08-11 differed from "Unknown".
    """
    ix, builds = spy_indexer
    for reads in (["2026-08-11"], [None], ["2026-08-11"]):
        _reads(monkeypatch, *reads)
        ix.refresh_if_stale()

    assert len(builds) == 1, f"rebuilt {len(builds)} times for one release"
    assert ix.last_known_db_time == "2026-08-11"


def test_a_stamp_never_read_adopts_the_first_readable_week(spy_indexer, monkeypatch):
    """Constructed while the store was unreadable, so the week is genuinely unknown.

    Rebuilding once to find out is the safe direction: the index was built against a
    store whose week nobody learned.
    """
    ix, builds = spy_indexer
    ix.last_known_db_time = None
    _reads(monkeypatch, "2026-08-11")

    assert ix.refresh_if_stale() is True
    assert len(builds) == 1
