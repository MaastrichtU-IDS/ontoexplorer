"""Integration tests for the starter-queries endpoints."""
import pytest


@pytest.mark.anyio
async def test_import_requires_admin(client):
    """Without admin auth the endpoint must reject."""
    resp = await client.post(
        "/api/v1/sparql/starters/import",
        data={"text": '{"starters": []}'},
    )
    # 401 (no auth) or 403 (auth but not admin) — both acceptable.
    assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_import_paste_json_creates_starters(admin_client):
    body = (
        '{"starters": [{"name": "Test starter", "category": "Test", '
        '"query_text": "SELECT * WHERE { ?s ?p ?o }"}]}'
    )
    resp = await admin_client.post(
        "/api/v1/sparql/starters/import",
        data={"text": body},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 1
    assert data["skipped"] == 0


@pytest.mark.anyio
async def test_import_paste_rq_creates_one_starter(admin_client):
    body = (
        "# @name Test rq\n# @category Test\n\n"
        "SELECT * WHERE { ?s ?p ?o }"
    )
    resp = await admin_client.post(
        "/api/v1/sparql/starters/import",
        data={"text": body},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1


@pytest.mark.anyio
async def test_import_duplicate_name_is_skipped(admin_client):
    body = (
        '{"starters": [{"name": "All classes in scope", '
        '"query_text": "SELECT *"}]}'
    )
    resp = await admin_client.post(
        "/api/v1/sparql/starters/import",
        data={"text": body},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 0
    assert data["skipped"] == 1
    assert data["errors"] and data["errors"][0]["reason"] == "duplicate name"


@pytest.mark.anyio
async def test_import_url_rejects_non_https(admin_client):
    resp = await admin_client.post(
        "/api/v1/sparql/starters/import",
        data={"source_url": "http://example.com/starters.json"},
    )
    assert resp.status_code == 400
    assert "https" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_import_url_allows_localhost_http(admin_client, monkeypatch):
    """Stub the URL fetcher so we don't open a socket; localhost http should be OK."""
    async def fake_fetch(url: str) -> str:
        return '{"starters": [{"name": "Local test", "query_text": "SELECT *"}]}'
    monkeypatch.setattr(
        "ontoexplorer.api.sparql_queries._fetch_starter_url",
        fake_fetch,
    )
    resp = await admin_client.post(
        "/api/v1/sparql/starters/import",
        data={"source_url": "http://localhost:9999/lib.json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1


@pytest.mark.anyio
async def test_starters_list_returns_seeded_rows(client):
    resp = await client.get("/api/v1/sparql/starters")
    assert resp.status_code == 200
    data = resp.json()
    assert "starters" in data
    # We seeded 10 starters in the migration.
    assert len(data["starters"]) >= 10
    names = [s["name"] for s in data["starters"]]
    assert "All classes in scope" in names


@pytest.mark.anyio
async def test_starters_list_ordered_by_category_then_name(client):
    resp = await client.get("/api/v1/sparql/starters")
    starters = resp.json()["starters"]
    sortable = [(s.get("category") or "", s["name"]) for s in starters]
    assert sortable == sorted(sortable)


@pytest.mark.anyio
async def test_import_url_rejects_oversize_response(admin_client, monkeypatch):
    """A response body exceeding 1 MB must be rejected (streaming hard cap)."""
    async def fake_fetch(url: str) -> str:
        raise ValueError("Response exceeded 1048576 byte cap")
    monkeypatch.setattr(
        "ontoexplorer.api.sparql_queries._fetch_starter_url",
        fake_fetch,
    )
    resp = await admin_client.post(
        "/api/v1/sparql/starters/import",
        data={"source_url": "https://example.com/big.json"},
    )
    assert resp.status_code == 400
    assert "exceeded" in resp.json()["detail"].lower() or "cap" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_starters_not_in_public_listing(client):
    public = await client.get("/api/v1/sparql/queries/public")
    public_names = {q["name"] for q in public.json()["queries"]}
    starters = await client.get("/api/v1/sparql/starters")
    starter_names = {s["name"] for s in starters.json()["starters"]}
    # Disjoint sets — starters must not bleed into /public.
    assert public_names.isdisjoint(starter_names)
