"""Resolve an ontology source to raw bytes.

Supports three registration modes:
  - IRI:   HTTP GET with RDF content negotiation; follow redirects
  - URL:   HTTP GET without negotiation (direct file URL)
  - bytes: raw content already in memory (upload / paste)
"""

from dataclasses import dataclass
from enum import StrEnum

import httpx

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
_MAX_SIZE = 512 * 1024 * 1024  # 512 MB hard limit


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
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(iri, headers={"Accept": _RDF_ACCEPT})
        resp.raise_for_status()
        _check_size(resp)
        return ResolvedSource(
            data=resp.content,
            content_type=resp.headers.get("content-type"),
            final_url=str(resp.url),
            mode=SourceMode.IRI,
        )


def resolve_url(url: str) -> ResolvedSource:
    """Fetch ontology from a direct file URL without content negotiation."""
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        _check_size(resp)
        return ResolvedSource(
            data=resp.content,
            content_type=resp.headers.get("content-type"),
            final_url=str(resp.url),
            mode=SourceMode.URL,
        )


def resolve_bytes(data: bytes, content_type: str | None = None) -> ResolvedSource:
    """Wrap already-in-memory bytes (upload / paste)."""
    return ResolvedSource(
        data=data,
        content_type=content_type,
        final_url=None,
        mode=SourceMode.BYTES,
    )


def _check_size(resp: httpx.Response) -> None:
    content_length = resp.headers.get("content-length")
    if content_length and int(content_length) > _MAX_SIZE:
        raise ValueError(f"Response exceeds size limit ({_MAX_SIZE} bytes)")
    if len(resp.content) > _MAX_SIZE:
        raise ValueError(f"Downloaded content exceeds size limit ({_MAX_SIZE} bytes)")
