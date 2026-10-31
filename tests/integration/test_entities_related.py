"""Integration tests for GET /api/v1/entities/related (semantic neighbours)."""
import uuid

import pytest

import ontoexplorer.modules.search.semantic as sem
from ontoexplorer.models.db import (
    EntityIndex, Ontology, OntologyVersion, TermEmbedding,
)
from ontoexplorer.modules.search.indexer import normalise_label
from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache


def _vec(*head):
    return [*head] + [0.0] * (768 - len(head))


def _ent(vid, oid, iri, label, etype="class", definitions=None):
    return EntityIndex(
        version_id=vid, iri=iri, ontology_id=oid, type=etype, primary_label=label,
        primary_label_norm=normalise_label(label), short=iri.rsplit("/", 1)[-1],
        source="src", search_text=label, definitions=definitions or [])


def _emb(vid, iri, etype, vec):
    return TermEmbedding(version_id=vid, entity_iri=iri, entity_type=etype,
                         text_hash="h", embedding=vec)


@pytest.fixture()
async def seeded(db_session, monkeypatch):
    tag = uuid.uuid4().hex[:8]
    a = f"oa-{tag}"
    db_session.add(Ontology(id=a, iri=f"http://ex.org/{tag}/a", shortname=f"a{tag}",
                            title="Onto A"))
    await db_session.flush()
    v1, v2 = f"a1-{tag}", f"a2-{tag}"
    for vid, vi in ((v1, "1.0.0"), (v2, "2.0.0")):
        db_session.add(OntologyVersion(
            id=vid, ontology_id=a, version_iri=f"http://ex.org/{tag}/{vi}",
            minio_key=f"k/{vid}", sha256=f"sha-{vid}", format="owl", status="ready"))
    await db_session.flush()
    u = f"http://ex.org/{tag}/"
    db_session.add_all([
        _ent(v2, a, u + "near", "near", definitions=[{"value": " Near thing. "}]),
        _ent(v2, a, u + "mid", "mid"),
        _ent(v2, a, u + "far", "far"),
        _ent(v2, a, u + "prop", "prop", etype="object_property"),
        _ent(v1, a, u + "stale", "stale"),
    ])
    await db_session.flush()
    db_session.add_all([
        _emb(v2, u + "near", "class", _vec(1, 0.1)),
        _emb(v2, u + "mid", "class", _vec(1, 1)),
        _emb(v2, u + "far", "class", _vec(0, 1)),
        _emb(v2, u + "prop", "object_property", _vec(1, 0)),   # best match, wrong type
        _emb(v1, u + "stale", "class", _vec(1, 0)),            # superseded version
    ])
    await db_session.commit()
    invalidate_latest_ready_versions_cache()
    monkeypatch.setattr(sem, "embed_query", lambda text: _vec(1, 0))
    yield {"a": a, "v1": v1, "v2": v2, "u": u}
    invalidate_latest_ready_versions_cache()


@pytest.mark.anyio
async def test_related_ordered_typed_latest_only(client, seeded):
    r = await client.get("/api/v1/entities/related",
                         params={"type": "class", "q": "x", "ontology": seeded["a"]})
    assert r.status_code == 200
    body = r.json()
    assert body["unavailable"] is False
    iris = [e["iri"] for e in body["entities"]]
    assert iris == [seeded["u"] + n for n in ("near", "mid", "far")]
    scores = [e["score"] for e in body["entities"]]
    assert scores == sorted(scores, reverse=True) and scores[0] > 0.99
    e0 = body["entities"][0]
    assert set(e0) == {"iri", "primary_label", "short", "type", "ontology_id",
                       "ontology_title", "ontology_shortname", "version_id", "source", "definition", "score"}
    assert e0["definition"] == "Near thing." and e0["ontology_title"] == "Onto A"
    assert all(e["type"] == "class" and e["version_id"] == seeded["v2"]
               for e in body["entities"])


@pytest.mark.anyio
async def test_related_k_limits(client, seeded):
    r = await client.get("/api/v1/entities/related",
                         params={"type": "class", "q": "x", "k": 2,
                                 "ontology": seeded["a"]})
    assert len(r.json()["entities"]) == 2


@pytest.mark.anyio
async def test_related_embed_failure_is_unavailable_200(client, seeded, monkeypatch):
    def boom(text):
        raise RuntimeError("embed backend down")
    monkeypatch.setattr(sem, "embed_query", boom)
    r = await client.get("/api/v1/entities/related", params={"type": "class", "q": "x"})
    assert r.status_code == 200
    assert r.json() == {"entities": [], "unavailable": True}


@pytest.mark.anyio
async def test_related_no_embeddings_not_unavailable(client, seeded):
    r = await client.get("/api/v1/entities/related",
                         params={"type": "individual", "q": "x", "ontology": seeded["a"]})
    assert r.status_code == 200
    assert r.json() == {"entities": [], "unavailable": False}


@pytest.mark.anyio
async def test_related_bad_type_422(client, seeded):
    r = await client.get("/api/v1/entities/related", params={"type": "bogus", "q": "x"})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_related_db_error_not_masked(client, seeded, monkeypatch):
    """A failure in the ranking query (after a successful embed) must not be
    reported as `unavailable`; it propagates."""
    def bad_select(*a, **kw):
        raise RuntimeError("db exploded")
    monkeypatch.setattr(sem, "select", bad_select)
    with pytest.raises(RuntimeError, match="db exploded"):
        await client.get("/api/v1/entities/related",
                         params={"type": "class", "q": "x"})
