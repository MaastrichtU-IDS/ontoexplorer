"""SSRF guard for outbound fetches of user-supplied URLs.

Ingestion fetches whatever URL, IRI, or ``owl:imports`` target a submission
carries, with redirects followed. Nothing validated where those went, so an
uploader could point a registration at ``http://169.254.169.254/`` (cloud
metadata), ``http://127.0.0.1:…`` (the worker's own loopback), or any
``*.svc.cluster.local`` datastore, and the response was fetched, parsed, stored
and served back as ontology content — confirmed live: a source URL of
``http://minio.ontoexplorer-dev.svc.cluster.local:9000/minio/health/live``
reached internal MinIO and failed only at format detection, i.e. with the bytes
already in hand.

Two properties make a naive pre-check insufficient, and both are handled here by
guarding at the *transport* level:

* **Redirects.** ``follow_redirects=True`` means a public URL can 302 into an
  internal one. httpx routes every redirect hop back through the transport as a
  fresh request, so validating in the transport validates every hop, not just
  the first.
* **DNS rebinding.** A name that resolves to a public address when checked can
  resolve to an internal one microseconds later when connected. So we resolve
  once, validate every returned address, and **pin the connection to the
  validated IP** — rewriting the URL host to the address while preserving the
  original ``Host`` header and TLS SNI, so nothing re-resolves between check and
  connect.

The default is deny: anything that is not a normal public address is refused.
``INGEST_ALLOW_PRIVATE_FETCH`` and ``INGEST_FETCH_ALLOW_HOSTS`` reopen it for
local development, where fetching ``localhost`` imports is legitimate.
"""

from __future__ import annotations

import ipaddress
import socket

import httpx

# CGNAT (RFC 6598). Python 3.10's ``is_private`` does not flag 100.64.0.0/10, so
# it is checked explicitly; later versions fold it into ``is_private``.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class SsrfBlocked(ValueError):
    """Raised when a fetch target resolves to a non-public address."""


def _ip_is_forbidden(ip: ipaddress._BaseAddress) -> bool:
    """True for any address ingestion must not reach.

    IPv4-mapped IPv6 (``::ffff:127.0.0.1``) is unwrapped first, so the mapped
    form cannot smuggle a loopback or private v4 address past the v4 checks.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local        # 169.254/16 & fe80::/10 — covers cloud metadata
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_forbidden_ip(literal: str) -> bool:
    """True if `literal` parses as an address ingestion must not reach."""
    try:
        return _ip_is_forbidden(ipaddress.ip_address(literal))
    except ValueError:
        return False


def _default_resolver(host: str, port: int) -> list[str]:
    """Resolve `host` to the list of IP strings a connection could land on.

    A resolution failure returns an empty list (surfaced as a ConnectError by
    the caller), matching the async resolver, so a name that will not resolve —
    which cannot be a rebinding vector — is handled the same on both paths.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    # De-duplicate while preserving order; sockaddr[0] is the address.
    seen: dict[str, None] = {}
    for info in infos:
        seen.setdefault(info[4][0], None)
    return list(seen)


class GuardedTransport(httpx.BaseTransport):
    """An httpx transport that refuses non-public targets and pins the DNS result.

    `resolver` and `inner` are injectable so the validation and pinning logic can
    be tested without real sockets.
    """

    def __init__(
        self,
        *,
        inner: httpx.BaseTransport | None = None,
        resolver=None,
        allow_hosts: frozenset[str] = frozenset(),
        allow_private: bool = False,
    ) -> None:
        self._inner = inner if inner is not None else httpx.HTTPTransport()
        self._resolve = resolver if resolver is not None else _default_resolver
        self._allow_hosts = allow_hosts
        self._allow_private = allow_private

    def _bypass(self, host: str) -> bool:
        return self._allow_private or host in self._allow_hosts

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = _guard_scheme(request.url)
        if self._bypass(host):
            return self._inner.handle_request(request)
        addresses = self._resolve(host, _port_of(request.url))
        _pin_to_validated(request, host, addresses)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class AsyncGuardedTransport(httpx.AsyncBaseTransport):
    """Async sibling of `GuardedTransport`, sharing its validation and pinning.

    The two are deliberately kept as thin wrappers over the same module-level
    helpers so the guard cannot drift between the sync and async fetch paths.
    """

    def __init__(
        self,
        *,
        inner: httpx.AsyncBaseTransport | None = None,
        resolver=None,
        allow_hosts: frozenset[str] = frozenset(),
        allow_private: bool = False,
    ) -> None:
        self._inner = inner if inner is not None else httpx.AsyncHTTPTransport()
        self._resolve = resolver if resolver is not None else _default_async_resolver
        self._allow_hosts = allow_hosts
        self._allow_private = allow_private

    def _bypass(self, host: str) -> bool:
        return self._allow_private or host in self._allow_hosts

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = _guard_scheme(request.url)
        if self._bypass(host):
            return await self._inner.handle_async_request(request)
        addresses = await self._resolve(host, _port_of(request.url))
        _pin_to_validated(request, host, addresses)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _guard_scheme(url: httpx.URL) -> str:
    """Reject non-http(s) schemes; return the target host."""
    if url.scheme not in ("http", "https"):
        raise SsrfBlocked(f"scheme not allowed for fetch: {url.scheme!r}")
    return url.host


def _port_of(url: httpx.URL) -> int:
    return url.port or (443 if url.scheme == "https" else 80)


def _pin_to_validated(request: httpx.Request, host: str, addresses: list[str]) -> None:
    """Block if any resolved address is non-public, else pin the connection to one.

    Blocking on *any* forbidden address stops a round-robin record waving an
    internal answer through. Pinning to a validated address means nothing
    re-resolves between here and the socket (DNS rebinding). The Host header the
    client built is left untouched (the real authority) and `sni_hostname` keeps
    TLS SNI and certificate verification on the name rather than the pinned IP.
    """
    if not addresses:
        raise httpx.ConnectError(f"name did not resolve: {host}", request=request)
    for literal in addresses:
        if _ip_is_forbidden(ipaddress.ip_address(literal)):
            raise SsrfBlocked(
                f"fetch target {host!r} resolves to a non-public address ({literal})"
            )
    request.url = request.url.copy_with(host=addresses[0])
    request.extensions = {**request.extensions, "sni_hostname": host}


async def _default_async_resolver(host: str, port: int) -> list[str]:
    """Async DNS resolution via anyio (httpx's own concurrency backend)."""
    import anyio

    try:
        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    seen: dict[str, None] = {}
    for info in infos:
        seen.setdefault(info[4][0], None)
    return list(seen)


def guarded_transport() -> GuardedTransport:
    """Build the sync guard transport from application settings."""
    return GuardedTransport(**_guard_kwargs())


def async_guarded_transport() -> AsyncGuardedTransport:
    """Build the async guard transport from application settings."""
    return AsyncGuardedTransport(**_guard_kwargs())


def _guard_kwargs() -> dict:
    from ontoexplorer.config import get_settings

    s = get_settings()
    allow = frozenset(
        h.strip().lower() for h in s.ingest_fetch_allow_hosts.split(",") if h.strip()
    )
    return {"allow_hosts": allow, "allow_private": s.ingest_allow_private_fetch}
