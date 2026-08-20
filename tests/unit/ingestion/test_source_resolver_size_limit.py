"""Download size-cap behaviour for the ingestion source resolver.

Background: loading DRON (`.../dron/releases/2026-06-04/dron.owl`, 706,398,355
bytes) failed with `ValueError: Response exceeds size limit (536870912 bytes)`.
Two defects: the cap was a hard-coded 512 MiB constant, and it was enforced
only *after* `httpx.Client.get()` had already buffered the whole body into
memory — so a file destined for rejection was still downloaded in full (and
re-downloaded on every Celery retry).

These tests pin the fixed behaviour: the cap is configuration, and it is
enforced *while* streaming so an oversized body is abandoned early.
"""
import httpx
import pytest

from ontoexplorer.config import get_settings
from ontoexplorer.modules.ingestion import source_resolver

# Actual size of dron.owl 2026-06-04 (Content-Length from the GitHub release asset).
DRON_BYTES = 706_398_355


@pytest.fixture(autouse=True)
def _fresh_settings():
    """get_settings() is @lru_cache'd — drop the cache so monkeypatched env applies."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mock_client(monkeypatch, handler):
    """Route every httpx.Client created by source_resolver through `handler`."""
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(source_resolver.httpx, "Client", factory)


def test_default_cap_admits_dron():
    """The default cap must accommodate DRON, the ontology that exposed the bug."""
    assert get_settings().ingest_max_source_bytes >= DRON_BYTES


def test_cap_is_configurable(monkeypatch):
    monkeypatch.setenv("INGEST_MAX_SOURCE_BYTES", "12345")
    assert get_settings().ingest_max_source_bytes == 12345


def test_declared_oversize_aborts_before_reading_the_body(monkeypatch):
    """A Content-Length over the cap must be rejected without touching the body."""
    monkeypatch.setenv("INGEST_MAX_SOURCE_BYTES", "1024")
    consumed = []

    def body():
        consumed.append(1)
        yield b"x" * 4096

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-length": "4096", "content-type": "application/rdf+xml"},
            content=body(),
        )

    _mock_client(monkeypatch, handler)

    with pytest.raises(ValueError, match="size limit"):
        source_resolver.resolve_iri("http://example.org/big.owl")

    assert consumed == [], "body was streamed despite an oversized Content-Length"


def test_undeclared_oversize_aborts_midstream(monkeypatch):
    """Without Content-Length the cap must still stop the transfer early."""
    monkeypatch.setenv("INGEST_MAX_SOURCE_BYTES", "1024")
    chunks_sent = []

    def body():
        for i in range(100):          # 100 KiB total, cap is 1 KiB
            chunks_sent.append(i)
            yield b"x" * 1024

    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "application/rdf+xml"},
            content=body(),
        )

    _mock_client(monkeypatch, handler)

    with pytest.raises(ValueError, match="size limit"):
        source_resolver.resolve_url("http://example.org/big.owl")

    assert len(chunks_sent) < 10, (
        f"streamed {len(chunks_sent)} chunks past a 1 KiB cap — not aborting early"
    )


def test_under_cap_returns_full_payload(monkeypatch):
    monkeypatch.setenv("INGEST_MAX_SOURCE_BYTES", str(1024 * 1024))
    payload = b"<rdf:RDF/>" * 500

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "application/rdf+xml"}, content=payload
        )

    _mock_client(monkeypatch, handler)

    resolved = source_resolver.resolve_iri("http://example.org/small.owl")
    assert resolved.data == payload
    assert resolved.content_type == "application/rdf+xml"
    assert resolved.mode is source_resolver.SourceMode.IRI


def test_http_error_still_raises(monkeypatch):
    """Streaming must not swallow a non-2xx response."""
    def handler(request):
        return httpx.Response(404, content=b"nope")

    _mock_client(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        source_resolver.resolve_iri("http://example.org/missing.owl")
