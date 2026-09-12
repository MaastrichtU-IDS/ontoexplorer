"""SSRF guard for ingestion fetches.

Confirmed live before this guard existed: a submitted source URL of
``http://minio.ontoexplorer-dev.svc.cluster.local:9000/minio/health/live``
reached an internal, cluster-DNS-only service and failed only at format
detection — i.e. the worker fetched it. These tests pin the guard that closes
it: a default-deny on non-public addresses, enforced on every redirect hop and
against DNS rebinding by pinning the connection to a validated address.
"""
import ipaddress

import httpx
import pytest

from ontoexplorer.clients.fetch_guard import (
    GuardedTransport,
    SsrfBlocked,
    _ip_is_forbidden,
    is_forbidden_ip,
)

FORBIDDEN = [
    "127.0.0.1", "127.0.0.53",          # loopback
    "10.0.0.5", "172.16.9.9", "192.168.1.1",  # RFC1918
    "169.254.169.254",                  # link-local / cloud metadata
    "100.64.0.1",                       # CGNAT (RFC6598) — not is_private on 3.10
    "0.0.0.0",                          # unspecified
    "224.0.0.1",                        # multicast
    "::1",                              # IPv6 loopback
    "fc00::1", "fd12::1",              # IPv6 ULA
    "fe80::1",                          # IPv6 link-local
    "::ffff:127.0.0.1",                # IPv4-mapped loopback — must be unwrapped
    "::ffff:10.0.0.1",                 # IPv4-mapped RFC1918
]

PUBLIC = ["8.8.8.8", "93.184.216.34", "1.1.1.1", "2606:2800:220:1:248:1893:25c8:1946"]


@pytest.mark.parametrize("addr", FORBIDDEN)
def test_forbidden_addresses(addr):
    assert _ip_is_forbidden(ipaddress.ip_address(addr)), addr
    assert is_forbidden_ip(addr), addr


@pytest.mark.parametrize("addr", PUBLIC)
def test_public_addresses_allowed(addr):
    assert not _ip_is_forbidden(ipaddress.ip_address(addr)), addr
    assert not is_forbidden_ip(addr), addr


def _resolver(mapping):
    def resolve(host, port):
        if host not in mapping:
            import socket
            raise socket.gaierror(f"no fake record for {host}")
        return mapping[host]
    return resolve


def _ok_handler(captured):
    def handler(request):
        captured["host"] = request.url.host
        captured["host_header"] = request.headers.get("host")
        captured["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, content=b"ok")
    return handler


def test_non_http_scheme_blocked():
    t = GuardedTransport(inner=httpx.MockTransport(lambda r: httpx.Response(200)),
                         resolver=_resolver({}))
    with httpx.Client(transport=t) as c:
        with pytest.raises(SsrfBlocked, match="scheme"):
            c.get("file:///etc/passwd")


def test_internal_resolution_blocked():
    t = GuardedTransport(
        inner=httpx.MockTransport(lambda r: httpx.Response(200, content=b"SHOULD NOT REACH")),
        resolver=_resolver({"evil.example": ["169.254.169.254"]}),
    )
    with httpx.Client(transport=t) as c:
        with pytest.raises(SsrfBlocked, match="non-public"):
            c.get("http://evil.example/x")


def test_one_internal_answer_in_a_set_blocks_all():
    """A round-robin record must not wave through an internal address."""
    t = GuardedTransport(
        inner=httpx.MockTransport(lambda r: httpx.Response(200)),
        resolver=_resolver({"mixed.example": ["93.184.216.34", "10.0.0.1"]}),
    )
    with httpx.Client(transport=t) as c:
        with pytest.raises(SsrfBlocked):
            c.get("http://mixed.example/x")


def test_public_target_is_pinned_and_host_preserved():
    captured = {}
    t = GuardedTransport(
        inner=httpx.MockTransport(_ok_handler(captured)),
        resolver=_resolver({"example.org": ["93.184.216.34"]}),
    )
    with httpx.Client(transport=t) as c:
        r = c.get("http://example.org/data.owl")
    assert r.status_code == 200
    assert captured["host"] == "93.184.216.34", "connection not pinned to the validated IP"
    assert captured["host_header"] == "example.org", "original Host header not preserved"
    assert captured["sni"] == "example.org", "TLS SNI/verification not kept on the hostname"


def test_redirect_into_internal_is_blocked():
    """A public URL that 302s to an internal one must be caught on the second hop."""
    def handler(request):
        if request.url.host == "93.184.216.34":       # first hop, pinned public IP
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        return httpx.Response(200, content=b"SHOULD NOT REACH")

    t = GuardedTransport(
        inner=httpx.MockTransport(handler),
        resolver=_resolver({
            "public.example": ["93.184.216.34"],
            "internal.example": ["127.0.0.1"],
        }),
    )
    with httpx.Client(transport=t, follow_redirects=True) as c:
        with pytest.raises(SsrfBlocked, match="non-public"):
            c.get("http://public.example/start")


def test_allow_hosts_exemption_skips_resolution():
    captured = {}

    def blowup(host, port):
        raise AssertionError("resolver must not run for an allow-listed host")

    t = GuardedTransport(
        inner=httpx.MockTransport(_ok_handler(captured)),
        resolver=blowup,
        allow_hosts=frozenset({"localhost"}),
    )
    with httpx.Client(transport=t) as c:
        r = c.get("http://localhost/x")
    assert r.status_code == 200
    assert captured["host"] == "localhost", "allow-listed host should not be pinned/rewritten"


def test_allow_private_disables_the_guard():
    t = GuardedTransport(
        inner=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ok")),
        resolver=lambda h, p: (_ for _ in ()).throw(AssertionError("should not resolve")),
        allow_private=True,
    )
    with httpx.Client(transport=t) as c:
        assert c.get("http://127.0.0.1:9000/x").status_code == 200


# ── async sibling: same validation, exercised through AsyncGuardedTransport ──

from ontoexplorer.clients.fetch_guard import AsyncGuardedTransport  # noqa: E402


def _async_resolver(mapping):
    async def resolve(host, port):
        return mapping.get(host, [])
    return resolve


@pytest.mark.anyio
async def test_async_internal_resolution_blocked():
    t = AsyncGuardedTransport(
        inner=httpx.MockTransport(lambda r: httpx.Response(200, content=b"SHOULD NOT REACH")),
        resolver=_async_resolver({"evil.example": ["169.254.169.254"]}),
    )
    async with httpx.AsyncClient(transport=t) as c:
        with pytest.raises(SsrfBlocked, match="non-public"):
            await c.get("http://evil.example/x")


@pytest.mark.anyio
async def test_async_https_to_internal_is_blocked():
    """The old scheme guard let https:// reach any host; this must not."""
    t = AsyncGuardedTransport(
        inner=httpx.MockTransport(lambda r: httpx.Response(200)),
        resolver=_async_resolver({"kubernetes.default.svc": ["10.0.0.1"]}),
    )
    async with httpx.AsyncClient(transport=t) as c:
        with pytest.raises(SsrfBlocked):
            await c.get("https://kubernetes.default.svc/api")


@pytest.mark.anyio
async def test_async_public_target_is_pinned_and_host_preserved():
    captured = {}

    def handler(request):
        captured["host"] = request.url.host
        captured["host_header"] = request.headers.get("host")
        captured["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, content=b"ok")

    t = AsyncGuardedTransport(
        inner=httpx.MockTransport(handler),
        resolver=_async_resolver({"example.org": ["93.184.216.34"]}),
    )
    async with httpx.AsyncClient(transport=t) as c:
        r = await c.get("https://example.org/lib.rq")
    assert r.status_code == 200
    assert captured["host"] == "93.184.216.34"
    assert captured["host_header"] == "example.org"
    assert captured["sni"] == "example.org"


@pytest.mark.anyio
async def test_async_redirect_into_internal_is_blocked():
    def handler(request):
        if request.url.host == "93.184.216.34":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        return httpx.Response(200, content=b"SHOULD NOT REACH")

    t = AsyncGuardedTransport(
        inner=httpx.MockTransport(handler),
        resolver=_async_resolver({
            "public.example": ["93.184.216.34"],
            "internal.example": ["127.0.0.1"],
        }),
    )
    async with httpx.AsyncClient(transport=t, follow_redirects=True) as c:
        with pytest.raises(SsrfBlocked, match="non-public"):
            await c.get("https://public.example/start")


# ── proxy awareness (regression: transport= bypassed env proxy, breaking
#    external ingestion in egress-locked namespaces) ──────────────────────────

def test_external_host_is_proxied_by_hostname_not_pinned():
    """A public host must go through the proxy transport WITH its hostname intact
    (the proxy's allow-list matches names) — not pinned to an IP, not sent direct."""
    direct_hit = {"n": 0}
    proxy_seen = {}

    def direct_handler(request):
        direct_hit["n"] += 1
        return httpx.Response(200, content=b"DIRECT (wrong)")

    def proxy_handler(request):
        proxy_seen["host"] = request.url.host
        return httpx.Response(200, content=b"ok")

    t = GuardedTransport(
        inner=httpx.MockTransport(direct_handler),
        proxy_inner=httpx.MockTransport(proxy_handler),
        proxy_url="http://egress-proxy:3128",
        resolver=_resolver({"purl.obolibrary.org": ["93.184.216.34"]}),
    )
    with httpx.Client(transport=t) as c:
        r = c.get("http://purl.obolibrary.org/obo/bfo.owl")
    assert r.status_code == 200
    assert direct_hit["n"] == 0, "external request went direct, bypassing the proxy"
    assert proxy_seen["host"] == "purl.obolibrary.org", "proxy must see the hostname, not a pinned IP"


def test_internal_target_still_blocked_even_with_a_proxy():
    """Validation runs on the proxy path too: an internal-resolving host is refused
    before it can reach either the proxy or a direct socket."""
    t = GuardedTransport(
        inner=httpx.MockTransport(lambda r: httpx.Response(200)),
        proxy_inner=httpx.MockTransport(lambda r: httpx.Response(200, content=b"SHOULD NOT REACH")),
        proxy_url="http://egress-proxy:3128",
        resolver=_resolver({"evil.example": ["10.0.0.5"]}),
    )
    with httpx.Client(transport=t) as c:
        with pytest.raises(SsrfBlocked):
            c.get("http://evil.example/x")


def test_no_proxy_host_goes_direct_and_pinned(monkeypatch):
    """A host matched by NO_PROXY bypasses the proxy and uses the pinned direct path."""
    monkeypatch.setenv("NO_PROXY", ".svc.cluster.local,localhost")
    captured = {}

    def direct_handler(request):
        captured["host"] = request.url.host
        return httpx.Response(200, content=b"ok")

    t = GuardedTransport(
        inner=httpx.MockTransport(direct_handler),
        proxy_inner=httpx.MockTransport(lambda r: httpx.Response(200, content=b"PROXY (wrong)")),
        proxy_url="http://egress-proxy:3128",
        resolver=_resolver({"thing.svc.cluster.local": ["93.184.216.34"]}),  # pretend-public for the test
    )
    with httpx.Client(transport=t) as c:
        r = c.get("http://thing.svc.cluster.local/x")
    assert r.status_code == 200
    assert captured["host"] == "93.184.216.34", "NO_PROXY host should go direct and be pinned to the IP"
