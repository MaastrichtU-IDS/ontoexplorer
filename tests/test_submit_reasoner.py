"""Tests for reasoner selection/validation at ontology submit time (SP2 Task 3)."""

import pytest

from ontoexplorer.clients import reasoning


@pytest.fixture(autouse=True)
def _reasoners(monkeypatch):
    async def _names():
        return {"whelk", "rustdl"}
    monkeypatch.setattr(reasoning, "available_reasoner_names", _names)


@pytest.fixture()
def _captured_delay(monkeypatch):
    captured: dict = {}
    from ontoexplorer.modules.jobs import tasks
    monkeypatch.setattr(
        tasks.ingest_ontology,
        "delay",
        lambda **kw: captured.update(kw) or type("T", (), {"id": "t1"})(),
    )
    return captured


@pytest.fixture()
def _allow_upload(monkeypatch):
    """Treat the authenticated test user as an allowed uploader."""
    monkeypatch.setattr("ontoexplorer.modules.auth.dependencies.can_upload", lambda user: True)


@pytest.mark.anyio
async def test_submit_rejects_unknown_reasoner(client, user_and_key, _allow_upload, _captured_delay):
    _, key = user_and_key
    auth = {"Authorization": f"Bearer {key}"}
    r = await client.post("/api/v1/ontologies", json={"iri": "http://x/o.owl", "reasoner": "hermit"}, headers=auth)
    assert r.status_code == 422
    assert "hermit" in r.text


@pytest.mark.anyio
async def test_submit_threads_reasoner_to_task(client, user_and_key, _allow_upload, _captured_delay):
    _, key = user_and_key
    auth = {"Authorization": f"Bearer {key}"}
    r = await client.post("/api/v1/ontologies", json={"iri": "http://x/o.owl", "reasoner": "rustdl"}, headers=auth)
    assert r.status_code == 200
    assert _captured_delay.get("reasoner") == "rustdl"


@pytest.mark.anyio
async def test_submit_defaults_reasoner_when_omitted(client, user_and_key, _allow_upload, _captured_delay):
    _, key = user_and_key
    auth = {"Authorization": f"Bearer {key}"}
    r = await client.post("/api/v1/ontologies", json={"iri": "http://x/o.owl"}, headers=auth)
    assert r.status_code == 200
    assert _captured_delay.get("reasoner") == "whelk"   # app default


@pytest.mark.anyio
async def test_submit_requires_auth(client, _captured_delay):
    """Uploads require login — anonymous POST is rejected."""
    r = await client.post("/api/v1/ontologies", json={"iri": "http://x/o.owl"})
    assert r.status_code == 401


@pytest.mark.anyio
async def test_submit_forbidden_for_non_uploader(client, user_and_key, _captured_delay):
    """Authenticated but not an admin / not on the upload allowlist -> 403."""
    _, key = user_and_key
    auth = {"Authorization": f"Bearer {key}"}
    r = await client.post("/api/v1/ontologies", json={"iri": "http://x/o.owl"}, headers=auth)
    assert r.status_code == 403
