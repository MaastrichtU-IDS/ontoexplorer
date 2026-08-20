"""POST /ontologies must honour an explicit `format`, and refuse an unknown one.

`format` used to be forwarded as the request's Content-Type. None of the values
the paste form sent ("turtle", "obo", …) are MIME types, so it never matched and
was silently discarded — picking "obo" for Turtle content still ingested Turtle.
It now travels as its own argument, canonicalised at this boundary.
"""
import pytest

from ontoexplorer.clients import reasoning


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
        tasks.ingest_ontology,
        "delay",
        lambda **kw: captured.update(kw) or type("T", (), {"id": "t1"})(),
    )
    return captured


@pytest.fixture()
def _allow_upload(monkeypatch):
    monkeypatch.setattr("ontoexplorer.modules.auth.dependencies.can_upload", lambda user: True)


@pytest.mark.anyio
async def test_paste_format_reaches_the_task_as_format(client, user_and_key, _allow_upload, _captured):
    _, key = user_and_key
    r = await client.post(
        "/api/v1/ontologies",
        json={"content": "Class: :Person", "format": "omn"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert _captured.get("format") == "omn"
    # and must NOT be smuggled through content_type any more
    assert _captured.get("content_type") != "omn"


@pytest.mark.anyio
async def test_paste_format_alias_is_canonicalised(client, user_and_key, _allow_upload, _captured):
    _, key = user_and_key
    r = await client.post(
        "/api/v1/ontologies",
        json={"content": "@prefix : <http://x/> .", "format": "turtle"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert _captured.get("format") == "ttl"


@pytest.mark.anyio
async def test_omitted_format_means_auto_detect(client, user_and_key, _allow_upload, _captured):
    _, key = user_and_key
    r = await client.post(
        "/api/v1/ontologies",
        json={"content": "@prefix : <http://x/> ."},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert _captured.get("format") is None


@pytest.mark.anyio
async def test_empty_format_means_auto_detect(client, user_and_key, _allow_upload, _captured):
    """The Auto-detect option submits an empty string."""
    _, key = user_and_key
    r = await client.post(
        "/api/v1/ontologies",
        json={"content": "@prefix : <http://x/> .", "format": ""},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert _captured.get("format") is None


@pytest.mark.anyio
async def test_unknown_format_is_rejected(client, user_and_key, _allow_upload, _captured):
    _, key = user_and_key
    r = await client.post(
        "/api/v1/ontologies",
        json={"content": "whatever", "format": "not-a-format"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 422
    assert "not-a-format" in r.text
    assert not _captured, "no task should be queued for an invalid format"


@pytest.mark.anyio
async def test_format_also_accepted_alongside_an_iri(client, user_and_key, _allow_upload, _captured):
    """Useful when a server reports the wrong Content-Type for its own file."""
    _, key = user_and_key
    r = await client.post(
        "/api/v1/ontologies",
        json={"iri": "http://example.org/o.owl", "format": "ofn"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200
    assert _captured.get("format") == "ofn"
