"""GET /ontologies?federated=true — remote MOD-API results in a SEPARATE block.

The federation service is monkeypatched (no network / real peers). The local
``ontologies[]`` array must stay local-only; remote rows live in ``federated``.
"""
import uuid

import pytest

from ontoexplorer.config import get_settings
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.federation import service as fed_service
from ontoexplorer.modules.federation.models import ArtefactRow, CatalogueStatus, SourceRef

REMOTE_IRI = "https://remote.example.org/onto/zzz"


def _remote_row() -> ArtefactRow:
    return ArtefactRow(
        iri=REMOTE_IRI,
        acronym="ZZZ",
        title="Remote ZZZ",
        source_landing_url="https://remote.example.org/o/zzz",
        source=SourceRef(id="peer1", label="Peer One"),
    )


def _status() -> CatalogueStatus:
    return CatalogueStatus(id="peer1", label="Peer One", status="ok", count=1, took_ms=12)


@pytest.fixture()
def fed_stub(monkeypatch):
    """Stub federated_artefacts; records calls. Federation enabled by default."""
    calls: list[tuple] = []

    async def fake(q, local_iris, peers=None, limit=None):
        calls.append((q, local_iris))  # live ref: filled once the local page is known
        return [_remote_row()], [_status()]

    monkeypatch.setattr(fed_service, "federated_artefacts", fake)
    monkeypatch.setenv("FEDERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield calls
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture()
async def cleanup(db_session):
    """The integration DB is shared: remove the rows a test created (other tests,
    e.g. the empty-list check, assume a clean catalogue)."""
    from sqlalchemy import delete
    created: list[Ontology] = []
    yield created
    for o in created:
        await db_session.execute(delete(OntologyVersion).where(OntologyVersion.ontology_id == o.id))
        await db_session.execute(delete(Ontology).where(Ontology.id == o.id))
    await db_session.commit()


async def _onto(db, *, token, created):
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{token}/{uuid.uuid4()}", title=f"Title {token}")
    db.add(o)
    db.add(OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k", sha256=uuid.uuid4().hex,
        format="turtle", status="ready", triple_count=10,
    ))
    await db.commit()
    created.append(o)
    return o


@pytest.mark.anyio
async def test_federated_block_present_and_local_unchanged(client, db_session, fed_stub, cleanup):
    token = f"fedtok{uuid.uuid4().hex[:10]}"
    o = await _onto(db_session, token=token, created=cleanup)

    base = await client.get(f"/api/v1/ontologies?q={token}")
    r = await client.get(f"/api/v1/ontologies?q={token}&federated=true")
    assert r.status_code == 200
    body = r.json()

    assert body["federated"]["catalogues"] == [_status().model_dump(mode="json")]
    assert body["federated"]["results"] == [_remote_row().model_dump(mode="json")]
    # Local array is unchanged and carries no remote rows.
    assert body["ontologies"] == base.json()["ontologies"]
    assert {x["id"] for x in body["ontologies"]} == {o.id}
    assert all(x["iri"] != REMOTE_IRI for x in body["ontologies"])
    # The stub saw the query and the local page's IRIs (for dedup).
    assert len(fed_stub) == 1
    assert fed_stub[0][0] == token
    assert fed_stub[0][1] == {o.iri}


@pytest.mark.anyio
async def test_offset_gt_zero_no_fanout(client, fed_stub):
    r = await client.get("/api/v1/ontologies?q=abc&federated=true&offset=1")
    assert r.status_code == 200
    assert "federated" not in r.json()
    assert fed_stub == []


@pytest.mark.anyio
async def test_missing_q_no_fanout(client, fed_stub):
    for url in ("/api/v1/ontologies?federated=true", "/api/v1/ontologies?federated=true&q="):
        r = await client.get(url)
        assert r.status_code == 200
        assert "federated" not in r.json()
    assert fed_stub == []


@pytest.mark.anyio
async def test_federation_disabled_no_fanout(client, fed_stub, monkeypatch):
    monkeypatch.setenv("FEDERATION_ENABLED", "false")
    get_settings.cache_clear()
    r = await client.get("/api/v1/ontologies?q=abc&federated=true")
    assert r.status_code == 200
    assert "federated" not in r.json()
    assert fed_stub == []


@pytest.mark.anyio
async def test_default_call_has_no_federated_key(client, fed_stub):
    r = await client.get("/api/v1/ontologies?q=abc")
    assert r.status_code == 200
    assert "federated" not in r.json()
    assert fed_stub == []


@pytest.mark.anyio
async def test_endpoint_late_redup_drops_local_iri_and_decrements_count(
    client, db_session, monkeypatch, cleanup
):
    """The service answers immediately and IGNORES local_iris (the race: a fast/cached
    peer replies before the local page is known). The endpoint's own post-await
    dedup must still drop the local-IRI row and decrement the catalogue count."""
    token = f"fedtok{uuid.uuid4().hex[:10]}"
    o = await _onto(db_session, token=token, created=cleanup)

    async def fake(q, local_iris, peers=None, limit=None):
        assert local_iris == set()  # local page not known yet when we answer
        dup = _remote_row().model_copy(update={"iri": o.iri})
        st = _status().model_copy(update={"count": 2})
        return [dup, _remote_row()], [st]

    monkeypatch.setattr(fed_service, "federated_artefacts", fake)
    monkeypatch.setenv("FEDERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        r = await client.get(f"/api/v1/ontologies?q={token}&federated=true")
    finally:
        get_settings.cache_clear()
    body = r.json()
    assert [x["iri"] for x in body["federated"]["results"]] == [REMOTE_IRI]
    assert body["federated"]["catalogues"][0]["count"] == 1  # 2 -> 1
    assert {x["id"] for x in body["ontologies"]} == {o.id}


@pytest.mark.anyio
async def test_service_raise_degrades_to_local_only(client, db_session, monkeypatch, cleanup):
    token = f"fedtok{uuid.uuid4().hex[:10]}"
    o = await _onto(db_session, token=token, created=cleanup)

    async def boom(q, local_iris, peers=None, limit=None):
        raise RuntimeError("peer layer exploded")

    monkeypatch.setattr(fed_service, "federated_artefacts", boom)
    monkeypatch.setenv("FEDERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        r = await client.get(f"/api/v1/ontologies?q={token}&federated=true")
    finally:
        get_settings.cache_clear()
    assert r.status_code == 200
    body = r.json()
    assert "federated" not in body
    assert {x["id"] for x in body["ontologies"]} == {o.id}


@pytest.mark.anyio
async def test_enabled_with_zero_peers_gives_empty_block(client, monkeypatch):
    """Real service, federation enabled, no peers configured -> block present, empty."""
    monkeypatch.setenv("FEDERATION_ENABLED", "true")
    monkeypatch.setenv("FEDERATION_PEERS_JSON", "")
    get_settings.cache_clear()
    try:
        r = await client.get("/api/v1/ontologies?q=abc&federated=true")
    finally:
        get_settings.cache_clear()
    assert r.status_code == 200
    assert r.json()["federated"] == {"catalogues": [], "results": []}


@pytest.mark.anyio
async def test_local_failure_cancels_inflight_fanout(client, monkeypatch):
    import asyncio

    from ontoexplorer.api import ontologies as api_ontologies

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow(q, local_iris, peers=None, limit=None):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return [], []

    async def local_boom(**kwargs):
        await started.wait()
        raise RuntimeError("local query failed")

    monkeypatch.setattr(fed_service, "federated_artefacts", slow)
    monkeypatch.setattr(api_ontologies, "_list_ontologies_local", local_boom)
    monkeypatch.setenv("FEDERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="local query failed"):
            await client.get("/api/v1/ontologies?q=abc&federated=true")
        await asyncio.wait_for(cancelled.wait(), timeout=2)
    finally:
        get_settings.cache_clear()
