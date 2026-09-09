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
    """Resolve `host` to the list of IP strings a connection could land on."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
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

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme not in ("http", "https"):
            raise SsrfBlocked(f"scheme not allowed for fetch: {url.scheme!r}")

        host = url.host
        if self._allow_private or host in self._allow_hosts:
            return self._inner.handle_request(request)

        port = url.port or (443 if url.scheme == "https" else 80)
        try:
            addresses = self._resolve(host, port)
        except socket.gaierror as exc:
            # A name that will not resolve cannot be a rebinding vector; let the
            # normal connect path surface it as the usual "could not fetch".
            raise httpx.ConnectError(f"name resolution failed: {host}", request=request) from exc
        if not addresses:
            raise httpx.ConnectError(f"name did not resolve: {host}", request=request)

        # Block if *any* resolved address is forbidden — a round-robin record
        # must not let one public answer wave through an internal one.
        for literal in addresses:
            if _ip_is_forbidden(ipaddress.ip_address(literal)):
                raise SsrfBlocked(
                    f"fetch target {host!r} resolves to a non-public address ({literal})"
                )

        # Pin to a validated address so nothing re-resolves between here and the
        # socket. Host header stays as the client built it (the real authority);
        # sni_hostname keeps TLS SNI and certificate verification on the name.
        pinned = addresses[0]
        request.url = url.copy_with(host=pinned)
        request.extensions = {**request.extensions, "sni_hostname": host}
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def guarded_transport() -> GuardedTransport:
    """Build the guard transport from application settings."""
    from ontoexplorer.config import get_settings

    s = get_settings()
    allow = frozenset(
        h.strip().lower() for h in s.ingest_fetch_allow_hosts.split(",") if h.strip()
    )
    return GuardedTransport(allow_hosts=allow, allow_private=s.ingest_allow_private_fetch)
