"""SPARQL 1.1 proxy endpoints.

GET/POST /sparql         → QLever/Fuseki (FAIR metadata)
GET/POST /sparql/content → oxigraph-sparql container (asserted ontology triples)
"""

import re
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ontoexplorer import metrics
from ontoexplorer.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["sparql"])

_DEFAULT_ACCEPT = "application/sparql-results+json"

_UPDATE_RE = re.compile(
    r"\b(INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE)\b",
    re.IGNORECASE,
)


def _check_query_guard(query: str) -> None:
    """Raise ValueError if query contains SPARQL Update keywords.

    Best-effort guard: strips IRIs and string literals before checking.
    Primary enforcement is the oxigraph-server --read-only flag.
    """
    # Strip IRIs (<...>), quoted strings ("..." and '...'), then comments (#...)
    stripped = re.sub(r"<[^>]*>", " ", query)
    stripped = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', " ", stripped)
    stripped = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", " ", stripped)
    stripped = re.sub(r"#[^\n]*", "", stripped)
    if _UPDATE_RE.search(stripped):
        raise ValueError("SPARQL Update not permitted")


@router.get("/sparql", summary="SPARQL 1.1 over QLever metadata store")
@router.post("/sparql")
async def sparql_metadata(request: Request):
    try:
        query, accept = await _extract_query_and_accept(request)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    metrics.sparql_requests_total.labels(endpoint="qlever", method=request.method).inc()
    t0 = time.monotonic()
    try:
        from ontoexplorer.clients import qlever as qlever_client
        body, content_type = await qlever_client.query_passthrough(query, accept)
    except Exception:
        metrics.sparql_errors_total.labels(endpoint="qlever").inc()
        raise
    finally:
        metrics.sparql_latency_seconds.labels(endpoint="qlever").observe(time.monotonic() - t0)
    return Response(content=body, media_type=content_type)


@router.get("/sparql/content", summary="SPARQL 1.1 over Oxigraph content store (asserted triples)")
@router.post("/sparql/content")
async def sparql_content(request: Request):
    try:
        query, accept = await _extract_query_and_accept(request)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    try:
        _check_query_guard(query)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    settings = get_settings()
    metrics.sparql_requests_total.labels(endpoint="oxigraph", method=request.method).inc()
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.sparql_query_timeout_seconds) as http:
            resp = await http.post(
                f"{settings.oxigraph_sparql_url}/query",
                content=query.encode(),
                headers={"Content-Type": "application/sparql-query", "Accept": accept},
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", accept),
        )
    except httpx.TimeoutException:
        metrics.sparql_errors_total.labels(endpoint="oxigraph").inc()
        return JSONResponse(status_code=504, content={"detail": "Query timed out"})
    except Exception:
        metrics.sparql_errors_total.labels(endpoint="oxigraph").inc()
        raise
    finally:
        metrics.sparql_latency_seconds.labels(endpoint="oxigraph").observe(time.monotonic() - t0)


async def _extract_query_and_accept(request: Request) -> tuple[str, str]:
    accept = request.headers.get("accept", _DEFAULT_ACCEPT)

    if request.method == "GET":
        query = request.query_params.get("query", "")
    else:
        content_type = request.headers.get("content-type", "")
        if "application/sparql-query" in content_type:
            query = (await request.body()).decode()
        else:
            form = await request.form()
            query = form.get("query", "")  # type: ignore[arg-type]

    if not query:
        raise ValueError("Missing 'query' parameter")
    return query, accept
