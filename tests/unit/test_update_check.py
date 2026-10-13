"""Tests for ingestion.update_check — the upstream-update detector.

Covers the pure helpers (target selection, version parsing, versionIRI/versionInfo
extraction) and the classify-against-current logic (up_to_date / older_skipped /
update_available) with a stubbed HTTP fetch.
"""
import hashlib
import types

from ontoexplorer.modules.ingestion import update_check as uc


class _Ont:
    def __init__(self, iri=None):
        self.iri = iri


class _Ver:
    def __init__(self, sha256=None, version_iri=None, source_url=None):
        self.sha256 = sha256
        self.version_iri = version_iri
        self.source_url = source_url


# ── fetch_target: IRI first, source_url fallback ────────────────────────────────

def test_fetch_target_prefers_iri():
    url, conneg = uc.fetch_target(_Ont(iri="http://ex.org/o.owl"),
                                  _Ver(source_url="http://lov/snap/2016.n3"))
    assert url == "http://ex.org/o.owl" and conneg is True


def test_fetch_target_falls_back_to_source_url():
    url, conneg = uc.fetch_target(_Ont(iri=None), _Ver(source_url="http://host/download"))
    assert url == "http://host/download" and conneg is False


def test_fetch_target_none_when_neither():
    assert uc.fetch_target(_Ont(iri=None), _Ver(source_url=None)) == (None, False)


# ── version_key ─────────────────────────────────────────────────────────────────

def test_version_key_semver_and_date():
    assert uc.version_key("http://x/ontology/sio/v1.62/sio-release.owl") == (1, 62)
    assert uc.version_key("2024-05-01") == (2024, 5, 1)
    assert uc.version_key(None) == ()
    assert uc.version_key("no-digits-here") == ()


def test_version_key_orders_correctly():
    assert uc.version_key("v1.62") > uc.version_key("v1.61")
    assert uc.version_key("v1.34.0") < uc.version_key("v1.61")


# ── extract_upstream_version across syntaxes ────────────────────────────────────

def test_extract_versioniri_rdfxml():
    body = b'<owl:versionIRI rdf:resource="http://x/sio/v1.62/sio.owl"/>'
    assert uc.extract_upstream_version(body) == "http://x/sio/v1.62/sio.owl"


def test_extract_versioniri_turtle():
    body = b'<http://x/sio> owl:versionIRI <http://x/sio/v1.62/sio.owl> .'
    assert uc.extract_upstream_version(body) == "http://x/sio/v1.62/sio.owl"


def test_extract_versioninfo_turtle():
    body = b'<http://x/o> owl:versionInfo "1.62" .'
    assert uc.extract_upstream_version(body) == "1.62"


def test_extract_none_when_absent():
    assert uc.extract_upstream_version(b"<rdf:RDF></rdf:RDF>") is None


# ── check_for_update (stubbed HTTP) ─────────────────────────────────────────────

def _stub_httpx(monkeypatch, body: bytes, status: int = 200):
    """Replace httpx.AsyncClient with a fake returning *body*."""
    class _Resp:
        content = body
        def raise_for_status(self):
            if status >= 400:
                import httpx
                raise httpx.HTTPStatusError("err", request=None,
                                            response=types.SimpleNamespace(status_code=status))
    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()
    monkeypatch.setattr(uc.httpx, "AsyncClient", _Client)


SIO_162 = b'<owl:versionIRI rdf:resource="http://semanticscience.org/ontology/sio/v1.62/sio-release.owl"/>'


async def test_no_source():
    r = await uc.check_for_update(_Ont(iri=None), _Ver(source_url=None))
    assert r["status"] == "no_source"


async def test_up_to_date_identical_sha(monkeypatch):
    _stub_httpx(monkeypatch, SIO_162)
    cur = _Ver(sha256=hashlib.sha256(SIO_162).hexdigest(), version_iri="…/v1.62/…")
    r = await uc.check_for_update(_Ont(iri="http://x/o.owl"), cur)
    assert r["status"] == "up_to_date"


async def test_update_available_newer(monkeypatch):
    _stub_httpx(monkeypatch, SIO_162)
    cur = _Ver(sha256="different", version_iri="http://x/sio/v1.61/sio.owl")
    r = await uc.check_for_update(_Ont(iri="http://x/o.owl"), cur)
    assert r["status"] == "update_available"
    assert r["use_conneg"] is True
    assert "v1.62" in (r["fetched_version"] or "")


async def test_older_upstream_skipped(monkeypatch):
    # Upstream serves v1.62, but our current is already v1.63 -> don't regress.
    _stub_httpx(monkeypatch, SIO_162)
    cur = _Ver(sha256="different", version_iri="http://x/sio/v1.63/sio.owl")
    r = await uc.check_for_update(_Ont(iri="http://x/o.owl"), cur)
    assert r["status"] == "older_skipped"


async def test_fetch_error(monkeypatch):
    _stub_httpx(monkeypatch, b"", status=503)
    cur = _Ver(sha256="x", version_iri="http://x/sio/v1.61/sio.owl")
    r = await uc.check_for_update(_Ont(iri="http://x/o.owl"), cur)
    assert r["status"] == "fetch_error"
