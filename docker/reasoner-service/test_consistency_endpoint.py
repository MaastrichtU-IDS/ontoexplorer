import subprocess

from fastapi.testclient import TestClient

import main


# The endpoint runs the reasoner in an isolated subprocess (consistency_worker.py)
# so a rustdl segfault/OOM can't kill the uvicorn worker. Tests below mock the
# isolation seam (`main._consistency_isolated`) to exercise the endpoint's own
# logic — OFN merge, Thing->inconsistent, bad-OFN 422 — and mock `subprocess.run`
# to exercise the subprocess result/crash handling inside `_consistency_isolated`.


def test_consistency_consistent(monkeypatch):
    monkeypatch.setattr(main, "get_backend", lambda name: object())
    monkeypatch.setattr(main, "_consistency_isolated", lambda nt, reasoner: [])
    c = TestClient(main.app)
    r = c.post("/consistency", json={"ntriples": "", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert r.json()["inconsistent"] is False
    assert r.json()["unsatisfiable_classes"] == []


def test_consistency_reports_thing_as_inconsistent(monkeypatch):
    monkeypatch.setattr(main, "get_backend", lambda name: object())
    monkeypatch.setattr(
        main, "_consistency_isolated",
        lambda nt, reasoner: ["http://www.w3.org/2002/07/owl#Thing", "http://x/C"])
    c = TestClient(main.app)
    r = c.post("/consistency", json={"ntriples": "", "reasoner": "rustdl"})
    assert r.json()["inconsistent"] is True
    assert "http://x/C" in r.json()["unsatisfiable_classes"]


def test_consistency_merges_ofn(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "get_backend", lambda name: object())
    def _fake(nt, reasoner):
        seen["nt"] = nt
        return []
    monkeypatch.setattr(main, "_consistency_isolated", _fake)
    c = TestClient(main.app)
    ofn = ("Declaration(Class(<http://x#DemoRole>))\n"
           "SubClassOf(<http://x#DemoRole> <https://w3id.org/sulo/Role>)")
    r = c.post("/consistency", json={"ntriples": "", "ofn": ofn, "reasoner": "rustdl"})
    assert r.status_code == 200
    assert r.json()["inconsistent"] is False
    # the OFN was converted to N-Triples and handed to the isolated worker
    assert "DemoRole" in seen["nt"]


def test_consistency_bad_ofn_returns_422(monkeypatch):
    monkeypatch.setattr(main, "get_backend", lambda name: object())
    c = TestClient(main.app)
    r = c.post("/consistency",
               json={"ntriples": "", "ofn": "this is not valid OFN ((", "reasoner": "rustdl"})
    assert r.status_code == 422


class _Proc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_consistency_isolated_success_parses_stdout(monkeypatch):
    """A clean worker exit (rc 0) with a JSON stdout line yields the unsat set."""
    monkeypatch.setattr(main, "get_backend", lambda name: object())
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _Proc(0, stdout='INFO some log noise\n{"unsatisfiable": ["http://x/C"]}\n'))
    c = TestClient(main.app)
    r = c.post("/consistency", json={"ntriples": "<a> <b> <c> .", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert r.json()["unsatisfiable_classes"] == ["http://x/C"]
    assert r.json()["inconsistent"] is False


def test_consistency_isolated_crash_returns_500(monkeypatch):
    """A non-zero worker exit (segfault/OOM/abort) becomes a clean HTTP 500,
    NOT a uvicorn worker death / disconnected connection."""
    monkeypatch.setattr(main, "get_backend", lambda name: object())
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _Proc(-11, stdout="", stderr="Segmentation fault"))
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.post("/consistency", json={"ntriples": "<a> <b> <c> .", "reasoner": "rustdl"})
    assert r.status_code == 500
    assert "crashed" in r.json()["detail"]


def test_consistency_isolated_timeout_returns_504(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="consistency_worker", timeout=1)
    monkeypatch.setattr(main, "get_backend", lambda name: object())
    monkeypatch.setattr(subprocess, "run", _boom)
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.post("/consistency", json={"ntriples": "<a> <b> <c> .", "reasoner": "rustdl"})
    assert r.status_code == 504
