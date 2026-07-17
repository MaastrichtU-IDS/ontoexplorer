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
