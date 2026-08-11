"""_reasoning_status must recognize the reasoner-scoped classification cache
(`classification:{vid}:{reasoner}`) — regression for the admin panel showing
'not_started' even after reasoning completed, because it only checked the
legacy bare `classification:{vid}` key.

It must also report 'running' while a reason Job is pending/running. The old
`/classify/{vid}` progress probe was dropped (the reasoner-service now returns
403 for it), so 'running' is derived from the jobs table instead.
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


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeDB:
    """Minimal async DB stub: returns one row iff an active reason job exists."""

    def __init__(self, active_job: bool):
        self._active = active_job

    async def execute(self, *args, **kwargs):
        return _FakeResult(("job-1",) if self._active else None)


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
async def test_not_started_when_uncached_and_no_db(monkeypatch):
    _patch(monkeypatch, {"classification:other:rustdl"})
    assert await _common._reasoning_status("v1", "rustdl") == "not_started"


@pytest.mark.anyio
async def test_running_when_active_reason_job(monkeypatch):
    # No classification yet, but a pending/running reason Job exists.
    _patch(monkeypatch, set())
    assert await _common._reasoning_status("v1", "rustdl", _FakeDB(active_job=True)) == "running"


@pytest.mark.anyio
async def test_not_started_when_job_finished_but_uncached(monkeypatch):
    # No active job and no cache → not_started (e.g. a failed run).
    _patch(monkeypatch, set())
    assert await _common._reasoning_status("v1", "rustdl", _FakeDB(active_job=False)) == "not_started"


@pytest.mark.anyio
async def test_ready_takes_precedence_over_running(monkeypatch):
    # Cached classification wins even if a stray job row looks active.
    _patch(monkeypatch, {"classification:v1:rustdl"})
    assert await _common._reasoning_status("v1", "rustdl", _FakeDB(active_job=True)) == "ready"
