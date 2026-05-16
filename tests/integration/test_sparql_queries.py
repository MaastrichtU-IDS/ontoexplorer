"""Integration tests for saved SPARQL queries API."""
import pytest

BASE = "/api/v1/sparql/queries"


@pytest.mark.anyio
async def test_create_and_list(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    resp = await client.post(
        BASE,
        json={
            "name": "My query",
            "description": "Test",
            "query_text": "SELECT * WHERE { ?s ?p ?o } LIMIT 10",
            "tags": ["hp", "mondo"],
            "is_public": False,
        },
        headers=auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "My query"
    assert body["tags"] == ["hp", "mondo"]
    assert body["is_public"] is False
    qid = body["id"]

    resp = await client.get(BASE, headers=auth)
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["queries"]]
    assert qid in ids


@pytest.mark.anyio
async def test_private_query_access(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    resp = await client.post(
        BASE,
        json={"name": "private", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": [], "is_public": False},
        headers=auth,
    )
    qid = resp.json()["id"]

    # Owner can access
    assert (await client.get(f"{BASE}/{qid}", headers=auth)).status_code == 200
    # Unauthenticated gets 404 (not 403 — don't leak existence)
    assert (await client.get(f"{BASE}/{qid}")).status_code == 404


@pytest.mark.anyio
async def test_public_query_no_auth(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    resp = await client.post(
        BASE,
        json={"name": "public", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": ["go"], "is_public": True},
        headers=auth,
    )
    qid = resp.json()["id"]

    resp = await client.get(f"{BASE}/{qid}")
    assert resp.status_code == 200
    assert resp.json()["is_public"] is True


@pytest.mark.anyio
async def test_public_gallery_and_filter(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    await client.post(
        BASE,
        json={"name": "Gallery query", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": ["hp"], "is_public": True},
        headers=auth,
    )

    resp = await client.get(f"{BASE}/public")
    assert resp.status_code == 200
    names = [q["name"] for q in resp.json()["queries"]]
    assert "Gallery query" in names

    resp = await client.get(f"{BASE}/public?ontology=hp")
    assert resp.status_code == 200
    for q in resp.json()["queries"]:
        assert "hp" in q["tags"]

    resp = await client.get(f"{BASE}/public?q=Gallery")
    assert resp.status_code == 200
    names = [q["name"] for q in resp.json()["queries"]]
    assert "Gallery query" in names


@pytest.mark.anyio
async def test_update_and_delete(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    resp = await client.post(
        BASE,
        json={"name": "to-update", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": [], "is_public": False},
        headers=auth,
    )
    qid = resp.json()["id"]

    resp = await client.patch(f"{BASE}/{qid}", json={"name": "updated"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated"

    resp = await client.delete(f"{BASE}/{qid}", headers=auth)
    assert resp.status_code == 204

    assert (await client.get(f"{BASE}/{qid}", headers=auth)).status_code == 404


@pytest.mark.anyio
async def test_unauthenticated_create_returns_401(client):
    resp = await client.post(
        BASE,
        json={"name": "q", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": [], "is_public": False},
    )
    assert resp.status_code == 401
