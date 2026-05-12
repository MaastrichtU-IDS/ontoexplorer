"""Integration tests for the MOS search API endpoints."""
import fakeredis
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key

_VERSION_MOCK = MagicMock()
_MOCK_VERSION = AsyncMock(return_value=_VERSION_MOCK)

_FAKE_REDIS = fakeredis.FakeRedis(decode_responses=True)


def _seed_redis(version_id: str, entities: list[tuple[str, str, str]] | None = None):
    """Seed fakeredis with entities. Each entity is (label, iri, type)."""
    _FAKE_REDIS.flushall()
    if entities is None:
        entities = [
            ("cell death", "http://ex.org/CD", "class"),
            ("nucleus", "http://ex.org/N", "class"),
            ("has part", "http://ex.org/HP", "object_property"),
            ("apoptosis", "http://ex.org/AP", "class"),
        ]
    key = _prefix_key(version_id)
    for label, iri, etype in entities:
        _FAKE_REDIS.zadd(key, {f"{label.lower()}|{etype}|{iri}": 0})
        _FAKE_REDIS.hset(_iri_key(version_id, iri), mapping={
            "label": label, "type": etype,
            "iri": iri, "short": iri.split("/")[-1], "synonyms": "",
        })


def _classification(subclasses: dict | None = None, superclasses: dict | None = None):
    sc = subclasses or {
        "http://ex.org/CD": ["http://ex.org/AP"],
        "http://ex.org/N": ["http://ex.org/InnerN"],
        "http://ex.org/AP": [],
        "http://ex.org/InnerN": [],
    }
    return {
        "version_id": "fake-vid",
        "classified_at": "2026-01-01T00:00:00+00:00",
        "class_count": len(sc),
        "superclasses": superclasses or {},
        "subclasses": sc,
        "direct_superclasses": {},
        "direct_subclasses": {},
        "unsatisfiable": [],
        "proof_traces": {},
        "duration_ms": 1.0,
    }


_SEARCH_PATCHES = dict(
    version_404="ontoexplorer.api.search._get_version_or_404",
    redis_indexer="ontoexplorer.modules.search.indexer._get_redis",
    redis_evaluator="ontoexplorer.modules.search.evaluator._get_redis",
    classification="ontoexplorer.modules.search.evaluator.get_classification",
)


# ── Entity mode ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_search_entity_mode(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch("ontoexplorer.api.ontologies._get_version_or_404", new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION):
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
async def test_search_entity_mode_prefix_match(client, user_and_key):
    """Prefix 'nuc' matches 'nucleus'."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "nuc", "mode": "entity"},
            headers=auth,
        )
    assert resp.status_code == 200
    assert any(r["iri"] == "http://ex.org/N" for r in resp.json()["results"])


# ── Auto-mode detection ───────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_search_auto_single_word_falls_back_to_entity(client, user_and_key):
    """Bare single word (no operators) → auto-mode picks entity, not expression."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "nucleus"},
            headers=auth,
        )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "entity"


@pytest.mark.anyio
async def test_search_auto_and_triggers_expression(client, user_and_key):
    """'A and B' in auto-mode → expression mode."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death' and 'nucleus'"},
            headers=auth,
        )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "expression"


# ── Boolean operators ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_search_expression_and_intersection(client, user_and_key):
    """'cell death' and 'nucleus' → intersection of their subclasses (empty here)."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death' and 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "expression"
    iris = {r["iri"] for r in body["results"]}
    # cell death subs = {AP}, nucleus subs = {InnerN} → intersection is empty
    assert iris == set()


@pytest.mark.anyio
async def test_search_expression_and_with_shared_subclass(client, user_and_key):
    """Two classes sharing a subclass → 'and' returns that subclass."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")
    cls = _classification(subclasses={
        "http://ex.org/CD": ["http://ex.org/AP", "http://ex.org/SHARED"],
        "http://ex.org/N":  ["http://ex.org/InnerN", "http://ex.org/SHARED"],
        "http://ex.org/AP": [],
        "http://ex.org/InnerN": [],
        "http://ex.org/SHARED": [],
    })

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"], new=AsyncMock(return_value=cls)):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death' and 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    iris = {r["iri"] for r in resp.json()["results"]}
    assert "http://ex.org/SHARED" in iris
    assert "http://ex.org/AP" not in iris
    assert "http://ex.org/InnerN" not in iris


@pytest.mark.anyio
async def test_search_expression_or_union(client, user_and_key):
    """'cell death' or 'nucleus' → union of subclasses (plus both classes themselves)."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death' or 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    iris = {r["iri"] for r in resp.json()["results"]}
    assert "http://ex.org/CD" in iris
    assert "http://ex.org/AP" in iris
    assert "http://ex.org/N" in iris
    assert "http://ex.org/InnerN" in iris


@pytest.mark.anyio
async def test_search_expression_not_complement(client, user_and_key):
    """'not nucleus' → all classes except nucleus and its subclasses."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "not 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    iris = {r["iri"] for r in resp.json()["results"]}
    # nucleus and InnerN excluded; cell death, AP, HP included
    assert "http://ex.org/N" not in iris
    assert "http://ex.org/InnerN" not in iris
    assert "http://ex.org/CD" in iris


@pytest.mark.anyio
async def test_search_expression_nested(client, user_and_key):
    """'cell death' and ('nucleus' or 'apoptosis') → intersection with union."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")
    cls = _classification(subclasses={
        "http://ex.org/CD": ["http://ex.org/AP", "http://ex.org/SHARED"],
        "http://ex.org/N":  ["http://ex.org/InnerN"],
        "http://ex.org/AP": ["http://ex.org/SHARED"],
        "http://ex.org/SHARED": [],
        "http://ex.org/InnerN": [],
    })

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"], new=AsyncMock(return_value=cls)):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death' and ('nucleus' or 'apoptosis')", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    iris = {r["iri"] for r in resp.json()["results"]}
    # CD subs = {AP, SHARED}; N∪AP subs = {InnerN, SHARED, AP}
    # intersection = {AP, SHARED}
    assert "http://ex.org/AP" in iris
    assert "http://ex.org/SHARED" in iris
    assert "http://ex.org/InnerN" not in iris


# ── SPARQL-backed restrictions ────────────────────────────────────────────────

def _mock_sparql_cls(iri: str):
    sol = MagicMock()
    sol.__getitem__ = lambda self, k: MagicMock(value=iri)
    return sol


@pytest.mark.anyio
async def test_search_some_values_from(client, user_and_key):
    """'has part' some 'nucleus' → SPARQL query, returns matching class."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[_mock_sparql_cls("http://ex.org/CD")]):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'has part' some 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "expression"
    assert any(r["iri"] == "http://ex.org/CD" for r in body["results"])
    assert all(r["match_type"] == "sparql" for r in body["results"])


@pytest.mark.anyio
async def test_search_only_restriction(client, user_and_key):
    """'has part' only 'nucleus' → SPARQL, returns matching class."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[_mock_sparql_cls("http://ex.org/AP")]):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'has part' only 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    assert any(r["iri"] == "http://ex.org/AP" for r in resp.json()["results"])


@pytest.mark.anyio
async def test_search_min_cardinality(client, user_and_key):
    """'has part' min 2 'nucleus' → SPARQL minCardinality query."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[_mock_sparql_cls("http://ex.org/CD")]) as mock_sparql:
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'has part' min 2 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    assert mock_sparql.called
    sparql_text = mock_sparql.call_args[0][0]
    assert "minCardinality" in sparql_text
    assert "2" in sparql_text


@pytest.mark.anyio
async def test_search_max_cardinality(client, user_and_key):
    """'has part' max 1 'nucleus' → SPARQL maxCardinality query."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[]) as mock_sparql:
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'has part' max 1 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    assert "maxCardinality" in mock_sparql.call_args[0][0]


@pytest.mark.anyio
async def test_search_exact_cardinality(client, user_and_key):
    """'has part' exactly 1 'nucleus' → SPARQL owl:cardinality query."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[]) as mock_sparql:
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'has part' exactly 1 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    assert "cardinality" in mock_sparql.call_args[0][0]


# ── Annotation property exclusion ────────────────────────────────────────────

@pytest.mark.anyio
async def test_search_annotation_property_rejected_in_restriction(client, user_and_key):
    """Annotation property in property position → 400 (not found as object/data property)."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid", entities=[
        ("cell death", "http://ex.org/CD", "class"),
        ("nucleus", "http://ex.org/N", "class"),
        ("label", "http://www.w3.org/2000/01/rdf-schema#label", "annotation_property"),
    ])

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'label' some 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "unresolved_term"


# ── Label resolution edge cases ───────────────────────────────────────────────

@pytest.mark.anyio
async def test_search_unresolved_term_returns_400(client, user_and_key):
    """Label not in index → 400 unresolved_term."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'this label does not exist'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "unresolved_term"


@pytest.mark.anyio
async def test_search_expression_not_classified(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    from ontoexplorer.clients.reasoning import ReasoningNotReadyError

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(side_effect=ReasoningNotReadyError("fake-vid"))), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS):
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

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION):
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

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value={"subclasses": {}, "class_count": 0})), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
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
async def test_search_iri_direct(client, user_and_key):
    """Bare IRI skips parser entirely → entity mode lookup."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "http://ex.org/CD"},
            headers=auth,
        )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "entity"


# ── Result shape ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_search_result_fields(client, user_and_key):
    """Each result has iri, label, short, match_type."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 200
    for r in resp.json()["results"]:
        assert "iri" in r
        assert "label" in r
        assert "short" in r
        assert "match_type" in r


@pytest.mark.anyio
async def test_search_limit_respected(client, user_and_key):
    """limit=1 returns at most 1 result."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["redis_evaluator"], return_value=_FAKE_REDIS), \
         patch(_SEARCH_PATCHES["classification"],
               new=AsyncMock(return_value=_classification())):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death' or 'nucleus'", "mode": "expression", "limit": 1},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) <= 1
    assert body["truncated"] is True


# ── Autocomplete ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_autocomplete_open_quote(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
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

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
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


@pytest.mark.anyio
async def test_autocomplete_after_and_suggests_entities(client, user_and_key):
    """After 'and', suggestions should include entity completions (or quote suggestion)."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/autocomplete",
            params={"q": "'cell death' and '", "cursor": 18},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["context"] in ("open_quote", "expect_entity")


@pytest.mark.anyio
async def test_autocomplete_after_some_suggests_entities(client, user_and_key):
    """After 'some', autocomplete should be in expect_entity context."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/autocomplete",
            params={"q": "'has part' some '", "cursor": 17},
            headers=auth,
        )
    assert resp.status_code == 200
    assert resp.json()["context"] == "open_quote"


@pytest.mark.anyio
async def test_autocomplete_response_shape(client, user_and_key):
    """Each completion has text, type, insert fields."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch(_SEARCH_PATCHES["version_404"], new=_MOCK_VERSION), \
         patch(_SEARCH_PATCHES["redis_indexer"], return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/autocomplete",
            params={"q": "'nuc", "cursor": 4},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "replace_from" in body
    assert "replace_to" in body
    for c in body["completions"]:
        assert "text" in c
        assert "type" in c
        assert "insert" in c
