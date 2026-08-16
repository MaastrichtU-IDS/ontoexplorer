from fastapi.testclient import TestClient
import main
from classifier import ClassificationResult


class _FakeBackend:
    def __init__(self, unsat):
        self._unsat = unsat
    def classify_ntriples(self, ntriples, version_id, params=None):
        return ClassificationResult(
            version_id=version_id, classified_at="t", class_count=0,
            superclasses={}, subclasses={}, direct_superclasses={},
            direct_subclasses={}, unsatisfiable=list(self._unsat),
            proof_traces={}, duration_ms=0.0)


def test_consistency_consistent(monkeypatch):
    monkeypatch.setattr(main, "get_backend", lambda name: _FakeBackend([]))
    c = TestClient(main.app)
    r = c.post("/consistency", json={"ntriples": "", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert r.json()["inconsistent"] is False
    assert r.json()["unsatisfiable_classes"] == []


def test_consistency_reports_thing_as_inconsistent(monkeypatch):
    monkeypatch.setattr(main, "get_backend",
                        lambda name: _FakeBackend(["http://www.w3.org/2002/07/owl#Thing", "http://x/C"]))
    c = TestClient(main.app)
    r = c.post("/consistency", json={"ntriples": "", "reasoner": "rustdl"})
    assert r.json()["inconsistent"] is True
    assert "http://x/C" in r.json()["unsatisfiable_classes"]
