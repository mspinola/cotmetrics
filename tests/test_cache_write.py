"""The per-symbol parquet cache must never be readable while half-written.

This mattered little while every process had its own CACHE_DIR. It matters now that
they share one: cot-analyzer's store poller rebuilds on a five-minute tick and npf's
Friday launchd jobs read the same directory, so a rebuild overlapping a read is an
ordinary Friday. A torn file would surface as a parquet error on a file that is
plainly present, which is the most misleading shape a cache failure can take.
"""
import os
import pathlib

import pandas as pd
import pytest

from cotmetrics.CotIndexer import _write_cache_atomic

FRAME = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})


def test_it_round_trips(tmp_path):
    dest = tmp_path / "GC.parquet"
    _write_cache_atomic(FRAME, str(dest))

    pd.testing.assert_frame_equal(pd.read_parquet(dest), FRAME)


def test_an_existing_cache_is_replaced_not_truncated(tmp_path):
    """The reader-visible property: the old file stays complete until the new one is."""
    dest = tmp_path / "GC.parquet"
    _write_cache_atomic(FRAME, str(dest))

    bigger = pd.concat([FRAME] * 4, ignore_index=True)
    _write_cache_atomic(bigger, str(dest))

    assert len(pd.read_parquet(dest)) == 12


def test_a_failed_write_leaves_the_previous_file_intact(tmp_path):
    """The whole point of tmp-then-replace. A rebuild that dies mid-write must not
    take the good cache with it."""
    dest = tmp_path / "GC.parquet"
    _write_cache_atomic(FRAME, str(dest))

    class Exploding:
        def to_parquet(self, path):
            pathlib.Path(path).write_bytes(b"partial garbage")
            raise OSError("disk full")

    with pytest.raises(OSError):
        _write_cache_atomic(Exploding(), str(dest))

    pd.testing.assert_frame_equal(pd.read_parquet(dest), FRAME)


def test_a_failed_write_leaves_no_tmp_litter(tmp_path):
    """Otherwise a flaky disk slowly fills the cache dir with .tmp-<pid> files that
    nothing ever cleans up."""
    dest = tmp_path / "GC.parquet"

    class Exploding:
        def to_parquet(self, path):
            pathlib.Path(path).write_bytes(b"partial")
            raise OSError("nope")

    with pytest.raises(OSError):
        _write_cache_atomic(Exploding(), str(dest))

    assert [p.name for p in tmp_path.iterdir()] == []


def test_the_tmp_name_is_per_process(tmp_path):
    """Two processes rebuilding at once must not collide on the SAME tmp file, or
    tmp-then-replace just moves the tearing one step earlier."""
    dest = tmp_path / "GC.parquet"
    seen = []

    class Recording:
        def to_parquet(self, path):
            seen.append(path)
            FRAME.to_parquet(path)

    _write_cache_atomic(Recording(), str(dest))
    assert str(os.getpid()) in seen[0]
