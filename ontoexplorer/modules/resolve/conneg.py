"""HTTP content negotiation for ontology IRI dereferencing."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Sent on every dereference so shared hosts (w3id.org, OBO PURLs) can identify and
# rate-shape us rather than blanket-blocking an anonymous client.
POLITE_UA = "OntoExplorer-ResolvabilityBot/1.0 (+https://ontoexplorer.dev; dereference check)"

# Ask for RDF in rough fidelity order, then fall back to anything so a server
# that ignores Accept still answers (we judge the response by its Content-Type).
RDF_ACCEPT = (
    "text/turtle,application/rdf+xml,application/ld+json,"
    "application/n-triples,application/n-quads,application/trig,"
    "text/n3;q=0.9,application/owl+xml;q=0.9,*/*;q=0.1"
)

_RDF_TYPES = {
    "text/turtle", "application/x-turtle", "application/rdf+xml", "application/ld+json",
    "application/n-triples", "application/n-quads", "application/trig",
    "text/n3", "text/rdf+n3", "application/owl+xml", "application/xml",  # some servers label RDF/XML this way
}

# Generic/missing content-types that MIGHT be RDF served by a plain file server
# (OBO PURLs → raw .owl, GitHub raw, etc.); these trigger a body sniff.
_GENERIC_TYPES = {"application/octet-stream", "text/plain"}

# RDF signatures to recognise in the first bytes of a body. Bytes-based to skip
# decoding; case-insensitive. Covers Turtle/N3, RDF/XML, OWL, JSON-LD.
_RDF_MARKERS_RE = re.compile(
    rb"@prefix|@base|rdf:RDF|<rdf:|owl:Ontology|<owl:|\"@context\"", re.IGNORECASE)
# An N-Triples/Turtle IRI-subject statement: <iri> <iri> …
_TRIPLE_RE = re.compile(rb"<https?://[^>\s]+>\s+<https?://[^>\s]+>")

_TIMEOUT_S = 10.0
_MAX_REDIRECTS = 5
_SNIFF_CAP = 4096


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> datetime | None:
    """Absolute 'do not retry before' time from a `Retry-After` header, or None.

    Accepts either delta-seconds (``"120"``) or an HTTP-date
    (``"Wed, 01 Jan 2026 12:05:00 GMT"``). Never raises — a malformed value yields
    None so a bad header can't crash the check.
    """
    if not value:
        return None
    now = now or datetime.now(timezone.utc)
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return now + timedelta(seconds=int(value))
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_rdf_content_type(content_type: str | None) -> bool:
    """True if a response `Content-Type` names an RDF serialization.

    Tolerant of charset/q params and case; the bare media type is matched.
    """
    if not content_type:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return media in _RDF_TYPES


def _is_generic_type(content_type: str | None) -> bool:
    """True for a missing or generic content-type (octet-stream / text-plain),
    where the label can't be trusted and we fall back to a body sniff."""
    if not content_type:
        return True
    media = content_type.split(";", 1)[0].strip().lower()
    return media in _GENERIC_TYPES


def _sniff_rdf(resp, cap: int = _SNIFF_CAP) -> bool:
    """Read up to `cap` bytes of the (streamed) response body and decide whether
    it looks like RDF — for servers that serve RDF under a generic content-type.
    Bounded and best-effort; never raises."""
    try:
        buf = b""
        for chunk in resp.iter_bytes():
            buf += chunk
            if len(buf) >= cap:
                break
        head = buf[:cap]
    except Exception:
        return False
    if _RDF_MARKERS_RE.search(head) or _TRIPLE_RE.search(head):
        return True
    low = head.lstrip().lower()
    # XML that declares an RDF/OWL namespace (RDF/XML without a proper label).
    return low.startswith(b"<?xml") and (b"rdf" in low or b"owl" in low)


@dataclass(frozen=True)
class ResolveResult:
    resolvable: bool
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    error: str | None = None
    # ISO-8601 'do not retry before' time parsed from a Retry-After header on a
    # throttled (429/503) response; None when absent/unparseable. Drives the
    # polite re-check cooldown.
    retry_after: str | None = None


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
            with client.stream(
                "GET", iri, headers={"Accept": RDF_ACCEPT, "User-Agent": POLITE_UA}
            ) as resp:
                status = resp.status_code
                ctype = resp.headers.get("content-type")
                final = str(getattr(resp, "url", iri) or iri)
                if not 200 <= status < 300:
                    ra = parse_retry_after(resp.headers.get("retry-after"))
                    return ResolveResult(
                        False, final_url=final, http_status=status, content_type=ctype,
                        retry_after=ra.isoformat() if ra else None,
                    )
                # RDF by its label, OR a generic/missing label whose body sniffs as
                # RDF (OBO PURLs → raw .owl served as octet-stream/text-plain, etc.).
                ok = is_rdf_content_type(ctype) or (_is_generic_type(ctype) and _sniff_rdf(resp))
                return ResolveResult(ok, final_url=final, http_status=status, content_type=ctype)
    except Exception as exc:  # httpx errors, guard rejection, DNS, etc.
        logger.debug("resolvability check failed for %s", iri, exc_info=True)
        return ResolveResult(False, error=str(exc)[:500])
