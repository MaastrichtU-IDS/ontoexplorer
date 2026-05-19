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


@pytest.mark.anyio
async def test_diff_api_includes_inferred_status_and_breakdown(client, db_session):
    """Diff API response carries inferred_status and the asserted/inferred
    axiom breakdown in the summary."""
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff

    ont = Ontology(iri="http://example.org/test.owl", shortname="test")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="t1", sha256="t1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="t2", sha256="t2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    diff = OntologyDiff(
        ontology_id=ont.id,
        version_from_id=v1.id, version_to_id=v2.id,
        status="ready",
        summary={
            "added": 0, "removed": 0, "modified": 1,
            "literal_changes": 0, "axiom_changes": 3,
            "asserted_axiom_changes": 2,
            "inferred_axiom_changes": 1,
            "by_entity_type": {},
            "inferred_status": {"from_version": "ready", "to_version": "ready"},
        },
        diff_data={"added": [], "removed": [], "modified": []},
    )
    db_session.add(diff)
    await db_session.commit()

    r = await client.get(f"/api/v1/ontologies/{ont.id}/diff", params={"from": v1.id, "to": v2.id})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    summary = body["summary"]
    assert summary["asserted_axiom_changes"] == 2
    assert summary["inferred_axiom_changes"] == 1
    assert summary["inferred_status"] == {"from_version": "ready", "to_version": "ready"}
