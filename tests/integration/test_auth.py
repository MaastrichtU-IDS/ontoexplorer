"""Tests for auth endpoints and API key authentication."""

import pytest


@pytest.mark.anyio
async def test_me_unauthenticated(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_me_with_api_key(client, user_and_key):
    _, raw_key = user_and_key
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "test@example.com"


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
