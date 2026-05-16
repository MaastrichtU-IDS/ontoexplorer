"""Integration tests for the ontology diff API endpoints."""
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion


@pytest.mark.anyio
async def test_get_consecutive_diff_no_previous_version(client, user_and_key, db_session):
    """Returns 404 when the version has no predecessor."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    # Create an ontology with a single version directly in the DB
    ont = Ontology(iri="http://example.org/diff-test-single.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/diff-single.ttl",
        sha256="difftest001",
        format="turtle",
        status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    oid = ont.id
    vid = ver.id

    # First (only) version has no predecessor — expect 404
    r = await client.get(f"/api/v1/ontologies/{oid}/{vid}/diff", headers=auth)
    assert r.status_code == 404
    assert "previous" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_arbitrary_diff_same_version_rejected(client, user_and_key):
    """Returns 400 when from and to are the same version ID."""
    r = await client.get(
        "/api/v1/ontologies/fake-oid/diff",
        params={"from": "same-vid", "to": "same-vid"},
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_get_arbitrary_diff_unknown_version(client, user_and_key):
    """Returns 404 when either version does not exist."""
    r = await client.get(
        "/api/v1/ontologies/nonexistent/diff",
        params={"from": "v1", "to": "v2"},
    )
    assert r.status_code == 404
