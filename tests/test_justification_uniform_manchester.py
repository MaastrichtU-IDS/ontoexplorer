"""SP3 Task 3: get_justification is a uniform Manchester passthrough for every
reasoner (whelk and rustdl alike, now that the reasoner-service renders both to
Manchester), the no-justify (reasoning_available: False) path still works, and
the version serializer exposes `reasoner`.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
async def make_version(db_session):
    """Create an Ontology + OntologyVersion row and return the version."""
    import uuid

    from ontoexplorer.models.db import Ontology, OntologyVersion

    async def _make(*, reasoner: str = "whelk", status: str = "ready"):
        unique = uuid.uuid4().hex[:12]
        ont = Ontology(iri=f"http://example.org/justif-manchester-test-{unique}.owl")
        db_session.add(ont)
        await db_session.flush()
        ver = OntologyVersion(
            ontology_id=ont.id,
            minio_key=f"test/justif-manchester-test-{unique}.ttl",
            sha256=f"justifmanchester{unique}",
            format="turtle",
            status=status,
            reasoner=reasoner,
        )
        db_session.add(ver)
        await db_session.commit()
        return ver

    return _make


@pytest.mark.asyncio
async def test_whelk_version_returns_manchester(client, make_version):
    version = await make_version(reasoner="whelk", status="ready")
    manchester = {
        "format": "manchester",
        "timed_out": False,
        "justifications": [["A SubClassOf B", "B SubClassOf C"]],
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
    assert body["justifications"] == [["A SubClassOf B", "B SubClassOf C"]]
    assert body["reasoning_available"] is True
    assert body["timed_out"] is False

    _, kwargs = m.call_args
    passed = kwargs.get("reasoner") or (m.call_args[0][4] if len(m.call_args[0]) > 4 else None)
    assert passed == "whelk"


@pytest.mark.asyncio
async def test_response_includes_labels_for_iris(client, make_version):
    """Every full IRI in the Manchester justification gets a display label in
    `labels` so the UI can render clickable, human-readable tokens. With no
    indexed label the endpoint falls back to the IRI fragment."""
    version = await make_version(reasoner="whelk", status="ready")
    manchester = {
        "format": "manchester",
        "timed_out": False,
        "justifications": [["http://ex.org/Foo SubClassOf http://ex.org/Bar"]],
    }
    # No indexed labels available in tests -> _label falls back to the IRI
    # fragment. Patch the redis handle so hgetall returns nothing cleanly
    # (otherwise the label lookup raises and the endpoint drops to the BFS path).
    fake_redis = MagicMock()
    fake_redis.hgetall.return_value = {}
    with patch(
        "ontoexplorer.api.ontologies.elk_request_justification",
        new=AsyncMock(return_value=manchester),
    ), patch(
        "ontoexplorer.modules.search.indexer._get_redis", return_value=fake_redis
    ):
        r = await client.get(
            f"/api/v1/ontologies/{version.ontology_id}/{version.id}"
            f"/justification?sub=http://ex.org/Foo&sup=http://ex.org/Bar"
        )
    assert r.status_code == 200
    labels = r.json()["labels"]
    assert labels["http://ex.org/Foo"] == "Foo"
    assert labels["http://ex.org/Bar"] == "Bar"


@pytest.mark.asyncio
async def test_rustdl_version_returns_manchester(client, make_version):
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
    ):
        r = await client.get(
            f"/api/v1/ontologies/{version.ontology_id}/{version.id}"
            f"/justification?sub=http://x/A&sup=http://x/C"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["reasoning_available"] is False
    assert body["justifications"] == []
    assert body["reason"] == "reasoner 'konclude' does not support justifications"


@pytest.mark.asyncio
async def test_empty_justifications_falls_back_to_bfs(client, make_version):
    """SP3 final fix: when the reasoner-service call succeeds but returns no
    justifications (and hasn't timed out), get_justification must fall through
    to the Oxigraph asserted-subClassOf BFS fallback rather than returning an
    empty result."""
    version = await make_version(reasoner="whelk", status="ready")
    empty_result = {
        "format": "manchester",
        "timed_out": False,
        "justifications": [],
    }
    known_path = [[
        {
            "sub": {"type": "named", "iri": "http://x/A", "label": "A"},
            "rel": "subClassOf",
            "sup": {"type": "named", "iri": "http://x/C", "label": "C"},
        },
    ]]
    with patch(
        "ontoexplorer.api.ontologies.elk_request_justification",
        new=AsyncMock(return_value=empty_result),
    ) as m, patch(
        "ontoexplorer.clients.oxigraph.get_store",
        return_value=object(),
    ), patch(
        "ontoexplorer.api.ontologies._find_subclass_path",
        return_value=known_path,
    ) as bfs_mock:
        r = await client.get(
            f"/api/v1/ontologies/{version.ontology_id}/{version.id}"
            f"/justification?sub=http://x/A&sup=http://x/C"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["reasoning_available"] is True
    assert body["format"] == "manchester"
    assert body["timed_out"] is False
    assert body["justifications"] == [["A SubClassOf C"]]

    m.assert_awaited_once()
    bfs_mock.assert_called_once()


@pytest.mark.asyncio
async def test_no_justify_response_includes_format_and_timed_out(client, make_version):
    """SP3 final fix: the reasoning_available:False (no-justify) return must
    include format/timed_out for uniformity with the other branches, since the
    frontend JustificationResult type requires them."""
    version = await make_version(reasoner="konclude", status="ready")
    unavailable = {
        "justifications": [],
        "reasoning_available": False,
        "reason": "reasoner 'konclude' does not support justifications",
    }
    with patch(
        "ontoexplorer.api.ontologies.elk_request_justification",
        new=AsyncMock(return_value=unavailable),
    ):
        r = await client.get(
            f"/api/v1/ontologies/{version.ontology_id}/{version.id}"
            f"/justification?sub=http://x/A&sup=http://x/C"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["reasoning_available"] is False
    assert body["justifications"] == []
    assert body["format"] == "manchester"
    assert body["timed_out"] is False


@pytest.mark.asyncio
async def test_version_serialization_includes_reasoner(client, make_version):
    version = await make_version(reasoner="rustdl", status="ready")
    r = await client.get(f"/api/v1/ontologies/{version.ontology_id}/{version.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["reasoner"] == "rustdl"
