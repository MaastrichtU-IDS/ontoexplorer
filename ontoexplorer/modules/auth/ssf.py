"""Shared Signals Framework (SSF) receiver for Keycloak security events (#372).

Keycloak (the ids3-era realms, 26.8+) acts as an SSF transmitter: when an admin
deletes a user it emits a RISC ``account-purged`` Security Event Token (SET) — a
signed JWT, ``Content-Type: application/secevent+jwt`` — to a registered push
stream. Without this, OntoExplorer's local ``users`` row lingers after the
Keycloak user is gone, and a re-signup (new Keycloak ``sub``, same email) dies on
the email-collision guard with no way to re-link.

This module only *verifies and parses* a SET; the endpoint in ``api/auth.py``
decides what to do with each event. Verification mirrors how an ID token would be
checked: RS256 signature against the realm JWKS (the same keys), ``iss`` = the
realm issuer, ``aud`` = our client, ``typ`` = ``secevent+jwt``.
"""

from __future__ import annotations

import time

import httpx
from jose import jwt

from ontoexplorer.config import get_settings
from ontoexplorer.logging_config import get_logger

log = get_logger(__name__)

# Event type URIs we understand (RISC + CAEP). Anything else is accepted and
# ignored (202) so Keycloak doesn't retry forever on events we don't handle.
EVT_ACCOUNT_PURGED = "https://schemas.openid.net/secevent/risc/event-type/account-purged"
EVT_ACCOUNT_DISABLED = "https://schemas.openid.net/secevent/risc/event-type/account-disabled"
EVT_SESSION_REVOKED = "https://schemas.openid.net/secevent/caep/event-type/session-revoked"

_ACCEPTED_TYP = {"secevent+jwt", "application/secevent+jwt"}

# Short JWKS cache. The realm's signing keys rotate rarely; on an unknown kid we
# refresh once (handles rotation without a restart).
_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}


class SETError(Exception):
    """An invalid SET. ``err`` is an RFC 8935 error code returned to Keycloak."""

    def __init__(self, err: str, description: str):
        self.err = err
        self.description = description
        super().__init__(description)


async def _fetch_jwks(force: bool = False) -> list[dict]:
    s = get_settings()
    issuer = str(s.keycloak_issuer).rstrip("/")
    if not issuer:
        raise SETError("invalid_request", "Keycloak issuer is not configured")
    now = time.time()
    cached = _jwks_cache["keys"]
    if not force and cached is not None and (now - _jwks_cache["fetched_at"]) < _JWKS_TTL_SECONDS:
        return cached
    url = f"{issuer}/protocol/openid-connect/certs"
    # httpx honours the egress-proxy env (HTTP(S)_PROXY/NO_PROXY), so this reaches
    # the external Keycloak host the same way the app's other OAuth calls do.
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        keys = resp.json().get("keys", [])
    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now
    return keys


async def _signing_key(kid: str | None) -> dict:
    keys = await _fetch_jwks()
    if kid:
        for k in keys:
            if k.get("kid") == kid:
                return k
        # Unknown kid: the realm may have rotated its keys. Refresh once.
        for k in await _fetch_jwks(force=True):
            if k.get("kid") == kid:
                return k
    # No kid, or still not found: fall back to the first signing key if unambiguous.
    sig_keys = [k for k in keys if k.get("use", "sig") == "sig"]
    if len(sig_keys) == 1:
        return sig_keys[0]
    raise SETError("invalid_key", "No matching signing key for the SET")


async def verify_set(token: str) -> dict:
    """Verify a SET's signature and claims; return its payload.

    Raises :class:`SETError` (carrying an RFC 8935 error code) on anything
    unexpected: malformed token, wrong ``typ``, unknown key, bad signature, or a
    mismatched ``iss``/``aud``.
    """
    s = get_settings()
    issuer = str(s.keycloak_issuer).rstrip("/")
    audience = s.keycloak_client_id
    if not issuer:
        raise SETError("invalid_request", "Keycloak issuer is not configured")

    token = (token or "").strip()
    if not token:
        raise SETError("invalid_request", "Empty request body")
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:  # malformed JWT
        raise SETError("invalid_request", f"Malformed token: {exc}") from exc

    typ = (header.get("typ") or "").lower()
    if typ not in _ACCEPTED_TYP:
        raise SETError("invalid_request", f"Unexpected token typ: {header.get('typ')!r}")

    key = await _signing_key(header.get("kid"))
    alg = key.get("alg") or header.get("alg") or "RS256"
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[alg],
            issuer=issuer,
            # SETs are not ID tokens: no at_hash, and they may legitimately carry
            # no exp. Signature + iss are enforced here; aud is checked below
            # against a set of accepted values (Keycloak stamps the SET's aud
            # itself — observed to be the stream/push identity, not the client id).
            options={"verify_at_hash": False, "verify_exp": False, "verify_aud": False},
        )
    except Exception as exc:
        raise SETError("invalid_request", f"SET verification failed: {exc}") from exc

    token_auds = claims.get("aud")
    token_auds = [token_auds] if isinstance(token_auds, str) else list(token_auds or [])
    app_url = str(s.app_url).rstrip("/")
    accepted = {a for a in (audience, app_url, f"{app_url}/auth/keycloak/ssf") if a}
    if not set(token_auds) & accepted:
        raise SETError("invalid_request",
                       f"Invalid audience {token_auds!r}; accepted {sorted(accepted)}")

    if not isinstance(claims.get("events"), dict) or not claims["events"]:
        raise SETError("invalid_request", "SET carries no events")
    return claims


def iter_events(claims: dict) -> list[tuple[str, dict]]:
    """``[(event_type_uri, event_payload), ...]`` from a verified SET."""
    events = claims.get("events") or {}
    return [(k, v if isinstance(v, dict) else {}) for k, v in events.items()]


def subject_sub(claims: dict, event_payload: dict) -> str | None:
    """Best-effort Keycloak user ``sub`` for an event.

    The subject can appear as a per-event ``subject`` or a top-level ``sub_id``
    (RFC 9493 Subject Identifiers), in ``iss_sub`` or ``opaque`` form, or as a
    plain ``sub``. We don't yet know Keycloak's exact shape here — the issue flags
    verifying it against a real event — so we read all the common spots and log the
    raw subject when we can't resolve one.
    """

    def _from_subid(sid: object) -> str | None:
        if not isinstance(sid, dict):
            return None
        fmt = sid.get("format")
        if fmt == "iss_sub":
            return sid.get("sub")
        if fmt == "opaque":
            return sid.get("id")
        # email / phone / other formats don't carry a Keycloak sub.
        return sid.get("sub") or sid.get("id")

    for candidate in (
        _from_subid(event_payload.get("subject")),
        _from_subid(claims.get("sub_id")),
        claims.get("sub"),
    ):
        if candidate:
            return str(candidate)
    return None
