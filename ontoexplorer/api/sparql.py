"""SPARQL 1.1 proxy endpoints.

GET/POST /sparql         → QLever (FAIR metadata)
GET/POST /sparql/content → Oxigraph (asserted ontology triples)
"""

import time

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ontoexplorer.clients import qlever as qlever_client
from ontoexplorer import metrics

router = APIRouter(tags=["sparql"])

_DEFAULT_ACCEPT = "application/sparql-results+json"


@router.get("/sparql", summary="SPARQL 1.1 over QLever metadata store")
@router.post("/sparql")
async def sparql_metadata(request: Request):
    query, accept = await _extract_query_and_accept(request)
    metrics.sparql_requests_total.labels(endpoint="qlever", method=request.method).inc()
    t0 = time.monotonic()
    try:
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
    query, accept = await _extract_query_and_accept(request)
    metrics.sparql_requests_total.labels(endpoint="oxigraph", method=request.method).inc()
    t0 = time.monotonic()
    try:
        body, content_type = _oxigraph_query(query, accept)
    except Exception:
        metrics.sparql_errors_total.labels(endpoint="oxigraph").inc()
        raise
    finally:
        metrics.sparql_latency_seconds.labels(endpoint="oxigraph").observe(time.monotonic() - t0)
    return Response(content=body, media_type=content_type)


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


def _oxigraph_query(query: str, accept: str) -> tuple[bytes, str]:
    from io import BytesIO

    import pyoxigraph

    from ontoexplorer.clients.oxigraph import get_store

    store = get_store()
    result = store.query(query)

    if isinstance(result, pyoxigraph.QuerySolutions):
        buf = BytesIO()
        if "json" in accept or accept == "*/*":
            result.serialize(buf, "application/sparql-results+json")
            return buf.getvalue(), "application/sparql-results+json"
        else:
            result.serialize(buf, "application/sparql-results+xml")
            return buf.getvalue(), "application/sparql-results+xml"

    if isinstance(result, pyoxigraph.QueryTriples):
        buf = BytesIO()
        if "turtle" in accept:
            pyoxigraph.serialize(result, buf, "text/turtle")
            return buf.getvalue(), "text/turtle"
        else:
            pyoxigraph.serialize(result, buf, "application/n-triples")
            return buf.getvalue(), "application/n-triples"

    # ASK
    body = b'{"boolean": true}' if result else b'{"boolean": false}'
    return body, "application/sparql-results+json"
