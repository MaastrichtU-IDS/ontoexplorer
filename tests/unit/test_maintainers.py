"""Maintainer-role request workflow: user requests + admin approve/deny."""

import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import MaintainerRequest, Ontology, OntologyMaintainer, User


async def _make_ontology(db) -> Ontology:
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}")
    db.add(o)
    await db.commit()
    return o


async def _make_user(db) -> User:
    u = User(id=str(uuid.uuid4()), email=f"req-{uuid.uuid4()}@example.com", display_name="Requester")
    db.add(u)
    await db.commit()
    return u


@pytest.fixture()
def _as_admin(monkeypatch):
    monkeypatch.setattr("ontoexplorer.modules.auth.dependencies.is_admin", lambda user: True)


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ── User-facing ────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_request_uploader(client, user_and_key):
    _, key = user_and_key
    r = await client.post("/api/v1/maintainer-requests",
                          json={"request_type": "uploader", "note": "I curate several OBO ontologies"},
                          headers=_auth(key))
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "pending"
    assert b["request_type"] == "uploader"
    assert b["note"].startswith("I curate")


@pytest.mark.anyio
async def test_request_ontology(client, user_and_key, db_session):
    onto = await _make_ontology(db_session)
    _, key = user_and_key
    r = await client.post("/api/v1/maintainer-requests",
                          json={"request_type": "ontology", "ontology_id": onto.id, "note": "I authored it"},
                          headers=_auth(key))
    assert r.status_code == 200
    assert r.json()["ontology_id"] == onto.id


@pytest.mark.anyio
async def test_request_ontology_missing_404(client, user_and_key):
    _, key = user_and_key
    r = await client.post("/api/v1/maintainer-requests",
                          json={"request_type": "ontology", "ontology_id": "does-not-exist", "note": "x"},
                          headers=_auth(key))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_request_unknown_type_422(client, user_and_key):
    _, key = user_and_key
    r = await client.post("/api/v1/maintainer-requests", json={"request_type": "boss"}, headers=_auth(key))
    assert r.status_code == 422


@pytest.mark.anyio
async def test_request_duplicate_pending_409(client, user_and_key):
    _, key = user_and_key
    a = await client.post("/api/v1/maintainer-requests", json={"request_type": "uploader"}, headers=_auth(key))
    assert a.status_code == 200
    b = await client.post("/api/v1/maintainer-requests", json={"request_type": "uploader"}, headers=_auth(key))
    assert b.status_code == 409


@pytest.mark.anyio
async def test_request_requires_auth(client):
    r = await client.post("/api/v1/maintainer-requests", json={"request_type": "uploader"})
    assert r.status_code == 401


@pytest.mark.anyio
async def test_my_requests_lists_own(client, user_and_key):
    _, key = user_and_key
    await client.post("/api/v1/maintainer-requests", json={"request_type": "uploader"}, headers=_auth(key))
    r = await client.get("/api/v1/maintainer-requests", headers=_auth(key))
    assert r.status_code == 200
    assert len(r.json()["requests"]) >= 1


# ── Admin review ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_admin_list_forbidden_for_non_admin(client, user_and_key):
    _, key = user_and_key
    r = await client.get("/api/v1/admin/maintainer-requests", headers=_auth(key))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_admin_approve_uploader_grants_is_uploader(client, user_and_key, db_session, _as_admin):
    _, key = user_and_key
    requester = await _make_user(db_session)
    req = MaintainerRequest(user_id=requester.id, request_type="uploader", note="please")
    db_session.add(req)
    await db_session.commit()

    r = await client.post(f"/api/v1/admin/maintainer-requests/{req.id}/approve",
                          json={"note": "trusted contributor"}, headers=_auth(key))
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["decision_note"] == "trusted contributor"

    u = (await db_session.execute(select(User).where(User.id == requester.id))).scalar_one()
    assert u.is_uploader is True


@pytest.mark.anyio
async def test_admin_approve_ontology_creates_maintainer(client, user_and_key, db_session, _as_admin):
    _, key = user_and_key
    requester = await _make_user(db_session)
    onto = await _make_ontology(db_session)
    req = MaintainerRequest(user_id=requester.id, request_type="ontology", ontology_id=onto.id, note="mine")
    db_session.add(req)
    await db_session.commit()

    r = await client.post(f"/api/v1/admin/maintainer-requests/{req.id}/approve", json={}, headers=_auth(key))
    assert r.status_code == 200

    m = (await db_session.execute(
        select(OntologyMaintainer).where(
            OntologyMaintainer.user_id == requester.id,
            OntologyMaintainer.ontology_id == onto.id,
        )
    )).scalar_one_or_none()
    assert m is not None


@pytest.mark.anyio
async def test_admin_deny_sets_denied(client, user_and_key, db_session, _as_admin):
    _, key = user_and_key
    requester = await _make_user(db_session)
    req = MaintainerRequest(user_id=requester.id, request_type="uploader")
    db_session.add(req)
    await db_session.commit()

    r = await client.post(f"/api/v1/admin/maintainer-requests/{req.id}/deny",
                          json={"note": "insufficient rationale"}, headers=_auth(key))
    assert r.status_code == 200
    assert r.json()["status"] == "denied"

    u = (await db_session.execute(select(User).where(User.id == requester.id))).scalar_one()
    assert u.is_uploader is False


@pytest.mark.anyio
async def test_admin_approve_already_decided_409(client, user_and_key, db_session, _as_admin):
    _, key = user_and_key
    requester = await _make_user(db_session)
    req = MaintainerRequest(user_id=requester.id, request_type="uploader")
    db_session.add(req)
    await db_session.commit()

    first = await client.post(f"/api/v1/admin/maintainer-requests/{req.id}/approve", json={}, headers=_auth(key))
    assert first.status_code == 200
    second = await client.post(f"/api/v1/admin/maintainer-requests/{req.id}/approve", json={}, headers=_auth(key))
    assert second.status_code == 409
