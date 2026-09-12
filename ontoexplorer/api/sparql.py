"""SPARQL 1.1 endpoints.

GET/POST /sparql         → in-process metadata store (DCAT/VoID/PROV FAIR metadata)
GET/POST /sparql/content → in-process Oxigraph store (asserted ontology triples)

Both are separate embedded pyoxigraph stores, queried read-only here, so /sparql
sees only metadata and /sparql/content only content — no cross-leakage.
"""

import asyncio
import json
import re
import time

import pyoxigraph
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ontoexplorer import metrics
from ontoexplorer.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["sparql"])

_DEFAULT_ACCEPT = "application/sparql-results+json"

_UPDATE_RE = re.compile(
    r"\b(INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD)\b",
    re.IGNORECASE,
)

# SERVICE makes the evaluating process open an outbound HTTP connection to a
# host named in the query. On an endpoint anyone can reach that is request
# forgery from inside the cluster, and NO_PROXY covers .svc.cluster.local, so
# in-namespace targets are dialled directly rather than through egress-proxy.
# pyoxigraph 0.5.9 exposes no switch to disable federation and no query parser
# to inspect, so this lexical check is the only control available in-process.
_FEDERATION_RE = re.compile(r"\bSERVICE\b", re.IGNORECASE)


def _strip_non_keyword_text(query: str) -> str:
    """Remove comments, string literals and IRIs, leaving only SPARQL syntax.

    Order matters and previously did not. IRIs were stripped first with
    `<[^>]*>`, whose character class spans newlines, so a single unpaired `<`
    anywhere -- including inside a comment, which had not been removed yet --
    consumed everything up to the next `>`. A keyword in between vanished with
    it and the guard passed:

        # <
        INSERT DATA { <urn:a> <urn:b> <urn:c> }
        #>

    Comments go first, and the IRI pattern no longer crosses a line, so an
    unterminated `<` can hide at most the rest of its own line.
    """
    stripped = re.sub(r"#[^\n]*", " ", query)
    stripped = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', " ", stripped)
    stripped = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", " ", stripped)
    stripped = re.sub(r"<[^>\n]*>", " ", stripped)
    return stripped


def _check_query_guard(query: str) -> None:
    """Reject SPARQL Update verbs and federation on the public endpoints.

    Update is additionally prevented by the store being opened read-only; there
    is no such second line of defence for SERVICE, so this check is load-bearing
    rather than best-effort.
    """
    stripped = _strip_non_keyword_text(query)
    if _UPDATE_RE.search(stripped):
        raise ValueError("SPARQL Update not permitted")
    if _FEDERATION_RE.search(stripped):
        raise ValueError("SPARQL SERVICE (federation) is not permitted on this endpoint")


def _serialize_result(result, primary_accept: str) -> tuple[bytes, str]:
    if isinstance(result, bool):
        return json.dumps({"head": {}, "boolean": result}).encode(), pyoxigraph.QueryResultsFormat.JSON.media_type
    if isinstance(result, pyoxigraph.QueryTriples):
        try:
            fmt = pyoxigraph.RdfFormat.from_media_type(primary_accept)
        except (ValueError, KeyError):
            fmt = pyoxigraph.RdfFormat.TURTLE
        return result.serialize(format=fmt), fmt.media_type
    try:
        fmt = pyoxigraph.QueryResultsFormat.from_media_type(primary_accept)
    except (ValueError, KeyError):
        fmt = pyoxigraph.QueryResultsFormat.JSON
    return result.serialize(format=fmt), fmt.media_type


async def _serve_sparql(request: Request, store, endpoint_label: str):
    """Read-only SPARQL over one embedded pyoxigraph store.

    Shared by /sparql (metadata store) and /sparql/content (content store) — the
    only difference is which store, so both get the same guard, dataset scoping,
    off-loop execution, timeout, and serialisation. Update is blocked twice over:
    the lexical guard, and the store being opened read-only in the API.
    """
    try:
        query, accept = await _extract_query_and_accept(request)
        _check_query_guard(query)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    default_graph_uris, named_graph_uris = await _extract_dataset_uris(request)
    settings = get_settings()
    metrics.sparql_requests_total.labels(endpoint=endpoint_label, method=request.method).inc()
    t0 = time.monotonic()
    primary_accept = accept.split(",")[0].split(";")[0].strip()

    def _run() -> tuple[bytes, str]:
        query_kwargs: dict = {}
        if default_graph_uris:
            query_kwargs["default_graph"] = [pyoxigraph.NamedNode(u) for u in default_graph_uris]
        if named_graph_uris:
            query_kwargs["named_graphs"] = [pyoxigraph.NamedNode(u) for u in named_graph_uris]
        return _serialize_result(store.query(query, **query_kwargs), primary_accept)

    try:
        body, content_type = await asyncio.wait_for(
            asyncio.to_thread(_run), timeout=settings.sparql_query_timeout_seconds
        )
        return Response(content=body, media_type=content_type)
    except asyncio.TimeoutError:
        metrics.sparql_errors_total.labels(endpoint=endpoint_label).inc()
        return JSONResponse(status_code=504, content={"detail": "Query timed out"})
    except Exception as exc:
        metrics.sparql_errors_total.labels(endpoint=endpoint_label).inc()
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    finally:
        metrics.sparql_latency_seconds.labels(endpoint=endpoint_label).observe(time.monotonic() - t0)


@router.get("/sparql", summary="SPARQL 1.1 over the FAIR metadata store")
@router.post("/sparql")
async def sparql_metadata(request: Request):
    from ontoexplorer.clients.metadata_store import get_metadata_store

    return await _serve_sparql(request, get_metadata_store(), "metadata")


@router.get("/sparql/content", summary="SPARQL 1.1 over Oxigraph content store (asserted triples)")
@router.post("/sparql/content")
async def sparql_content(request: Request):
    from ontoexplorer.clients.oxigraph import get_store

    return await _serve_sparql(request, get_store(), "oxigraph")


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


async def _extract_dataset_uris(request: Request) -> tuple[list[str], list[str]]:
    """Return (default_graph_uris, named_graph_uris) per SPARQL Protocol §2.1.

    URL query params and POST form fields are both accepted; values appearing
    in either are merged. Empty lists mean "use the store defaults".
    """
    default_graphs: list[str] = list(request.query_params.getlist("default-graph-uri"))
    named_graphs: list[str] = list(request.query_params.getlist("named-graph-uri"))

    if request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/sparql-query" not in content_type:
            form = await request.form()
            # Starlette's FormData supports getlist for repeated keys.
            default_graphs.extend(str(v) for v in form.getlist("default-graph-uri"))
            named_graphs.extend(str(v) for v in form.getlist("named-graph-uri"))

    return default_graphs, named_graphs
