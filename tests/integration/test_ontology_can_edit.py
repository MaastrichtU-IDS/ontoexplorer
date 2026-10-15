"""GET /ontologies/{id} exposes a per-viewer `can_edit` flag so the SPA can show
maintainer-only affordances (the OWL-profile full-report command)."""
import uuid

import pytest

from ontoexplorer.models.db import Ontology


async def _seed(db_session, owner_id=None) -> str:
    oid = str(uuid.uuid4())
    db_session.add(Ontology(
        id=oid, iri=f"http://ex/{uuid.uuid4()}",
        shortname=f"o{uuid.uuid4().hex[:8]}", owner_id=owner_id,
    ))
    await db_session.commit()
    return oid


@pytest.mark.anyio
async def test_owner_sees_can_edit_true(client, db_session, user_and_key):
    owner, key = user_and_key
    oid = await _seed(db_session, owner_id=owner.id)
    resp = await client.get(f"/api/v1/ontologies/{oid}",
                            headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 200
    assert resp.json()["can_edit"] is True


@pytest.mark.anyio
async def test_anonymous_sees_can_edit_false(client, db_session, user_and_key):
    owner, _key = user_and_key
    oid = await _seed(db_session, owner_id=owner.id)
    resp = await client.get(f"/api/v1/ontologies/{oid}")  # no auth header
    assert resp.status_code == 200
    assert resp.json()["can_edit"] is False
