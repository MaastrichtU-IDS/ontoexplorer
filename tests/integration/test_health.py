"""Tests for health and readiness endpoints."""

import pytest


@pytest.mark.anyio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.anyio
async def test_ready_returns_json(client):
    """Ready endpoint runs backend checks; may return 200 or 503 in test env, but always JSON."""
    resp = await client.get("/ready")
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert "postgres" in body
