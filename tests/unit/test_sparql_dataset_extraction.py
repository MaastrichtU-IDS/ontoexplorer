"""Unit tests for the dataset-URI extraction helper used by /sparql/content.

The frontend's SPARQL scope toolbar sends `default-graph-uri` and
`named-graph-uri` parameters per SPARQL 1.1 Protocol §2.1. The handler
must extract them (URL query and/or POST form body) and forward them as
`default_graph` / `named_graphs` keyword args to `pyoxigraph.Store.query`.
"""
from urllib.parse import urlencode

import pytest
from starlette.datastructures import FormData
from starlette.requests import Request


def _request(method: str, query_params: dict | list[tuple[str, str]] | None = None, *, form: list[tuple[str, str]] | None = None) -> Request:
    qs = ""
    if query_params:
        qs = urlencode(query_params, doseq=True) if isinstance(query_params, dict) else urlencode(query_params)
    headers = []
    if form is not None:
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))
    scope = {
        "type": "http",
        "method": method,
        "path": "/api/v1/sparql/content",
        "query_string": qs.encode(),
        "headers": headers,
    }

    body = b""
    if form is not None:
        body = urlencode(form).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.mark.anyio
async def test_extract_dataset_uris_empty_when_no_params():
    from ontoexplorer.api.sparql import _extract_dataset_uris
    req = _request("GET")
    default_uris, named_uris = await _extract_dataset_uris(req)
    assert default_uris == []
    assert named_uris == []


@pytest.mark.anyio
async def test_extract_dataset_uris_from_get_query_string():
    from ontoexplorer.api.sparql import _extract_dataset_uris
    req = _request("GET", [
        ("default-graph-uri", "urn:ontology:O1:V1"),
        ("named-graph-uri", "urn:ontology:O1:V1"),
    ])
    default_uris, named_uris = await _extract_dataset_uris(req)
    assert default_uris == ["urn:ontology:O1:V1"]
    assert named_uris == ["urn:ontology:O1:V1"]


@pytest.mark.anyio
async def test_extract_dataset_uris_repeated_params_kept():
    from ontoexplorer.api.sparql import _extract_dataset_uris
    req = _request("GET", [
        ("default-graph-uri", "urn:a"),
        ("default-graph-uri", "urn:b"),
        ("named-graph-uri", "urn:a"),
        ("named-graph-uri", "urn:b"),
    ])
    default_uris, named_uris = await _extract_dataset_uris(req)
    assert default_uris == ["urn:a", "urn:b"]
    assert named_uris == ["urn:a", "urn:b"]


@pytest.mark.anyio
async def test_extract_dataset_uris_from_post_form_body():
    from ontoexplorer.api.sparql import _extract_dataset_uris
    req = _request(
        "POST",
        form=[
            ("query", "SELECT * WHERE { ?s ?p ?o }"),
            ("default-graph-uri", "urn:a"),
            ("named-graph-uri", "urn:a"),
        ],
    )
    default_uris, named_uris = await _extract_dataset_uris(req)
    assert default_uris == ["urn:a"]
    assert named_uris == ["urn:a"]


@pytest.mark.anyio
async def test_extract_dataset_uris_merges_url_and_form():
    from ontoexplorer.api.sparql import _extract_dataset_uris
    req = _request(
        "POST",
        [("default-graph-uri", "urn:from-url")],
        form=[
            ("query", "SELECT * WHERE { ?s ?p ?o }"),
            ("default-graph-uri", "urn:from-form"),
        ],
    )
    default_uris, named_uris = await _extract_dataset_uris(req)
    assert default_uris == ["urn:from-url", "urn:from-form"]
    assert named_uris == []


@pytest.mark.anyio
async def test_extract_dataset_uris_skips_form_for_sparql_query_content_type():
    """When the POST body is application/sparql-query (raw SPARQL), there's no
    form to parse — graph URIs come only from URL params."""
    from ontoexplorer.api.sparql import _extract_dataset_uris
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/sparql/content",
        "query_string": b"named-graph-uri=urn%3Aa",
        "headers": [(b"content-type", b"application/sparql-query")],
    }

    async def receive():
        return {"type": "http.request", "body": b"SELECT * WHERE { ?s ?p ?o }", "more_body": False}

    req = Request(scope, receive)
    default_uris, named_uris = await _extract_dataset_uris(req)
    assert default_uris == []
    assert named_uris == ["urn:a"]
