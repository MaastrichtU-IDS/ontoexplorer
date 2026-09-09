"""The SSRF guard is actually on the ingestion fetch paths, not just available.

A guard that exists but isn't wired in is the failure mode this whole review
kept finding, so these tests drive resolve_url / resolve_iri / _fetch_import and
assert an internal target is refused and the import path is size-capped.
"""
import httpx
import pytest

from ontoexplorer.clients import fetch_guard
from ontoexplorer.clients.fetch_guard import GuardedTransport, SsrfBlocked
from ontoexplorer.config import get_settings
from ontoexplorer.modules.ingestion import import_resolver, source_resolver


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _point_dns_at(monkeypatch, ip):
    """Make every hostname resolve to `ip` for the real guarded_transport()."""
    monkeypatch.setattr(fetch_guard, "_default_resolver", lambda host, port: [ip])


def test_resolve_url_refuses_internal_target(monkeypatch):
    _point_dns_at(monkeypatch, "169.254.169.254")
    with pytest.raises(SsrfBlocked):
        source_resolver.resolve_url("http://metadata.example/latest/meta-data/")


def test_resolve_iri_refuses_loopback(monkeypatch):
    _point_dns_at(monkeypatch, "127.0.0.1")
    with pytest.raises(SsrfBlocked):
        source_resolver.resolve_iri("http://whatever.example/ont")


def test_fetch_import_refuses_internal_target(monkeypatch):
    _point_dns_at(monkeypatch, "10.1.2.3")
    with pytest.raises(SsrfBlocked):
        import_resolver._fetch_import("http://internal.example/import.owl")


def test_fetch_import_is_size_capped(monkeypatch):
    """The import path used to buffer resp.content with no ceiling."""
    monkeypatch.setenv("INGEST_MAX_SOURCE_BYTES", "1024")

    def body():
        for _ in range(100):        # 100 KiB against a 1 KiB cap
            yield b"x" * 1024

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/turtle"}, content=body())

    # allow_private=True skips resolution so the MockTransport body is what's tested.
    monkeypatch.setattr(
        import_resolver, "guarded_transport",
        lambda: GuardedTransport(inner=httpx.MockTransport(handler), allow_private=True),
    )
    with pytest.raises(ValueError, match="size limit"):
        import_resolver._fetch_import("http://host.example/big.owl")
