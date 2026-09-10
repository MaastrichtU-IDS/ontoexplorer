"""Integration tests for the cross-repository entity listing endpoint."""
import pytest
from sqlalchemy import delete

from ontoexplorer.models.db import Ontology, OntologyVersion, EntityIndex
from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache

pytestmark = pytest.mark.anyio


# Every ontology id this file seeds. The test engine is a session-scoped
# in-memory SQLite DB (tests/conftest.py), so rows persist across tests and
# `approx_total` is a global COUNT — we must clear ALL of our ids before each
# test, not just the one being seeded, or leftover rows inflate the counts.
_ALL_IDS = ["o1", "multi", "oa", "ob"]


async def _reset(db_session):
    """Clear every ontology this file uses, and drop the process-wide
    latest-ready-versions cache so freshly-seeded versions are visible
    (see modules/search/versions.py)."""
    await db_session.execute(delete(EntityIndex).where(EntityIndex.ontology_id.in_(_ALL_IDS)))
    await db_session.execute(delete(OntologyVersion).where(OntologyVersion.ontology_id.in_(_ALL_IDS)))
    await db_session.execute(delete(Ontology).where(Ontology.id.in_(_ALL_IDS)))
    await db_session.commit()
    invalidate_latest_ready_versions_cache()


def _ei(vid, oid, iri, etype, label):
    return EntityIndex(
        version_id=vid, iri=iri, ontology_id=oid, type=etype,
        primary_label=label, primary_label_norm=label.lower(),
        short=iri.split("/")[-1], source="onto", search_text=label.lower(),
    )


async def _seed_basic(db_session):
    """One ontology, one ready + one deprecated version. Classes live under the
    ready version; a 'ghost' class lives under the deprecated one (excluded)."""
    await _reset(db_session)
    db_session.add(Ontology(id="o1", iri="http://ex.org/onto", shortname="onto"))
    db_session.add_all([
        OntologyVersion(id="v-ready", ontology_id="o1", minio_key="k1", sha256="sha-ready",
                        format="owl", status="ready", version_iri="onto-1.0.0"),
        OntologyVersion(id="v-dep", ontology_id="o1", minio_key="k2", sha256="sha-dep",
                        format="owl", status="deprecated", version_iri="onto-0.9.0"),
    ])
    db_session.add_all([
        _ei("v-ready", "o1", "http://ex.org/Cell", "class", "cell"),
        _ei("v-ready", "o1", "http://ex.org/Apoptosis", "class", "apoptosis"),
        _ei("v-ready", "o1", "http://ex.org/Nucleus", "class", "nucleus"),
        _ei("v-ready", "o1", "http://ex.org/hasPart", "object_property", "has part"),
        _ei("v-dep", "o1", "http://ex.org/Ghost", "class", "ghost"),
    ])
    await db_session.commit()
    invalidate_latest_ready_versions_cache()


async def test_lists_classes_from_default_version_only(client, db_session):
    await _seed_basic(db_session)
    body = (await client.get("/api/v1/entities?type=class")).json()
    assert body["approx_total"] == 3  # ghost (deprecated version) excluded
    assert [e["label"] for e in body["entities"]] == ["apoptosis", "cell", "nucleus"]
    assert body["next"] is None
    assert body["entities"][0]["ontologies"] == [{"ontology_id": "o1", "version_id": "v-ready"}]


async def test_filters_by_type(client, db_session):
    await _seed_basic(db_session)
    body = (await client.get("/api/v1/entities?type=object_property")).json()
    assert body["approx_total"] == 1
    assert body["entities"][0]["label"] == "has part"


async def test_keyset_pagination(client, db_session):
    await _seed_basic(db_session)
    page1 = (await client.get("/api/v1/entities?type=class&limit=2")).json()
    assert [e["label"] for e in page1["entities"]] == ["apoptosis", "cell"]
    assert page1["next"] is not None
    page2 = (await client.get(f"/api/v1/entities?type=class&limit=2&cursor={page1['next']}")).json()
    assert [e["label"] for e in page2["entities"]] == ["nucleus"]
    assert page2["next"] is None


async def test_same_ontology_multiple_versions_are_deduped(client, db_session):
    """The bug that motivated default-version scoping: an ontology with several
    ready versions must NOT list the same IRI once per version."""
    await _reset(db_session)
    db_session.add(Ontology(id="multi", iri="http://ex.org/multi", shortname="multi"))
    db_session.add_all([
        OntologyVersion(id="mv1", ontology_id="multi", minio_key="m1", sha256="m-sha1",
                        format="owl", status="ready", version_iri="multi-1.0.0"),
        OntologyVersion(id="mv2", ontology_id="multi", minio_key="m2", sha256="m-sha2",
                        format="owl", status="ready", version_iri="multi-2.0.0"),
    ])
    db_session.add_all([
        _ei("mv1", "multi", "http://ex.org/Foo", "class", "foo"),
        _ei("mv2", "multi", "http://ex.org/Foo", "class", "foo"),
    ])
    await db_session.commit()
    invalidate_latest_ready_versions_cache()

    body = (await client.get("/api/v1/entities?type=class")).json()
    foos = [e for e in body["entities"] if e["iri"] == "http://ex.org/Foo"]
    assert len(foos) == 1  # once, not once-per-version
    assert body["approx_total"] == 1
    assert foos[0]["ontologies"] == [{"ontology_id": "multi", "version_id": "mv2"}]  # version-aware default (2.0.0)


async def test_collapse_aggregates_ontologies(client, db_session):
    """Same IRI reused across two ontologies: expanded => 2 rows; collapsed => 1
    row whose `ontologies` lists both."""
    await _reset(db_session)
    db_session.add_all([
        Ontology(id="oa", iri="http://ex.org/oa", shortname="oa"),
        Ontology(id="ob", iri="http://ex.org/ob", shortname="ob"),
    ])
    db_session.add_all([
        OntologyVersion(id="va", ontology_id="oa", minio_key="a", sha256="a-sha",
                        format="owl", status="ready", version_iri="oa-1.0.0"),
        OntologyVersion(id="vb", ontology_id="ob", minio_key="b", sha256="b-sha",
                        format="owl", status="ready", version_iri="ob-1.0.0"),
    ])
    db_session.add_all([
        _ei("va", "oa", "http://shared/Term", "class", "shared term"),
        _ei("vb", "ob", "http://shared/Term", "class", "shared term"),
    ])
    await db_session.commit()
    invalidate_latest_ready_versions_cache()

    expanded = (await client.get("/api/v1/entities?type=class")).json()
    assert len([e for e in expanded["entities"] if e["iri"] == "http://shared/Term"]) == 2
    assert expanded["approx_total"] == 2

    collapsed = (await client.get("/api/v1/entities?type=class&collapse=true")).json()
    rows = [e for e in collapsed["entities"] if e["iri"] == "http://shared/Term"]
    assert len(rows) == 1
    assert collapsed["approx_total"] == 1
    assert {o["ontology_id"] for o in rows[0]["ontologies"]} == {"oa", "ob"}


async def test_search_q_delegates_to_pg_entity_search(client, db_session, monkeypatch):
    """A non-empty `q` runs the ranked exact/prefix/fuzzy search and returns the
    hits in the /entities entity shape (single page, next=None)."""
    async def _fake_search(db, q, limit, types=None):
        assert q == "cell" and types == ["class"]
        return [{
            "iri": "http://ex.org/Cell", "label": "cell", "short": "Cell", "type": "class",
            "version_id": "v-ready", "ontology_id": "o1", "source": "onto",
        }]
    monkeypatch.setattr("ontoexplorer.api.entities.pg_entity_search", _fake_search)

    body = (await client.get("/api/v1/entities?type=class&q=cell")).json()
    assert body["next"] is None
    assert body["query"] == "cell"
    assert body["entities"][0]["iri"] == "http://ex.org/Cell"
    assert body["entities"][0]["ontologies"] == [{"ontology_id": "o1", "version_id": "v-ready"}]


async def test_unknown_type_is_rejected(client, db_session):
    assert (await client.get("/api/v1/entities?type=bogus")).status_code == 422


async def test_bad_cursor_is_rejected(client, db_session):
    assert (await client.get("/api/v1/entities?type=class&cursor=not-base64!!")).status_code == 422
