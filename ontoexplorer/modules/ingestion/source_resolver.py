"""Resolve an ontology source to raw bytes.

Supports three registration modes:
  - IRI:   HTTP GET with RDF content negotiation; follow redirects
  - URL:   HTTP GET without negotiation (direct file URL)
  - bytes: raw content already in memory (upload / paste)
"""

from dataclasses import dataclass
from enum import StrEnum

import httpx

from ontoexplorer.clients.fetch_guard import guarded_transport
from ontoexplorer.config import get_settings

# Accept header for IRI mode — prefer OWL/XML, then Turtle, then RDF/XML, then anything
_RDF_ACCEPT = (
    "application/owl+xml;q=1.0,"
    "text/turtle;q=0.9,"
    "application/rdf+xml;q=0.8,"
    "application/ld+json;q=0.7,"
    "application/n-triples;q=0.6,"
    "text/plain;q=0.5"
)

_TIMEOUT = httpx.Timeout(60.0)


class SourceMode(StrEnum):
    IRI = "iri"
    URL = "url"
    BYTES = "bytes"


@dataclass
class ResolvedSource:
    data: bytes
    content_type: str | None   # as reported by the server (or None for bytes mode)
    final_url: str | None      # URL after redirect resolution (None for bytes mode)
    mode: SourceMode


def resolve_iri(iri: str) -> ResolvedSource:
    """Fetch ontology by canonical IRI with RDF content negotiation."""
    data, content_type, final_url = _fetch(iri, headers={"Accept": _RDF_ACCEPT})
    return ResolvedSource(
        data=data, content_type=content_type, final_url=final_url, mode=SourceMode.IRI,
    )


def resolve_url(url: str) -> ResolvedSource:
    """Fetch ontology from a direct file URL without content negotiation."""
    data, content_type, final_url = _fetch(url, headers=None)
    return ResolvedSource(
        data=data, content_type=content_type, final_url=final_url, mode=SourceMode.URL,
    )


def resolve_bytes(data: bytes, content_type: str | None = None) -> ResolvedSource:
    """Wrap already-in-memory bytes (upload / paste)."""
    return ResolvedSource(
        data=data,
        content_type=content_type,
        final_url=None,
        mode=SourceMode.BYTES,
    )


def _fetch(
    url: str, headers: dict[str, str] | None
) -> tuple[bytes, str | None, str]:
    """GET `url`, streaming the body so the size cap can abort the transfer.

    The cap is checked twice: once against the declared Content-Length (so an
    oversized source costs nothing but the response headers) and again against
    the running byte count while reading (so a chunked response without a
    declared length is abandoned as soon as it crosses the limit) — rather than
    buffering the whole body first and rejecting it afterwards.
    """
    max_size = get_settings().ingest_max_source_bytes
    # transport=guarded_transport(): refuse non-public targets and pin the DNS
    # result, on this request and every redirect hop (see clients/fetch_guard).
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, transport=guarded_transport()) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()

            declared = resp.headers.get("content-length")
            if declared and int(declared) > max_size:
                raise ValueError(
                    f"Response exceeds size limit ({int(declared)} bytes, "
                    f"limit {max_size} bytes)"
                )

            # iter_bytes() with no chunk size yields each decoded network chunk
            # as it arrives, so the cap is tested at the earliest opportunity
            # instead of after re-buffering to a fixed block size.
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if len(buf) > max_size:
                    raise ValueError(
                        f"Downloaded content exceeds size limit ({max_size} bytes)"
                    )

            return bytes(buf), resp.headers.get("content-type"), str(resp.url)
