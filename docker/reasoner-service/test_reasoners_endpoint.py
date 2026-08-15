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
    assert "profile" in by_name["whelk"] and "available" in by_name["whelk"]


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
