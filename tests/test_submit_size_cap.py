"""POST /ontologies must cap EVERY submission mode (not just URL/IRI fetches, which
the worker's source_resolver already caps). File-upload and inline `content` were
uncapped — a DoS/resource hole."""
import pytest

from ontoexplorer.clients import reasoning
from ontoexplorer.config import get_settings


@pytest.fixture(autouse=True)
def _reasoners(monkeypatch):
    async def _names():
        return {"whelk", "rustdl"}
    monkeypatch.setattr(reasoning, "available_reasoner_names", _names)


@pytest.fixture()
def _captured(monkeypatch):
    captured: dict = {}
    from ontoexplorer.modules.jobs import tasks
    monkeypatch.setattr(
        tasks.ingest_ontology, "delay",
        lambda **kw: captured.update(kw) or type("T", (), {"id": "t1"})(),
    )
    return captured


@pytest.fixture()
def _allow_upload(monkeypatch):
    monkeypatch.setattr("ontoexplorer.modules.auth.dependencies.can_upload", lambda user: True)


@pytest.fixture()
def _tiny_cap(monkeypatch):
    # 100 bytes: a tiny request envelope ({"content":"x",…}) fits; the oversize
    # payloads below clearly exceed it. (The Content-Length guard bounds the whole
    # request, so the cap must leave room for the JSON/multipart envelope.)
    monkeypatch.setattr(get_settings(), "ingest_max_source_bytes", 100, raising=False)


@pytest.mark.anyio
async def test_inline_content_over_cap_rejected(client, user_and_key, _allow_upload, _tiny_cap, _captured):
    _, key = user_and_key
    r = await client.post(
        "/api/v1/ontologies",
        json={"content": "Class: :Person " * 20, "format": "omn"},  # ~300 bytes > 100
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 413
    assert _captured == {}  # never queued


@pytest.mark.anyio
async def test_file_upload_over_cap_rejected(client, user_and_key, _allow_upload, _tiny_cap, _captured):
    _, key = user_and_key
    big = b"@prefix : <http://ex/> . :A a :Class ." * 5  # ~190 bytes > 100
    r = await client.post(
        "/api/v1/ontologies",
        files={"file": ("o.ttl", big, "text/turtle")},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 413
    assert _captured == {}


@pytest.mark.anyio
async def test_small_content_under_cap_passes(client, user_and_key, _allow_upload, _tiny_cap, _captured):
    _, key = user_and_key
    r = await client.post(
        "/api/v1/ontologies",
        json={"content": "x", "format": "omn"},  # 1 byte < 10
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert _captured.get("raw_bytes_hex") == b"x".hex()
