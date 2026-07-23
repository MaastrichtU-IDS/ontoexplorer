"""Tests for health and readiness endpoints."""

import pytest


@pytest.mark.anyio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.anyio
async def test_version(client):
    from ontoexplorer import __version__
    resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == __version__
    # git_ref/git_sha are null in the test env (no build-time injection)
    assert "git_ref" in body and "git_sha" in body


@pytest.mark.anyio
async def test_ready_returns_json(client):
    """Ready endpoint runs backend checks; may return 200 or 503 in test env, but always JSON."""
    resp = await client.get("/ready")
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert "postgres" in body
