"""Unit tests for the MOS expression evaluator."""
import fakeredis
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from ontoexplorer.modules.search.mos_parser import (
    NamedClass, And, Or, Not,
    SomeValuesFrom, AllValuesFrom, MinCardinality,
)
from ontoexplorer.modules.search.evaluator import (
    AmbiguousLabelError,
    evaluate,
    SearchResult,
)
from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key


def _make_classification(subclasses: dict) -> dict:
    return {
        "version_id": "v1",
        "classified_at": "2026-01-01T00:00:00+00:00",
        "class_count": len(subclasses),
        "superclasses": {},
        "subclasses": subclasses,
        "direct_superclasses": {},
        "direct_subclasses": {},
        "unsatisfiable": [],
        "proof_traces": {},
        "duration_ms": 1.0,
    }


def _make_redis_with_entity(version_id: str, label: str, iri: str, entity_type: str = "class"):
    r = fakeredis.FakeRedis(decode_responses=True)
    norm = label.lower()
    r.zadd(_prefix_key(version_id), {f"{norm}|{entity_type}|{iri}": 0})
    r.hset(_iri_key(version_id, iri), mapping={
        "label": label, "type": entity_type,
        "iri": iri, "short": iri.split("/")[-1], "synonyms": "",
    })
    return r


@pytest.mark.anyio
async def test_evaluate_named_class_returns_subclasses():
    r = _make_redis_with_entity("v1", "Cell", "http://ex.org/Cell")
    classification = _make_classification({
        "http://ex.org/Cell": ["http://ex.org/EukaryoticCell", "http://ex.org/ProkaryoticCell"],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(NamedClass(ref="Cell", curie=None), "v1", "ont1")
    iris = {r.iri for r in results}
    assert "http://ex.org/EukaryoticCell" in iris
    assert "http://ex.org/ProkaryoticCell" in iris


@pytest.mark.anyio
async def test_evaluate_and_intersects():
    r = fakeredis.FakeRedis(decode_responses=True)
    # Cell subclasses: A, B; Nucleus subclasses: B, C → and = {B}
    for label, iri in [("Cell", "http://ex.org/Cell"), ("Nucleus", "http://ex.org/Nucleus")]:
        r.zadd(_prefix_key("v1"), {f"{label.lower()}|class|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": label, "type": "class", "iri": iri, "short": label, "synonyms": "",
        })
    classification = _make_classification({
        "http://ex.org/Cell":   ["http://ex.org/A", "http://ex.org/B"],
        "http://ex.org/Nucleus":["http://ex.org/B", "http://ex.org/C"],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(
            And(NamedClass("Cell", None), NamedClass("Nucleus", None)), "v1", "ont1"
        )
    iris = {r.iri for r in results}
    assert iris == {"http://ex.org/B"}


@pytest.mark.anyio
async def test_evaluate_or_unions():
    r = fakeredis.FakeRedis(decode_responses=True)
    for label, iri in [("Cell", "http://ex.org/Cell"), ("Virus", "http://ex.org/Virus")]:
        r.zadd(_prefix_key("v1"), {f"{label.lower()}|class|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": label, "type": "class", "iri": iri, "short": label, "synonyms": "",
        })
    classification = _make_classification({
        "http://ex.org/Cell":  ["http://ex.org/A"],
        "http://ex.org/Virus": ["http://ex.org/B"],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(
            Or(NamedClass("Cell", None), NamedClass("Virus", None)), "v1", "ont1"
        )
    iris = {r.iri for r in results}
    assert {"http://ex.org/A", "http://ex.org/B"} <= iris


@pytest.mark.anyio
async def test_evaluate_ambiguous_label_raises():
    r = fakeredis.FakeRedis(decode_responses=True)
    # Two IRIs share label "cell death"
    for iri in ["http://go.org/CD", "http://mondo.org/CD"]:
        r.zadd(_prefix_key("v1"), {f"cell death|class|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": "cell death", "type": "class",
            "iri": iri, "short": iri.split("/")[-1], "synonyms": "",
        })
    classification = _make_classification({})
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        with pytest.raises(AmbiguousLabelError) as exc_info:
            await evaluate(NamedClass(ref="cell death", curie=None), "v1", "ont1")
    assert exc_info.value.label == "cell death"
    assert len(exc_info.value.candidates) == 2


@pytest.mark.anyio
async def test_evaluate_some_values_from_calls_sparql():
    r = fakeredis.FakeRedis(decode_responses=True)
    for label, iri, etype in [
        ("hasPart", "http://bfo.org/HP", "property"),
        ("Nucleus",  "http://ex.org/N",   "class"),
    ]:
        r.zadd(_prefix_key("v1"), {f"{label.lower()}|{etype}|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": label, "type": etype, "iri": iri, "short": label, "synonyms": "",
        })

    mock_sol = MagicMock()
    mock_sol.__getitem__ = lambda self, k: MagicMock(value="http://ex.org/Cell")
    classification = _make_classification({})

    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[mock_sol]) as mock_sparql:
        results = await evaluate(
            SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None)), "v1", "ont1"
        )
    assert mock_sparql.called
    assert any(r.match_type == "sparql" for r in results)
