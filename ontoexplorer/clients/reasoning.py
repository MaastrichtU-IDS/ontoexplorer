"""HTTP client for the ELK reasoning service (v2)."""
from __future__ import annotations

import asyncio
import httpx
import rdflib

from ontoexplorer.config import get_settings


def _elk_url(path: str) -> str:
    return f"{get_settings().elk_service_url}{path}"


async def classify_v2(graph: rdflib.Graph, version_id: str) -> dict:
    """
    POST N-Triples to ELK service (returns 202 immediately), then poll until done.
    Max wait is elk_service_timeout seconds (default 3600); raises TimeoutError if exceeded.

    Re-submits the job every RESUBMIT_INTERVAL seconds if still getting 409 — this handles
    ELK service restarts that clear the in-progress set but not the Redis cache.
    """
    ntriples = graph.serialize(format="nt")
    RESUBMIT_INTERVAL = 120  # re-POST if job still missing after this many seconds

    async def _submit() -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(_elk_url("/classify"),
                                     json={"ntriples": ntriples, "version_id": version_id})
            resp.raise_for_status()
            return resp.json()

    posted = await _submit()

    # If already cached (status="done"), we're done
    if posted.get("status") == "done":
        return posted

    # Poll GET /classify/{version_id} until 200 or timeout
    max_wait = get_settings().elk_service_timeout
    poll_interval = 5
    elapsed = 0
    last_resubmit = 0

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        # Re-POST periodically to recover from ELK restarts that lose the in-progress state
        if elapsed - last_resubmit >= RESUBMIT_INTERVAL:
            last_resubmit = elapsed
            posted = await _submit()
            if posted.get("status") == "done":
                break

        async with httpx.AsyncClient(timeout=30.0) as client:
            poll = await client.get(_elk_url(f"/classify/{version_id}"))
        if poll.status_code == 200:
            return poll.json()
        if poll.status_code != 409:
            poll.raise_for_status()

    raise TimeoutError(f"ELK classification for {version_id} did not complete within {max_wait}s")


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
