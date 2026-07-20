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


@pytest.mark.anyio
async def test_submit_rejects_unknown_reasoner(client, _captured_delay):
    r = await client.post("/api/v1/ontologies", json={"iri": "http://x/o.owl", "reasoner": "hermit"})
    assert r.status_code == 422
    assert "hermit" in r.text


@pytest.mark.anyio
async def test_submit_threads_reasoner_to_task(client, _captured_delay):
    r = await client.post("/api/v1/ontologies", json={"iri": "http://x/o.owl", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert _captured_delay.get("reasoner") == "rustdl"


@pytest.mark.anyio
async def test_submit_defaults_reasoner_when_omitted(client, _captured_delay):
    r = await client.post("/api/v1/ontologies", json={"iri": "http://x/o.owl"})
    assert r.status_code == 200
    assert _captured_delay.get("reasoner") == "whelk"   # app default
