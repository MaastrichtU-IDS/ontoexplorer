"""Admin review surface for the #364 quality gate: publish a held version."""
import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import Ontology, OntologyVersion


async def _held_version(db, *, status="needs_review") -> tuple[Ontology, OntologyVersion]:
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}", title="T")
    db.add(o)
    v = OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k",
        sha256=uuid.uuid4().hex, format="turtle", status=status, triple_count=10,
    )
    db.add(v)
    await db.commit()
    return o, v


@pytest.mark.anyio
async def test_publish_requires_admin(client, user_and_key, db_session):
    _, v = await _held_version(db_session)
    _, raw_key = user_and_key
    r = await client.post(f"/api/v1/admin/versions/{v.id}/publish",
                          headers={"Authorization": f"Bearer {raw_key}"})
    assert r.status_code == 403  # authenticated but not admin


@pytest.mark.anyio
async def test_publish_held_version_becomes_ready(client, user_and_key, db_session, monkeypatch):
    monkeypatch.setattr("ontoexplorer.api.admin._common.is_admin", lambda u: True)
    _, v = await _held_version(db_session)
    _, raw_key = user_and_key

    r = await client.post(f"/api/v1/admin/versions/{v.id}/publish",
                          headers={"Authorization": f"Bearer {raw_key}"})
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "version_id": v.id}

    row = (await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.id == v.id))).scalar_one()
    assert row.status == "ready"


@pytest.mark.anyio
async def test_publish_non_held_is_409(client, user_and_key, db_session, monkeypatch):
    monkeypatch.setattr("ontoexplorer.api.admin._common.is_admin", lambda u: True)
    _, v = await _held_version(db_session, status="ready")
    _, raw_key = user_and_key

    r = await client.post(f"/api/v1/admin/versions/{v.id}/publish",
                          headers={"Authorization": f"Bearer {raw_key}"})
    assert r.status_code == 409
    row = (await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.id == v.id))).scalar_one()
    assert row.status == "ready"  # unchanged
