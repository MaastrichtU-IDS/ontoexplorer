"""Federation peer configuration.

Peers come from the ``FEDERATION_PEERS_JSON`` setting: a JSON list of objects
``{id, label, base_url, mod_path?, adapter?, timeout_ms?, auth?}``. Parsing is
defensive: malformed JSON yields ``[]`` and a bad individual entry is skipped,
each with a logged warning, so configuration can never break boot.

Secrets are never held here. ``auth.secret_ref`` is the *name* of an
environment variable; it is resolved at call time by the client.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from ontoexplorer.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_PEER_TIMEOUT_MS = 5000
DEFAULT_MOD_PATH = ""
DEFAULT_ADAPTER = "mod"

AuthKind = Literal["apikey_param", "bearer"]
_AUTH_KINDS = ("apikey_param", "bearer")


@dataclass(frozen=True)
class PeerAuth:
    kind: AuthKind
    secret_ref: str  # env var NAME holding the secret; never the secret itself
    name: str | None = None  # query-param name for apikey_param


@dataclass(frozen=True)
class Peer:
    id: str
    label: str
    base_url: str
    mod_path: str = DEFAULT_MOD_PATH
    adapter: str = DEFAULT_ADAPTER
    timeout_ms: int = DEFAULT_PEER_TIMEOUT_MS
    auth: PeerAuth | None = None


def _parse_auth(raw: object) -> PeerAuth | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("auth must be an object")
    kind = raw.get("kind")
    if kind not in _AUTH_KINDS:
        raise ValueError(f"auth.kind must be one of {_AUTH_KINDS}")
    secret_ref = raw.get("secret_ref")
    if not isinstance(secret_ref, str) or not secret_ref.strip():
        raise ValueError("auth.secret_ref is required")
    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError("auth.name must be a string")
    if kind == "apikey_param" and not name:
        name = "apikey"
    return PeerAuth(kind=kind, secret_ref=secret_ref.strip(), name=name)


def _parse_peer(raw: object) -> Peer:
    if not isinstance(raw, dict):
        raise ValueError("peer must be an object")
    pid = raw.get("id")
    if not isinstance(pid, str) or not pid.strip():
        raise ValueError("id is required")
    base_url = raw.get("base_url")
    if not isinstance(base_url, str):
        raise ValueError("base_url is required")
    base_url = base_url.strip().rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("base_url must be an http(s) URL")
    timeout_ms = raw.get("timeout_ms", DEFAULT_PEER_TIMEOUT_MS)
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    label = raw.get("label")
    return Peer(
        id=pid.strip(),
        label=label if isinstance(label, str) and label else pid.strip(),
        base_url=base_url,
        mod_path=str(raw.get("mod_path") or DEFAULT_MOD_PATH),
        adapter=str(raw.get("adapter") or DEFAULT_ADAPTER),
        timeout_ms=timeout_ms,
        auth=_parse_auth(raw.get("auth")),
    )


def get_federation_peers() -> list[Peer]:
    """Parse ``federation_peers_json`` into peers. Never raises."""
    raw = (get_settings().federation_peers_json or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError as exc:
        logger.warning("federation: FEDERATION_PEERS_JSON is not valid JSON (%s); no peers", exc)
        return []
    if not isinstance(data, list):
        logger.warning("federation: FEDERATION_PEERS_JSON must be a JSON list; no peers")
        return []
    peers: list[Peer] = []
    seen: set[str] = set()
    for i, entry in enumerate(data):
        try:
            peer = _parse_peer(entry)
        except ValueError as exc:
            logger.warning("federation: skipping peer #%d: %s", i, exc)
            continue
        if peer.id in seen:
            logger.warning("federation: skipping duplicate peer id %r (#%d)", peer.id, i)
            continue
        seen.add(peer.id)
        peers.append(peer)
    return peers


def peer_host_allowlist() -> frozenset[str]:
    """Lower-cased hostnames of all configured peers' base URLs (no ports)."""
    return frozenset(
        urlsplit(p.base_url).hostname.lower()  # type: ignore[union-attr]
        for p in get_federation_peers()
    )
