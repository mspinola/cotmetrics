"""The visitor_logs schema, its 0.10.0 migration, and the geo cache.

The table this pins is written by cot-analyzer's request hooks and read by its /admin
page. Two properties matter enough to test rather than assume:

- The migration is in place, not by rebuild. The deployed database has years of rows,
  so 0.10.0's new columns arrive as ALTERs against whatever shape is on disk, and a
  pre-0.10.0 caller (positional args only) must keep producing valid rows.
- NULL `kind` means landing. Every pre-migration row is a document load, and the admin
  page's pageview filter relies on that reading rather than on a backfill.
"""
import sqlite3

import pandas as pd
import pytest

from cotmetrics.CotDatabase import CotDatabase


@pytest.fixture
def db(tmp_path):
    return CotDatabase(db_name=str(tmp_path / "visits.db"))


def _columns(db, table):
    conn = sqlite3.connect(db.db_name)
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return cols


def test_fresh_database_carries_the_tracking_columns(db):
    assert {'kind', 'visitor_id', 'is_bot', 'referrer'} <= set(_columns(db, 'visitor_logs'))
    assert {'ip', 'city', 'country', 'looked_up_at',
            'hosting'} <= set(_columns(db, 'geo_cache'))


def test_a_pre_migration_database_is_altered_in_place(tmp_path):
    """Build the 0.9.0 table shape by hand, then let setup_database migrate it."""
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute('''CREATE TABLE visitor_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, ip_address TEXT,
        path TEXT, user_agent TEXT, city TEXT, country TEXT)''')
    conn.execute("INSERT INTO visitor_logs (timestamp, ip_address, path, user_agent, city, country) "
                 "VALUES ('2026-01-01 00:00:00', '1.2.3.4', '/', 'ua', 'X', 'Y')")
    conn.commit()
    conn.close()

    db = CotDatabase(db_name=path)
    assert {'kind', 'visitor_id', 'is_bot', 'referrer'} <= set(_columns(db, 'visitor_logs'))

    # The old row survives, and its NULL kind is what marks it a landing.
    df = db.get_visitor_stats()
    assert len(df) == 1
    assert pd.isna(df.loc[0, 'kind'])


def test_the_old_call_signature_still_writes_a_valid_row(db):
    db.log_visit('1.2.3.4', '/', 'Mozilla/5.0', 'Lisbon', 'Portugal')
    df = db.get_visitor_stats()
    assert len(df) == 1
    row = df.iloc[0]
    assert row['kind'] == 'landing'
    assert row['is_bot'] == 0
    assert pd.isna(row['visitor_id'])


def test_the_new_fields_round_trip(db):
    db.log_visit('1.2.3.4', '/heatmap', 'Mozilla/5.0', 'Lisbon', 'Portugal',
                 kind='pageview', visitor_id='abcd1234', is_bot=True,
                 referrer='https://news.ycombinator.com/')
    row = db.get_visitor_stats().iloc[0]
    assert row['kind'] == 'pageview'
    assert row['visitor_id'] == 'abcd1234'
    assert row['is_bot'] == 1
    assert row['referrer'] == 'https://news.ycombinator.com/'


def test_hosting_is_unknown_until_it_is_recorded(db):
    assert db.get_cached_hosting('9.9.9.9') is None          # never looked up
    db.cache_geo('9.9.9.9', 'Zurich', 'Switzerland')         # pre-0.11.0 call shape
    assert db.get_cached_hosting('9.9.9.9') is None          # cached, but no answer


def test_hosting_round_trips_as_a_bool(db):
    db.cache_geo('1.1.1.1', 'Santa Clara', 'United States', hosting=True)
    db.cache_geo('2.2.2.2', 'Verona', 'Italy', hosting=False)
    assert db.get_cached_hosting('1.1.1.1') is True
    # False must not read back as unknown, or a residential address would be
    # refetched on every visit it ever makes.
    assert db.get_cached_hosting('2.2.2.2') is False


def test_a_later_lookup_fills_in_a_row_cached_without_hosting(db):
    """The self-healing path: a row written before this column refetches once."""
    db.cache_geo('3.3.3.3', 'Beijing', 'China')
    assert db.get_cached_hosting('3.3.3.3') is None
    db.cache_geo('3.3.3.3', 'Beijing', 'China', hosting=True)
    assert db.get_cached_hosting('3.3.3.3') is True


def test_a_geo_cache_predating_hosting_is_altered_in_place(tmp_path):
    """The 0.10.0 table shape, migrated by setup_database rather than rebuilt."""
    path = str(tmp_path / "old_geo.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE geo_cache (ip TEXT PRIMARY KEY, city TEXT, "
                 "country TEXT, looked_up_at TEXT)")
    conn.execute("INSERT INTO geo_cache VALUES ('8.8.8.8', 'X', 'Y', '2026-01-01 00:00:00')")
    conn.commit()
    conn.close()

    db = CotDatabase(db_name=path)
    assert 'hosting' in _columns(db, 'geo_cache')
    assert db.get_cached_geo('8.8.8.8') == ('X', 'Y')   # the old row survives
    assert db.get_cached_hosting('8.8.8.8') is None     # with no answer yet


def test_geo_cache_round_trip_and_miss(db):
    assert db.get_cached_geo('9.9.9.9') is None
    db.cache_geo('9.9.9.9', 'Zurich', 'Switzerland')
    assert db.get_cached_geo('9.9.9.9') == ('Zurich', 'Switzerland')
    # Upsert, not insert-or-fail: a retried lookup overwrites.
    db.cache_geo('9.9.9.9', 'Geneva', 'Switzerland')
    assert db.get_cached_geo('9.9.9.9') == ('Geneva', 'Switzerland')
