import fakeredis
import httpx
import pytest
from ontoexplorer.clients import reasoning


def _client_capturing(calls, *, justify_422=False):
    class _Resp:
        def __init__(self, status=200, payload=None):
            self.status_code = status; self._p = payload or {}
        def json(self): return self._p
        def raise_for_status(self): pass
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            calls.append(("POST", url, json))
            if justify_422 and url.endswith("/justification"):
                return _Resp(422, {"detail": "reasoner 'konclude' does not support justifications"})
            return _Resp(202, {"status": "running"})
        async def get(self, url):
            calls.append(("GET", url, None))
            return _Resp(200, {"superclasses": {}, "consistent": True})
    return lambda *a, **k: _Client()


@pytest.mark.asyncio
async def test_request_justification_reasoner_in_body(monkeypatch):
    calls = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing(calls))
    await reasoning.request_justification("v1", "s", "o", 1, reasoner="rustdl")
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[2]["reasoner"] == "rustdl"


@pytest.mark.asyncio
async def test_request_justification_422_becomes_unavailable(monkeypatch):
    calls = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing(calls, justify_422=True))
    result = await reasoning.request_justification("v1", "s", "o", 1, reasoner="konclude")
    assert result["reasoning_available"] is False
    assert result["justifications"] == []


def _client_capturing_get_with_params(calls, payload=None):
    class _Resp:
        def __init__(self, status=200, payload=None):
            self.status_code = status; self._p = payload or {}
        def json(self): return self._p
        def raise_for_status(self): pass
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            calls.append((url, params))
            return _Resp(200, payload or {"superclasses": []})
    return lambda *a, **k: _Client()


@pytest.mark.asyncio
async def test_superclasses_reasoner_reaches_wire(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: r)
    calls = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing_get_with_params(calls))
    await reasoning.superclasses("v1", "http://example.org/C", reasoner="rustdl")
    assert len(calls) == 1
    _, params = calls[0]
    assert params["reasoner"] == "rustdl"


@pytest.mark.asyncio
async def test_superclasses_cache_scoped_by_reasoner(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: r)
    calls = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing_get_with_params(calls))

    await reasoning.superclasses("v1", "http://example.org/C", reasoner="whelk")
    assert len(calls) == 1

    # Same (version_id, class_iri, direct, reasoner) -> served from cache, no new GET.
    await reasoning.superclasses("v1", "http://example.org/C", reasoner="whelk")
    assert len(calls) == 1

    # Same (version_id, class_iri, direct) but a DIFFERENT reasoner -> must not
    # collide with whelk's cached entry; a fresh GET is required.
    await reasoning.superclasses("v1", "http://example.org/C", reasoner="rustdl")
    assert len(calls) == 2
    assert calls[1][1]["reasoner"] == "rustdl"


@pytest.mark.asyncio
async def test_subclasses_reasoner_reaches_wire(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: r)
    calls = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing_get_with_params(calls))
    await reasoning.subclasses("v1", "http://example.org/C", reasoner="konclude")
    assert len(calls) == 1
    _, params = calls[0]
    assert params["reasoner"] == "konclude"


@pytest.mark.asyncio
async def test_subclasses_cache_scoped_by_reasoner(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: r)
    calls = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing_get_with_params(calls))

    await reasoning.subclasses("v1", "http://example.org/C", reasoner="whelk")
    assert len(calls) == 1
    await reasoning.subclasses("v1", "http://example.org/C", reasoner="whelk")
    assert len(calls) == 1
    await reasoning.subclasses("v1", "http://example.org/C", reasoner="rustdl")
    assert len(calls) == 2
    assert calls[1][1]["reasoner"] == "rustdl"


def test_elk_cache_key_scoped_by_reasoner():
    k1 = reasoning._elk_cache_key("super", "v1", "http://example.org/C", False, "whelk")
    k2 = reasoning._elk_cache_key("super", "v1", "http://example.org/C", False, "rustdl")
    assert k1 != k2
    assert "whelk" in k1
    assert "rustdl" in k2


def _client_capturing_get_url(calls, payload=None):
    class _Resp:
        def __init__(self, status=200, payload=None):
            self.status_code = status; self._p = payload or {}
        def json(self): return self._p
        def raise_for_status(self): pass
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url):
            calls.append(url)
            return _Resp(200, payload or {"superclasses": {}})
    return lambda *a, **k: _Client()


@pytest.mark.asyncio
async def test_get_classification_reasoner_reaches_wire(monkeypatch):
    """Regression for Critical Fix #2: get_classification must append
    ?reasoner=<reasoner> to the /classify/{version_id} GET, otherwise the
    reasoner-service's whelk-scoped cache key 409s for non-whelk versions.
    """
    calls: list[str] = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing_get_url(calls))
    await reasoning.get_classification("v-get-classification-rustdl", reasoner="rustdl")
    assert len(calls) == 1
    assert "reasoner=rustdl" in calls[0]


@pytest.mark.asyncio
async def test_get_classification_defaults_to_whelk(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing_get_url(calls))
    await reasoning.get_classification("v-get-classification-default")
    assert len(calls) == 1
    assert "reasoner=whelk" in calls[0]
