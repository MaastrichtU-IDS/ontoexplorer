"""Integration tests for GET /api/v1/entities/facets (ontology facet counts)."""
import uuid
from unittest.mock import patch

import pytest

from ontoexplorer.models.db import EntityIndex, Ontology, OntologyVersion
from ontoexplorer.modules.search import browse
from ontoexplorer.modules.search.indexer import normalise_label
from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache


def _ent(vid, oid, iri, label, etype="class"):
    return EntityIndex(
        version_id=vid, iri=iri, ontology_id=oid, type=etype, primary_label=label,
        primary_label_norm=normalise_label(label), short=iri.rsplit("/", 1)[-1],
        source="src", search_text=label, definitions=[],
    )


@pytest.fixture()
async def seeded(db_session):
    """A: v1 (superseded, 3 classes) + v2 (latest, 1 class). B: 2 classes + 1 individual."""
    tag = uuid.uuid4().hex[:8]
    a, b = f"fa-{tag}", f"fb-{tag}"
    db_session.add_all([
        Ontology(id=a, iri=f"http://ex.org/{tag}/a", shortname=f"a{tag}", title="Onto A"),
        Ontology(id=b, iri=f"http://ex.org/{tag}/b", shortname=f"b{tag}", title="Onto B"),
    ])
    await db_session.flush()
    v1, v2, v3 = f"fa1-{tag}", f"fa2-{tag}", f"fb1-{tag}"
    for vid, oid, vi in ((v1, a, "1.0.0"), (v2, a, "2.0.0"), (v3, b, "1.0.0")):
        db_session.add(OntologyVersion(
            id=vid, ontology_id=oid, version_iri=f"http://ex.org/{tag}/{oid}/{vi}",
            minio_key=f"k/{vid}", sha256=f"sha-{vid}", format="owl", status="ready"))
    await db_session.flush()
    u = f"http://ex.org/{tag}"
    db_session.add_all([
        _ent(v1, a, f"{u}/o1", "old one"), _ent(v1, a, f"{u}/o2", "old two"),
        _ent(v1, a, f"{u}/o3", "old three"),
        _ent(v2, a, f"{u}/c1", "new one"),
        _ent(v3, b, f"{u}/c2", "b one"), _ent(v3, b, f"{u}/c3", "b two"),
        _ent(v3, b, f"{u}/i1", "ind", etype="individual"),
    ])
    await db_session.commit()
    invalidate_latest_ready_versions_cache()
    yield {"a": a, "b": b, "tag": tag}
    invalidate_latest_ready_versions_cache()


def _mine(body, s):
    return [o for o in body["ontologies"] if o["ontology_id"] in (s["a"], s["b"])]


@pytest.mark.anyio
async def test_counts_scoped_to_latest_and_desc(client, seeded):
    r = await client.get("/api/v1/entities/facets", params={"type": "class"})
    assert r.status_code == 200
    body = r.json()
    mine = _mine(body, seeded)
    assert [(o["ontology_id"], o["count"]) for o in mine] == [
        (seeded["b"], 2), (seeded["a"], 1)]  # A: only v2 counted, not v1
    assert mine[0]["short"] == f"b{seeded['tag']}" and mine[0]["title"] == "Onto B"
    assert set(mine[0]) == {"ontology_id", "short", "title", "count"}
    counts = [o["count"] for o in body["ontologies"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.anyio
async def test_individual_type(client, seeded):
    r = await client.get("/api/v1/entities/facets", params={"type": "individual"})
    mine = _mine(r.json(), seeded)
    assert [(o["ontology_id"], o["count"]) for o in mine] == [(seeded["b"], 1)]


@pytest.mark.anyio
async def test_unknown_type_422(client, seeded):
    r = await client.get("/api/v1/entities/facets", params={"type": "bogus"})
    assert r.status_code == 422
    r = await client.get("/api/v1/entities/facets")
    assert r.status_code == 422


@pytest.mark.anyio
async def test_redis_absent_fallback(client, seeded):
    with patch("ontoexplorer.modules.search.indexer._get_redis",
               side_effect=RuntimeError("no redis")):
        r = await client.get("/api/v1/entities/facets", params={"type": "class"})
    assert r.status_code == 200
    mine = _mine(r.json(), seeded)
    assert [o["count"] for o in mine] == [2, 1]


@pytest.mark.anyio
async def test_facet_counts_helper(db_session, seeded):
    rows = await browse.facet_counts(db_session, "class")
    assert {r["ontology_id"]: r["count"] for r in rows}[seeded["a"]] == 1
