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
async def test_local_row_not_duplicated_by_early_fanout(client, db_session, monkeypatch, cleanup):
    """A remote row whose IRI equals a local row's IRI is dropped, even though the
    fan-out starts before the local page is known."""
    token = f"fedtok{uuid.uuid4().hex[:10]}"
    o = await _onto(db_session, token=token, created=cleanup)

    async def fake(q, local_iris, peers=None, limit=None):
        import asyncio
        await asyncio.sleep(0.2)  # let the local query finish first
        dup = _remote_row().model_copy(update={"iri": o.iri})
        rows = [r for r in [dup, _remote_row()] if r.iri not in local_iris]
        return rows, [_status()]

    monkeypatch.setattr(fed_service, "federated_artefacts", fake)
    monkeypatch.setenv("FEDERATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        r = await client.get(f"/api/v1/ontologies?q={token}&federated=true")
    finally:
        get_settings.cache_clear()
    assert [x["iri"] for x in r.json()["federated"]["results"]] == [REMOTE_IRI]
