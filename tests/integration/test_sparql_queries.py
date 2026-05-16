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
    body = resp.json()
    assert "total" in body
    assert body["total"] >= 1
    names = [q["name"] for q in body["queries"]]
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


@pytest.mark.anyio
async def test_cross_user_private_access(client, db_session):
    """Authenticated user B cannot see/modify user A's private query."""
    import hashlib
    import uuid as _uuid

    from ontoexplorer.models.db import ApiKey, User

    # Create user A with API key
    raw_key_a = f"oe_test_{_uuid.uuid4().hex}"
    user_a = User(id=str(_uuid.uuid4()), email=f"a-{_uuid.uuid4()}@example.com", display_name="A")
    key_a = ApiKey(
        id=str(_uuid.uuid4()),
        user_id=user_a.id,
        key_hash=hashlib.sha256(raw_key_a.encode()).hexdigest(),
        name="key-a",
        scopes=["read", "write"],
    )
    # Create user B with API key
    raw_key_b = f"oe_test_{_uuid.uuid4().hex}"
    user_b = User(id=str(_uuid.uuid4()), email=f"b-{_uuid.uuid4()}@example.com", display_name="B")
    key_b = ApiKey(
        id=str(_uuid.uuid4()),
        user_id=user_b.id,
        key_hash=hashlib.sha256(raw_key_b.encode()).hexdigest(),
        name="key-b",
        scopes=["read", "write"],
    )
    db_session.add_all([user_a, key_a, user_b, key_b])
    await db_session.commit()

    auth_a = {"Authorization": f"Bearer {raw_key_a}"}
    auth_b = {"Authorization": f"Bearer {raw_key_b}"}

    # User A creates a private query
    resp = await client.post(
        "/api/v1/sparql/queries",
        json={"name": "secret", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": [], "is_public": False},
        headers=auth_a,
    )
    assert resp.status_code == 201
    qid = resp.json()["id"]

    # User B cannot read it
    assert (await client.get(f"/api/v1/sparql/queries/{qid}", headers=auth_b)).status_code == 404

    # User B cannot update it
    assert (await client.patch(f"/api/v1/sparql/queries/{qid}", json={"name": "hacked"}, headers=auth_b)).status_code == 404

    # User B cannot delete it
    assert (await client.delete(f"/api/v1/sparql/queries/{qid}", headers=auth_b)).status_code == 404

    # User A can still read it
    assert (await client.get(f"/api/v1/sparql/queries/{qid}", headers=auth_a)).status_code == 200
