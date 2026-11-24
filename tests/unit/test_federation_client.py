"""Unit tests for the MOD-API federation client.

Every test injects an ``httpx.MockTransport`` (no network). The peer host
allowlist used by the redirect policy is built the real way: by setting
``FEDERATION_PEERS_JSON`` and clearing the settings cache, mirroring
``tests/unit/test_federation_config.py``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ontoexplorer.clients.fetch_guard import SsrfBlocked
from ontoexplorer.config import get_settings
from ontoexplorer.modules.federation.client import (
    FederationFetchError,
    fetch_catalogue,
    search_artefacts,
)
from ontoexplorer.modules.federation.config import get_federation_peers
from ontoexplorer.modules.federation.models import ArtefactRow

PEER_HOST = "peer.test"
PEER_BASE = f"https://{PEER_HOST}"


def _peer_json(*, auth: dict | None = None, mod_path: str = "/mod", adapter: str = "mod") -> str:
    entry: dict = {
        "id": "self",
        "label": "Self",
        "base_url": PEER_BASE,
        "mod_path": mod_path,
        "adapter": adapter,
        "timeout_ms": 2000,
    }
    if auth is not None:
        entry["auth"] = auth
    return json.dumps([entry])


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (
        "FEDERATION_ENABLED",
        "FEDERATION_PEERS_JSON",
        "FEDERATION_MAX_RESPONSE_BYTES",
        "FEDERATION_MAX_REDIRECTS",
        "PEER_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure(monkeypatch, peer_json: str, **env: str):
    monkeypatch.setenv("FEDERATION_PEERS_JSON", peer_json)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    peers = get_federation_peers()
    assert peers, "peer config did not parse"
    return peers[0]


# A minimal MOD JSON-LD artefact collection the default adapter can parse.
_COLLECTION = {
    "@context": {
        "dcterms": "http://purl.org/dc/terms/",
        "mod": "https://w3id.org/mod#",
        "hydra": "http://www.w3.org/ns/hydra/core#",
    },
    "@type": "hydra:Collection",
    "hydra:member": [
        {
            "@id": "https://peer.test/ontology/AGRO",
            "@type": "mod:SemanticArtefact",
            "mod:acronym": "AGRO",
            "dcterms:title": "Agronomy Ontology",
        }
    ],
}


def _json_response(request: httpx.Request, payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=request)


# --------------------------------------------------------------------- auth


@pytest.mark.anyio
async def test_apikey_param_only_on_peer_host(monkeypatch):
    peer = _configure(
        monkeypatch,
        _peer_json(auth={"kind": "apikey_param", "name": "apikey", "secret_ref": "PEER_KEY"}),
        PEER_KEY="s3cret",
    )
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        assert request.url.host == PEER_HOST
        assert request.url.params.get("apikey") == "s3cret"
        assert "authorization" not in {h.lower() for h in request.headers}
        return _json_response(request, _COLLECTION)

    rows = await search_artefacts(peer, "agro", 10, transport=httpx.MockTransport(handler))
    assert len(rows) == 1 and rows[0].acronym == "AGRO"
    assert seen and all(u.host == PEER_HOST for u in seen)


@pytest.mark.anyio
async def test_bearer_sets_authorization_header(monkeypatch):
    peer = _configure(
        monkeypatch,
        _peer_json(auth={"kind": "bearer", "secret_ref": "PEER_KEY"}),
        PEER_KEY="tok-123",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer tok-123"
        assert request.url.params.get("apikey") is None
        return _json_response(request, _COLLECTION)

    rows = await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert len(rows) == 1


@pytest.mark.anyio
async def test_missing_secret_env_sends_no_auth_and_does_not_crash(monkeypatch):
    # auth configured, but PEER_KEY not in the environment.
    peer = _configure(
        monkeypatch,
        _peer_json(auth={"kind": "apikey_param", "name": "apikey", "secret_ref": "PEER_KEY"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("apikey") is None
        return _json_response(request, _COLLECTION)

    rows = await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert len(rows) == 1


# --------------------------------------------------------------------- status


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 403])
async def test_unauthorized_status(monkeypatch, status):
    peer = _configure(monkeypatch, _peer_json())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={}, request=request)

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "unauthorized"


@pytest.mark.anyio
async def test_server_error_maps_to_error(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom", request=request)

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "error"


# --------------------------------------------------------------------- redirects


@pytest.mark.anyio
async def test_redirect_to_loopback_is_blocked(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "http://127.0.0.1:8080/mod/artefacts"}, request=request
        )

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "blocked_redirect"


@pytest.mark.anyio
async def test_redirect_to_non_allowlisted_host_blocked_and_no_auth_leak(monkeypatch):
    peer = _configure(
        monkeypatch,
        _peer_json(auth={"kind": "apikey_param", "name": "apikey", "secret_ref": "PEER_KEY"}),
        PEER_KEY="s3cret",
    )
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        # the secret must never reach a non-peer host
        if request.url.host != PEER_HOST:
            assert request.url.params.get("apikey") is None
        return httpx.Response(
            302, headers={"Location": "https://evil.example.com/x"}, request=request
        )

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "blocked_redirect"
    # the evil host was never contacted at all (so the secret never left)
    assert "evil.example.com" not in hosts


@pytest.mark.anyio
async def test_https_to_http_downgrade_to_non_allowlisted_refused(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "http://other.example.org/mod/artefacts"}, request=request
        )

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "blocked_redirect"


@pytest.mark.anyio
async def test_guard_ssrf_block_maps_to_blocked_redirect(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())

    def handler(request: httpx.Request) -> httpx.Response:
        raise SsrfBlocked("resolves to a non-public address")

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "blocked_redirect"


@pytest.mark.anyio
async def test_allowlisted_same_host_redirect_is_followed(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                302, headers={"Location": f"{PEER_BASE}/mod/artefacts/final"}, request=request
            )
        return _json_response(request, _COLLECTION)

    rows = await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert len(rows) == 1 and calls["n"] == 2


# --------------------------------------------------------------------- size cap


@pytest.mark.anyio
async def test_oversize_body_aborted(monkeypatch):
    peer = _configure(monkeypatch, _peer_json(), FEDERATION_MAX_RESPONSE_BYTES="128")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000, request=request)

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "oversize"


# --------------------------------------------------------------------- timeout


@pytest.mark.anyio
async def test_timeout_maps_to_timeout(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow peer", request=request)

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "timeout"


# --------------------------------------------------------------------- happy path


@pytest.mark.anyio
async def test_happy_path_parses_rows_via_adapter(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())
    captured: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url)
        return _json_response(request, _COLLECTION)

    rows = await search_artefacts(peer, "agro", 7, transport=httpx.MockTransport(handler))
    assert all(isinstance(r, ArtefactRow) for r in rows)
    assert rows[0].iri == "https://peer.test/ontology/AGRO"
    assert rows[0].source.id == "self"
    # URL is {base_url}{mod_path}/artefacts with q + page_size
    u = captured[0]
    assert str(u).startswith(f"{PEER_BASE}/mod/artefacts")
    assert u.params.get("q") == "agro"
    assert u.params.get("page_size") == "7"


@pytest.mark.anyio
async def test_fetch_catalogue_returns_raw_dict(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())
    captured: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url)
        assert "ld+json" in request.headers.get("accept", "")
        return _json_response(request, _COLLECTION)

    doc = await fetch_catalogue(peer, transport=httpx.MockTransport(handler))
    assert isinstance(doc, dict) and doc.get("@type") == "hydra:Collection"
    assert str(captured[0]) == f"{PEER_BASE}/mod/"


@pytest.mark.anyio
async def test_artefacts_404_falls_back_to_metadata_search(monkeypatch):
    peer = _configure(monkeypatch, _peer_json())
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/mod/artefacts":
            return httpx.Response(404, text="no such endpoint", request=request)
        return _json_response(request, _COLLECTION)

    rows = await search_artefacts(peer, "agro", 5, transport=httpx.MockTransport(handler))
    assert len(rows) == 1
    assert paths == ["/mod/artefacts", "/mod/search/metadata"]
