"""Federation service: fan-out, partial-failure tolerance, cache, dedup+append."""

from __future__ import annotations

import asyncio
import time

import pytest

from ontoexplorer.config import get_settings
from ontoexplorer.modules.federation import client, service
from ontoexplorer.modules.federation.client import FederationFetchError
from ontoexplorer.modules.federation.config import Peer
from ontoexplorer.modules.federation.models import ArtefactRow, SourceRef


def _peer(pid: str) -> Peer:
    return Peer(id=pid, label=pid.upper(), base_url=f"https://{pid}.example.org")


def _row(peer: Peer, n: int, iri: str | None = None) -> ArtefactRow:
    return ArtefactRow(
        iri=iri or f"https://{peer.id}.example.org/onto/{n}",
        acronym=f"{peer.id}{n}",
        title=f"{peer.id} onto {n}",
        source_landing_url=f"https://{peer.id}.example.org/o/{n}",
        source=SourceRef(id=peer.id, label=peer.label),
    )


class FakeRedis:
    def __init__(self, fail_get: bool = False, fail_set: bool = False):
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple] = []
        self.fail_get = fail_get
        self.fail_set = fail_set

    def get(self, key):
        if self.fail_get:
            raise ConnectionError("redis down")
        return self.store.get(key)

    def setex(self, key, ttl, value):
        if self.fail_set:
            raise ConnectionError("redis down")
        self.setex_calls.append((key, ttl))
        self.store[key] = value


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(service, "_redis", lambda: r)
    return r


def _patch_client(monkeypatch, handlers):
    calls: list[str] = []

    async def fake(peer, q, limit, *, transport=None):
        calls.append(peer.id)
        return await handlers[peer.id](peer, q, limit)

    monkeypatch.setattr(client, "search_artefacts", fake)
    return calls


async def test_slow_peer_times_out_healthy_returned(monkeypatch, fake_redis):
    good, slow = _peer("good"), _peer("slow")

    async def ok(peer, q, limit):
        return [_row(peer, 1), _row(peer, 2)]

    async def hang(peer, q, limit):
        await asyncio.sleep(30)
        return [_row(peer, 1)]

    _patch_client(monkeypatch, {"good": ok, "slow": hang})
    monkeypatch.setattr(get_settings(), "federation_fanout_timeout_ms", 200)
    t0 = time.monotonic()
    rows, statuses = await service.federated_artefacts("onto", set(), [good, slow])
    assert time.monotonic() - t0 < 2
    assert [r.iri for r in rows] == [
        "https://good.example.org/onto/1",
        "https://good.example.org/onto/2",
    ]
    by_id = {s.id: s for s in statuses}
    assert by_id["good"].status == "ok" and by_id["good"].count == 2
    assert by_id["slow"].status == "timeout" and by_id["slow"].count == 0


async def test_client_timeout_error_maps_to_timeout(monkeypatch, fake_redis):
    p = _peer("p")

    async def boom(peer, q, limit):
        raise FederationFetchError("timeout")

    _patch_client(monkeypatch, {"p": boom})
    rows, statuses = await service.federated_artefacts("x", set(), [p])
    assert rows == []
    assert statuses[0].status == "timeout"


async def test_other_errors_map_to_error(monkeypatch, fake_redis):
    a, b = _peer("a"), _peer("b")

    async def unauth(peer, q, limit):
        raise FederationFetchError("unauthorized")

    async def weird(peer, q, limit):
        raise RuntimeError("boom")

    _patch_client(monkeypatch, {"a": unauth, "b": weird})
    rows, statuses = await service.federated_artefacts("x", set(), [a, b])
    assert rows == []
    assert [(s.id, s.status, s.count) for s in statuses] == [
        ("a", "error", 0),
        ("b", "error", 0),
    ]


async def test_zero_rows_is_empty(monkeypatch, fake_redis):
    p = _peer("p")

    async def none(peer, q, limit):
        return []

    _patch_client(monkeypatch, {"p": none})
    rows, statuses = await service.federated_artefacts("x", set(), [p])
    assert rows == [] and statuses[0].status == "empty"


async def test_dedup_against_local_and_stable_order(monkeypatch, fake_redis):
    a, b = _peer("a"), _peer("b")
    dup = "https://a.example.org/onto/2"

    async def ha(peer, q, limit):
        return [_row(peer, 1), _row(peer, 2), _row(peer, 3)]

    async def hb(peer, q, limit):
        await asyncio.sleep(0.05)  # b finishes after a regardless
        return [_row(peer, 9), _row(peer, 8)]

    _patch_client(monkeypatch, {"a": ha, "b": hb})
    expected = [
        "https://a.example.org/onto/1",
        "https://a.example.org/onto/3",
        "https://b.example.org/onto/9",
        "https://b.example.org/onto/8",
    ]
    for _ in range(3):
        fake_redis.store.clear()
        rows, statuses = await service.federated_artefacts("x", {dup}, [a, b])
        assert [r.iri for r in rows] == expected
        assert [s.id for s in statuses] == ["a", "b"]
        assert statuses[0].status == "ok" and statuses[0].count == 2


async def test_per_peer_limit_cap(monkeypatch, fake_redis):
    p = _peer("p")

    async def many(peer, q, limit):
        return [_row(peer, i) for i in range(10)]

    _patch_client(monkeypatch, {"p": many})
    rows, statuses = await service.federated_artefacts("x", set(), [p], limit=3)
    assert len(rows) == 3 and statuses[0].count == 3


async def test_cache_miss_then_hit(monkeypatch, fake_redis):
    p = _peer("p")

    async def ok(peer, q, limit):
        return [_row(peer, 1)]

    calls = _patch_client(monkeypatch, {"p": ok})
    r1, s1 = await service.federated_artefacts("  OntoLogy ", set(), [p])
    assert calls == ["p"] and len(fake_redis.setex_calls) == 1
    key, ttl = fake_redis.setex_calls[0]
    assert key.startswith("federation:p:")
    assert ttl == get_settings().federation_cache_ttl_s

    r2, s2 = await service.federated_artefacts("ontology", set(), [p])
    assert calls == ["p"]  # no second client call (normalised q hits cache)
    assert r2 == r1 and s2[0].status == "ok" and s2[0].count == 1
    assert all(isinstance(r, ArtefactRow) for r in r2)


async def test_redis_get_raising_falls_through(monkeypatch):
    r = FakeRedis(fail_get=True)
    monkeypatch.setattr(service, "_redis", lambda: r)
    p = _peer("p")

    async def ok(peer, q, limit):
        return [_row(peer, 1)]

    calls = _patch_client(monkeypatch, {"p": ok})
    rows, statuses = await service.federated_artefacts("x", set(), [p])
    assert calls == ["p"] and len(rows) == 1 and statuses[0].status == "ok"


async def test_redis_unavailable_and_setex_raising(monkeypatch):
    def no_redis():
        raise ConnectionError("no redis")

    monkeypatch.setattr(service, "_redis", no_redis)
    p = _peer("p")

    async def ok(peer, q, limit):
        return [_row(peer, 1)]

    _patch_client(monkeypatch, {"p": ok})
    rows, statuses = await service.federated_artefacts("x", set(), [p])
    assert len(rows) == 1 and statuses[0].status == "ok"

    r = FakeRedis(fail_set=True)
    monkeypatch.setattr(service, "_redis", lambda: r)
    rows, statuses = await service.federated_artefacts("x", set(), [p])
    assert len(rows) == 1 and statuses[0].status == "ok"


async def test_defaults_use_configured_peers(monkeypatch, fake_redis):
    p = _peer("p")
    monkeypatch.setattr(service, "get_federation_peers", lambda: [p])

    async def ok(peer, q, limit):
        assert limit == get_settings().federation_max_results_per_peer
        return [_row(peer, 1)]

    _patch_client(monkeypatch, {"p": ok})
    rows, statuses = await service.federated_artefacts("x", set())
    assert len(rows) == 1 and statuses[0].id == "p"


async def test_cancel_resistant_peer_cannot_extend_call(monkeypatch, fake_redis):
    good, stubborn = _peer("good"), _peer("stubborn")
    monkeypatch.setattr(service, "_CANCEL_GRACE_S", 0.2)
    monkeypatch.setattr(get_settings(), "federation_fanout_timeout_ms", 200)

    async def ok(peer, q, limit):
        return [_row(peer, 1)]

    async def resistant(peer, q, limit):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(3)  # slow cleanup, swallows the cancel
        return [_row(peer, 1)]  # would flip to "ok" if not guarded

    _patch_client(monkeypatch, {"good": ok, "stubborn": resistant})
    t0 = time.monotonic()
    rows, statuses = await service.federated_artefacts("x", set(), [good, stubborn])
    assert time.monotonic() - t0 < 0.2 + 0.2 + 0.5  # budget + grace + slack
    by_id = {s.id: s for s in statuses}
    assert by_id["good"].status == "ok"
    assert by_id["stubborn"].status == "timeout" and by_id["stubborn"].count == 0
    assert [r.source.id for r in rows] == ["good"]


async def test_hung_redis_get_degrades_to_miss(monkeypatch):
    class HungRedis(FakeRedis):
        def get(self, key):
            time.sleep(1.0)  # blocks its worker thread
            return None

    monkeypatch.setattr(service, "_CACHE_TIMEOUT_S", 0.1)
    monkeypatch.setattr(get_settings(), "federation_fanout_timeout_ms", 2000)
    monkeypatch.setattr(service, "_redis", lambda: HungRedis())
    p = _peer("p")

    async def ok(peer, q, limit):
        return [_row(peer, 1)]

    calls = _patch_client(monkeypatch, {"p": ok})
    t0 = time.monotonic()
    rows, statuses = await service.federated_artefacts("x", set(), [p])
    assert time.monotonic() - t0 < 1.0
    assert calls == ["p"] and len(rows) == 1 and statuses[0].status == "ok"


async def test_cached_empty_is_served_as_empty(monkeypatch, fake_redis):
    p = _peer("p")
    fake_redis.store[service._cache_key("p", "x")] = "[]"

    async def never(peer, q, limit):
        raise AssertionError("client must not be called on a cache hit")

    calls = _patch_client(monkeypatch, {"p": never})
    rows, statuses = await service.federated_artefacts("X", set(), [p])
    assert calls == [] and rows == []
    assert statuses[0].status == "empty" and statuses[0].count == 0
