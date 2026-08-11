"""_reasoning_status must recognize the reasoner-scoped classification cache
(`classification:{vid}:{reasoner}`) — regression for the admin panel showing
'not_started' even after reasoning completed, because it only checked the
legacy bare `classification:{vid}` key.
"""
import fnmatch

import pytest

from ontoexplorer.api.admin import _common


class _FakeRedis:
    def __init__(self, keys):
        self.keys = set(keys)

    def exists(self, k):
        return 1 if k in self.keys else 0

    def scan_iter(self, match=None, count=None):
        return iter([k for k in self.keys if fnmatch.fnmatch(k, match)])


def _patch(monkeypatch, keys):
    monkeypatch.setattr(_common, "_elk_redis", lambda: _FakeRedis(keys))


@pytest.mark.anyio
async def test_ready_from_reasoner_scoped_key(monkeypatch):
    _patch(monkeypatch, {"classification:v1:rustdl"})
    assert await _common._reasoning_status("v1", "rustdl") == "ready"


@pytest.mark.anyio
async def test_ready_from_legacy_bare_key(monkeypatch):
    _patch(monkeypatch, {"classification:v1"})
    assert await _common._reasoning_status("v1", "whelk") == "ready"


@pytest.mark.anyio
async def test_ready_from_any_reasoner_scan(monkeypatch):
    # Classified with konclude but asked about rustdl → scan still finds it.
    _patch(monkeypatch, {"classification:v1:konclude"})
    assert await _common._reasoning_status("v1", "rustdl") == "ready"


@pytest.mark.anyio
async def test_not_ready_for_other_version(monkeypatch):
    _patch(monkeypatch, {"classification:other:rustdl"})
    # No cache for v1 → falls through to the reasoner-service probe. Point it at
    # an unroutable host so the probe fails fast and we get not_started.
    monkeypatch.setattr(
        _common.get_settings(), "reasoner_service_url", "http://127.0.0.1:0", raising=False,
    )
    assert await _common._reasoning_status("v1", "rustdl") == "not_started"
