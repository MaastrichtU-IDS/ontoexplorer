import httpx
import pytest
from ontoexplorer.clients import reasoning


class _FakeResp:
    def __init__(self, payload): self._p = payload; self.status_code = 200
    def json(self): return self._p
    def raise_for_status(self): pass


@pytest.mark.asyncio
async def test_available_reasoner_names_from_service(monkeypatch):
    payload = [
        {"name": "whelk", "capabilities": ["classify"], "available": True},
        {"name": "rustdl", "capabilities": ["classify"], "available": True},
        {"name": "konclude", "capabilities": ["classify"], "available": False},
    ]

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _FakeResp(payload)

    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _Client())
    names = await reasoning.available_reasoner_names()
    assert names == {"whelk", "rustdl"}          # konclude excluded (available False)


@pytest.mark.asyncio
async def test_available_reasoner_names_falls_back_when_unreachable(monkeypatch):
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise httpx.ConnectError("down")

    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _Client())
    names = await reasoning.available_reasoner_names()
    assert names == {"whelk", "rdflib", "rustdl", "konclude"}   # known-names fallback
