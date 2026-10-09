"""HTTP content negotiation for ontology IRI dereferencing."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Ask for RDF in rough fidelity order, then fall back to anything so a server
# that ignores Accept still answers (we judge the response by its Content-Type).
RDF_ACCEPT = (
    "text/turtle,application/rdf+xml,application/ld+json,"
    "application/n-triples,application/n-quads,application/trig,"
    "text/n3;q=0.9,application/owl+xml;q=0.9,*/*;q=0.1"
)

_RDF_TYPES = {
    "text/turtle", "application/rdf+xml", "application/ld+json",
    "application/n-triples", "application/n-quads", "application/trig",
    "text/n3", "application/owl+xml", "application/xml",  # some servers label RDF/XML this way
}

_TIMEOUT_S = 10.0
_MAX_REDIRECTS = 5


def is_rdf_content_type(content_type: str | None) -> bool:
    """True if a response `Content-Type` names an RDF serialization.

    Tolerant of charset/q params and case; the bare media type is matched.
    """
    if not content_type:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return media in _RDF_TYPES


@dataclass(frozen=True)
class ResolveResult:
    resolvable: bool
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    error: str | None = None


def _default_client_factory():
    import httpx
    from ontoexplorer.clients.fetch_guard import guarded_transport
    return lambda: httpx.Client(
        timeout=_TIMEOUT_S,
        follow_redirects=True,
        max_redirects=_MAX_REDIRECTS,
        transport=guarded_transport(),   # SSRF guard on EVERY hop incl. redirects
        trust_env=False,
    )


def check_resolvable(iri: str, *, client_factory=None) -> ResolveResult:
    """Best-effort: does `iri` dereference to RDF via content negotiation?

    Read-only, bounded (no body download — status + Content-Type only), and
    SSRF-guarded. Never raises: any failure is reported as resolvable=False.
    """
    scheme = urlparse(iri).scheme.lower()
    if scheme not in ("http", "https"):
        return ResolveResult(False, error="non-http scheme")

    factory = client_factory or _default_client_factory()
    try:
        with factory() as client:
            with client.stream("GET", iri, headers={"Accept": RDF_ACCEPT}) as resp:
                status = resp.status_code
                ctype = resp.headers.get("content-type")
                final = str(getattr(resp, "url", iri) or iri)
                ok = 200 <= status < 300 and is_rdf_content_type(ctype)
                return ResolveResult(ok, final_url=final, http_status=status, content_type=ctype)
    except Exception as exc:  # httpx errors, guard rejection, DNS, etc.
        logger.debug("resolvability check failed for %s", iri, exc_info=True)
        return ResolveResult(False, error=str(exc)[:500])
