"""API key scopes must actually restrict what a key can do.

Scopes were stored at creation and never read anywhere, so a key created with
["read"] — which is what the UI issued — carried its owner's full authority,
including deleting ontologies. The field promised least privilege the system did
not provide, which is worse than having no scopes at all.
"""

import hashlib
import uuid

import pytest

from ontoexplorer.models.db import ApiKey, Ontology, User


@pytest.fixture(autouse=True)
def _identity_is_real(monkeypatch):
    """A developer .env sets AUTH_BYPASS=true, under which every request is
    dev@localhost and no key is consulted — these assertions would pass while
    testing nothing."""
    from ontoexplorer.config import get_settings
    monkeypatch.setattr(get_settings(), "auth_bypass", False, raising=False)


async def _key_with_scopes(db, scopes: list[str]) -> tuple[User, str]:
    raw = f"oe_test_{uuid.uuid4().hex}"
    user = User(id=str(uuid.uuid4()), email=f"u-{uuid.uuid4()}@example.com", display_name="Keyholder")
    db.add(user)
    db.add(ApiKey(id=str(uuid.uuid4()), user_id=user.id, name="k",
                  key_hash=hashlib.sha256(raw.encode()).hexdigest(), scopes=scopes))
    await db.commit()
    return user, raw


async def _owned_ontology(db, owner: User) -> Ontology:
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                 shortname=f"o{uuid.uuid4().hex[:8]}", owner_id=owner.id)
    db.add(o)
    await db.commit()
    return o


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


@pytest.mark.anyio
async def test_read_key_cannot_delete_its_owners_ontology(client, db_session):
    """The exact shape that made the scope field a false promise: the key's own
    user is allowed to delete, so only the scope stands between them."""
    owner, key = await _key_with_scopes(db_session, ["read"])
    ontology = await _owned_ontology(db_session, owner)

    r = await client.delete(f"/api/v1/ontologies/{ontology.id}", headers=_auth(key))
    assert r.status_code == 403
    assert "read-only" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_write_key_is_not_blocked_by_the_scope_check(client, db_session, monkeypatch):
    owner, key = await _key_with_scopes(db_session, ["read", "write"])
    ontology = await _owned_ontology(db_session, owner)

    from ontoexplorer.modules.jobs import tasks
    monkeypatch.setattr(tasks.purge_version_artifacts, "delay", lambda *a, **k: None, raising=False)

    r = await client.delete(f"/api/v1/ontologies/{ontology.id}", headers=_auth(key))
    assert r.status_code == 204


@pytest.mark.anyio
async def test_read_key_can_still_read(client, db_session):
    """Enforcement must not break the thing read keys are for."""
    _owner, key = await _key_with_scopes(db_session, ["read"])
    r = await client.get("/api/v1/ontologies?limit=1", headers=_auth(key))
    assert r.status_code == 200


@pytest.mark.anyio
async def test_key_with_no_scopes_recorded_fails_closed(client, db_session):
    """An absent grant is not a grant."""
    owner, key = await _key_with_scopes(db_session, [])
    ontology = await _owned_ontology(db_session, owner)

    r = await client.delete(f"/api/v1/ontologies/{ontology.id}", headers=_auth(key))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_admin_scope_also_permits_writes(client, db_session, monkeypatch):
    owner, key = await _key_with_scopes(db_session, ["admin"])
    ontology = await _owned_ontology(db_session, owner)

    from ontoexplorer.modules.jobs import tasks
    monkeypatch.setattr(tasks.purge_version_artifacts, "delay", lambda *a, **k: None, raising=False)

    r = await client.delete(f"/api/v1/ontologies/{ontology.id}", headers=_auth(key))
    assert r.status_code == 204
