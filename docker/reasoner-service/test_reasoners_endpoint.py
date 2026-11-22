import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import fakeredis
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, "_redis", fakeredis.FakeStrictRedis())


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def test_reasoners_endpoint_lists_capabilities(client):
    resp = client.get("/reasoners")
    assert resp.status_code == 200
    by_name = {r["name"]: r for r in resp.json()}
    assert {"rustdl", "konclude", "km"} <= set(by_name)
    assert "justify" in by_name["rustdl"]["capabilities"]
    assert "justify" not in by_name["konclude"]["capabilities"]
    assert "profile" in by_name["rustdl"] and "available" in by_name["rustdl"]


def test_justification_422_for_konclude(client, monkeypatch):
    # A cached classification must exist for the endpoint to proceed to the
    # capability check; store a minimal one under the konclude key.
    import cache as cache_mod
    from classifier import ClassificationResult
    r = ClassificationResult("v1", "t", 0, {}, {}, {}, {}, [], {}, 1.0)
    cache_mod.store_classification(r, "konclude")
    resp = client.post("/classify/v1/justification",
                       json={"sub": "s", "sup": "o", "reasoner": "konclude"})
    assert resp.status_code == 422
    assert "does not support justifications" in resp.json()["detail"]


def test_justification_returns_the_justifying_axioms(client):
    # End-to-end through the justify_worker subprocess: A ⊑ B ⊑ C entails
    # A ⊑ C, justified by both asserted axioms. Guards the whole path, which
    # once failed on every request (NameError in the endpoint) while still
    # answering 200 with an empty list.
    pytest.importorskip("rustdl")
    import cache as cache_mod
    from classifier import ClassificationResult
    ex = "http://example.org/"
    sub = "<http://www.w3.org/2000/01/rdf-schema#subClassOf>"
    nt = "".join(
        f"<{ex}{c}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
        f"<http://www.w3.org/2002/07/owl#Class> .\n" for c in "ABC"
    ) + f"<{ex}A> {sub} <{ex}B> .\n<{ex}B> {sub} <{ex}C> .\n"
    r = ClassificationResult("vj", "t", 3, {}, {}, {}, {}, [], {}, 1.0)
    cache_mod.store_classification(r, "rustdl")
    cache_mod.store_input_axioms("vj", nt, "rustdl")
    resp = client.post("/classify/vj/justification",
                       json={"sub": f"{ex}A", "sup": f"{ex}C", "reasoner": "rustdl"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["justifications_found"] == 1, body
    assert len(body["justifications"]) == 1
