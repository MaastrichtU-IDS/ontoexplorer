"""Integration tests for the starter-queries endpoints."""
import pytest


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
async def test_starters_not_in_public_listing(client):
    public = await client.get("/api/v1/sparql/queries/public")
    public_names = {q["name"] for q in public.json()["queries"]}
    starters = await client.get("/api/v1/sparql/starters")
    starter_names = {s["name"] for s in starters.json()["starters"]}
    # Disjoint sets — starters must not bleed into /public.
    assert public_names.isdisjoint(starter_names)
