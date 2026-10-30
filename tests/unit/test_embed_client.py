import json
import math

import httpx
import pytest

from ontoexplorer.modules.search import embed_client as ec

PRIMARY = "http://primary.test/v1"
FALLBACK = "http://fallback.test/v1"
DIM = 768


class _S:
    embedding_base_url = PRIMARY
    embedding_api_key = "sk-test"
    embedding_model = "nomic-embed-text"
    embedding_fallback_base_url = FALLBACK
    embedding_timeout_s = 5.0
    embedding_fallback_timeout_s = 7.0
    embedding_dim = DIM


def _vec(seed=1.0, dim=DIM):
    v = [0.0] * dim
    v[0] = seed
    v[1] = 2.0
    return v


def _ok(vectors, order=None):
    data = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    if order:
        data = [data[i] for i in order]
    return httpx.Response(200, json={"data": data})


@pytest.fixture
def wire(monkeypatch):
    calls = []
    state = {"handler": None}

    def handler(request):
        body = json.loads(request.content)
        calls.append((str(request.url), body, dict(request.headers)))
        return state["handler"](request, body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ec, "_client", client)
    monkeypatch.setattr(ec, "get_settings", lambda: _S())
    monkeypatch.setattr(ec.time, "sleep", lambda s: None)
    return calls, state


def test_embed_batch_prepends_prefix(wire):
    calls, st = wire
    st["handler"] = lambda r, b: _ok([_vec() for _ in b["input"]])
    ec.embed_batch(["a", "b"], prefix="search_document: ")
    url, body, headers = calls[0]
    assert url == PRIMARY + "/embeddings"
    assert body["input"] == ["search_document: a", "search_document: b"]
    assert body["model"] == "nomic-embed-text"
    assert headers["authorization"] == "Bearer sk-test"


def test_embed_batch_normalizes(wire):
    _, st = wire
    st["handler"] = lambda r, b: _ok([_vec(3.0)])
    out = ec.embed_batch(["a"], prefix="")
    assert math.isclose(math.sqrt(sum(x * x for x in out[0])), 1.0, rel_tol=1e-9)


def test_embed_batch_rejects_wrong_dim(wire):
    _, st = wire
    st["handler"] = lambda r, b: _ok([_vec(dim=10)])
    with pytest.raises(ec.EmbeddingError):
        ec.embed_batch(["a"], prefix="")


def test_embed_batch_sorts_by_index(wire):
    _, st = wire
    vecs = [_vec(1.0), _vec(5.0), _vec(9.0)]
    st["handler"] = lambda r, b: _ok(vecs, order=[2, 0, 1])
    out = ec.embed_batch(["a", "b", "c"], prefix="")
    assert out == [ec._l2(v) for v in vecs]


def test_embed_batch_splits_on_too_large(wire):
    calls, st = wire

    def h(r, b):
        if len(b["input"]) > 1:
            return httpx.Response(413, text="too large")
        return _ok([_vec(float(b["input"][0][-1] == "b") + 1)])

    st["handler"] = h
    out = ec.embed_batch(["a", "b"], prefix="")
    assert [len(c[1]["input"]) for c in calls] == [2, 1, 1]
    assert len(out) == 2 and out[0] != out[1]


def test_embed_batch_splits_on_500_too_large_body(wire):
    calls, st = wire

    def h(r, b):
        if len(b["input"]) > 1:
            return httpx.Response(500, text="input is too large for batch")
        return _ok([_vec()])

    st["handler"] = h
    assert len(ec.embed_batch(["a", "b"], prefix="")) == 2
    assert [len(c[1]["input"]) for c in calls] == [2, 1, 1]


def test_embed_batch_falls_back_on_primary_error(wire):
    calls, st = wire
    before = ec.FALLBACK_COUNT

    def h(r, b):
        if str(r.url).startswith(PRIMARY):
            return httpx.Response(401, text="nope")
        return _ok([_vec()])

    st["handler"] = h
    out = ec.embed_batch(["a"], prefix="")
    assert len(out) == 1
    assert calls[-1][0] == FALLBACK + "/embeddings"
    assert "authorization" not in calls[-1][2]
    assert ec.FALLBACK_COUNT == before + 1


def test_embed_batch_raises_when_both_fail(wire):
    _, st = wire
    st["handler"] = lambda r, b: httpx.Response(500, text="boom")
    with pytest.raises(ec.EmbeddingError):
        ec.embed_batch(["a"], prefix="")


def test_embed_batch_retries_then_falls_back_on_429(wire):
    calls, st = wire

    def h(r, b):
        if str(r.url).startswith(PRIMARY):
            return httpx.Response(429, text="slow down")
        return _ok([_vec()])

    st["handler"] = h
    ec.embed_batch(["a"], prefix="")
    hosts = [c[0].split("/v1")[0] for c in calls]
    assert hosts == ["http://primary.test"] * 3 + ["http://fallback.test"]


def test_empty_primary_goes_straight_to_fallback(wire, monkeypatch):
    calls, st = wire

    class S2(_S):
        embedding_base_url = ""

    monkeypatch.setattr(ec, "get_settings", lambda: S2())
    st["handler"] = lambda r, b: _ok([_vec()])
    ec.embed_batch(["a"], prefix="")
    assert [c[0] for c in calls] == [FALLBACK + "/embeddings"]
