"""Integration tests for the cross-repository entity listing endpoint."""
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion, EntityIndex

pytestmark = pytest.mark.anyio


async def _seed(db_session):
    # The test-session in-memory DB persists across tests (see tests/integration/
    # conftest.py's session-scoped `engine`), so clear any leftovers from a
    # previous test's call to _seed before re-inserting the same fixed ids.
    from sqlalchemy import delete

    await db_session.execute(delete(EntityIndex).where(EntityIndex.ontology_id == "o1"))
    await db_session.execute(delete(OntologyVersion).where(OntologyVersion.ontology_id == "o1"))
    await db_session.execute(delete(Ontology).where(Ontology.id == "o1"))
    await db_session.commit()

    ont = Ontology(id="o1", iri="http://ex.org/onto", shortname="onto")
    db_session.add(ont)
    ready = OntologyVersion(
        id="v-ready", ontology_id="o1", minio_key="k1",
        sha256="sha-ready", format="owl", status="ready",
    )
    dep = OntologyVersion(
        id="v-dep", ontology_id="o1", minio_key="k2",
        sha256="sha-dep", format="owl", status="deprecated",
    )
    db_session.add_all([ready, dep])

    def _ei(vid, iri, etype, label):
        return EntityIndex(
            version_id=vid, iri=iri, ontology_id="o1", type=etype,
            primary_label=label, primary_label_norm=label.lower(),
            short=iri.split("/")[-1], source="onto", search_text=label.lower(),
        )

    db_session.add_all([
        _ei("v-ready", "http://ex.org/Cell", "class", "cell"),
        _ei("v-ready", "http://ex.org/Apoptosis", "class", "apoptosis"),
        _ei("v-ready", "http://ex.org/Nucleus", "class", "nucleus"),
        _ei("v-ready", "http://ex.org/hasPart", "object_property", "has part"),
        # under a deprecated version - must be excluded
        _ei("v-dep", "http://ex.org/Ghost", "class", "ghost"),
    ])
    await db_session.commit()


async def test_lists_classes_excluding_deprecated_versions(client, db_session):
    await _seed(db_session)
    resp = await client.get("/api/v1/entities?type=class")
    assert resp.status_code == 200
    body = resp.json()
    assert body["approx_total"] == 3  # ghost (deprecated version) excluded
    labels = [e["label"] for e in body["entities"]]
    assert labels == ["apoptosis", "cell", "nucleus"]  # alphabetical by norm
    assert body["next"] is None  # only 3 rows, default limit 50
    assert body["entities"][0]["ontology_id"] == "o1"
    assert body["entities"][0]["type"] == "class"


async def test_filters_by_type(client, db_session):
    await _seed(db_session)
    body = (await client.get("/api/v1/entities?type=object_property")).json()
    assert body["approx_total"] == 1
    assert body["entities"][0]["label"] == "has part"


async def test_keyset_pagination(client, db_session):
    await _seed(db_session)
    page1 = (await client.get("/api/v1/entities?type=class&limit=2")).json()
    assert [e["label"] for e in page1["entities"]] == ["apoptosis", "cell"]
    assert page1["next"] is not None
    page2 = (await client.get(f"/api/v1/entities?type=class&limit=2&cursor={page1['next']}")).json()
    assert [e["label"] for e in page2["entities"]] == ["nucleus"]
    assert page2["next"] is None  # last page


async def test_unknown_type_is_rejected(client, db_session):
    await _seed(db_session)
    assert (await client.get("/api/v1/entities?type=bogus")).status_code == 422


async def test_bad_cursor_is_rejected(client, db_session):
    await _seed(db_session)
    assert (await client.get("/api/v1/entities?type=class&cursor=not-base64!!")).status_code == 422
