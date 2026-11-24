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
async def test_https_to_http_downgrade_to_own_peer_host_blocked_no_cleartext_secret(monkeypatch):
    # The peer 302s https->http back to ITS OWN allowlisted host. Must still be
    # refused: an http hop would carry the bearer token in cleartext.
    peer = _configure(
        monkeypatch,
        _peer_json(auth={"kind": "bearer", "secret_ref": "PEER_KEY"}),
        PEER_KEY="tok-xyz",
    )
    schemes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        schemes.append(request.url.scheme)
        # the http hop must never be contacted (so the secret never goes cleartext)
        assert request.url.scheme == "https"
        return httpx.Response(
            302, headers={"Location": f"http://{PEER_HOST}/mod/artefacts"}, request=request
        )

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "blocked_redirect"
    assert "http" not in schemes


@pytest.mark.anyio
async def test_cross_allowlisted_peer_redirect_withholds_auth(monkeypatch):
    # Two allowlisted peers. Peer A (with auth) 302s to peer B's host. B IS
    # contacted (it is allowlisted), but A's secret must NOT travel to B.
    entries = [
        {
            "id": "a",
            "label": "A",
            "base_url": "https://a.test",
            "mod_path": "/mod",
            "adapter": "mod",
            "auth": {"kind": "apikey_param", "name": "apikey", "secret_ref": "PEER_KEY"},
        },
        {"id": "b", "label": "B", "base_url": "https://b.test", "mod_path": "/mod", "adapter": "mod"},
    ]
    monkeypatch.setenv("FEDERATION_PEERS_JSON", json.dumps(entries))
    monkeypatch.setenv("PEER_KEY", "s3cret")
    get_settings.cache_clear()
    peer_a = get_federation_peers()[0]
    assert peer_a.id == "a"

    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "a.test":
            assert request.url.params.get("apikey") == "s3cret"  # A's own host: auth sent
            return httpx.Response(
                302, headers={"Location": "https://b.test/mod/artefacts/final"}, request=request
            )
        # peer B: A's secret must be withheld (host != A's host)
        assert request.url.host == "b.test"
        assert request.url.params.get("apikey") is None
        assert "authorization" not in {h.lower() for h in request.headers}
        return _json_response(request, _COLLECTION)

    rows = await search_artefacts(peer_a, "x", 5, transport=httpx.MockTransport(handler))
    assert len(rows) == 1
    assert "b.test" in hosts  # B really was contacted (the withhold branch ran)


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


class _CountingStream(httpx.AsyncByteStream):
    """A multi-chunk async body that records how many chunks were actually pulled.

    Lets the test prove the client aborts *mid-stream* (streaming cap), not after
    buffering the whole body: a one-shot ``.read()`` would pull every chunk.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.pulled = 0

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for chunk in self._chunks:
            self.pulled += 1
            yield chunk

    async def aclose(self) -> None:
        pass


@pytest.mark.anyio
async def test_oversize_body_aborted_mid_stream(monkeypatch):
    # cap 100 bytes; ten 40-byte chunks (400 total) — the cap is crossed by the
    # 3rd chunk, so the stream must be abandoned long before all ten are pulled.
    peer = _configure(monkeypatch, _peer_json(), FEDERATION_MAX_RESPONSE_BYTES="100")
    chunks = [b"x" * 40 for _ in range(10)]
    stream = _CountingStream(chunks)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, request=request)

    with pytest.raises(FederationFetchError) as exc:
        await search_artefacts(peer, "x", 5, transport=httpx.MockTransport(handler))
    assert exc.value.reason == "oversize"
    assert 0 < stream.pulled < len(chunks), "stream was not aborted mid-transfer"


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
