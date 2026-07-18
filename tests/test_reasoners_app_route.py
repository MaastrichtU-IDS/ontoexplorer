"""Tests for the app-level GET /api/v1/reasoners passthrough (SP3 Task 4).

The frontend api client calls /api/v1/reasoners to populate a reasoner picker.
The app itself has no reasoner state of its own -- it proxies the
reasoner-service's own /reasoners payload via reasoning.list_reasoners().
"""

import pytest
from ontoexplorer.clients import reasoning


class _FakeResp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


@pytest.mark.anyio
async def test_reasoners_route_proxies_service_payload(client, monkeypatch):
    payload = [
        {"name": "whelk", "profile": "el", "capabilities": ["classify", "justify"], "available": True},
        {"name": "rustdl", "profile": "dl", "capabilities": ["classify"], "available": True},
        {"name": "konclude", "profile": "dl", "capabilities": ["classify"], "available": False},
    ]

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _FakeResp(payload)

    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _Client())

    r = await client.get("/api/v1/reasoners")
    assert r.status_code == 200
    assert r.json() == payload


@pytest.mark.anyio
async def test_reasoners_route_propagates_service_error(client, monkeypatch):
    import httpx

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _Client())

    with pytest.raises(httpx.ConnectError):
        await client.get("/api/v1/reasoners")
