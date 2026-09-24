"""Tests for the ontologies REST API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MINIMAL_TURTLE = b"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <http://example.org/> .

<http://example.org/TestOntology> a owl:Ontology .
ex:ClassName a owl:Class .
"""


@pytest.mark.anyio
async def test_list_ontologies_empty(client, user_and_key):
    _, raw_key = user_and_key
    resp = await client.get("/api/v1/ontologies", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    assert resp.json()["ontologies"] == []


@pytest.mark.anyio
async def test_submit_ontology_by_content(client, user_and_key):
    """Submit an ontology inline; pipeline runs with MinIO/Celery mocked."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    # Mock external services so the test doesn't need Docker
    mock_store = MagicMock()
    mock_store.return_value = "ontologies/oid/vid/sha.ttl"
    mock_load = MagicMock(return_value=2)
    mock_reason = MagicMock()
    mock_reason.delay = MagicMock()
    mock_index = MagicMock()
    mock_index.delay = MagicMock()

    with (
        patch("ontoexplorer.modules.storage.minio_client.store_ontology", mock_store),
        patch("ontoexplorer.clients.oxigraph.load_graph", mock_load),
        patch("ontoexplorer.modules.ingestion.pipeline.reason_ontology", mock_reason, create=True),
        patch("ontoexplorer.modules.ingestion.pipeline.index_ontology", mock_index, create=True),
        patch("ontoexplorer.modules.ingestion.pipeline._write_fair_metadata", new=AsyncMock()),
    ):
        resp = await client.post(
            "/api/v1/ontologies",
            json={"format": "turtle", "content": _MINIMAL_TURTLE.decode()},
            headers=auth,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "task_id" in body or "ontology_id" in body


@pytest.mark.anyio
async def test_submit_ontology_by_url_mocked(client, user_and_key):
    """Submit via URL; HTTP fetch and pipeline are mocked."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    mock_fetch = MagicMock(return_value=MagicMock(
        data=_MINIMAL_TURTLE,
        content_type="text/turtle",
        final_url="http://example.org/test.ttl",
        mode=MagicMock(value="url"),
    ))
    mock_store = MagicMock(return_value="ontologies/oid/vid/sha.ttl")
    mock_load = MagicMock(return_value=2)

    with (
        patch("ontoexplorer.modules.ingestion.source_resolver.resolve_url", mock_fetch),
        patch("ontoexplorer.modules.storage.minio_client.store_ontology", mock_store),
        patch("ontoexplorer.clients.oxigraph.load_graph", mock_load),
        patch("ontoexplorer.modules.ingestion.pipeline._write_fair_metadata", new=AsyncMock()),
        patch("ontoexplorer.modules.jobs.tasks.reason_ontology", MagicMock(delay=MagicMock()), create=True),
        patch("ontoexplorer.modules.jobs.tasks.index_ontology", MagicMock(delay=MagicMock()), create=True),
    ):
        resp = await client.post(
            "/api/v1/ontologies",
            json={"url": "http://example.org/test.ttl"},
            headers=auth,
        )

    assert resp.status_code in (200, 202)


@pytest.mark.anyio
async def test_delete_ontology(client, user_and_key, db_session):
    """DELETE /api/v1/ontologies/{id} removes the ontology and returns 204."""
    from ontoexplorer.models.db import Ontology
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    ont = Ontology(iri="http://example.org/to-delete.owl")
    db_session.add(ont)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/ontologies/{ont.id}", headers=auth)
    assert resp.status_code == 204

    resp2 = await client.get(f"/api/v1/ontologies/{ont.id}", headers=auth)
    assert resp2.status_code == 404


@pytest.mark.anyio
async def test_delete_ontology_not_found(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    resp = await client.delete("/api/v1/ontologies/does-not-exist", headers=auth)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_versions_include_triple_count(client, user_and_key, db_session):
    """GET /api/v1/ontologies/{id}/versions includes triple_count field."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    ont = Ontology(iri="http://example.org/triple-count.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key.ttl",
        sha256="abc123",
        format="turtle",
        status="ready",
        triple_count=42000,
    )
    db_session.add(ver)
    await db_session.commit()

    resp = await client.get(f"/api/v1/ontologies/{ont.id}/versions", headers=auth)
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    assert versions[0]["triple_count"] == 42000


@pytest.mark.anyio
async def test_get_nonexistent_ontology(client, user_and_key):
    _, raw_key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies/nonexistent-id",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_pagination_sort_and_total(client, user_and_key, db_session):
    """The list endpoint paginates server-side: echoes offset/limit/total, sorts
    by name (case-insensitive), and slices cleanly so infinite scroll can page
    through it. Written to tolerate rows left by other tests (shared DB)."""
    from ontoexplorer.models.db import Ontology
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    base = (await client.get("/api/v1/ontologies?limit=1", headers=auth)).json()["total"]

    # Unique prefix → these three sort contiguously and are identifiable amid any
    # pre-existing rows. Mixed case verifies case-insensitive ordering.
    P = "zzzpag-"
    for sn in (f"{P}Charlie", f"{P}alpha", f"{P}Bravo"):
        db_session.add(Ontology(iri=f"http://example.org/{sn}.owl", shortname=sn))
    await db_session.commit()

    # total reflects the three new rows.
    r_asc = (await client.get(f"/api/v1/ontologies?limit={base + 10}&sort=name&dir=asc", headers=auth)).json()
    assert r_asc["total"] == base + 3
    mine_asc = [o["shortname"] for o in r_asc["ontologies"] if o["shortname"].startswith(P)]
    assert mine_asc == [f"{P}alpha", f"{P}Bravo", f"{P}Charlie"]   # case-insensitive

    # Descending flips their relative order.
    r_desc = (await client.get(f"/api/v1/ontologies?limit={base + 10}&sort=name&dir=desc", headers=auth)).json()
    mine_desc = [o["shortname"] for o in r_desc["ontologies"] if o["shortname"].startswith(P)]
    assert mine_desc == [f"{P}Charlie", f"{P}Bravo", f"{P}alpha"]

    # Pagination mechanics: two disjoint pages concatenate to the combined page.
    p0 = (await client.get("/api/v1/ontologies?limit=2&offset=0&sort=name&dir=asc", headers=auth)).json()
    p1 = (await client.get("/api/v1/ontologies?limit=2&offset=2&sort=name&dir=asc", headers=auth)).json()
    combined = (await client.get("/api/v1/ontologies?limit=4&offset=0&sort=name&dir=asc", headers=auth)).json()
    assert p0["offset"] == 0 and p0["limit"] == 2 and len(p0["ontologies"]) == 2
    assert [o["id"] for o in p0["ontologies"]] + [o["id"] for o in p1["ontologies"]] == [o["id"] for o in combined["ontologies"]]

    # Offset past the end is an empty page, not an error.
    r_end = await client.get("/api/v1/ontologies?limit=2&offset=999999", headers=auth)
    assert r_end.status_code == 200 and r_end.json()["ontologies"] == []

    # Bad sort/dir are rejected.
    assert (await client.get("/api/v1/ontologies?sort=bogus", headers=auth)).status_code == 422
    assert (await client.get("/api/v1/ontologies?dir=sideways", headers=auth)).status_code == 422
