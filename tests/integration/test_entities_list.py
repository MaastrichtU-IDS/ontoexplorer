"""Integration tests for GET /api/v1/entities (cross-repo browse listing)."""
import uuid

import pytest

from ontoexplorer.models.db import EntityIndex, Ontology, OntologyVersion
from ontoexplorer.modules.search.indexer import normalise_label
from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache


def _ent(vid, oid, iri, label, etype="class", definitions=None):
    return EntityIndex(
        version_id=vid, iri=iri, ontology_id=oid, type=etype, primary_label=label,
        primary_label_norm=normalise_label(label), short=iri.rsplit("/", 1)[-1],
        source="src", search_text=label, definitions=definitions or [],
    )


@pytest.fixture()
async def seeded(db_session):
    """Ontology A: v1 (superseded) + v2 (latest, ready). Ontology B: one ready version."""
    tag = uuid.uuid4().hex[:8]
    a, b = f"oa-{tag}", f"ob-{tag}"
    db_session.add_all([
        Ontology(id=a, iri=f"http://ex.org/{tag}/a", shortname=f"a{tag}", title="Onto A"),
        Ontology(id=b, iri=f"http://ex.org/{tag}/b", shortname=f"b{tag}", title="Onto B"),
    ])
    await db_session.flush()
    v1, v2, v3 = f"a1-{tag}", f"a2-{tag}", f"b1-{tag}"
    for vid, oid, vi in ((v1, a, "1.0.0"), (v2, a, "2.0.0"), (v3, b, "1.0.0")):
        db_session.add(OntologyVersion(
            id=vid, ontology_id=oid, version_iri=f"http://ex.org/{tag}/{oid}/{vi}",
            minio_key=f"k/{vid}", sha256=f"sha-{vid}", format="owl", status="ready"))
    await db_session.flush()
    p = f"zq{tag}"  # unique label prefix
    db_session.add_all([
        _ent(v1, a, f"http://ex.org/{tag}/old", f"{p} stale", ),
        _ent(v2, a, f"http://ex.org/{tag}/c1", f"{p} alpha",
             definitions=[{"value": "  An alpha thing.  ", "lang": "en"}]),
        _ent(v2, a, f"http://ex.org/{tag}/c2", f"{p} bravo"),
        _ent(v2, a, f"http://ex.org/{tag}/pun", f"{p} punned"),
        _ent(v2, a, f"http://ex.org/{tag}/ind1", f"{p} punned", etype="individual"),
        _ent(v3, b, f"http://ex.org/{tag}/c3", f"{p} charlie"),
        _ent(v3, b, f"http://ex.org/{tag}/c4", f"{p} delta"),
        _ent(v3, b, f"http://ex.org/{tag}/op", f"{p} has part", etype="object_property"),
    ])
    await db_session.commit()
    invalidate_latest_ready_versions_cache()
    yield {"a": a, "b": b, "v1": v1, "v2": v2, "v3": v3, "p": p, "tag": tag}
    invalidate_latest_ready_versions_cache()


def _params(s, **kw):
    return {"type": "class", "ontology": [s["a"], s["b"]], **kw}


@pytest.mark.anyio
async def test_browse_ordered_and_latest_only(client, seeded):
    r = await client.get("/api/v1/entities", params=_params(seeded))
    assert r.status_code == 200
    body = r.json()
    labels = [e["primary_label"] for e in body["entities"]]
    p = seeded["p"]
    assert labels == [f"{p} {x}" for x in ("alpha", "bravo", "charlie", "delta", "punned")]
    assert all(e["version_id"] != seeded["v1"] for e in body["entities"])
    assert body["next"] is None and body["limit"] == 50
    e0 = body["entities"][0]
    assert e0["ontology_title"] == "Onto A" and e0["source"] == "src"
    assert set(e0) == {"iri", "primary_label", "short", "type", "ontology_id",
                       "ontology_title", "ontology_shortname", "version_id", "source", "definition"}


@pytest.mark.anyio
async def test_pagination_no_overlap_no_gap(client, seeded):
    r1 = (await client.get("/api/v1/entities", params=_params(seeded, limit=2))).json()
    assert len(r1["entities"]) == 2 and r1["next"]
    r2 = (await client.get("/api/v1/entities",
                           params=_params(seeded, limit=2, cursor=r1["next"]))).json()
    r3 = (await client.get("/api/v1/entities",
                           params=_params(seeded, limit=2, cursor=r2["next"]))).json()
    assert r3["next"] is None
    got = [e["primary_label"] for r in (r1, r2, r3) for e in r["entities"]]
    p = seeded["p"]
    assert got == [f"{p} {x}" for x in ("alpha", "bravo", "charlie", "delta", "punned")]


@pytest.mark.anyio
async def test_bad_type_and_cursor_422(client, seeded):
    assert (await client.get("/api/v1/entities", params={"type": "bogus"})).status_code == 422
    for bad in ("!!!notbase64", "e30=", "bm90LWpzb24="):
        r = await client.get("/api/v1/entities", params=_params(seeded, cursor=bad))
        assert r.status_code == 422, bad


@pytest.mark.anyio
async def test_unknown_ontology_empty(client, seeded):
    r = await client.get("/api/v1/entities",
                         params={"type": "class", "ontology": ["nope-id"]})
    assert r.status_code == 200
    assert r.json()["entities"] == [] and r.json()["next"] is None


@pytest.mark.anyio
async def test_punned_class_vs_individual(client, seeded):
    cls = (await client.get("/api/v1/entities", params=_params(seeded))).json()["entities"]
    ind = (await client.get("/api/v1/entities",
                            params=_params(seeded, type="individual"))).json()["entities"]
    assert any(e["iri"].endswith("/pun") for e in cls)
    assert not any(e["iri"].endswith("/pun") for e in ind)
    assert [e["iri"].rsplit("/", 1)[-1] for e in ind] == ["ind1"]


@pytest.mark.anyio
async def test_definition_trimmed_and_empty(client, seeded):
    ents = (await client.get("/api/v1/entities", params=_params(seeded))).json()["entities"]
    assert ents[0]["definition"] == "An alpha thing."
    assert ents[1]["definition"] == ""


@pytest.mark.anyio
async def test_q_delegates_to_pg_entity_search(client, seeded, monkeypatch):
    from ontoexplorer.api import entities as mod
    p, tag = seeded["p"], seeded["tag"]
    calls = {}

    async def fake(db, q, limit, types=None, version_id=None, ontology_ids=None,
                   version_ids=None):
        calls.update(q=q, limit=limit, types=types, ontology_ids=ontology_ids,
                     version_ids=version_ids)
        hits = [{"iri": f"http://ex.org/{tag}/c1", "label": f"{p} alpha", "short": "c1",
                 "type": "class", "version_id": seeded["v2"], "ontology_id": seeded["a"],
                 "source": "src", "ontology_shortname": "x"},
                {"iri": f"http://ex.org/{tag}/old", "label": "stale", "short": "old",
                 "type": "class", "version_id": seeded["v1"], "ontology_id": seeded["a"],
                 "source": "", "ontology_shortname": "x"}]
        return [h for h in hits if h["version_id"] in set(version_ids or [])]  # scoping is in-query
    monkeypatch.setattr(mod, "pg_entity_search", fake)
    r = await client.get("/api/v1/entities", params=_params(seeded, q="alpha"))
    assert r.status_code == 200
    body = r.json()
    assert calls["types"] == ["class"] and calls["q"] == "alpha"
    assert seeded["v2"] in calls["version_ids"] and seeded["v1"] not in calls["version_ids"]
    assert [e["primary_label"] for e in body["entities"]] == [f"{p} alpha"]  # superseded dropped
    assert body["entities"][0]["definition"] == "An alpha thing."
    assert body["entities"][0]["ontology_title"] == "Onto A"
    assert body["next"] is None
    assert body["approx_total"] == len(body["entities"]) == 1  # q mode: hit count


@pytest.mark.usefixtures("requires_postgres")
@pytest.mark.anyio
async def test_q_real_search(client, seeded):
    r = await client.get("/api/v1/entities", params=_params(seeded, q=f"{seeded['p']} bra"))
    assert r.status_code == 200
    assert [e["primary_label"] for e in r.json()["entities"]] == [f"{seeded['p']} bravo"]
    assert r.json()["next"] is None


@pytest.mark.usefixtures("requires_postgres")
@pytest.mark.anyio
async def test_q_keeps_latest_ready_hit_when_superseded_shares_iri(client, seeded, db_session):
    """Same IRI in superseded v1 and latest v2: v2 hit must not be dedup-shadowed."""
    tag, p = seeded["tag"], seeded["p"]
    db_session.add(_ent(seeded["v1"], seeded["a"], f"http://ex.org/{tag}/c2", f"{p} bravo"))
    await db_session.commit()
    r = await client.get("/api/v1/entities", params=_params(seeded, q=f"{p} bravo"))
    assert r.status_code == 200
    ents = r.json()["entities"]
    assert [(e["primary_label"], e["version_id"]) for e in ents] == [(f"{p} bravo", seeded["v2"])]


@pytest.mark.anyio
async def test_approx_total_unfiltered_uses_public_stats(client, seeded, monkeypatch):
    from ontoexplorer.api import entities as mod

    async def fake_stats(db):
        return {"total_classes": 12345, "total_individuals": 77}
    monkeypatch.setattr(mod, "read_public_stats", fake_stats)
    r = await client.get("/api/v1/entities", params={"type": "class", "limit": 1})
    assert r.json()["approx_total"] == 12345
    r = await client.get("/api/v1/entities", params={"type": "individual", "limit": 1})
    assert r.json()["approx_total"] == 77
