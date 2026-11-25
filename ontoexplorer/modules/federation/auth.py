"""Shared federation auth helpers.

Security-critical logic used by both the federation client and the ingestion
source resolver: resolving a peer's secret from the environment, attaching it
only to requests aimed at the peer's own host, and looking a peer up by host.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

import httpx

from ontoexplorer.modules.federation.config import Peer, PeerAuth, get_federation_peers

logger = logging.getLogger(__name__)


def resolve_secret(auth: PeerAuth | None) -> str | None:
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


def apply_auth(
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


def peer_for_host(host: str | None) -> Peer | None:
    """The configured peer whose base URL host equals ``host`` (case-insensitive).

    Returns ``None`` for no match or a falsy ``host``.
    """
    if not host:
        return None
    wanted = host.lower()
    for p in get_federation_peers():
        peer_host = urlsplit(p.base_url).hostname
        if peer_host and peer_host.lower() == wanted:
            return p
    return None
