"""Admin trigger for the gated MOD-API harvest (POST /api/v1/admin/harvest).

Thin endpoint: validates the body and enqueues ``harvest_peer``; dry-run by default.
"""
import pytest

from ontoexplorer.modules.jobs import tasks


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)

        class _Result:
            id = "task-123"

        return _Result()


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(tasks.harvest_peer, "delay", rec)
    return rec


@pytest.mark.anyio
async def test_requires_admin(client, recorder):
    # No admin override -> _require_admin rejects before anything is enqueued.
    r = await client.post("/api/v1/admin/harvest", json={"dry_run": True})
    assert r.status_code in (401, 403)
    assert recorder.calls == []


@pytest.mark.anyio
async def test_requires_admin_for_non_admin_key(client, user_and_key, recorder):
    _, raw_key = user_and_key
    r = await client.post(
        "/api/v1/admin/harvest", json={"dry_run": False},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 403
    assert recorder.calls == []


@pytest.mark.anyio
async def test_enqueues_harvest_task(admin_client, recorder):
    r = await admin_client.post(
        "/api/v1/admin/harvest", json={"dry_run": True, "peer_id": "agroportal", "limit": 25}
    )
    assert r.status_code == 200
    assert r.json() == {"task_id": "task-123", "dry_run": True, "peer_id": "agroportal"}
    assert recorder.calls == [{"peer_id": "agroportal", "limit": 25, "dry_run": True}]


@pytest.mark.anyio
async def test_defaults_to_dry_run(admin_client, recorder):
    r = await admin_client.post("/api/v1/admin/harvest", json={})
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert recorder.calls[0]["dry_run"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [-1, 0, 501, 99999])
async def test_rejects_bad_limit(admin_client, recorder, limit):
    r = await admin_client.post("/api/v1/admin/harvest", json={"limit": limit})
    assert r.status_code == 422
    assert recorder.calls == []
