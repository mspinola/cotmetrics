"""The ETL rebuild must not reuse an indexer built before the load.

`CotIndexer` reads the params years, roles, instrument list, lookbacks and
`last_known_db_time` once in `__init__`. An instance built before an ETL run describes the
data as it was beforehand, and only a fresh construction re-reads any of it. `handle_updates`
then emails a Signal Matrix through `cotmetrics.reports`, which resolves the same singleton,
so reusing a stale one mails pre-ETL numbers under a subject announcing the new data.
"""
import cotmetrics.indexer as indexer
import cotmetrics.pipelines.etl_scheduler as etl


def teardown_function():
    indexer.reset_indexer()


def _scheduler(monkeypatch):
    """A scheduler whose constructor does no network setup."""
    monkeypatch.setattr(etl, "CotExtractor", lambda: object())
    return etl.CotJobScheduler(enable_email=False)


def test_the_rebuild_discards_an_indexer_built_before_the_load(monkeypatch):
    built = []

    class FakeIndexer:
        def __init__(self):
            built.append(self)

    monkeypatch.setattr(indexer, "CotIndexer", FakeIndexer)
    indexer.reset_indexer()

    stale = indexer.get_indexer()          # the pre-ETL singleton
    assert built == [stale]

    _scheduler(monkeypatch).rebuild_indexer_cache()

    fresh = indexer.get_indexer()
    assert fresh is not stale, "the rebuild reused the pre-ETL indexer"
    assert built == [stale, fresh], "the rebuild must construct exactly once"


def test_the_rebuild_works_with_no_indexer_yet(monkeypatch):
    """The scheduler may run before anything has asked for an indexer."""
    built = []
    monkeypatch.setattr(indexer, "CotIndexer", lambda: built.append(1))
    indexer.reset_indexer()

    _scheduler(monkeypatch).rebuild_indexer_cache()

    assert len(built) == 1


def test_reports_see_the_rebuilt_indexer(monkeypatch):
    """The emailed Signal Matrix resolves the singleton, so it must see the new one."""
    import cotmetrics.reports as reports

    class FakeIndexer:
        pass

    monkeypatch.setattr(indexer, "CotIndexer", FakeIndexer)
    indexer.reset_indexer()

    stale = indexer.get_indexer()
    _scheduler(monkeypatch).rebuild_indexer_cache()

    assert reports.get_indexer() is not stale
