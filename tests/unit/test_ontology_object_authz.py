"""Object-level authorization on destructive ontology endpoints.

These endpoints authenticated the caller but never checked that the caller owned
the thing they were acting on, so any account that could log in could delete any
ontology in the catalogue. Authentication is not authorization; each test below
asserts a *stranger* is refused, and the owner is not.
"""

import hashlib
import uuid

import pytest

from ontoexplorer.models.db import ApiKey, Ontology, OntologyVersion, User


async def _user_with_key(db) -> tuple[User, str]:
    raw = f"oe_test_{uuid.uuid4().hex}"
    user = User(id=str(uuid.uuid4()), email=f"u-{uuid.uuid4()}@example.com", display_name="Stranger")
    db.add(user)
    db.add(ApiKey(id=str(uuid.uuid4()), user_id=user.id, name="k",
                  key_hash=hashlib.sha256(raw.encode()).hexdigest(), scopes=["read"]))
    await db.commit()
    return user, raw


async def _owned_ontology(db, owner: User) -> tuple[Ontology, OntologyVersion]:
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                 shortname=f"o{uuid.uuid4().hex[:8]}", owner_id=owner.id)
    db.add(o)
    await db.commit()
    v = OntologyVersion(id=str(uuid.uuid4()), ontology_id=o.id, minio_key=f"{o.id}/v/x.ttl",
                        sha256=uuid.uuid4().hex, format="ttl", status="ready")
    db.add(v)
    await db.commit()
    return o, v


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture(autouse=True)
def _identity_is_real(monkeypatch):
    """Resolve the caller from their key, not from AUTH_BYPASS.

    A developer .env with AUTH_BYPASS=true makes every request dev@localhost, so
    without this the refusal assertions below pass for the wrong reason — the
    bypass user owns nothing — and the owner case fails. CI has no .env and so
    would never show it.
    """
    from ontoexplorer.config import get_settings
    monkeypatch.setattr(get_settings(), "auth_bypass", False, raising=False)


@pytest.mark.anyio
async def test_stranger_cannot_delete_someone_elses_ontology(client, db_session, user_and_key):
    owner, _ = user_and_key
    ontology, _v = await _owned_ontology(db_session, owner)
    _stranger, stranger_key = await _user_with_key(db_session)

    r = await client.delete(f"/api/v1/ontologies/{ontology.id}", headers=_auth(stranger_key))
    assert r.status_code == 403, f"a stranger deleted another user's ontology ({r.status_code})"


@pytest.mark.anyio
async def test_owner_can_delete_their_own_ontology(client, db_session, user_and_key):
    owner, owner_key = user_and_key
    ontology, _v = await _owned_ontology(db_session, owner)

    r = await client.delete(f"/api/v1/ontologies/{ontology.id}", headers=_auth(owner_key))
    assert r.status_code == 204


@pytest.mark.anyio
async def test_stranger_cannot_deprecate_someone_elses_version(client, db_session, user_and_key):
    owner, _ = user_and_key
    ontology, version = await _owned_ontology(db_session, owner)
    _stranger, stranger_key = await _user_with_key(db_session)

    r = await client.delete(f"/api/v1/ontologies/{ontology.id}/{version.id}",
                            headers=_auth(stranger_key))
    assert r.status_code == 403, f"a stranger deprecated another user's version ({r.status_code})"


@pytest.mark.anyio
async def test_stranger_cannot_rewrite_someone_elses_annotation_profile(client, db_session, user_and_key):
    owner, _ = user_and_key
    ontology, version = await _owned_ontology(db_session, owner)
    _stranger, stranger_key = await _user_with_key(db_session)

    r = await client.patch(f"/api/v1/ontologies/{ontology.id}/{version.id}/profile",
                           json={"label_props": ["http://evil/label"]},
                           headers=_auth(stranger_key))
    assert r.status_code == 403, f"a stranger rewrote another user's profile ({r.status_code})"


@pytest.mark.anyio
async def test_stranger_cannot_trigger_detection_on_someone_elses_version(client, db_session, user_and_key):
    owner, _ = user_and_key
    ontology, version = await _owned_ontology(db_session, owner)
    _stranger, stranger_key = await _user_with_key(db_session)

    r = await client.post(f"/api/v1/ontologies/{ontology.id}/{version.id}/profile/detect",
                          headers=_auth(stranger_key))
    assert r.status_code == 403, f"a stranger triggered detection on another user's version ({r.status_code})"
