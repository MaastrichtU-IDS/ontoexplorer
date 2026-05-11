"""HTTP client for the ELK reasoning service."""

import httpx
import rdflib

from ontoexplorer.config import get_settings


async def classify(graph: rdflib.Graph, version_id: str) -> rdflib.Graph:
    """
    Send the ontology graph to the ELK service for OWL-EL classification.
    Returns a Graph containing only the inferred axioms.
    """
    settings = get_settings()
    ntriples = graph.serialize(format="nt")

    async with httpx.AsyncClient(timeout=settings.elk_service_timeout) as client:
        resp = await client.post(
            f"{settings.elk_service_url}/reason",
            json={"ntriples": ntriples, "version_id": version_id},
        )
        resp.raise_for_status()

    data = resp.json()
    inferred = rdflib.Graph()
    if data.get("inferred_ntriples"):
        inferred.parse(data=data["inferred_ntriples"], format="nt")
    return inferred


async def health_check() -> bool:
    """Return True if the ELK service is reachable and healthy."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.elk_service_url}/health")
            return resp.status_code == 200
    except Exception:
        return False
