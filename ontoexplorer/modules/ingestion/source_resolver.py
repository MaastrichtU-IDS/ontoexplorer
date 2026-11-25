"""Resolve an ontology source to raw bytes.

Supports three registration modes:
  - IRI:   HTTP GET with RDF content negotiation; follow redirects
  - URL:   HTTP GET without negotiation (direct file URL)
  - bytes: raw content already in memory (upload / paste)
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

import httpx

from ontoexplorer.clients.fetch_guard import guarded_transport
from ontoexplorer.config import get_settings
from ontoexplorer.modules.federation.auth import apply_auth, peer_for_host, resolve_secret
from ontoexplorer.modules.federation.config import PeerAuth

logger = logging.getLogger(__name__)

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

# Redirect budget for the authenticated (peer-host) fetch path, which follows
# redirects manually so the key can be withheld on any off-host hop.
_MAX_REDIRECTS = 5


class PeerAuthDownloadError(Exception):
    """An authenticated (peer-host) download failed.

    Deliberately NOT an httpx error: httpx stringifies the request URL, which
    carries an apikey_param key. This message mentions only a redacted URL and
    the status code. A plain Exception, so the ingest task's retry still applies.
    """


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


def _stream_capped(resp: httpx.Response, max_size: int) -> bytes:
    """Read the body of `resp`, enforcing the size cap.

    The cap is checked twice: once against the declared Content-Length (so an
    oversized source costs nothing but the response headers) and again against
    the running byte count while reading (so a chunked response without a
    declared length is abandoned as soon as it crosses the limit) — rather than
    buffering the whole body first and rejecting it afterwards.
    """
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
    return bytes(buf)


def _fetch(
    url: str, headers: dict[str, str] | None
) -> tuple[bytes, str | None, str]:
    """GET `url`, streaming the body so the size cap can abort the transfer.

    If `url` is on a configured federation peer's host (and its secret is
    available), the peer's API key is attached — on that host only; see
    `_fetch_authed`. Otherwise this is a plain, unauthenticated download.
    """
    max_size = get_settings().ingest_max_source_bytes

    peer = peer_for_host(urlsplit(url).hostname)
    secret = resolve_secret(peer.auth) if peer else None
    if peer is not None and secret is not None:
        peer_host = (urlsplit(peer.base_url).hostname or "").lower()
        return _fetch_authed(url, headers, peer_host, peer.auth, secret, max_size)

    # transport=guarded_transport(): refuse non-public targets and pin the DNS
    # result, on this request and every redirect hop (see clients/fetch_guard).
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, transport=guarded_transport()) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            return _stream_capped(resp, max_size), resp.headers.get("content-type"), str(resp.url)


def _fetch_authed(
    url: str,
    headers: dict[str, str] | None,
    peer_host: str,
    auth: PeerAuth | None,
    secret: str,
    max_size: int,
) -> tuple[bytes, str | None, str]:
    """Like the plain fetch, but attaches the peer's key while on the peer host.

    Redirects are followed by hand so each hop is re-evaluated: `apply_auth`
    withholds the key as soon as `current` is no longer the peer host, and an
    https->http downgrade on the peer host is refused (it would carry the key
    in cleartext). Nothing here logs a URL or an exception string — an
    apikey_param key rides in the query string.
    """
    current = httpx.URL(url)
    req_url = current
    failure: tuple[int | None, str, str] | None = None
    try:
        with httpx.Client(
            timeout=_TIMEOUT, follow_redirects=False, transport=guarded_transport()
        ) as client:
            for _ in range(_MAX_REDIRECTS):
                req_url, req_headers = apply_auth(
                    current, {**(headers or {})}, auth, secret, peer_host
                )
                with client.stream("GET", req_url, headers=req_headers) as resp:
                    if resp.is_redirect:
                        loc = resp.headers.get("location")
                        if not loc:
                            raise ValueError("redirect without location")
                        nxt = resp.url.join(loc)
                        if (
                            (current.host or "").lower() == peer_host
                            and current.scheme == "https"
                            and nxt.scheme == "http"
                        ):
                            raise ValueError(
                                "refusing https->http downgrade on the peer host"
                            )
                        current = nxt
                        continue
                    resp.raise_for_status()
                    return (
                        _stream_capped(resp, max_size),
                        resp.headers.get("content-type"),
                        str(resp.url),
                    )
            raise ValueError("too many redirects")
    except httpx.HTTPError as exc:
        # httpx stringifies the request URL (HTTPStatusError, transport errors),
        # and an apikey_param key rides in it. Record only what is safe, and
        # raise the scrubbed error below, OUTSIDE this block, so neither
        # __cause__ nor __context__ carries the original exception.
        redacted = req_url
        if (
            auth is not None
            and auth.kind == "apikey_param"
            and (auth.name or "apikey") in req_url.params
        ):
            redacted = req_url.copy_set_param(auth.name or "apikey", "REDACTED")
        status = getattr(getattr(exc, "response", None), "status_code", None)
        failure = (status, str(redacted), type(exc).__name__)
    # ValueError (size cap, redirect policy) carries no URL and propagates as-is.

    status, redacted_url, exc_name = failure
    logger.warning(
        "ingest: authenticated fetch from peer host %s failed (%s)", peer_host, exc_name
    )
    raise PeerAuthDownloadError(
        f"peer download failed (status={status}) for {redacted_url}"
    ) from None
