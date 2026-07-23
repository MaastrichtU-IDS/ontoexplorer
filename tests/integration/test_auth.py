"""Tests for auth endpoints and API key authentication."""

import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import OAuthAccount, User
from ontoexplorer.modules.auth.session import link_oauth_account, unlink_oauth_account


async def _make_user(db, email=None, display_name=None) -> User:
    u = User(id=str(uuid.uuid4()), email=email, display_name=display_name)
    db.add(u)
    await db.commit()
    return u


async def _add_oauth(db, user_id, provider, provider_user_id=None) -> OAuthAccount:
    a = OAuthAccount(
        id=str(uuid.uuid4()),
        user_id=user_id,
        provider=provider,
        provider_user_id=provider_user_id or f"{provider}-{uuid.uuid4()}",
    )
    db.add(a)
    await db.commit()
    return a


async def _providers_of(db, user_id) -> set[str]:
    rows = (await db.execute(select(OAuthAccount).where(OAuthAccount.user_id == user_id))).scalars().all()
    return {a.provider for a in rows}


@pytest.mark.anyio
async def test_me_unauthenticated(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_me_with_api_key(client, user_and_key):
    user, raw_key = user_and_key
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == user.email


@pytest.mark.anyio
async def test_api_keys_list_authenticated(client, user_and_key):
    _, raw_key = user_and_key
    resp = await client.get("/api/v1/api-keys", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    assert "api_keys" in resp.json()


@pytest.mark.anyio
async def test_api_keys_list_unauthenticated(client):
    resp = await client.get("/api/v1/api-keys")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_create_and_revoke_api_key(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    # Create
    resp = await client.post("/api/v1/api-keys", json={"name": "ci-key", "scopes": ["read"]}, headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "ci-key"
    assert "key" in body  # raw key shown once
    key_id = body["id"]

    # Verify it appears in list
    resp = await client.get("/api/v1/api-keys", headers=auth)
    ids = [k["id"] for k in resp.json()["api_keys"]]
    assert key_id in ids

    # Revoke
    resp = await client.delete(f"/api/v1/api-keys/{key_id}", headers=auth)
    assert resp.status_code == 200

    # No longer in list
    resp = await client.get("/api/v1/api-keys", headers=auth)
    ids = [k["id"] for k in resp.json()["api_keys"]]
    assert key_id not in ids


@pytest.mark.anyio
async def test_oauth_login_redirect(client):
    """Login endpoint should redirect to OAuth provider."""
    resp = await client.get("/auth/github/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "github.com" in resp.headers.get("location", "")


# ── Account linking: session-layer unit tests ──────────────────────────────────

@pytest.mark.anyio
async def test_link_attaches_new_provider_and_backfills(db_session):
    u = await _make_user(db_session)  # no email/name
    await _add_oauth(db_session, u.id, "github")
    email = f"link-{uuid.uuid4()}@example.com"
    res = await link_oauth_account(
        db_session, u.id, "orcid", f"orcid-{uuid.uuid4()}",
        email=email, display_name="Dr X",
        access_token="t", refresh_token=None, expires_at=None,
    )
    assert await _providers_of(db_session, u.id) == {"github", "orcid"}
    assert res.email == email          # backfilled (was empty)
    assert res.display_name == "Dr X"  # backfilled (was empty)


@pytest.mark.anyio
async def test_link_conflict_with_other_user_raises(db_session):
    a = await _make_user(db_session)
    b = await _make_user(db_session)
    shared = f"orcid-{uuid.uuid4()}"
    await _add_oauth(db_session, a.id, "orcid", shared)
    with pytest.raises(ValueError, match="already linked"):
        await link_oauth_account(
            db_session, b.id, "orcid", shared,
            email=None, display_name=None,
            access_token=None, refresh_token=None, expires_at=None,
        )
    # b gained nothing
    assert await _providers_of(db_session, b.id) == set()


@pytest.mark.anyio
async def test_link_same_user_is_idempotent(db_session):
    u = await _make_user(db_session)
    puid = f"gh-{uuid.uuid4()}"
    await _add_oauth(db_session, u.id, "github", puid)
    await link_oauth_account(
        db_session, u.id, "github", puid,
        email=None, display_name=None,
        access_token="newtok", refresh_token=None, expires_at=None,
    )
    rows = (await db_session.execute(
        select(OAuthAccount).where(OAuthAccount.user_id == u.id, OAuthAccount.provider == "github")
    )).scalars().all()
    assert len(rows) == 1              # not duplicated
    assert rows[0].access_token == "newtok"  # tokens refreshed


@pytest.mark.anyio
async def test_link_does_not_backfill_email_if_taken(db_session):
    taken_email = f"taken-{uuid.uuid4()}@example.com"
    await _make_user(db_session, email=taken_email)
    u = await _make_user(db_session)  # no email
    await _add_oauth(db_session, u.id, "orcid")
    res = await link_oauth_account(
        db_session, u.id, "github", f"gh-{uuid.uuid4()}",
        email=taken_email, display_name=None,   # collides -> must NOT set
        access_token=None, refresh_token=None, expires_at=None,
    )
    assert res.email is None
    assert await _providers_of(db_session, u.id) == {"orcid", "github"}


@pytest.mark.anyio
async def test_unlink_refuses_only_provider(db_session):
    u = await _make_user(db_session)
    await _add_oauth(db_session, u.id, "github")
    with pytest.raises(ValueError, match="only sign-in method"):
        await unlink_oauth_account(db_session, u.id, "github")
    assert await _providers_of(db_session, u.id) == {"github"}  # still there


@pytest.mark.anyio
async def test_unlink_success(db_session):
    u = await _make_user(db_session)
    await _add_oauth(db_session, u.id, "github")
    await _add_oauth(db_session, u.id, "orcid")
    remaining = await unlink_oauth_account(db_session, u.id, "github")
    assert remaining == ["orcid"]
    assert await _providers_of(db_session, u.id) == {"orcid"}


# ── Account linking: endpoint tests ─────────────────────────────────────────────

@pytest.mark.anyio
async def test_link_start_requires_auth(client):
    resp = await client.get("/auth/github/link", follow_redirects=False)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_link_start_returns_authorize_url_and_sets_cookie(client, user_and_key):
    _, raw_key = user_and_key
    resp = await client.get("/auth/github/link", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    assert "github.com" in resp.json()["authorize_url"]
    assert "oauth_link=" in resp.headers.get("set-cookie", "")


@pytest.mark.anyio
async def test_unlink_requires_auth(client):
    resp = await client.post("/auth/github/unlink")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_unlink_unknown_provider_404(client, user_and_key):
    _, raw_key = user_and_key
    resp = await client.post("/auth/frobnicate/unlink", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 404
