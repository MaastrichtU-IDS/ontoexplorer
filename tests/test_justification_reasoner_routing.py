"""SP2 Task 6: get_justification routes the version's reasoner; manchester
passthrough + no-justify (reasoning_available: False) handling."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
async def make_version(db_session):
    """Create an Ontology + OntologyVersion row and return the version."""
    import uuid

    from ontoexplorer.models.db import Ontology, OntologyVersion

    async def _make(*, reasoner: str = "whelk", status: str = "ready"):
        unique = uuid.uuid4().hex[:12]
        ont = Ontology(iri=f"http://example.org/justif-routing-test-{unique}.owl")
        db_session.add(ont)
        await db_session.flush()
        ver = OntologyVersion(
            ontology_id=ont.id,
            minio_key=f"test/justif-routing-test-{unique}.ttl",
            sha256=f"justifroute{unique}",
            format="turtle",
            status=status,
            reasoner=reasoner,
        )
        db_session.add(ver)
        await db_session.commit()
        return ver

    return _make


@pytest.mark.asyncio
async def test_konclude_version_reports_no_explanations(client, make_version):
    version = await make_version(reasoner="konclude", status="ready")
    unavailable = {
        "justifications": [],
        "reasoning_available": False,
        "reason": "reasoner 'konclude' does not support justifications",
    }
    with patch(
        "ontoexplorer.api.ontologies.elk_request_justification",
        new=AsyncMock(return_value=unavailable),
    ) as m:
        r = await client.get(
            f"/api/v1/ontologies/{version.ontology_id}/{version.id}"
            f"/justification?sub=http://x/A&sup=http://x/C"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["reasoning_available"] is False
    assert body["justifications"] == []
    assert body["reason"] == "reasoner 'konclude' does not support justifications"

    # Confirm the endpoint actually threaded the version's reasoner through.
    _, kwargs = m.call_args
    passed = kwargs.get("reasoner") or (m.call_args[0][4] if len(m.call_args[0]) > 4 else None)
    assert passed == "konclude"


@pytest.mark.asyncio
async def test_rustdl_manchester_passthrough(client, make_version):
    version = await make_version(reasoner="rustdl", status="ready")
    manchester = {
        "format": "manchester",
        "timed_out": False,
        "justifications": [["SubClassOf(A B)", "SubClassOf(B C)"]],
    }
    with patch(
        "ontoexplorer.api.ontologies.elk_request_justification",
        new=AsyncMock(return_value=manchester),
    ) as m:
        r = await client.get(
            f"/api/v1/ontologies/{version.ontology_id}/{version.id}"
            f"/justification?sub=http://x/A&sup=http://x/C"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "manchester"
    assert body["justifications"] == [["SubClassOf(A B)", "SubClassOf(B C)"]]
    assert body["reasoning_available"] is True

    _, kwargs = m.call_args
    passed = kwargs.get("reasoner") or (m.call_args[0][4] if len(m.call_args[0]) > 4 else None)
    assert passed == "rustdl"
