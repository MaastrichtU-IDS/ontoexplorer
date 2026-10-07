"""Unit tests for the MOS expression evaluator."""
import pytest
from unittest.mock import patch, MagicMock

from ontoexplorer.modules.search.mos_parser import (
    NamedClass, And, Or, Not,
    SomeValuesFrom, HasValue, HasSelf,
    MinCardinality, MaxCardinality, ExactCardinality,
    InverseRestriction,
    Literal, DatatypeRestriction,
)

_XSD = "http://www.w3.org/2001/XMLSchema#"
from ontoexplorer.modules.search.evaluator import (
    AmbiguousLabelError,
    evaluate,
)

CELL   = "http://ex.org/Cell"
EUKARYOTE = "http://ex.org/EukaryoticCell"
PROK   = "http://ex.org/ProkaryoticCell"
HP_IRI = "http://bfo.org/HP"
NUC    = "http://ex.org/Nucleus"


from contextlib import contextmanager


@contextmanager
def _patch_reasoner(classification: dict):
    """The evaluator now uses targeted per-IRI subclasses()/superclasses() calls
    instead of loading the full classification (#277). Serve those from the same
    classification dict the tests already build: subclasses(direct=False) from
    `subclasses`, subclasses(direct=True) and superclasses(direct=True) from the
    `direct_*` maps."""
    subs = classification.get("subclasses", {}) or {}
    dsub = classification.get("direct_subclasses", {}) or {}
    dsup = classification.get("direct_superclasses", {}) or {}

    async def _fsub(version_id, class_iri, direct=False, reasoner="rustdl"):
        m = dsub if direct else subs
        return {"subclasses": list(m.get(class_iri, []))}

    async def _fsup(version_id, class_iri, direct=False, reasoner="rustdl"):
        return {"superclasses": list(dsup.get(class_iri, []))}

    with patch("ontoexplorer.modules.search.evaluator._reasoner_subclasses", new=_fsub), \
         patch("ontoexplorer.modules.search.evaluator._reasoner_superclasses", new=_fsup):
        yield


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


def _make_resolver_multi(version_id: str, entities: list[tuple[str, str, str]]):
    """Build an evaluator `_Resolver` from (label, iri, entity_type) entries —
    the evaluator resolves labels/CURIEs from entity_index now (#242 Workstream B)."""
    from types import SimpleNamespace
    from ontoexplorer.modules.search.evaluator import _resolver_from_rows
    rows = [
        SimpleNamespace(
            iri=iri, primary_label=label, short=iri.split("/")[-1], type=etype,
            source=None, labels={"en": label}, synonyms=[], definitions=[], types=[],
            is_individual=(etype == "individual"),
        )
        for (label, iri, etype) in entities
    ]
    return _resolver_from_rows(rows)


def _make_redis_with_entity(version_id: str, label: str, iri: str, entity_type: str = "class"):
    return _make_resolver_multi(version_id, [(label, iri, entity_type)])


def _make_redis_multi(version_id: str, entities: list[tuple[str, str, str]]):
    return _make_resolver_multi(version_id, entities)


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
    with _patch_reasoner(classification):
        results = await evaluate(NamedClass(ref="Cell", curie=None), "v1", "ont1", r)
    iris = {r.iri for r in results}
    assert "http://ex.org/EukaryoticCell" in iris
    assert "http://ex.org/ProkaryoticCell" in iris


def test_resolver_can_resolve_prefilter():
    # #277: pre-filter the global expression fan-out to versions that actually
    # contain the query's plain-label terms.
    from ontoexplorer.modules.search.evaluator import resolver_can_resolve
    r = _make_resolver_multi("v1", [
        ("Cell", "http://ex.org/Cell", "class"),
        ("has part", "http://ex.org/HP", "object_property"),
    ])
    # all plain-label refs present -> candidate
    assert resolver_can_resolve(r, {"Cell", "has part"}) is True
    # a missing plain-label ref -> not a candidate (evaluate would ValueError -> [])
    assert resolver_can_resolve(r, {"Cell", "Nucleus"}) is False
    assert resolver_can_resolve(r, {"Nucleus"}) is False
    # empty refs -> candidate (nothing to exclude on)
    assert resolver_can_resolve(r, set()) is True
    # CURIE/IRI-shaped refs (a colon) are not filtered on — handled as literal IRIs
    assert resolver_can_resolve(r, {"GO:0006915"}) is True
    assert resolver_can_resolve(r, {"http://x/Y"}) is True
    # owl:Thing is seeded into every resolver, so a bare Thing term stays a candidate
    assert resolver_can_resolve(r, {"Thing"}) is True


@pytest.mark.anyio
async def test_evaluate_owl_thing_label_returns_all_classes():
    # owl:Thing has no entity_index row (built-in) — the resolver seeds it, so a
    # `Thing` query still expands to every class (parity with the old Redis inject).
    r = _make_resolver_multi("v1", [
        ("Cell", "http://ex.org/Cell", "class"),
        ("Nucleus", "http://ex.org/Nucleus", "class"),
        ("hasPart", "http://ex.org/hp", "object_property"),
    ])
    classification = _make_classification({})
    with _patch_reasoner(classification):
        results = await evaluate(NamedClass("Thing", None), "v1", "ont1", r)
    iris = {x.iri for x in results}
    # every class, owl:Thing itself excluded, properties excluded
    assert iris == {"http://ex.org/Cell", "http://ex.org/Nucleus"}


@pytest.mark.anyio
async def test_evaluate_owl_thing_curie_returns_all_classes():
    r = _make_resolver_multi("v1", [("Cell", "http://ex.org/Cell", "class")])
    classification = _make_classification({})
    with _patch_reasoner(classification):
        results = await evaluate(NamedClass("owl:Thing", "owl:Thing"), "v1", "ont1", r)
    assert {x.iri for x in results} == {"http://ex.org/Cell"}


@pytest.mark.anyio
async def test_evaluate_real_thing_class_is_ambiguous_with_owl_thing():
    # An ontology defining its own class labelled "Thing" collides with the seeded
    # owl:Thing built-in → AmbiguousLabelError (the old Redis behaviour).
    r = _make_resolver_multi("v1", [("Thing", "http://ex.org/MyThing", "class")])
    classification = _make_classification({})
    with _patch_reasoner(classification):
        with pytest.raises(AmbiguousLabelError):
            await evaluate(NamedClass("Thing", None), "v1", "ont1", r)


@pytest.mark.anyio
async def test_evaluate_and_intersects():
    # Cell subclasses: A, B; Nucleus subclasses: B, C → and = {B}
    r = _make_resolver_multi("v1", [
        ("Cell", "http://ex.org/Cell", "class"),
        ("Nucleus", "http://ex.org/Nucleus", "class"),
    ])
    classification = _make_classification({
        "http://ex.org/Cell":   ["http://ex.org/A", "http://ex.org/B"],
        "http://ex.org/Nucleus":["http://ex.org/B", "http://ex.org/C"],
    })
    with _patch_reasoner(classification):
        results = await evaluate(
            And(NamedClass("Cell", None), NamedClass("Nucleus", None)), "v1", "ont1", r,
        )
    iris = {r.iri for r in results}
    assert iris == {"http://ex.org/B"}


@pytest.mark.anyio
async def test_evaluate_or_unions():
    r = _make_resolver_multi("v1", [
        ("Cell", "http://ex.org/Cell", "class"),
        ("Virus", "http://ex.org/Virus", "class"),
    ])
    classification = _make_classification({
        "http://ex.org/Cell":  ["http://ex.org/A"],
        "http://ex.org/Virus": ["http://ex.org/B"],
    })
    with _patch_reasoner(classification):
        results = await evaluate(
            Or(NamedClass("Cell", None), NamedClass("Virus", None)), "v1", "ont1", r,
        )
    iris = {r.iri for r in results}
    assert {"http://ex.org/A", "http://ex.org/B"} <= iris


@pytest.mark.anyio
async def test_evaluate_ambiguous_label_raises():
    # Two IRIs share label "cell death"
    r = _make_resolver_multi("v1", [
        ("cell death", "http://go.org/CD", "class"),
        ("cell death", "http://mondo.org/CD", "class"),
    ])
    classification = _make_classification({})
    with _patch_reasoner(classification):
        with pytest.raises(AmbiguousLabelError) as exc_info:
            await evaluate(NamedClass(ref="cell death", curie=None), "v1", "ont1", r)
    assert exc_info.value.label == "cell death"
    assert len(exc_info.value.candidates) == 2


@pytest.mark.anyio
async def test_evaluate_some_values_from_calls_sparql():
    r = _make_resolver_multi("v1", [
        ("hasPart", "http://bfo.org/HP", "object_property"),
        ("Nucleus",  "http://ex.org/N",   "class"),
    ])

    mock_sol = MagicMock()
    mock_sol.__getitem__ = lambda self, k: MagicMock(value="http://ex.org/Cell")
    classification = _make_classification({})

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[mock_sol]) as mock_sparql:
        results = await evaluate(
            SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None)), "v1", "ont1", r,
        )
    assert mock_sparql.called
    assert any(r.match_type == "sparql" for r in results)


def _redis_props_and_classes(version_id: str):
    return _make_redis_multi(version_id, [
        ("has part", HP_IRI, "object_property"),
        ("cell", CELL, "class"),
        ("nucleus", NUC, "class"),
    ])


@pytest.mark.anyio
async def test_evaluate_inverse_some_reverse_lookup():
    # `inverse 'has part' some 'cell'` → fillers of has-part on cell (+ subclasses).
    r = _redis_props_and_classes("v1")
    classification = _make_classification(subclasses={CELL: [EUKARYOTE]})
    captured = {}

    def fake_sparql(q):
        captured["q"] = q
        return _mock_sparql([NUC])

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query", side_effect=fake_sparql):
        results = await evaluate(
            InverseRestriction(NamedClass("has part", None), "some", NamedClass("cell", None)),
            "v1", "ont1", r,
        )
    assert {res.iri for res in results} == {NUC}
    q = captured["q"]
    assert "?fill" in q                       # projects the filler, not the holder
    assert "someValuesFrom" in q
    assert f"<{CELL}>" in q and f"<{EUKARYOTE}>" in q  # holder set = cell + subclasses


@pytest.mark.anyio
async def test_evaluate_inverse_only_uses_allvaluesfrom():
    r = _redis_props_and_classes("v1")
    classification = _make_classification({})
    captured = {}

    def fake_sparql(q):
        captured["q"] = q
        return _mock_sparql([NUC])

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query", side_effect=fake_sparql):
        await evaluate(
            InverseRestriction(NamedClass("has part", None), "only", NamedClass("cell", None)),
            "v1", "ont1", r,
        )
    assert "allValuesFrom" in captured["q"]


@pytest.mark.anyio
async def test_evaluate_inverse_value_uses_hasvalue():
    r = _redis_props_and_classes("v1")
    classification = _make_classification({})
    captured = {}

    def fake_sparql(q):
        captured["q"] = q
        return _mock_sparql([NUC])

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query", side_effect=fake_sparql):
        await evaluate(
            InverseRestriction(NamedClass("has part", None), "value", NamedClass("cell", None)),
            "v1", "ont1", r,
        )
    assert "hasValue" in captured["q"]


@pytest.mark.anyio
async def test_evaluate_inverse_min_uses_qualified_cardinality():
    r = _redis_props_and_classes("v1")
    classification = _make_classification({})
    captured = {}

    def fake_sparql(q):
        captured["q"] = q
        return _mock_sparql([NUC])

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query", side_effect=fake_sparql):
        await evaluate(
            InverseRestriction(NamedClass("has part", None), "min", NamedClass("cell", None), cardinality=2),
            "v1", "ont1", r,
        )
    q = captured["q"]
    assert "minQualifiedCardinality" in q
    assert "onClass" in q
    assert ">= 2" in q
    assert "someValuesFrom" not in q          # n=2 > 1


@pytest.mark.anyio
async def test_evaluate_inverse_min_one_includes_some_equivalence():
    r = _redis_props_and_classes("v1")
    classification = _make_classification({})
    captured = {}

    def fake_sparql(q):
        captured["q"] = q
        return _mock_sparql([NUC])

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query", side_effect=fake_sparql):
        await evaluate(
            InverseRestriction(NamedClass("has part", None), "min", NamedClass("cell", None), cardinality=1),
            "v1", "ont1", r,
        )
    # min 1 ≡ some, so someValuesFrom fillers must also be matched.
    assert "someValuesFrom" in captured["q"]


@pytest.mark.anyio
async def test_evaluate_inverse_max_and_exactly_predicates():
    r = _redis_props_and_classes("v1")
    classification = _make_classification({})
    captured = {}

    def fake_sparql(q):
        captured["q"] = q
        return _mock_sparql([NUC])

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query", side_effect=fake_sparql):
        await evaluate(
            InverseRestriction(NamedClass("has part", None), "max", NamedClass("cell", None), cardinality=2),
            "v1", "ont1", r,
        )
        assert "maxQualifiedCardinality" in captured["q"] and "<= 2" in captured["q"]
        await evaluate(
            InverseRestriction(NamedClass("has part", None), "exactly", NamedClass("cell", None), cardinality=3),
            "v1", "ont1", r,
        )
        q = captured["q"]
        assert "minQualifiedCardinality" not in q and "maxQualifiedCardinality" not in q
        assert "qualifiedCardinality" in q and "= 3" in q


@pytest.mark.anyio
async def test_evaluate_value_literal_builds_typed_literal():
    r = _make_redis_multi("v1", [("has age", HP_IRI, "data_property")])
    classification = _make_classification({})
    captured = {}

    def fake_sparql(q):
        captured["q"] = q
        return _mock_sparql([CELL])

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query", side_effect=fake_sparql):
        await evaluate(
            HasValue(NamedClass("has age", None), Literal("42", _XSD + "integer")),
            "v1", "ont1", r,
        )
    q = captured["q"]
    assert "hasValue" in q
    assert f'"42"^^<{_XSD}integer>' in q


@pytest.mark.anyio
async def test_evaluate_datatype_restriction_matches_facets():
    r = _make_redis_multi("v1", [("has age", HP_IRI, "data_property")])
    classification = _make_classification({})
    captured = {}

    def fake_sparql(q):
        captured["q"] = q
        return _mock_sparql([CELL])

    dr = DatatypeRestriction(
        datatype=NamedClass("xsd:integer", None),
        facets=[(_XSD + "minInclusive", Literal("18", _XSD + "integer"))],
    )
    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query", side_effect=fake_sparql):
        await evaluate(SomeValuesFrom(NamedClass("has age", None), dr), "v1", "ont1", r)
    q = captured["q"]
    assert "onDatatype" in q
    assert f"<{_XSD}integer>" in q                 # base datatype
    assert "withRestrictions" in q
    assert f"<{_XSD}minInclusive>" in q
    assert f'"18"^^<{_XSD}integer>' in q


# ── direct flag ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_evaluate_direct_uses_direct_subclasses_index():
    r = _make_redis_with_entity("v1", "Cell", CELL)
    # all subclasses: Eukaryote + Prokaryote; direct: Eukaryote only
    classification = _make_classification(
        subclasses={CELL: [EUKARYOTE, PROK]},
        direct_subclasses={CELL: [EUKARYOTE]},
    )
    with _patch_reasoner(classification):
        results = await evaluate(NamedClass("Cell", None), "v1", "ont1", r, direct=True)
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
    with _patch_reasoner(classification):
        results = await evaluate(NamedClass("Cell", None), "v1", "ont1", r, direct=False)
    iris = {r.iri for r in results}
    assert EUKARYOTE in iris
    assert PROK in iris


@pytest.mark.anyio
async def test_evaluate_named_class_includes_asserted_direct_subclasses():
    # Regression (GO 'catalytic activity'): the whelk backend keeps ASSERTED
    # subclass edges only in direct_subclasses — `subclasses` holds inferred-
    # not-asserted edges. A class whose subsumption under the query is asserted
    # (GO_0016218 subClassOf catalytic activity) lives only in direct_subclasses
    # and must still appear in a non-direct query. The complete closure is
    # subclasses ∪ direct_subclasses.
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification(
        subclasses={CELL: [PROK]},              # inferred-only transitive descendant
        direct_subclasses={CELL: [EUKARYOTE]},  # asserted direct child, ABSENT from subclasses
    )
    with _patch_reasoner(classification):
        results = await evaluate(NamedClass("Cell", None), "v1", "ont1", r, direct=False)
    iris = {res.iri for res in results}
    assert EUKARYOTE in iris   # asserted direct child — was dropped before the fix
    assert PROK in iris        # inferred transitive descendant
    assert CELL in iris        # reflexive


@pytest.mark.anyio
async def test_evaluate_and_includes_asserted_subclass_conjunct():
    # GO case in miniature: `Cell and (HP some Nucleus)`. The class that matches
    # the restriction (EUKARYOTE) is an ASSERTED subclass of Cell, so it sits in
    # direct_subclasses[Cell] but not subclasses[Cell]. The conjunction must
    # still return it.
    r = _make_redis_multi("v1", [
        ("Cell", CELL, "class"),
        ("Nucleus", NUC, "class"),
        ("hp", HP_IRI, "object_property"),
    ])
    classification = _make_classification(
        subclasses={CELL: [PROK]},              # inferred-only; EUKARYOTE missing
        direct_subclasses={CELL: [EUKARYOTE]},  # asserted direct child
    )
    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([EUKARYOTE])):
        results = await evaluate(
            And(NamedClass("Cell", None),
                SomeValuesFrom(NamedClass("hp", None), NamedClass("Nucleus", None))),
            "v1", "ont1", r, direct=False,
        )
    iris = {res.iri for res in results}
    assert EUKARYOTE in iris   # was dropped: absent from subclasses[Cell] before the fix


@pytest.mark.anyio
async def test_evaluate_direct_empty_direct_subclasses_not_treated_as_absent():
    # direct_subclasses={} (present but empty) must NOT fall back to subclasses.
    # Empty means "no direct subclasses", not "key absent".
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification(
        subclasses={CELL: [EUKARYOTE, PROK]},
        direct_subclasses={},  # present but empty — Cell has no direct subclasses listed
    )
    with _patch_reasoner(classification):
        results = await evaluate(NamedClass("Cell", None), "v1", "ont1", r, direct=True)
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
    with _patch_reasoner(classification):
        results = await evaluate(Not(NamedClass("Cell", None)), "v1", "ont1", r)
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
    with _patch_reasoner(classification):
        results_direct = await evaluate(Not(NamedClass("Cell", None)), "v1", "ont1", r, direct=True)
        results_all    = await evaluate(Not(NamedClass("Cell", None)), "v1", "ont1", r, direct=False)
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

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([CELL])):
        results = await evaluate(
            SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None)),
            "v1", "ont1", r,
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

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([CELL])):
        results = await evaluate(
            SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None)),
            "v1", "ont1", r, direct=True,
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

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([CELL])) as mock_sparql:
        results = await evaluate(
            HasValue(NamedClass("locatedIn", None), NamedClass("Brain", None)),
            "v1", "ont1", r,
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

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([CELL])) as mock_sparql:
        results = await evaluate(
            HasSelf(NamedClass("loves", None)),
            "v1", "ont1", r,
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

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[]) as mock_sparql:
        await evaluate(node, "v1", "ont1", r)
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

    with _patch_reasoner(classification), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=_mock_sparql([EUKARYOTE])):
        results = await evaluate(
            And(NamedClass("Cell", None), SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None))),
            "v1", "ont1", r,
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
    with _patch_reasoner(classification):
        results = await evaluate_relation(
            NamedClass("Eukaryote", None), "v1", "ont1", r, relation="superclasses",
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
    with _patch_reasoner(classification):
        direct = await evaluate_relation(
            NamedClass("Grandchild", None), "v1", "ont1", r, relation="superclasses", direct=True,
        )
        allsup = await evaluate_relation(
            NamedClass("Grandchild", None), "v1", "ont1", r, relation="superclasses", direct=False,
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
    with _patch_reasoner(classification):
        results = await evaluate_relation(
            NamedClass("A", None), "v1", "ont1", r, relation="equivalent",
        )
    assert {x.iri for x in results} == {B}


@pytest.mark.anyio
async def test_evaluate_relation_superclasses_rejects_complex_expression():
    from ontoexplorer.modules.search.evaluator import (
        evaluate_relation, RelationRequiresNamedClassError,
    )
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification_super({})
    with _patch_reasoner(classification):
        with pytest.raises(RelationRequiresNamedClassError):
            await evaluate_relation(
                Not(NamedClass("Cell", None)), "v1", "ont1", r, relation="superclasses",
            )


@pytest.mark.anyio
async def test_evaluate_relation_subclasses_delegates_to_evaluate():
    from ontoexplorer.modules.search.evaluator import evaluate_relation
    r = _make_redis_with_entity("v1", "Cell", CELL)
    classification = _make_classification({CELL: [EUKARYOTE, PROK]})
    with _patch_reasoner(classification):
        results = await evaluate_relation(
            NamedClass("Cell", None), "v1", "ont1", r, relation="subclasses",
        )
    iris = {x.iri for x in results}
    assert EUKARYOTE in iris and PROK in iris


def _redis_haspart_nucleus():
    return _make_resolver_multi("v1", [
        ("hasPart", "http://bfo.org/HP", "object_property"),
        ("Nucleus", "http://ex.org/N", "class"),
    ])


async def _min_query(cardinality: int) -> str:
    """Run evaluate() for `hasPart min N Nucleus` and return the SPARQL sent."""
    r = _redis_haspart_nucleus()
    with _patch_reasoner(_make_classification({})), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[]) as mock_sparql:
        await evaluate(
            MinCardinality(NamedClass("hasPart", None), cardinality, NamedClass("Nucleus", None)),
            "v1", "ont1", r,
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


async def _card_query(node) -> str:
    r = _redis_haspart_nucleus()
    with _patch_reasoner(_make_classification({})), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[]) as mock_sparql:
        await evaluate(node, "v1", "ont1", r)
    return " ".join(str(a) for call in mock_sparql.call_args_list for a in call.args)


@pytest.mark.anyio
async def test_evaluate_max_cardinality_qualified_on_filler():
    q = await _card_query(
        MaxCardinality(NamedClass("hasPart", None), 2, NamedClass("Nucleus", None)))
    assert "maxQualifiedCardinality" in q
    assert "onClass" in q and "http://ex.org/N" in q   # filler respected
    assert "<=" in q
    assert "someValuesFrom" not in q                   # max is not `some`


@pytest.mark.anyio
async def test_evaluate_exactly_cardinality_qualified_on_filler():
    q = await _card_query(
        ExactCardinality(NamedClass("hasPart", None), 1, NamedClass("Nucleus", None)))
    assert "qualifiedCardinality" in q
    assert "onClass" in q and "http://ex.org/N" in q
    assert "someValuesFrom" not in q                   # exactly 1 is not `some`
