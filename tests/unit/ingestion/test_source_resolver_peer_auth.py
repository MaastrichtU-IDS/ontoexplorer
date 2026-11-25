"""Federation peer auth on ingestion downloads.

The source resolver attaches a configured peer's API key to a download only when
the target host is that peer's own host, and withholds it on any other host
(including after a cross-host redirect). The key must never be persisted or
leak off the peer host.
"""
import json

import httpx
import pytest

from ontoexplorer.config import get_settings
from ontoexplorer.modules.ingestion import source_resolver

PEER_HOST = "peer.test"
OTHER_HOST = "cdn.example.org"
SECRET = "s3cret-key"
PAYLOAD = b"<rdf:RDF/>" * 50


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    for k in ("FEDERATION_ENABLED", "FEDERATION_PEERS_JSON", "PEER_KEY"):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mock_client(monkeypatch, handler):
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(source_resolver.httpx, "Client", factory)


def _configure_peer(monkeypatch, auth: dict, *, secret: str | None = SECRET):
    monkeypatch.setenv(
        "FEDERATION_PEERS_JSON",
        json.dumps(
            [
                {
                    "id": "self",
                    "label": "Self",
                    "base_url": f"https://{PEER_HOST}",
                    "mod_path": "/mod",
                    "adapter": "mod",
                    "timeout_ms": 2000,
                    "auth": auth,
                }
            ]
        ),
    )
    if secret is not None:
        monkeypatch.setenv("PEER_KEY", secret)
    get_settings.cache_clear()


_APIKEY = {"kind": "apikey_param", "name": "apikey", "secret_ref": "PEER_KEY"}
_BEARER = {"kind": "bearer", "secret_ref": "PEER_KEY"}


def _ok(request):
    return httpx.Response(
        200, headers={"content-type": "application/rdf+xml"}, content=PAYLOAD
    )


def test_non_peer_host_gets_no_key(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.params.get("apikey") is None
        assert "authorization" not in request.headers
        return _ok(request)

    _mock_client(monkeypatch, handler)
    resolved = source_resolver.resolve_url(f"https://{OTHER_HOST}/x.owl")
    assert resolved.data == PAYLOAD
    assert len(seen) == 1


def test_peer_host_gets_apikey_param(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.params["apikey"] == SECRET
        return _ok(request)

    _mock_client(monkeypatch, handler)
    resolved = source_resolver.resolve_url(f"https://{PEER_HOST}/ontologies/AGRO/download")
    assert resolved.data == PAYLOAD
    assert resolved.content_type == "application/rdf+xml"
    assert len(seen) == 1


def test_peer_host_match_is_case_insensitive(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)

    def handler(request):
        assert request.url.params["apikey"] == SECRET
        return _ok(request)

    _mock_client(monkeypatch, handler)
    resolved = source_resolver.resolve_iri("https://PEER.test/ontologies/AGRO/download")
    assert resolved.data == PAYLOAD


def test_missing_secret_sends_unauthenticated_without_crash(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY, secret=None)

    def handler(request):
        assert request.url.params.get("apikey") is None
        assert "authorization" not in request.headers
        return _ok(request)

    _mock_client(monkeypatch, handler)
    resolved = source_resolver.resolve_url(f"https://{PEER_HOST}/ontologies/AGRO/download")
    assert resolved.data == PAYLOAD


def test_cross_host_redirect_withholds_key(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)
    seen = []

    def handler(request):
        seen.append((request.url.host, request.url.params.get("apikey")))
        if request.url.host == PEER_HOST:
            assert request.url.params["apikey"] == SECRET
            return httpx.Response(
                302, headers={"location": f"https://{OTHER_HOST}/files/agro.owl"}
            )
        assert request.url.params.get("apikey") is None
        assert "authorization" not in request.headers
        return _ok(request)

    _mock_client(monkeypatch, handler)
    resolved = source_resolver.resolve_url(f"https://{PEER_HOST}/ontologies/AGRO/download")
    assert resolved.data == PAYLOAD
    assert seen == [(PEER_HOST, SECRET), (OTHER_HOST, None)]
    assert SECRET not in (resolved.final_url or "")


def test_https_to_http_downgrade_on_peer_host_refused(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)

    def handler(request):
        if request.url.scheme == "https":
            return httpx.Response(302, headers={"location": f"http://{PEER_HOST}/dl"})
        raise AssertionError("downgraded request must never be sent")

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="downgrade"):
        source_resolver.resolve_url(f"https://{PEER_HOST}/ontologies/AGRO/download")


def test_redirect_loop_is_bounded(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)

    def handler(request):
        return httpx.Response(302, headers={"location": f"https://{PEER_HOST}/again"})

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="too many redirects"):
        source_resolver.resolve_url(f"https://{PEER_HOST}/start")


def test_redirect_without_location_raises(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)

    def handler(request):
        return httpx.Response(302)

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="redirect without location"):
        source_resolver.resolve_url(f"https://{PEER_HOST}/start")


def test_authed_declared_oversize_aborts_before_reading_body(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)
    monkeypatch.setenv("INGEST_MAX_SOURCE_BYTES", "1024")
    get_settings.cache_clear()
    consumed = []

    def body():
        consumed.append(1)
        yield b"x" * 4096

    def handler(request):
        assert request.url.params["apikey"] == SECRET
        return httpx.Response(
            200, headers={"content-length": "4096"}, content=body()
        )

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="size limit"):
        source_resolver.resolve_url(f"https://{PEER_HOST}/big")
    assert consumed == []


def test_authed_undeclared_oversize_aborts_midstream(monkeypatch):
    _configure_peer(monkeypatch, _APIKEY)
    monkeypatch.setenv("INGEST_MAX_SOURCE_BYTES", "1024")
    get_settings.cache_clear()
    sent = []

    def body():
        for i in range(100):
            sent.append(i)
            yield b"x" * 1024

    def handler(request):
        assert request.url.params["apikey"] == SECRET
        return httpx.Response(200, content=body())

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="size limit"):
        source_resolver.resolve_url(f"https://{PEER_HOST}/big")
    assert len(sent) < 10


def test_bearer_only_on_peer_host(monkeypatch):
    _configure_peer(monkeypatch, _BEARER)
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == PEER_HOST:
            assert request.headers["authorization"] == f"Bearer {SECRET}"
            assert request.url.params.get("apikey") is None
            return httpx.Response(
                302, headers={"location": f"https://{OTHER_HOST}/files/agro.owl"}
            )
        assert "authorization" not in request.headers
        return _ok(request)

    _mock_client(monkeypatch, handler)
    resolved = source_resolver.resolve_url(f"https://{PEER_HOST}/ontologies/AGRO/download")
    assert resolved.data == PAYLOAD
    assert seen == [(PEER_HOST, f"Bearer {SECRET}"), (OTHER_HOST, None)]


def test_authed_error_does_not_log_key(monkeypatch, caplog):
    _configure_peer(monkeypatch, _APIKEY)

    def handler(request):
        return httpx.Response(500, content=b"boom")

    _mock_client(monkeypatch, handler)
    with caplog.at_level("DEBUG"):
        with pytest.raises(httpx.HTTPStatusError):
            source_resolver.resolve_url(f"https://{PEER_HOST}/x")
    assert SECRET not in caplog.text
