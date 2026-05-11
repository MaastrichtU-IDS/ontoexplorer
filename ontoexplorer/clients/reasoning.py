"""HTTP client for the ELK reasoning service (v2)."""
from __future__ import annotations

import httpx
import rdflib

from ontoexplorer.config import get_settings


def _elk_url(path: str) -> str:
    return f"{get_settings().elk_service_url}{path}"


async def classify_v2(graph: rdflib.Graph, version_id: str) -> dict:
    """
    Run full OWL-EL classification and cache in ELK service.
    Returns the summary dict from POST /classify.
    """
    ntriples = graph.serialize(format="nt")
    async with httpx.AsyncClient(timeout=get_settings().elk_service_timeout) as client:
        resp = await client.post(_elk_url("/classify"),
                                 json={"ntriples": ntriples, "version_id": version_id})
        resp.raise_for_status()
    return resp.json()


async def superclasses(version_id: str, class_iri: str, direct: bool = False) -> dict:
    """Return all (or direct-only) inferred superclasses of class_iri."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _elk_url(f"/classify/{version_id}/superclasses"),
            params={"cls": class_iri, "direct": str(direct).lower()},
        )
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        if resp.status_code == 404:
            raise ClassNotFoundError(class_iri)
        resp.raise_for_status()
    return resp.json()


async def subclasses(version_id: str, class_iri: str, direct: bool = False) -> dict:
    """Return all (or direct-only) inferred subclasses of class_iri."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _elk_url(f"/classify/{version_id}/subclasses"),
            params={"cls": class_iri, "direct": str(direct).lower()},
        )
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        if resp.status_code == 404:
            raise ClassNotFoundError(class_iri)
        resp.raise_for_status()
    return resp.json()


async def consistency(version_id: str) -> dict:
    """Return consistency check result including unsatisfiable classes."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_elk_url(f"/classify/{version_id}/consistency"))
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        resp.raise_for_status()
    return resp.json()


async def request_justification(
    version_id: str,
    sub: str,
    sup: str | None,
    max_justifications: int = 1,
) -> dict:
    """
    Synchronously request justification computation from ELK service.
    Long-running — always called from a Celery task, not an HTTP handler.
    """
    body: dict = {"sub": sub, "max_justifications": max_justifications}
    if sup:
        body["sup"] = sup
    else:
        body["type"] = "unsatisfiable"

    timeout = get_settings().elk_service_timeout + 60  # extra buffer over time limit
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            _elk_url(f"/classify/{version_id}/justification"),
            json=body,
        )
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        resp.raise_for_status()
    return resp.json()


async def invalidate_cache(version_id: str) -> None:
    """Invalidate ELK Redis cache for a version (called on deprecation)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.delete(_elk_url(f"/classify/{version_id}"))


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(_elk_url("/health"))
            return resp.status_code == 200 and resp.json().get("redis") == "ok"
    except Exception:
        return False


async def get_classification(version_id: str) -> dict:
    """Fetch the full ClassificationResult JSON from the ELK service cache.

    Returns the raw dict with keys: superclasses, subclasses, direct_superclasses,
    direct_subclasses, unsatisfiable, class_count, proof_traces, etc.

    Raises ReasoningNotReadyError if the version has not been classified yet.
    """
    url = f"{_elk_url('')}/classify/{version_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
    if resp.status_code in (404, 409):
        raise ReasoningNotReadyError(version_id)
    resp.raise_for_status()
    return resp.json()


class ReasoningNotReadyError(Exception):
    def __init__(self, version_id: str):
        super().__init__(f"Reasoning not yet completed for version {version_id}")
        self.version_id = version_id


class ClassNotFoundError(Exception):
    def __init__(self, class_iri: str):
        super().__init__(f"Class {class_iri} not found in classification index")
        self.class_iri = class_iri
