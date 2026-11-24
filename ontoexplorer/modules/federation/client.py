"""MOD-API federation client: query a remote peer's catalogue, safely.

This is the one place that makes an *outbound* request to a configured peer.
Peers are server-configured and trusted to be the right catalogues, but a peer
(or something impersonating one via a redirect) is still treated as hostile
network: every request goes through the SSRF-guarded transport
(:func:`async_guarded_transport`), redirects are followed by hand so each hop
is re-validated, the response body is streamed with a hard byte cap, and the
per-peer timeout bounds latency.

Auth secrets are resolved from the environment at call time (never stored in
config) and attached **only** to requests whose host is the peer's own host, so
a redirect to another host can never carry the key off to a third party.
"""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlsplit

import httpx

from ontoexplorer.clients.fetch_guard import SsrfBlocked, async_guarded_transport
from ontoexplorer.config import get_settings
from ontoexplorer.modules.federation.adapters import adapter_for
from ontoexplorer.modules.federation.config import (
    Peer,
    PeerAuth,
    peer_host_allowlist,
)
from ontoexplorer.modules.federation.models import ArtefactRow

logger = logging.getLogger(__name__)

_ACCEPT_LD_JSON = "application/ld+json, application/json;q=0.9"

# Internal-only reason, consumed by search_artefacts (fallback) and never
# surfaced to callers: the public reasons are the ones documented below.
_NOT_FOUND = "not_found"


class FederationFetchError(Exception):
    """A federated fetch failed. ``reason`` is a stable, UI-safe token.

    One of: ``"unauthorized"`` (peer returned 401/403), ``"timeout"``,
    ``"oversize"`` (response exceeded ``federation_max_response_bytes``),
    ``"blocked_redirect"`` (a redirect hop was refused by the allowlist /
    scheme-downgrade policy, or blocked by the SSRF guard), or ``"error"``
    (any other transport/HTTP/parse failure).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _default_transport() -> httpx.AsyncBaseTransport:
    """The SSRF-guarded transport used in production.

    Separated so tests can monkeypatch this (or pass ``transport=`` directly)
    and inject an ``httpx.MockTransport`` instead of touching the network.
    """
    return async_guarded_transport()


def _mod_root(peer: Peer) -> str:
    """The MOD-API root for a peer: ``base_url`` + ``mod_path`` (no trailing /)."""
    return (peer.base_url.rstrip("/") + (peer.mod_path or "")).rstrip("/")


def _resolve_secret(auth: PeerAuth | None) -> str | None:
    """Read the peer's secret from the environment at call time.

    A missing env var is not fatal: it degrades to an unauthenticated request
    (which a real peer will answer with 401, surfaced as ``"unauthorized"``)
    rather than crashing the fan-out.
    """
    if auth is None:
        return None
    secret = os.environ.get(auth.secret_ref)
    if not secret:
        logger.warning(
            "federation: auth secret %r for peer is unset; sending unauthenticated",
            auth.secret_ref,
        )
        return None
    return secret


def _apply_auth(
    url: httpx.URL,
    headers: dict[str, str],
    auth: PeerAuth | None,
    secret: str | None,
    peer_host: str,
) -> tuple[httpx.URL, dict[str, str]]:
    """Attach the peer's auth to this request, but only if it targets the peer host.

    On any other host (i.e. after a cross-host redirect) the secret is withheld,
    so a redirect can never exfiltrate the key.
    """
    if not (auth and secret):
        return url, headers
    if (url.host or "").lower() != peer_host:
        return url, headers
    if auth.kind == "apikey_param":
        return url.copy_set_param(auth.name or "apikey", secret), headers
    if auth.kind == "bearer":
        return url, {**headers, "Authorization": f"Bearer {secret}"}
    return url, headers


def _check_redirect(current: httpx.URL, location: str, allow: frozenset[str]) -> httpx.URL:
    """Validate a redirect hop; return the next URL or raise ``blocked_redirect``.

    Policy: refuse ANY https->http downgrade (even to the peer's own host — an
    http hop would carry the auth secret in cleartext), then require the next
    host to be on the peer allowlist. (The SSRF guard additionally blocks
    private/internal targets at connect time.)
    """
    if not location:
        raise FederationFetchError("blocked_redirect")
    nxt = current.join(location)
    host = (nxt.host or "").lower()
    if nxt.scheme not in ("http", "https"):
        raise FederationFetchError("blocked_redirect")
    # Refuse the downgrade outright, before the allowlist decision: a secret must
    # never be re-attached over cleartext, not even back to the peer's own host.
    if current.scheme == "https" and nxt.scheme == "http":
        raise FederationFetchError("blocked_redirect")
    if host not in allow:
        raise FederationFetchError("blocked_redirect")
    return nxt


async def _fetch_json(
    peer: Peer,
    url: httpx.URL,
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> dict:
    """GET ``url``, following redirects by hand, and return the parsed JSON dict.

    Raises :class:`FederationFetchError` on 401/403, timeout, oversize,
    blocked redirect, or any other failure. Raises the internal ``_NOT_FOUND``
    reason on 404 so :func:`search_artefacts` can fall back; other callers map
    it to ``"error"``.
    """
    settings = get_settings()
    max_bytes = settings.federation_max_response_bytes
    max_redirects = settings.federation_max_redirects

    transport = transport if transport is not None else _default_transport()
    timeout = httpx.Timeout(peer.timeout_ms / 1000)
    peer_host = (urlsplit(peer.base_url).hostname or "").lower()
    allow = peer_host_allowlist()
    secret = _resolve_secret(peer.auth)

    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=timeout, follow_redirects=False
        ) as http:
            current = url
            for _ in range(max_redirects + 1):
                req_url, req_headers = _apply_auth(
                    current, {"Accept": _ACCEPT_LD_JSON}, peer.auth, secret, peer_host
                )
                request = http.build_request("GET", req_url, headers=req_headers)
                resp = await http.send(request, stream=True)
                try:
                    if resp.is_redirect:
                        current = _check_redirect(
                            current, resp.headers.get("location", ""), allow
                        )
                        continue
                    if resp.status_code in (401, 403):
                        raise FederationFetchError("unauthorized")
                    if resp.status_code == 404:
                        raise FederationFetchError(_NOT_FOUND)
                    if resp.status_code >= 400:
                        raise FederationFetchError("error")
                    body = await _read_capped(resp, max_bytes)
                finally:
                    await resp.aclose()
                return json.loads(body)
            # Exhausted the redirect budget while still being redirected.
            raise FederationFetchError("blocked_redirect")
    except FederationFetchError:
        raise
    except httpx.TimeoutException as exc:
        raise FederationFetchError("timeout") from exc
    except SsrfBlocked as exc:
        # The guard refused an internal/private target (initial host or a hop).
        raise FederationFetchError("blocked_redirect") from exc
    except Exception as exc:  # transport error, bad JSON, etc.
        # Log the typed reason / exception class, NOT the raw exception str — for an
        # apikey_param peer the key rides in the query string and some httpx errors
        # stringify the URL, which would leak the secret into our logs.
        logger.info(
            "federation: fetch failed for peer %s: %s",
            peer.id, getattr(exc, "reason", None) or type(exc).__name__,
        )
        raise FederationFetchError("error") from exc


async def _read_capped(resp: httpx.Response, max_bytes: int) -> bytes:
    """Stream the body, aborting as soon as it exceeds ``max_bytes``."""
    buf = bytearray()
    async for chunk in resp.aiter_bytes():
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise FederationFetchError("oversize")
    return bytes(buf)


async def fetch_mod_json(
    peer: Peer,
    url: httpx.URL | str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Public, SSRF-guarded GET of an arbitrary peer MOD-API URL, returning parsed JSON.

    Thin wrapper over :func:`_fetch_json` for callers outside this module (e.g.
    the discovery harvest source). Raises :class:`FederationFetchError`.
    """
    if not isinstance(url, httpx.URL):
        url = httpx.URL(url)
    return await _fetch_json(peer, url, transport=transport)


async def search_artefacts(
    peer: Peer,
    q: str,
    limit: int,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[ArtefactRow]:
    """Search one peer's MOD-API for artefacts matching ``q``; return parsed rows.

    Hits ``{base_url}{mod_path}/artefacts?q=...&page_size=limit``. If that
    endpoint is absent (404) — some peers' ``/artefacts`` lacks a ``q`` filter —
    falls back to ``{base_url}{mod_path}/search/metadata?q=...``. The response is
    normalised to :class:`ArtefactRow` by the peer's configured adapter.
    """
    root = _mod_root(peer)
    params = {"q": q, "page_size": str(limit)}
    primary = httpx.URL(f"{root}/artefacts", params=params)
    try:
        doc = await _fetch_json(peer, primary, transport=transport)
    except FederationFetchError as exc:
        if exc.reason != _NOT_FOUND:
            raise
        fallback = httpx.URL(f"{root}/search/metadata", params=params)
        try:
            doc = await _fetch_json(peer, fallback, transport=transport)
        except FederationFetchError as exc2:
            raise FederationFetchError(
                "error" if exc2.reason == _NOT_FOUND else exc2.reason
            ) from exc2
    return adapter_for(peer.adapter)(doc, peer)


async def fetch_catalogue(
    peer: Peer,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """GET the peer's MOD-API catalogue node (``{base_url}{mod_path}/``).

    Returns the raw JSON-LD document (for config-validation / health checks).
    """
    url = httpx.URL(f"{_mod_root(peer)}/")
    try:
        return await _fetch_json(peer, url, transport=transport)
    except FederationFetchError as exc:
        if exc.reason == _NOT_FOUND:
            raise FederationFetchError("error") from exc
        raise
