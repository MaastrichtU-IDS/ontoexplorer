"""Owner self-serve re-evaluation of a held version (#364 Add-Ontology flow):
assert a license / fix title, re-run the gate, publish if it passes."""
import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import Ontology, OntologyVersion


async def _held(db, owner_id, *, title="T", triples=10, content_license=None):
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}", title=title, owner_id=owner_id)
    db.add(o)
    v = OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k",
        sha256=uuid.uuid4().hex, format="turtle", status="needs_review",
        triple_count=triples,
    )
    db.add(v)
    await db.commit()
    return o, v


@pytest.fixture()
def _no_content_license(monkeypatch):
    # The content declares no license (the common held case).
    monkeypatch.setattr(
        "ontoexplorer.modules.metadata.dcat.extract_ontology_annotations",
        lambda oid, vid, iri: {},
    )


def _hdr(raw_key):
    return {"Authorization": f"Bearer {raw_key}"}


@pytest.mark.anyio
async def test_declare_license_publishes(client, user_and_key, db_session, _no_content_license):
    user, raw = user_and_key
    o, v = await _held(db_session, user.id)
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reevaluate",
                          json={"declared_license": "CC-BY-4.0"}, headers=_hdr(raw))
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
    assert r.json()["review_reasons"] == []
    row = (await db_session.execute(select(OntologyVersion).where(OntologyVersion.id == v.id))).scalar_one()
    assert row.status == "ready"
    assert row.declared_license == "CC-BY-4.0"
    assert row.declared_by == user.id
    assert row.license_compliant is True


@pytest.mark.anyio
async def test_noncompliant_declared_license_422(client, user_and_key, db_session, _no_content_license):
    user, raw = user_and_key
    o, v = await _held(db_session, user.id)
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reevaluate",
                          json={"declared_license": "CC-BY-NC-4.0"}, headers=_hdr(raw))
    assert r.status_code == 422
    row = (await db_session.execute(select(OntologyVersion).where(OntologyVersion.id == v.id))).scalar_one()
    assert row.status == "needs_review"  # untouched


@pytest.mark.anyio
async def test_still_held_when_title_missing(client, user_and_key, db_session, _no_content_license):
    user, raw = user_and_key
    o, v = await _held(db_session, user.id, title=None)  # no title → still held
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reevaluate",
                          json={"declared_license": "MIT"}, headers=_hdr(raw))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "needs_review"
    assert any("title" in reason for reason in body["review_reasons"])
    # License was still recorded even though it didn't publish.
    row = (await db_session.execute(select(OntologyVersion).where(OntologyVersion.id == v.id))).scalar_one()
    assert row.declared_license == "MIT"


@pytest.mark.anyio
async def test_content_noncompliant_cannot_be_laundered(client, user_and_key, db_session, monkeypatch):
    # Content DECLARES an NC license → a declared compliant one must not rescue it.
    monkeypatch.setattr(
        "ontoexplorer.modules.metadata.dcat.extract_ontology_annotations",
        lambda oid, vid, iri: {"license": "http://creativecommons.org/licenses/by-nc/4.0/"},
    )
    user, raw = user_and_key
    o, v = await _held(db_session, user.id)
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reevaluate",
                          json={"declared_license": "CC-BY-4.0"}, headers=_hdr(raw))
    assert r.status_code == 200
    assert r.json()["status"] == "needs_review"
    assert any("license" in reason for reason in r.json()["review_reasons"])


@pytest.mark.anyio
async def test_non_held_is_409(client, user_and_key, db_session, _no_content_license):
    user, raw = user_and_key
    o, v = await _held(db_session, user.id)
    v.status = "ready"
    await db_session.commit()
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reevaluate",
                          json={}, headers=_hdr(raw))
    assert r.status_code == 409


@pytest.mark.anyio
async def test_non_owner_403(client, user_and_key, db_session, _no_content_license):
    _, raw = user_and_key
    o, v = await _held(db_session, owner_id=str(uuid.uuid4()))  # someone else owns it
    r = await client.post(f"/api/v1/ontologies/{o.id}/{v.id}/reevaluate",
                          json={"declared_license": "MIT"}, headers=_hdr(raw))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_compliant_licenses_endpoint(client):
    r = await client.get("/api/v1/ontologies/compliant-licenses")
    assert r.status_code == 200
    spdx = {x["spdx"] for x in r.json()["licenses"]}
    assert "CC-BY-4.0" in spdx and "MIT" in spdx
    assert "CC-BY-NC-4.0" not in spdx
