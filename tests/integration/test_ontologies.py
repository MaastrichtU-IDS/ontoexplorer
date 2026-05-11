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
async def test_get_nonexistent_ontology(client, user_and_key):
    _, raw_key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies/nonexistent-id",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404
