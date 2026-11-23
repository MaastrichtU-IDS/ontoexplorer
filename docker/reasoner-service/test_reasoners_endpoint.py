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


def _store_konclude_classification():
    # A cached classification must exist for the endpoint to proceed past the
    # existence check; store a minimal one under the konclude key.
    import cache as cache_mod
    from classifier import ClassificationResult
    r = ClassificationResult("v1", "t", 0, {}, {}, {}, {}, [], {}, 1.0)
    cache_mod.store_classification(r, "konclude")


def test_justification_for_konclude_version_runs_on_rustdl(client):
    # Konclude has no justify capability, but justifications are reasoner-
    # agnostic (#91): a konclude-classified version is justified by the
    # dedicated justifier (rustdl by default) instead of being refused.
    pytest.importorskip("rustdl")
    _store_konclude_classification()
    resp = client.post("/classify/v1/justification",
                       json={"sub": "s", "sup": "o", "reasoner": "konclude"})
    assert resp.status_code == 200
    assert resp.json()["reasoner"] == "konclude"
    assert resp.json()["justifier"] == "rustdl"


def test_justification_422_when_justifier_cannot_justify(client, monkeypatch):
    # Configuring a reasoner without justify as the justifier is refused.
    monkeypatch.setenv("JUSTIFY_REASONER", "konclude")
    _store_konclude_classification()
    resp = client.post("/classify/v1/justification",
                       json={"sub": "s", "sup": "o", "reasoner": "konclude"})
    assert resp.status_code == 422
    assert "justifier 'konclude' is unavailable" in resp.json()["detail"]


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


def test_failed_justification_is_not_cached(client, monkeypatch):
    # A worker failure answers with an empty list but must not be cached, or the
    # empty answer would be served for JUSTIFICATION_TTL after the cause is fixed.
    import subprocess
    import cache as cache_mod
    from classifier import ClassificationResult
    r = ClassificationResult("vf", "t", 0, {}, {}, {}, {}, [], {}, 1.0)
    cache_mod.store_classification(r, "rustdl")
    cache_mod.store_input_axioms("vf", "", "rustdl")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], returncode=1, stdout="", stderr="boom"))
    resp = client.post("/classify/vf/justification",
                       json={"sub": "http://ex/A", "sup": "http://ex/B", "reasoner": "rustdl"})
    assert resp.status_code == 200
    assert resp.json()["justifications_found"] == 0
    assert cache_mod.load_justification("vf", "http://ex/A", "http://ex/B", 1, "rustdl") is None
