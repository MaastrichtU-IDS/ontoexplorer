"""Tests for the webhooks API and HMAC signing."""

import hashlib
import hmac
import json

import pytest


@pytest.mark.anyio
async def test_create_list_delete_webhook(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    # Create
    resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "http://example.com/hook", "events": ["ontology.ingested"], "secret": "mysecret"},
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == "http://example.com/hook"
    webhook_id = body["id"]

    # List
    resp = await client.get("/api/v1/webhooks", headers=auth)
    ids = [w["id"] for w in resp.json()["webhooks"]]
    assert webhook_id in ids

    # Detail
    resp = await client.get(f"/api/v1/webhooks/{webhook_id}", headers=auth)
    assert resp.status_code == 200

    # Delivery history (empty)
    resp = await client.get(f"/api/v1/webhooks/{webhook_id}/deliveries", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["deliveries"] == []

    # Delete
    resp = await client.delete(f"/api/v1/webhooks/{webhook_id}", headers=auth)
    assert resp.status_code == 200

    # Gone
    resp = await client.get(f"/api/v1/webhooks/{webhook_id}", headers=auth)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_webhook_invalid_event(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "http://example.com/hook", "events": ["not.a.real.event"]},
        headers=auth,
    )
    assert resp.status_code == 422


def test_hmac_signature_format():
    """HMAC signing produces the expected sha256= prefix format."""
    from ontoexplorer.modules.webhooks.delivery import _sign_payload

    secret = "test-secret"
    payload = b'{"event":"ontology.ingested"}'
    sig = _sign_payload(secret, payload)

    assert sig.startswith("sha256=")
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert sig == expected


@pytest.mark.anyio
async def test_webhook_unauthenticated(client):
    resp = await client.get("/api/v1/webhooks")
    assert resp.status_code == 401
