"""Tests for the catalogue update poller's per-ontology branching (_poll_one).

Notify-by-default: a newer release sets update_available + broadcasts once on the
false->true edge, and does NOT auto-ingest unless auto_sync is set; an up-to-date
poll clears the flag. check_for_update, _choose, broadcast_event and ingest are
stubbed so this is a pure branching test (no DB, no network).
"""
from ontoexplorer.modules.jobs import tasks


class _FakeResult:
    def scalars(self):
        class _S:
            def all(self_inner):  # noqa: N805
                return []
        return _S()


class _FakeDB:
    async def execute(self, *a, **k):
        return _FakeResult()
    async def commit(self):
        pass


class _Ont:
    def __init__(self, **k):
        self.id = "o1"
        self.iri = "http://ex.org/o.owl"
        self.current_version_id = None
        self.owner_id = "u1"
        self.groups = []
        self.auto_sync = False
        self.update_available = False
        self.update_detail = None
        self.upstream_etag = None
        self.upstream_last_modified = None
        self.last_polled_at = None
        self.__dict__.update(k)


def _wire(monkeypatch, result):
    """Stub the four collaborators _poll_one pulls in; return a calls recorder."""
    calls = {"ingest": 0, "broadcast": 0, "broadcast_payloads": []}

    async def fake_check(ont, version, **kw):
        return result
    monkeypatch.setattr("ontoexplorer.modules.ingestion.update_check.check_for_update", fake_check)
    monkeypatch.setattr("ontoexplorer.modules.search.versions._choose", lambda v, c: None)

    async def fake_broadcast(db, event, payload):
        calls["broadcast"] += 1
        calls["broadcast_payloads"].append((event, payload))
    monkeypatch.setattr("ontoexplorer.modules.webhooks.delivery.broadcast_event", fake_broadcast)

    class _Ingest:
        def delay(self_inner, **kw):
            calls["ingest"] += 1
    monkeypatch.setattr(tasks, "ingest_ontology", _Ingest())
    return calls


_UPDATE = {"status": "update_available", "fetch_url": "http://ex.org/o.owl", "use_conneg": True,
           "fetched_version": "http://ex.org/o/v2.0/o.owl", "current_version": "http://ex.org/o/v1.0/o.owl",
           "etag": '"v2"', "last_modified": None}


async def test_notify_sets_flag_and_broadcasts_once(monkeypatch):
    calls = _wire(monkeypatch, _UPDATE)
    ont = _Ont(auto_sync=False, update_available=False)
    status = await tasks._poll_one(_FakeDB(), ont)
    assert status == "update_available"
    assert ont.update_available is True
    assert ont.update_detail["detected_version"] == "http://ex.org/o/v2.0/o.owl"
    assert calls["ingest"] == 0          # notify-by-default: no auto-ingest
    assert calls["broadcast"] == 1       # announced on the false->true edge
    assert ont.upstream_etag == '"v2"'   # validators persisted


async def test_no_rebroadcast_when_already_flagged(monkeypatch):
    calls = _wire(monkeypatch, _UPDATE)
    ont = _Ont(update_available=True)    # already known
    await tasks._poll_one(_FakeDB(), ont)
    assert ont.update_available is True
    assert calls["broadcast"] == 0       # no duplicate announcement


async def test_auto_sync_ingests_and_does_not_flag(monkeypatch):
    calls = _wire(monkeypatch, _UPDATE)
    ont = _Ont(auto_sync=True)
    status = await tasks._poll_one(_FakeDB(), ont)
    assert status == "auto_ingesting"
    assert calls["ingest"] == 1          # opt-in auto-ingest fired
    assert ont.update_available is False # handled, so no outstanding badge
    assert calls["broadcast"] == 0


async def test_up_to_date_clears_flag(monkeypatch):
    calls = _wire(monkeypatch, {"status": "up_to_date", "fetch_url": "http://ex.org/o.owl",
                                "use_conneg": True, "etag": '"v1"', "last_modified": None})
    ont = _Ont(update_available=True, update_detail={"detected_version": "x"})
    status = await tasks._poll_one(_FakeDB(), ont)
    assert status == "up_to_date"
    assert ont.update_available is False and ont.update_detail is None
    assert ont.upstream_etag == '"v1"'
    assert calls["ingest"] == 0


async def test_fetch_error_leaves_flag_untouched(monkeypatch):
    _wire(monkeypatch, {"status": "fetch_error", "detail": "boom", "fetch_url": "http://ex.org/o.owl"})
    ont = _Ont(update_available=True, update_detail={"detected_version": "x"}, upstream_etag='"keep"')
    status = await tasks._poll_one(_FakeDB(), ont)
    assert status == "fetch_error"
    assert ont.update_available is True          # transient error doesn't clear a known update
    assert ont.upstream_etag == '"keep"'         # validators untouched on error
    assert ont.last_polled_at is not None        # still advances rotation
