"""Integration tests for the MOS search API endpoints."""
import fakeredis
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key

_VERSION_MOCK = MagicMock()
_MOCK_VERSION = AsyncMock(return_value=_VERSION_MOCK)

_FAKE_REDIS = fakeredis.FakeRedis(decode_responses=True)

def _seed_redis(version_id: str):
    _FAKE_REDIS.flushall()
    key = _prefix_key(version_id)
    _FAKE_REDIS.zadd(key, {"cell death|class|http://ex.org/CD": 0})
    _FAKE_REDIS.zadd(key, {"nucleus|class|http://ex.org/N": 0})
    _FAKE_REDIS.hset(_iri_key(version_id, "http://ex.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://ex.org/CD", "short": "EX:CD", "synonyms": "",
    })
    _FAKE_REDIS.hset(_iri_key(version_id, "http://ex.org/N"), mapping={
        "label": "nucleus", "type": "class",
        "iri": "http://ex.org/N", "short": "EX:N", "synonyms": "",
    })


@pytest.mark.anyio
async def test_search_entity_mode(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch("ontoexplorer.api.ontologies._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "cell death", "mode": "entity"},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "entity"
    assert any(r["iri"] == "http://ex.org/CD" for r in body["results"])


@pytest.mark.anyio
async def test_search_expression_not_classified(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    from ontoexplorer.clients.reasoning import ReasoningNotReadyError

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(side_effect=ReasoningNotReadyError("fake-vid"))), \
         patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death' and 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 503
    assert resp.json()["error"] == "not_classified"


@pytest.mark.anyio
async def test_search_expression_parse_error(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "and and and", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "parse_error"


@pytest.mark.anyio
async def test_search_ambiguous_label_returns_422(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    from ontoexplorer.modules.search.evaluator import AmbiguousLabelError

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value={"subclasses": {}, "class_count": 0})), \
         patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.evaluator._resolve_label",
               side_effect=AmbiguousLabelError("cell death", [
                   {"label": "cell death", "short": "GO:CD", "iri": "http://go.org/CD"},
                   {"label": "cell death", "short": "MONDO:CD", "iri": "http://mondo.org/CD"},
               ])):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "ambiguous_label"
    assert len(body["candidates"]) == 2


@pytest.mark.anyio
async def test_autocomplete_open_quote(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/autocomplete",
            params={"q": "'cell", "cursor": 5},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "completions" in body
    assert any("cell death" in c["text"] for c in body["completions"])


@pytest.mark.anyio
async def test_autocomplete_after_entity_returns_keywords(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/autocomplete",
            params={"q": "'Cell'", "cursor": 6},
            headers=auth,
        )
    assert resp.status_code == 200
    texts = [c["text"] for c in resp.json()["completions"]]
    assert "some" in texts
    assert "and" in texts
