"""Unit tests for the MOS expression evaluator."""
import fakeredis
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from ontoexplorer.modules.search.mos_parser import (
    NamedClass, And, Or, Not,
    SomeValuesFrom, HasValue, HasSelf,
    MinCardinality, MaxCardinality, ExactCardinality,
)
from ontoexplorer.modules.search.evaluator import (
    AmbiguousLabelError,
    evaluate,
)
from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key

CELL   = "http://ex.org/Cell"
EUKARYOTE = "http://ex.org/EukaryoticCell"
PROK   = "http://ex.org/ProkaryoticCell"
HP_IRI = "http://bfo.org/HP"
NUC    = "http://ex.org/Nucleus"


def _make_classification(subclasses: dict, direct_subclasses: dict | None = None) -> dict:
    return {
        "version_id": "v1",
        "classified_at": "2026-01-01T00:00:00+00:00",
        "class_count": len(subclasses),
        "superclasses": {},
        "subclasses": subclasses,
        "direct_superclasses": {},
        "direct_subclasses": direct_subclasses if direct_subclasses is not None else {},
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


def _make_redis_multi(version_id: str, entities: list[tuple[str, str, str]]) -> fakeredis.FakeRedis:
    """Populate a FakeRedis with multiple (label, iri, entity_type) entries."""
    r = fakeredis.FakeRedis(decode_responses=True)
    for label, iri, etype in entities:
        r.zadd(_prefix_key(version_id), {f"{label.lower()}|{etype}|{iri}": 0})
        r.hset(_iri_key(version_id, iri), mapping={
            "label": label, "type": etype,
            "iri": iri, "short": iri.split("/")[-1], "synonyms": "",
        })
    return r


def _mock_sparql(iris: list[str]):
    """Return a mock sparql_query result yielding the given IRIs."""
    solutions = []
    for iri in iris:
        sol = MagicMock()
        sol.__getitem__ = lambda self, k, _i=iri: MagicMock(value=_i)
        solutions.append(sol)
    return solutions


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
        ("hasPart", "http://bfo.org/HP", "object_property"),
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


# ── direct flag ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_evaluate_direct_uses_direct_subclasses_index():
    r = _make_redis_with_entity("v1", "Cell", CELL)
    # all subclasses: Eukaryote + Prokaryote; direct: Eukaryote only
    classification = _make_classification(
        subclasses={CELL: [EUKARYOTE, PROK]},
        direct_subclasses={CELL: [EUKARYOTE]},
    )
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(NamedClass("Cell", None), "v1", "ont1", direct=True)
    iris = {r.iri for r in results}
    assert EUKARYOTE in iris
    assert PROK not in iris


@pytest.mark.anyio
async def test_evaluate_direct_false_uses_all_subclasses():
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification(
        subclasses={CELL: [EUKARYOTE, PROK]},
        direct_subclasses={CELL: [EUKARYOTE]},
    )
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(NamedClass("Cell", None), "v1", "ont1", direct=False)
    iris = {r.iri for r in results}
    assert EUKARYOTE in iris
    assert PROK in iris


@pytest.mark.anyio
async def test_evaluate_direct_fallback_when_key_absent():
    # When direct_subclasses key is missing entirely, fall back to subclasses.
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification(subclasses={CELL: [EUKARYOTE, PROK]})
    # Remove the key entirely to simulate an older ELK service
    classification.pop("direct_subclasses")
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(NamedClass("Cell", None), "v1", "ont1", direct=True)
    iris = {r.iri for r in results}
    # Falls back to full subclasses index
    assert EUKARYOTE in iris
    assert PROK in iris


@pytest.mark.anyio
async def test_evaluate_direct_empty_direct_subclasses_not_treated_as_absent():
    # direct_subclasses={} (present but empty) must NOT fall back to subclasses.
    # Empty means "no direct subclasses", not "key absent".
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification(
        subclasses={CELL: [EUKARYOTE, PROK]},
        direct_subclasses={},  # present but empty — Cell has no direct subclasses listed
    )
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(NamedClass("Cell", None), "v1", "ont1", direct=True)
    iris = {r.iri for r in results}
    # Only the queried class itself is returned (added via subs.add(iri))
    assert EUKARYOTE not in iris
    assert PROK not in iris


# ── Not node ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_evaluate_not_excludes_subclasses():
    r = _make_redis_multi("v1", [
        ("Cell", CELL, "class"),
        ("Virus", "http://ex.org/Virus", "class"),
    ])
    # all_class_iris = {Cell, Eukaryote, Prokaryote, Virus}
    classification = _make_classification({
        CELL: [EUKARYOTE, PROK],
        "http://ex.org/Virus": [],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(Not(NamedClass("Cell", None)), "v1", "ont1")
    iris = {r.iri for r in results}
    # Not Cell = all minus {Cell, Eukaryote, Prokaryote}
    assert CELL not in iris
    assert EUKARYOTE not in iris
    assert PROK not in iris
    assert "http://ex.org/Virus" in iris


@pytest.mark.anyio
async def test_evaluate_not_ignores_direct_flag():
    # Not always operates on full all_class_iris regardless of direct=True
    r = _make_redis_multi("v1", [
        ("Cell", CELL, "class"),
        ("Virus", "http://ex.org/Virus", "class"),
    ])
    classification = _make_classification(
        subclasses={CELL: [EUKARYOTE, PROK], "http://ex.org/Virus": []},
        direct_subclasses={CELL: [EUKARYOTE]},
    )
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results_direct = await evaluate(Not(NamedClass("Cell", None)), "v1", "ont1", direct=True)
        results_all    = await evaluate(Not(NamedClass("Cell", None)), "v1", "ont1", direct=False)
    # Not should give the same result regardless of direct flag
    assert {r.iri for r in results_direct} == {r.iri for r in results_all}


# ── ELK expansion for inherited restrictions ─────────────────────────────────

@pytest.mark.anyio
async def test_evaluate_restriction_expands_with_elk_subclasses():
    # SPARQL returns Cell as a direct asserter of (hasPart some Nucleus).
    # ELK says Eukaryote is a subclass of Cell.
    # direct=False (default) should include Eukaryote in the result.
    r = _make_redis_multi("v1", [
        ("hasPart", HP_IRI, "object_property"),
        ("Nucleus",  NUC,   "class"),
    ])
    classification = _make_classification(subclasses={CELL: [EUKARYOTE]})

    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([CELL])):
        results = await evaluate(
            SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None)),
            "v1", "ont1",
        )
    iris = {r.iri for r in results}
    assert CELL in iris
    assert EUKARYOTE in iris   # inherited via ELK expansion


@pytest.mark.anyio
async def test_evaluate_restriction_direct_skips_elk_expansion():
    # direct=True: only the SPARQL asserters, no ELK subclass expansion.
    r = _make_redis_multi("v1", [
        ("hasPart", HP_IRI, "object_property"),
        ("Nucleus",  NUC,   "class"),
    ])
    classification = _make_classification(
        subclasses={CELL: [EUKARYOTE]},
        direct_subclasses={CELL: [EUKARYOTE]},
    )

    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([CELL])):
        results = await evaluate(
            SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None)),
            "v1", "ont1", direct=True,
        )
    iris = {r.iri for r in results}
    assert CELL in iris
    assert EUKARYOTE not in iris   # not expanded in direct mode


# ── HasValue and HasSelf SPARQL branches ──────────────────────────────────────

@pytest.mark.anyio
async def test_evaluate_has_value_calls_sparql():
    r = _make_redis_multi("v1", [
        ("locatedIn", "http://ex.org/locatedIn", "object_property"),
        ("Brain",     "http://ex.org/Brain",     "class"),
    ])
    classification = _make_classification({})

    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([CELL])) as mock_sparql:
        results = await evaluate(
            HasValue(NamedClass("locatedIn", None), NamedClass("Brain", None)),
            "v1", "ont1",
        )
    assert mock_sparql.called
    query_text = mock_sparql.call_args[0][0]
    assert "hasValue" in query_text
    iris = {r.iri for r in results}
    assert CELL in iris


@pytest.mark.anyio
async def test_evaluate_has_self_calls_sparql():
    r = _make_redis_multi("v1", [
        ("loves", "http://ex.org/loves", "object_property"),
    ])
    classification = _make_classification({})

    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([CELL])) as mock_sparql:
        results = await evaluate(
            HasSelf(NamedClass("loves", None)),
            "v1", "ont1",
        )
    assert mock_sparql.called
    query_text = mock_sparql.call_args[0][0]
    assert "hasSelf" in query_text
    iris = {r.iri for r in results}
    assert CELL in iris


# ── Qualified cardinality SPARQL queries ─────────────────────────────────────

@pytest.mark.anyio
@pytest.mark.parametrize("node,expected_predicate", [
    (MinCardinality(NamedClass("hasPart", None), 2, NamedClass("Nucleus", None)),
     "minQualifiedCardinality"),
    (MaxCardinality(NamedClass("hasPart", None), 3, NamedClass("Nucleus", None)),
     "maxQualifiedCardinality"),
    (ExactCardinality(NamedClass("hasPart", None), 1, NamedClass("Nucleus", None)),
     "qualifiedCardinality"),
])
async def test_evaluate_cardinality_query_includes_qualified_form(node, expected_predicate):
    r = _make_redis_multi("v1", [
        ("hasPart", HP_IRI, "object_property"),
        ("Nucleus",  NUC,   "class"),
    ])
    classification = _make_classification({})

    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[]) as mock_sparql:
        await evaluate(node, "v1", "ont1")
    query_text = mock_sparql.call_args[0][0]
    assert expected_predicate in query_text


# ── Mixed ELK + SPARQL operands ───────────────────────────────────────────────

@pytest.mark.anyio
async def test_evaluate_and_named_class_with_restriction():
    # Regression: And(NamedClass, SomeValuesFrom) must not return None for either
    # operand — the restriction branch is handled by _eval (SPARQL), not _eval_with_index.
    r = _make_redis_multi("v1", [
        ("Cell",    CELL,   "class"),
        ("hasPart", HP_IRI, "object_property"),
        ("Nucleus", NUC,    "class"),
    ])
    classification = _make_classification(subclasses={CELL: [EUKARYOTE]})

    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([EUKARYOTE])):
        results = await evaluate(
            And(NamedClass("Cell", None), SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None))),
            "v1", "ont1",
        )
    iris = {r.iri for r in results}
    # Cell subclasses ∩ has-part-some-nucleus asserters = {EUKARYOTE}
    assert iris == {EUKARYOTE}


# ── evaluate_relation: superclasses / equivalent ───────────────────────────────

def _make_classification_super(direct_superclasses: dict) -> dict:
    """Classification with a direct_superclasses edge set (the trustworthy index)."""
    return {
        "version_id": "v1",
        "classified_at": "2026-01-01T00:00:00+00:00",
        "class_count": 0,
        "superclasses": {},        # deliberately empty — must not be relied upon
        "subclasses": {},
        "direct_superclasses": direct_superclasses,
        "direct_subclasses": {},
        "unsatisfiable": [],
        "proof_traces": {},
        "duration_ms": 1.0,
    }


@pytest.mark.anyio
async def test_evaluate_relation_superclasses_walks_ancestors():
    from ontoexplorer.modules.search.evaluator import evaluate_relation
    # Eukaryote ⊑ Cell ⊑ Thing  → ancestors(Eukaryote) = {Cell}
    r = _make_redis_with_entity("v1", "Eukaryote", EUKARYOTE)
    classification = _make_classification_super({
        EUKARYOTE: [CELL],
        CELL: ["http://www.w3.org/2002/07/owl#Thing"],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate_relation(
            NamedClass("Eukaryote", None), "v1", "ont1", relation="superclasses",
        )
    iris = {x.iri for x in results}
    assert iris == {CELL}  # owl:Thing and self excluded


@pytest.mark.anyio
async def test_evaluate_relation_superclasses_direct_is_one_hop():
    from ontoexplorer.modules.search.evaluator import evaluate_relation
    # Grandchild ⊑ Eukaryote ⊑ Cell ; direct parents of Grandchild = {Eukaryote}
    GRAND = "http://ex.org/Grandchild"
    r = _make_redis_with_entity("v1", "Grandchild", GRAND)
    classification = _make_classification_super({
        GRAND: [EUKARYOTE],
        EUKARYOTE: [CELL],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        direct = await evaluate_relation(
            NamedClass("Grandchild", None), "v1", "ont1", relation="superclasses", direct=True,
        )
        allsup = await evaluate_relation(
            NamedClass("Grandchild", None), "v1", "ont1", relation="superclasses", direct=False,
        )
    assert {x.iri for x in direct} == {EUKARYOTE}
    assert {x.iri for x in allsup} == {EUKARYOTE, CELL}


@pytest.mark.anyio
async def test_evaluate_relation_equivalent_detects_cycle():
    from ontoexplorer.modules.search.evaluator import evaluate_relation
    # A ≡ B represented as mutual direct-superclass edges.
    A = "http://ex.org/A"
    B = "http://ex.org/B"
    r = _make_redis_multi("v1", [("A", A, "class"), ("B", B, "class")])
    classification = _make_classification_super({A: [B], B: [A]})
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate_relation(
            NamedClass("A", None), "v1", "ont1", relation="equivalent",
        )
    assert {x.iri for x in results} == {B}


@pytest.mark.anyio
async def test_evaluate_relation_superclasses_rejects_complex_expression():
    from ontoexplorer.modules.search.evaluator import (
        evaluate_relation, RelationRequiresNamedClassError,
    )
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification_super({})
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        with pytest.raises(RelationRequiresNamedClassError):
            await evaluate_relation(
                Not(NamedClass("Cell", None)), "v1", "ont1", relation="superclasses",
            )


@pytest.mark.anyio
async def test_evaluate_relation_subclasses_delegates_to_evaluate():
    from ontoexplorer.modules.search.evaluator import evaluate_relation
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification({CELL: [EUKARYOTE, PROK]})
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate_relation(
            NamedClass("Cell", None), "v1", "ont1", relation="subclasses",
        )
    iris = {x.iri for x in results}
    assert EUKARYOTE in iris and PROK in iris


def _redis_haspart_nucleus():
    r = fakeredis.FakeRedis(decode_responses=True)
    for label, iri, etype in [
        ("hasPart", "http://bfo.org/HP", "object_property"),
        ("Nucleus", "http://ex.org/N", "class"),
    ]:
        r.zadd(_prefix_key("v1"), {f"{label.lower()}|{etype}|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": label, "type": etype, "iri": iri, "short": label, "synonyms": "",
        })
    return r


async def _min_query(cardinality: int) -> str:
    """Run evaluate() for `hasPart min N Nucleus` and return the SPARQL sent."""
    r = _redis_haspart_nucleus()
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=_make_classification({}))), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[]) as mock_sparql:
        await evaluate(
            MinCardinality(NamedClass("hasPart", None), cardinality, NamedClass("Nucleus", None)),
            "v1", "ont1",
        )
    return " ".join(str(a) for call in mock_sparql.call_args_list for a in call.args)


@pytest.mark.anyio
async def test_evaluate_min_one_matches_some_values_from():
    # min 1 R C ≡ some R C — the query must also match someValuesFrom on the filler.
    q = await _min_query(1)
    assert "someValuesFrom" in q
    assert "minQualifiedCardinality" in q
    assert "http://ex.org/N" in q          # filler is respected (not ignored)


@pytest.mark.anyio
async def test_evaluate_min_two_does_not_match_some_values_from():
    # min 2 is strictly stronger than some — must NOT match someValuesFrom.
    q = await _min_query(2)
    assert "someValuesFrom" not in q
    assert "minQualifiedCardinality" in q
