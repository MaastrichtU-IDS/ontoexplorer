import contextlib

import httpx

from ontoexplorer.modules.resolve.conneg import check_resolvable


class _Resp:
    def __init__(self, status, content_type, url, body: bytes = b""):
        self.status_code = status
        self.headers = {"content-type": content_type} if content_type else {}
        self.url = url
        self._body = body

    def iter_bytes(self):
        yield self._body


class _FakeClient:
    """Mimics httpx.Client.stream(...) as a context manager yielding a response."""
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc

    def __enter__(self): return self
    def __exit__(self, *a): return False

    @contextlib.contextmanager
    def stream(self, method, url, headers=None):
        if self._exc:
            raise self._exc
        yield self._resp


def _factory(resp=None, exc=None):
    return lambda: _FakeClient(resp, exc)


def test_check_resolvable_true_for_rdf():
    r = check_resolvable(
        "https://w3id.org/sulo/",
        client_factory=_factory(_Resp(200, "text/turtle", "https://example.org/sulo.ttl")),
    )
    assert r.resolvable is True
    assert r.http_status == 200
    assert r.content_type == "text/turtle"
    assert r.final_url == "https://example.org/sulo.ttl"


def test_check_resolvable_html_is_not_resolvable():
    r = check_resolvable("https://example.org/onto",
                         client_factory=_factory(_Resp(200, "text/html", "https://example.org/onto")))
    assert r.resolvable is False


def test_check_resolvable_non_2xx_is_false():
    r = check_resolvable("https://example.org/onto",
                         client_factory=_factory(_Resp(404, "text/turtle", "https://example.org/onto")))
    assert r.resolvable is False
    assert r.http_status == 404


def test_check_resolvable_non_http_scheme():
    r = check_resolvable("urn:uuid:1234", client_factory=_factory(_Resp(200, "text/turtle", "x")))
    assert r.resolvable is False
    assert r.error == "non-http scheme"


def test_check_resolvable_timeout_is_false():
    r = check_resolvable("https://example.org/onto",
                         client_factory=_factory(exc=httpx.ConnectTimeout("boom")))
    assert r.resolvable is False
    assert r.error and "boom" in r.error


def test_check_resolvable_sniffs_rdf_under_octet_stream():
    # OBO PURL → raw .owl served as application/octet-stream; body is RDF/XML.
    body = b'<?xml version="1.0"?>\n<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    r = check_resolvable(
        "http://purl.obolibrary.org/obo/omit.owl",
        client_factory=_factory(_Resp(200, "application/octet-stream", "https://x/omit.owl", body)),
    )
    assert r.resolvable is True


def test_check_resolvable_sniffs_turtle_under_text_plain():
    body = b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<x> a owl:Ontology ."
    r = check_resolvable(
        "https://example.org/onto.ttl",
        client_factory=_factory(_Resp(200, "text/plain; charset=utf-8", "https://example.org/onto.ttl", body)),
    )
    assert r.resolvable is True


def test_check_resolvable_generic_but_not_rdf_is_false():
    # text/plain README, not RDF.
    r = check_resolvable(
        "https://example.org/readme",
        client_factory=_factory(_Resp(200, "text/plain", "https://example.org/readme",
                                      b"This repository contains an ontology. See docs.")),
    )
    assert r.resolvable is False


def test_check_resolvable_blocks_redirect_to_private():
    # The guarded transport raises on a redirect that resolves to a private IP;
    # a guard rejection must surface as resolvable=False, not an exception.
    r = check_resolvable(
        "https://w3id.org/evil/",
        client_factory=_factory(exc=httpx.ConnectError("blocked private address 169.254.169.254")),
    )
    assert r.resolvable is False
    assert "169.254" in (r.error or "")
