"""Integration tests for the MOD-API compatibility layer (/mod/)."""

import uuid
from unittest.mock import patch
from urllib.parse import quote

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def ready_ontology(db_session):
    """Insert an Ontology + OntologyVersion (ready) + OntologyMetaProfile."""
    uid = uuid.uuid4().hex[:8]
    shortname = f"go_{uid}"
    iri = f"http://example.org/go_{uid}.owl"

    ont = Ontology(
        id=str(uuid.uuid4()),
        iri=iri,
        shortname=shortname,
        title="Gene Ontology",
        groups=[],
    )
    db_session.add(ont)
    await db_session.flush()

    ver = OntologyVersion(
        id=str(uuid.uuid4()),
        ontology_id=ont.id,
        minio_key=f"ontologies/go/{uid}/go.owl",
        sha256="abc123def456" + uuid.uuid4().hex,
        format="owl",
        status="ready",
        source_url="http://purl.obolibrary.org/obo/go.owl",
        triple_count=100000,
    )
    db_session.add(ver)
    await db_session.flush()

    meta = OntologyMetaProfile(
        id=str(uuid.uuid4()),
        version_id=ver.id,
        resolved={
            "title": "Gene Ontology",
            "description": "A comprehensive ontology of gene and gene product attributes.",
            "license": "https://creativecommons.org/licenses/by/4.0/",
        },
        candidates_data={},
        status="resolved",
    )
    db_session.add(meta)
    await db_session.commit()
    return ont, ver, meta


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_catalogue_returns_jsonld(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get("/mod/")
    assert resp.status_code == 200
    assert "application/ld+json" in resp.headers["content-type"]
    body = resp.json()
    assert "@context" in body


@pytest.mark.anyio
async def test_catalogue_returns_turtle(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get("/mod/?fmt=ttl")
    assert resp.status_code == 200
    assert "text/turtle" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_catalogue_accept_turtle_header(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get("/mod/", headers={"Accept": "text/turtle"})
    assert resp.status_code == 200
    assert "text/turtle" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_artefacts_list(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get("/mod/artefacts")
    assert resp.status_code == 200
    body = resp.json()
    assert "@context" in body


@pytest.mark.anyio
async def test_get_artefact_by_shortname(client, ready_ontology):
    ont, _, _ = ready_ontology
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get(f"/mod/artefacts/{ont.shortname}")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_artefact_by_encoded_iri(client, ready_ontology):
    ont, _, _ = ready_ontology
    # Double-encode so that after httpx decodes one level, FastAPI still sees
    # a percent-encoded IRI that the handler's unquote() will decode correctly.
    encoded = quote(quote(ont.iri, safe=""), safe="")
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get(f"/mod/artefacts/{encoded}")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_artefact_not_found(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get("/mod/artefacts/nonexistent")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_record(client, ready_ontology):
    ont, _, _ = ready_ontology
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get(f"/mod/records/{ont.shortname}")
    assert resp.status_code == 200
    body = resp.json()
    assert "@context" in body


@pytest.mark.anyio
async def test_list_distributions(client, ready_ontology):
    ont, _, _ = ready_ontology
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get(f"/mod/artefacts/{ont.shortname}/distributions")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_artefact_record_subpath(client, ready_ontology):
    ont, _, _ = ready_ontology
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get(f"/mod/artefacts/{ont.shortname}/record")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_catalogue_html(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=_fake_redis()):
        resp = await client.get("/mod/?fmt=html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert b"<table" in resp.content
