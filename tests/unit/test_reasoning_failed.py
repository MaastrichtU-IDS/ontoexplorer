"""classify_v2 raises ReasoningFailed (not a generic HTTP error) when the
reasoner-service has recorded a deterministic classification failure, so the
reason task can fail fast instead of retrying a doomed classification.
"""
import pytest
import rdflib

from ontoexplorer.clients import reasoning
from ontoexplorer.clients.reasoning import ReasoningFailed, classify_v2


class _Resp:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.text = ""

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Async-context httpx.AsyncClient stand-in with scripted POST/GET."""
    post_json = {"status": "running"}
    get_resp = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return _Resp(202, self.post_json)

    async def get(self, *a, **k):
        return self.get_resp


@pytest.fixture
def _no_sleep(monkeypatch):
    async def _sleep(*a, **k):
        return None
    monkeypatch.setattr(reasoning.asyncio, "sleep", _sleep)


@pytest.mark.anyio
async def test_classify_v2_raises_reasoning_failed_on_stored_error(monkeypatch, _no_sleep):
    class _C(_FakeClient):
        get_resp = _Resp(500, {"detail": "Classification failed: rustdl process exited -6 (crash)"})
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _C())
    with pytest.raises(ReasoningFailed):
        await classify_v2(rdflib.Graph(), "v1", reasoner="rustdl")


@pytest.mark.anyio
async def test_classify_v2_generic_500_is_not_reasoning_failed(monkeypatch, _no_sleep):
    # A 500 that is NOT a recorded classification error stays a retryable HTTP error.
    class _C(_FakeClient):
        get_resp = _Resp(500, {"detail": "Internal Server Error"})
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _C())
    with pytest.raises(Exception) as ei:
        await classify_v2(rdflib.Graph(), "v1", reasoner="rustdl")
    assert not isinstance(ei.value, ReasoningFailed)


@pytest.mark.anyio
async def test_classify_v2_returns_when_done(monkeypatch, _no_sleep):
    class _C(_FakeClient):
        post_json = {"status": "done", "version_id": "v1"}
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _C())
    out = await classify_v2(rdflib.Graph(), "v1", reasoner="whelk")
    assert out["status"] == "done"
