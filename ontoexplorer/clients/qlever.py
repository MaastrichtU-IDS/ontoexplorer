"""Async SPARQL 1.1 HTTP client for QLever.

QLever exposes a standard SPARQL endpoint and a SPARQL Update endpoint.
All methods are async (httpx).
"""

import logging

import httpx

from ontoexplorer.config import get_settings

logger = logging.getLogger(__name__)

_QUERY_ACCEPT = "application/sparql-results+json"
_CONSTRUCT_ACCEPT = "text/turtle"


def _endpoints() -> tuple[str, str]:
    s = get_settings()
    base = s.qlever_endpoint.rstrip("/")
    return f"{base}{s.qlever_sparql_path}", f"{base}/update"


async def sparql_select(query: str, timeout: float = 30.0) -> dict:
    """Execute a SELECT or ASK query; returns the parsed JSON result."""
    endpoint, _ = _endpoints()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            endpoint,
            data={"query": query},
            headers={"Accept": _QUERY_ACCEPT},
        )
        resp.raise_for_status()
        return resp.json()


async def sparql_construct(query: str, timeout: float = 30.0) -> str:
    """Execute a CONSTRUCT query; returns the Turtle string."""
    endpoint, _ = _endpoints()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            endpoint,
            data={"query": query},
            headers={"Accept": _CONSTRUCT_ACCEPT},
        )
        resp.raise_for_status()
        return resp.text


async def sparql_update(update: str, timeout: float = 30.0) -> None:
    """Execute a SPARQL Update statement (INSERT DATA / DELETE DATA / etc.)."""
    _, update_endpoint = _endpoints()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            update_endpoint,
            data={"update": update},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        logger.debug("SPARQL Update executed (%d chars)", len(update))


async def insert_turtle(ttl: str, graph_iri: str | None = None, timeout: float = 60.0) -> None:
    """
    Insert all triples from a Turtle string into QLever.

    If graph_iri is given, inserts into that named graph.
    QLever supports SPARQL 1.1 Update INSERT DATA with Turtle inline syntax.
    """
    if graph_iri:
        update = f"INSERT DATA {{ GRAPH <{graph_iri}> {{ {ttl} }} }}"
    else:
        update = f"INSERT DATA {{ {ttl} }}"
    await sparql_update(update, timeout=timeout)


async def delete_graph(graph_iri: str) -> None:
    """Drop all triples in a named graph."""
    await sparql_update(f"DROP SILENT GRAPH <{graph_iri}>")


async def query_passthrough(raw_query: str, accept: str, timeout: float = 30.0) -> tuple[bytes, str]:
    """
    Forward a raw SPARQL query string to QLever and return (body_bytes, content_type).
    Used by the SPARQL proxy endpoint.
    """
    endpoint, _ = _endpoints()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            endpoint,
            data={"query": raw_query},
            headers={"Accept": accept},
        )
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/sparql-results+json")
