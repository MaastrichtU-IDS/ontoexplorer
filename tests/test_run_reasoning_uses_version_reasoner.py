"""SP2 Task 5: _run_reasoning passes version.reasoner to reasoning_client.classify_v2."""

from unittest.mock import AsyncMock, patch

import pyoxigraph
import pytest

from ontoexplorer.modules.jobs import tasks


@pytest.fixture
async def make_version(db_session):
    """Create an Ontology + OntologyVersion row and return the version."""
    from ontoexplorer.models.db import Ontology, OntologyVersion

    async def _make(
        *, reasoner: str = "whelk", status: str = "ingested",
        iri: str | None = None, sha256: str = "reasontest001",
    ):
        ont = Ontology(iri=iri or "http://example.org/reason-test.owl")
        db_session.add(ont)
        await db_session.flush()
        ver = OntologyVersion(
            ontology_id=ont.id,
            minio_key="test/reason-test.ttl",
            sha256=sha256,
            format="turtle",
            status=status,
            reasoner=reasoner,
        )
        db_session.add(ver)
        await db_session.commit()
        return ver

    return _make


class _FakeHttpResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"superclasses": {}}


@pytest.mark.asyncio
async def test_run_reasoning_passes_version_reasoner(db_session, make_version):
    version = await make_version(reasoner="rustdl", status="ingested")

    # _run_reasoning also (a) touches the real Oxigraph store and (b) makes a
    # follow-up HTTP GET to the reasoner service to fetch the full
    # classification for persistence. Neither is under test here, so stub
    # both out with an in-memory store and a canned response.
    with patch(
        "ontoexplorer.clients.reasoning.classify_v2",
        new=AsyncMock(return_value={"inferred_count": 0}),
    ) as m, patch(
        "ontoexplorer.clients.oxigraph.get_store", return_value=pyoxigraph.Store()
    ), patch(
        "httpx.AsyncClient.get", new=AsyncMock(return_value=_FakeHttpResponse())
    ):
        await tasks._run_reasoning(db_session, version.id)

    # classify_v2(graph, version_id, reasoner) — reasoner is the 3rd positional or kw
    _, kwargs = m.call_args
    passed = kwargs.get("reasoner") or (m.call_args[0][2] if len(m.call_args[0]) > 2 else None)
    assert passed == "rustdl"


@pytest.mark.asyncio
async def test_run_reasoning_followup_get_carries_version_reasoner(db_session, make_version):
    """Regression for Critical Fix #1: the follow-up GET after classify_v2 must
    carry `?reasoner=<version.reasoner>`, otherwise the reasoner-service's
    whelk-scoped cache key 409s for any non-whelk version and the inferred
    graph is silently never persisted to Oxigraph.
    """
    version = await make_version(
        reasoner="rustdl", status="ingested",
        iri="http://example.org/reason-followup-get-test.owl",
        sha256="reasonfollowupget001",
    )

    captured_urls: list[str] = []

    async def _capturing_get(self, url, *args, **kwargs):
        captured_urls.append(url)
        return _FakeHttpResponse()

    with patch(
        "ontoexplorer.clients.reasoning.classify_v2",
        new=AsyncMock(return_value={"inferred_count": 0}),
    ), patch(
        "ontoexplorer.clients.oxigraph.get_store", return_value=pyoxigraph.Store()
    ), patch(
        "httpx.AsyncClient.get", new=_capturing_get
    ):
        await tasks._run_reasoning(db_session, version.id)

    # Two GETs now: the follow-up that fetches the inferred axioms, and the
    # classification read that materialises the inferred hierarchy for the tree.
    # Both address this version and must carry its reasoner — picking the wrong
    # one would silently read another backend's classification.
    assert len(captured_urls) == 2, captured_urls
    assert all(f"/classify/{version.id}" in u for u in captured_urls)
    assert all("reasoner=rustdl" in u for u in captured_urls)
