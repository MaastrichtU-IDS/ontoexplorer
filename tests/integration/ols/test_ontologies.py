"""Integration tests for OLS4-compat ontology endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_ontologies_hal_paged(client: AsyncClient, sample_ontology):
    resp = await client.get("/ols/api/ontologies?page=0&size=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "_embedded" in body
    assert "ontologies" in body["_embedded"]
    assert len(body["_embedded"]["ontologies"]) >= 1
    assert body["page"]["number"] == 0
    assert body["page"]["size"] == 10
    assert "_links" in body
    assert "self" in body["_links"]


@pytest.mark.anyio
async def test_get_ontology_detail(client: AsyncClient, sample_ontology):
    resp = await client.get(f"/ols/api/ontologies/{sample_ontology.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ontologyId"] == sample_ontology.shortname
    assert body["status"] == "LOADED"
    assert body["config"]["preferredPrefix"] == sample_ontology.shortname.upper()
    assert "numberOfTerms" in body
    assert "_links" in body


@pytest.mark.anyio
async def test_get_ontology_404(client: AsyncClient):
    resp = await client.get("/ols/api/ontologies/nonexistent_xyz")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_v2_list_ontologies_flat(client: AsyncClient, sample_ontology):
    resp = await client.get("/ols/api/v2/ontologies?page=0&size=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "_embedded" not in body
    assert "_links" not in body
    assert len(body["elements"]) >= 1


@pytest.mark.anyio
async def test_v2_get_ontology_detail(client: AsyncClient, sample_ontology):
    resp = await client.get(f"/ols/api/v2/ontologies/{sample_ontology.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ontologyId"] == sample_ontology.shortname
    assert "_links" not in body


@pytest.mark.anyio
async def test_download_redirects_to_existing_route(client: AsyncClient, sample_ontology, db_session):
    from ontoexplorer.models.db import OntologyVersion
    from sqlalchemy import select

    # Fetch the version id that sample_ontology fixture created
    result = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == sample_ontology.id)
    )
    ver = result.scalar_one()

    resp = await client.get(
        f"/ols/api/ontologies/{sample_ontology.id}/download",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert f"/api/v1/ontologies/{sample_ontology.id}/{ver.id}/download" in location
