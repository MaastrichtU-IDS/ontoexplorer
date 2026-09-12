"""SSRF guard for outbound fetches of user-supplied URLs.

Ingestion fetches whatever URL, IRI, or ``owl:imports`` target a submission
carries, with redirects followed. Nothing validated where those went, so an
uploader could point a registration at ``http://169.254.169.254/`` (cloud
metadata), ``http://127.0.0.1:…`` (the worker's own loopback), or any
``*.svc.cluster.local`` datastore, and the response was fetched, parsed, stored
and served back as ontology content.

The guard is a *transport* so it also covers redirects (httpx routes every hop
back through the transport) and DNS rebinding (it resolves once, validates every
address, and — on the direct path — pins the connection to a validated IP).

**Proxy awareness.** These namespaces are egress-locked: the only route
off-cluster is an HTTP proxy (``HTTPS_PROXY``), and internal hosts are in
``NO_PROXY``. Passing a single ``transport=`` to httpx bypasses env proxies
entirely — which broke ordinary external ontology fetches (they went direct and
the egress firewall refused them). So the transport is proxy-aware: it always
resolves-and-validates (blocking non-public targets on either path), then routes
external/public hosts *through the proxy by hostname* (the proxy is the egress
control and its allow-list matches names, so the host must not be rewritten to an
IP) and connects directly only for non-proxied hosts, pinning those to the
validated IP.

The default is deny: anything that resolves to a non-public address is refused.
``INGEST_ALLOW_PRIVATE_FETCH`` and ``INGEST_FETCH_ALLOW_HOSTS`` reopen it for
local development, where fetching ``localhost`` imports is legitimate.
"""

from __future__ import annotations

import ipaddress
import os
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


def _guard_scheme(url: httpx.URL) -> str:
    """Reject non-http(s) schemes; return the target host."""
    if url.scheme not in ("http", "https"):
        raise SsrfBlocked(f"scheme not allowed for fetch: {url.scheme!r}")
    return url.host


def _port_of(url: httpx.URL) -> int:
    return url.port or (443 if url.scheme == "https" else 80)


def _validate(request: httpx.Request, host: str, addresses: list[str]) -> None:
    """Block if the host did not resolve or any address is non-public.

    Blocking on *any* forbidden address stops a round-robin record waving an
    internal answer through. This runs on both the proxied and direct paths, so
    an internal target is refused regardless of how the connection would route.
    """
    if not addresses:
        raise httpx.ConnectError(f"name did not resolve: {host}", request=request)
    for literal in addresses:
        if _ip_is_forbidden(ipaddress.ip_address(literal)):
            raise SsrfBlocked(
                f"fetch target {host!r} resolves to a non-public address ({literal})"
            )


def _pin(request: httpx.Request, host: str, addresses: list[str]) -> None:
    """Pin the connection to a validated address (direct path only).

    Nothing re-resolves between here and the socket (DNS rebinding). The Host
    header the client built is left untouched (the real authority) and
    `sni_hostname` keeps TLS SNI and certificate verification on the name.
    Never applied on the proxy path — the proxy's allow-list matches on the
    hostname, so the host must stay a name there.
    """
    request.url = request.url.copy_with(host=addresses[0])
    request.extensions = {**request.extensions, "sni_hostname": host}


def _env_proxy() -> str | None:
    """The egress proxy from the environment, if any (HTTPS first, then HTTP)."""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key)
        if value:
            return value
    return None


def _host_bypasses_proxy(host: str) -> bool:
    """True if NO_PROXY says `host` should be reached directly, not via the proxy.

    Matches the common forms: exact host, and dotted-suffix entries like ``.svc``
    / ``.cluster.local`` / ``localhost``. CIDR entries (e.g. ``10.43.0.0/16``) are
    not matched here — an internal *IP-literal* target is caught by `_validate`
    instead, which resolves and rejects private/reserved addresses on either path.
    """
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    host = host.lower()
    for token in no_proxy.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token == "*":
            return True
        bare = token.lstrip(".")
        if host == bare or host.endswith("." + bare):
            return True
    return False


class GuardedTransport(httpx.BaseTransport):
    """SSRF-guarding, proxy-aware sync transport. See module docstring.

    `inner` (direct), `proxy_inner`, `resolver`, and `proxy_url` are injectable so
    the routing and validation logic can be tested without real sockets.
    """

    def __init__(
        self,
        *,
        inner: httpx.BaseTransport | None = None,
        proxy_inner: httpx.BaseTransport | None = None,
        resolver=None,
        proxy_url: str | None = None,
        allow_hosts: frozenset[str] = frozenset(),
        allow_private: bool = False,
    ) -> None:
        self._direct = inner if inner is not None else httpx.HTTPTransport()
        self._resolve = resolver if resolver is not None else _default_resolver
        self._allow_hosts = allow_hosts
        self._allow_private = allow_private
        # proxy_url is explicit (the factory reads the environment); __init__ stays
        # hermetic so tests aren't perturbed by an ambient HTTP(S)_PROXY.
        if proxy_inner is not None:
            self._proxy: httpx.BaseTransport | None = proxy_inner
        elif proxy_url:
            self._proxy = httpx.HTTPTransport(proxy=proxy_url)
        else:
            self._proxy = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = _guard_scheme(request.url)
        addresses: list[str] | None = None
        if not (self._allow_private or host in self._allow_hosts):
            addresses = self._resolve(host, _port_of(request.url))
            _validate(request, host, addresses)
        if self._proxy is not None and not _host_bypasses_proxy(host):
            return self._proxy.handle_request(request)   # external: proxied by hostname
        if addresses:
            _pin(request, host, addresses)               # direct: rebind-safe
        return self._direct.handle_request(request)

    def close(self) -> None:
        self._direct.close()
        if self._proxy is not None:
            self._proxy.close()


class AsyncGuardedTransport(httpx.AsyncBaseTransport):
    """Async sibling of `GuardedTransport`, sharing its validation/routing helpers
    so the guard cannot drift between the sync and async fetch paths."""

    def __init__(
        self,
        *,
        inner: httpx.AsyncBaseTransport | None = None,
        proxy_inner: httpx.AsyncBaseTransport | None = None,
        resolver=None,
        proxy_url: str | None = None,
        allow_hosts: frozenset[str] = frozenset(),
        allow_private: bool = False,
    ) -> None:
        self._direct = inner if inner is not None else httpx.AsyncHTTPTransport()
        self._resolve = resolver if resolver is not None else _default_async_resolver
        self._allow_hosts = allow_hosts
        self._allow_private = allow_private
        if proxy_inner is not None:
            self._proxy: httpx.AsyncBaseTransport | None = proxy_inner
        elif proxy_url:
            self._proxy = httpx.AsyncHTTPTransport(proxy=proxy_url)
        else:
            self._proxy = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = _guard_scheme(request.url)
        addresses: list[str] | None = None
        if not (self._allow_private or host in self._allow_hosts):
            addresses = await self._resolve(host, _port_of(request.url))
            _validate(request, host, addresses)
        if self._proxy is not None and not _host_bypasses_proxy(host):
            return await self._proxy.handle_async_request(request)
        if addresses:
            _pin(request, host, addresses)
        return await self._direct.handle_async_request(request)

    async def aclose(self) -> None:
        await self._direct.aclose()
        if self._proxy is not None:
            await self._proxy.aclose()


def guarded_transport() -> GuardedTransport:
    """Build the sync guard transport from application settings + environment."""
    return GuardedTransport(**_guard_kwargs())


def async_guarded_transport() -> AsyncGuardedTransport:
    """Build the async guard transport from application settings + environment."""
    return AsyncGuardedTransport(**_guard_kwargs())


def _guard_kwargs() -> dict:
    from ontoexplorer.config import get_settings

    s = get_settings()
    allow = frozenset(
        h.strip().lower() for h in s.ingest_fetch_allow_hosts.split(",") if h.strip()
    )
    return {
        "allow_hosts": allow,
        "allow_private": s.ingest_allow_private_fetch,
        "proxy_url": _env_proxy(),   # env read here, not in __init__, so tests stay hermetic
    }
