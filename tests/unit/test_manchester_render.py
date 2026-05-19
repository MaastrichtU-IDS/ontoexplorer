"""Unit tests for ontoexplorer.modules.diff.manchester.

Each test builds a minimal in-memory pyoxigraph.Store with a single named
graph and exercises one renderer function directly.
"""
import pyoxigraph as ox
import pytest

# Re-exported constants/helpers will be imported as tasks land.

_GRAPH = ox.NamedNode("urn:test:graph")


def _store(*quads: tuple) -> ox.Store:
    """Build an in-memory store with one named graph containing the given quads."""
    store = ox.Store()
    store.add_graph(_GRAPH)
    for s, p, o in quads:
        store.add(ox.Quad(s, p, o, _GRAPH))
    return store


from ontoexplorer.modules.diff.manchester import iri_to_label


def test_iri_to_label_uses_rdfs_label_en():
    iri = ox.NamedNode("http://example.org/Foo")
    store = _store(
        (iri, ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label"),
         ox.Literal("Foo Class", language="en")),
    )
    labels: dict[str, str] = {}
    assert iri_to_label(store, _GRAPH, iri.value, labels=labels) == "Foo Class"


def test_iri_to_label_falls_back_to_local_name_after_hash():
    iri = "http://example.org/ns#BarClass"
    store = _store()
    assert iri_to_label(store, _GRAPH, iri, labels={}) == "BarClass"


def test_iri_to_label_falls_back_to_local_name_after_slash():
    iri = "http://example.org/ns/Baz"
    store = _store()
    assert iri_to_label(store, _GRAPH, iri, labels={}) == "Baz"


def test_iri_to_label_falls_back_to_full_iri_when_no_separator():
    iri = "urn:weird-iri-no-separator"
    store = _store()
    assert iri_to_label(store, _GRAPH, iri, labels={}) == iri


def test_iri_to_label_caches_result():
    iri = "http://example.org/Foo"
    store = _store(
        (ox.NamedNode(iri),
         ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label"),
         ox.Literal("First", language="en")),
    )
    cache: dict[str, str] = {}
    assert iri_to_label(store, _GRAPH, iri, labels=cache) == "First"
    # Mutate the cache directly so we can prove it isn't queried again
    cache[iri] = "Cached"
    assert iri_to_label(store, _GRAPH, iri, labels=cache) == "Cached"


def test_iri_to_label_prefers_en_over_other_languages():
    iri = "http://example.org/Foo"
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Le Foo", language="fr")),
        (ox.NamedNode(iri), label_pred, ox.Literal("The Foo", language="en")),
    )
    assert iri_to_label(store, _GRAPH, iri, labels={}) == "The Foo"


def test_iri_to_label_takes_any_label_when_no_en():
    iri = "http://example.org/Foo"
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Le Foo", language="fr")),
    )
    assert iri_to_label(store, _GRAPH, iri, labels={}) == "Le Foo"


from ontoexplorer.modules.diff.manchester import _rdf_list_items


def _list_quads(items: list) -> tuple[ox.BlankNode, list[tuple]]:
    """Build RDF list quads for `items`. Returns (head_bnode, [quads])."""
    quads: list[tuple] = []
    nil = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#nil")
    first_pred = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first")
    rest_pred  = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest")
    nodes = [ox.BlankNode(f"list_{i}") for i in range(len(items))]
    for i, item in enumerate(items):
        quads.append((nodes[i], first_pred, item))
        nxt = nodes[i + 1] if i + 1 < len(nodes) else nil
        quads.append((nodes[i], rest_pred, nxt))
    return nodes[0], quads


def test_rdf_list_items_empty_returns_empty():
    store = _store()
    nil = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#nil")
    assert _rdf_list_items(store, _GRAPH, nil) == []


def test_rdf_list_items_returns_ordered_named_nodes():
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    c = ox.NamedNode("http://example.org/C")
    head, quads = _list_quads([a, b, c])
    store = _store(*quads)
    items = _rdf_list_items(store, _GRAPH, head)
    assert [t.value for t in items] == [a.value, b.value, c.value]


def test_rdf_list_items_handles_literal_items():
    lit = ox.Literal("hello", language="en")
    iri = ox.NamedNode("http://example.org/X")
    head, quads = _list_quads([lit, iri])
    store = _store(*quads)
    items = _rdf_list_items(store, _GRAPH, head)
    assert len(items) == 2
    assert isinstance(items[0], ox.Literal)
    assert items[0].value == "hello"
    assert isinstance(items[1], ox.NamedNode)


def test_rdf_list_items_stops_at_cycle():
    # Pathological cycle: list_0 → list_0 (self-rest). Helper must not loop.
    first_pred = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first")
    rest_pred  = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest")
    head = ox.BlankNode("list_0")
    a = ox.NamedNode("http://example.org/A")
    store = _store(
        (head, first_pred, a),
        (head, rest_pred,  head),  # cycle
    )
    items = _rdf_list_items(store, _GRAPH, head)
    assert [t.value for t in items] == [a.value]


from ontoexplorer.modules.diff.manchester import render_class_expression


def _flatten(tokens) -> str:
    """Join token list into a single Manchester string (label/v).

    Used by edge-case tests that care about the final rendered expression's
    string form (parens, separators, ordering). Token-shape tests assert the
    token list directly; this helper is only for the string-equivalent checks.
    """
    return "".join(
        t["v"] if t["t"] == "text" else t["label"] for t in tokens
    )


def test_render_named_class_returns_label():
    iri = "http://example.org/Pizza"
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Pizza", language="en")),
    )
    out = render_class_expression(
        store, _GRAPH, ox.NamedNode(iri), labels={}, known_iris=frozenset({iri}),
    )
    assert out == [{"t": "iri", "label": "Pizza", "iri": iri, "in_ontology": True}]


def test_render_named_class_uses_local_name_when_no_label():
    iri = "http://example.org/Pizza"
    store = _store()
    out = render_class_expression(
        store, _GRAPH, ox.NamedNode(iri), labels={}, known_iris=frozenset(),
    )
    assert out == [{"t": "iri", "label": "Pizza", "iri": iri, "in_ontology": False}]


def test_render_literal_object_renders_with_quotes_and_lang():
    lit = ox.Literal("hello", language="en")
    store = _store()
    out = render_class_expression(
        store, _GRAPH, lit, labels={}, known_iris=frozenset(),
    )
    assert out == [{"t": "text", "v": '"hello"@en'}]


def test_render_literal_object_typed_renders_with_datatype():
    lit = ox.Literal(
        "42",
        datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer"),
    )
    store = _store()
    out = render_class_expression(
        store, _GRAPH, lit, labels={}, known_iris=frozenset(),
    )
    assert out == [{"t": "text", "v": '"42"^^xsd:integer'}]


def test_render_xsd_string_literal_omits_datatype():
    lit = ox.Literal(
        "hello",
        datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#string"),
    )
    store = _store()
    out = render_class_expression(
        store, _GRAPH, lit, labels={}, known_iris=frozenset(),
    )
    assert out == [{"t": "text", "v": '"hello"'}]


def test_render_unknown_bnode_returns_bnode_placeholder():
    # Bnode with no recognized class-expression predicate falls through to fallback.
    bnode = ox.BlankNode("unknown_xyz")
    store = _store(
        (bnode,
         ox.NamedNode("http://example.org/randomPred"),
         ox.NamedNode("http://example.org/Whatever")),
    )
    out = render_class_expression(
        store, _GRAPH, bnode, labels={}, known_iris=frozenset(),
    )
    assert len(out) == 1 and out[0]["t"] == "text"
    assert out[0]["v"].startswith("[bnode:")


_OWL_RESTRICTION = ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction")
_OWL_ON_PROPERTY = ox.NamedNode("http://www.w3.org/2002/07/owl#onProperty")
_OWL_SOME = ox.NamedNode("http://www.w3.org/2002/07/owl#someValuesFrom")
_OWL_ALL  = ox.NamedNode("http://www.w3.org/2002/07/owl#allValuesFrom")
_OWL_HAS_VALUE = ox.NamedNode("http://www.w3.org/2002/07/owl#hasValue")
_OWL_HAS_SELF  = ox.NamedNode("http://www.w3.org/2002/07/owl#hasSelf")
_RDF_TYPE_N = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_XSD_TRUE = ox.Literal("true", datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#boolean"))


def test_restriction_some_values_from():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Tomato")
    r = ox.BlankNode("r1")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_SOME, c),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value, c.value}),
    )
    assert _flatten(out) == "hasTopping some Tomato"


def test_restriction_all_values_from():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Tomato")
    r = ox.BlankNode("r2")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_ALL, c),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value, c.value}),
    )
    assert _flatten(out) == "hasTopping only Tomato"


def test_restriction_has_value_iri():
    p = ox.NamedNode("http://example.org/hasTopping")
    v = ox.NamedNode("http://example.org/SpecificTomato")
    r = ox.BlankNode("r3")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_VALUE, v),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value, v.value}),
    )
    assert _flatten(out) == "hasTopping value SpecificTomato"


def test_restriction_has_value_literal():
    p = ox.NamedNode("http://example.org/hasName")
    v = ox.Literal("Salty", language="en")
    r = ox.BlankNode("r4")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_VALUE, v),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value}),
    )
    assert _flatten(out) == 'hasName value "Salty"@en'


def test_restriction_has_self_true():
    p = ox.NamedNode("http://example.org/hasPartOf")
    r = ox.BlankNode("r5")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_SELF, _XSD_TRUE),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value}),
    )
    assert _flatten(out) == "hasPartOf Self"


def test_restriction_has_self_false_falls_through():
    """hasSelf "false"^^xsd:boolean must not render as `p Self`."""
    p = ox.NamedNode("http://example.org/hasPartOf")
    r = ox.BlankNode("r_self_false")
    xsd_false = ox.Literal("false", datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#boolean"))
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_SELF, xsd_false),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value}),
    )
    flat = _flatten(out)
    assert "Self" not in flat
    assert flat.startswith("[restriction:") or flat.startswith("hasPartOf")


def test_restriction_has_self_plain_string_does_not_render_as_self():
    """A plain "true" string without xsd:boolean datatype must not render as Self."""
    p = ox.NamedNode("http://example.org/hasPartOf")
    r = ox.BlankNode("r_self_plainstr")
    plain_true = ox.Literal("true")  # default xsd:string datatype, not boolean
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_SELF, plain_true),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value}),
    )
    assert "Self" not in _flatten(out)


_OWL_CARD = ox.NamedNode("http://www.w3.org/2002/07/owl#cardinality")
_OWL_MIN_CARD = ox.NamedNode("http://www.w3.org/2002/07/owl#minCardinality")
_OWL_MAX_CARD = ox.NamedNode("http://www.w3.org/2002/07/owl#maxCardinality")
_OWL_QCARD = ox.NamedNode("http://www.w3.org/2002/07/owl#qualifiedCardinality")
_OWL_MIN_QCARD = ox.NamedNode("http://www.w3.org/2002/07/owl#minQualifiedCardinality")
_OWL_MAX_QCARD = ox.NamedNode("http://www.w3.org/2002/07/owl#maxQualifiedCardinality")
_OWL_ON_CLASS = ox.NamedNode("http://www.w3.org/2002/07/owl#onClass")
_XSD_NONNEG_INT = ox.NamedNode("http://www.w3.org/2001/XMLSchema#nonNegativeInteger")


def _int_lit(n: int) -> ox.Literal:
    return ox.Literal(str(n), datatype=_XSD_NONNEG_INT)


def test_restriction_cardinality_unqualified():
    p = ox.NamedNode("http://example.org/hasTopping")
    r = ox.BlankNode("rc1")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_CARD, _int_lit(3)),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value}),
    )
    assert _flatten(out) == "hasTopping exactly 3"


def test_restriction_min_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    r = ox.BlankNode("rc2")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MIN_CARD, _int_lit(1)),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value}),
    )
    assert _flatten(out) == "hasTopping min 1"


def test_restriction_max_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    r = ox.BlankNode("rc3")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MAX_CARD, _int_lit(5)),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value}),
    )
    assert _flatten(out) == "hasTopping max 5"


def test_restriction_min_qualified_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Vegetable")
    r = ox.BlankNode("rc4")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MIN_QCARD, _int_lit(2)),
        (r, _OWL_ON_CLASS, c),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value, c.value}),
    )
    assert _flatten(out) == "hasTopping min 2 Vegetable"


def test_restriction_max_qualified_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Vegetable")
    r = ox.BlankNode("rc5")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MAX_QCARD, _int_lit(4)),
        (r, _OWL_ON_CLASS, c),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value, c.value}),
    )
    assert _flatten(out) == "hasTopping max 4 Vegetable"


def test_restriction_qualified_cardinality_exactly():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Vegetable")
    r = ox.BlankNode("rc6")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_QCARD, _int_lit(2)),
        (r, _OWL_ON_CLASS, c),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value, c.value}),
    )
    assert _flatten(out) == "hasTopping exactly 2 Vegetable"


def test_restriction_unqualified_cardinality_ignores_onClass():
    """Ill-formed RDF: owl:cardinality + owl:onClass should NOT render as qualified."""
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Vegetable")
    r = ox.BlankNode("rc_illformed")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_CARD, _int_lit(3)),
        (r, _OWL_ON_CLASS, c),  # spec violation
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={}, known_iris=frozenset({p.value, c.value}),
    )
    flat = _flatten(out)
    assert flat == "hasTopping exactly 3", \
        f"unqualified cardinality must not absorb onClass, got: {flat}"


_OWL_INTERSECTION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#intersectionOf")
_OWL_UNION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#unionOf")
_OWL_COMPLEMENT_N = ox.NamedNode("http://www.w3.org/2002/07/owl#complementOf")


def test_intersection_of_named_classes():
    """Top-level junctions render without outer parens (depth == 0)."""
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    head, list_quads = _list_quads([a, b])
    expr = ox.BlankNode("expr1")
    store = _store(
        (expr, _OWL_INTERSECTION_N, head),
        *list_quads,
    )
    out = render_class_expression(
        store, _GRAPH, expr, labels={}, known_iris=frozenset({a.value, b.value}),
    )
    assert out == [
        {"t": "iri", "label": "A", "iri": a.value, "in_ontology": True},
        {"t": "text", "v": " and "},
        {"t": "iri", "label": "B", "iri": b.value, "in_ontology": True},
    ]


def test_union_of_named_classes():
    """Top-level junctions render without outer parens (depth == 0)."""
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    c = ox.NamedNode("http://example.org/C")
    head, list_quads = _list_quads([a, b, c])
    expr = ox.BlankNode("expr2")
    store = _store(
        (expr, _OWL_UNION_N, head),
        *list_quads,
    )
    out = render_class_expression(
        store, _GRAPH, expr, labels={},
        known_iris=frozenset({a.value, b.value, c.value}),
    )
    assert _flatten(out) == "A or B or C"
    # Verify token shape: 3 iri tokens interleaved with 2 ' or ' separators.
    assert [t["t"] for t in out] == ["iri", "text", "iri", "text", "iri"]


def test_complement_of_named_class():
    """`not A` — complement of a named class needs no parens."""
    a = ox.NamedNode("http://example.org/A")
    expr = ox.BlankNode("expr3")
    store = _store((expr, _OWL_COMPLEMENT_N, a))
    out = render_class_expression(
        store, _GRAPH, expr, labels={}, known_iris=frozenset({a.value}),
    )
    assert out == [
        {"t": "text", "v": "not "},
        {"t": "iri", "label": "A", "iri": a.value, "in_ontology": True},
    ]


def test_intersection_inside_restriction():
    """Nested: `hasTopping some (A and B)` — junction at depth>0 self-wraps."""
    p = ox.NamedNode("http://example.org/hasTopping")
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    head, list_quads = _list_quads([a, b])
    inter = ox.BlankNode("inter")
    r = ox.BlankNode("r_nested")
    store = _store(
        (inter, _OWL_INTERSECTION_N, head),
        *list_quads,
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_SOME, inter),
    )
    out = render_class_expression(
        store, _GRAPH, r, labels={},
        known_iris=frozenset({p.value, a.value, b.value}),
    )
    assert _flatten(out) == "hasTopping some (A and B)"


def test_complement_of_restriction_is_parenthesized():
    """`not (hasTopping some Meat)` — restriction inside complement must be wrapped."""
    p = ox.NamedNode("http://example.org/hasTopping")
    meat = ox.NamedNode("http://example.org/Meat")
    r = ox.BlankNode("inner_rest")
    expr = ox.BlankNode("compl_with_rest")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_SOME, meat),
        (expr, _OWL_COMPLEMENT_N, r),
    )
    out = render_class_expression(
        store, _GRAPH, expr, labels={},
        known_iris=frozenset({p.value, meat.value}),
    )
    assert _flatten(out) == "not (hasTopping some Meat)"
    # First token must open `not (` so a downstream consumer can detect the wrap.
    assert out[0] == {"t": "text", "v": "not ("}
    assert out[-1] == {"t": "text", "v": ")"}


def test_complement_of_junction_does_not_double_parenthesize():
    """`not (A and B)` — junction self-parenthesizes at depth>0; complement must not double-wrap."""
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    head, list_quads = _list_quads([a, b])
    inter = ox.BlankNode("inter_in_compl")
    expr = ox.BlankNode("compl_with_inter")
    store = _store(
        (inter, _OWL_INTERSECTION_N, head),
        *list_quads,
        (expr, _OWL_COMPLEMENT_N, inter),
    )
    out = render_class_expression(
        store, _GRAPH, expr, labels={},
        known_iris=frozenset({a.value, b.value}),
    )
    assert _flatten(out) == "not (A and B)"
    # The leading token must be exactly "not " (no extra `(`) — the junction
    # supplies its own parens at depth>0.
    assert out[0] == {"t": "text", "v": "not "}


_OWL_ONE_OF_N = ox.NamedNode("http://www.w3.org/2002/07/owl#oneOf")
_OWL_ON_DT = ox.NamedNode("http://www.w3.org/2002/07/owl#onDatatype")
_OWL_WITH_R = ox.NamedNode("http://www.w3.org/2002/07/owl#withRestrictions")
_XSD_INT = ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer")
_XSD_MIN_INC = ox.NamedNode("http://www.w3.org/2001/XMLSchema#minInclusive")
_XSD_MAX_INC = ox.NamedNode("http://www.w3.org/2001/XMLSchema#maxInclusive")


def test_one_of_named_individuals():
    a = ox.NamedNode("http://example.org/Alice")
    b = ox.NamedNode("http://example.org/Bob")
    c = ox.NamedNode("http://example.org/Carol")
    head, list_quads = _list_quads([a, b, c])
    expr = ox.BlankNode("enum1")
    store = _store(
        (expr, _OWL_ONE_OF_N, head),
        *list_quads,
    )
    out = render_class_expression(
        store, _GRAPH, expr, labels={},
        known_iris=frozenset({a.value, b.value, c.value}),
    )
    assert _flatten(out) == "{Alice, Bob, Carol}"
    # Verify the enumeration brackets are present as text tokens.
    assert out[0] == {"t": "text", "v": "{"}
    assert out[-1] == {"t": "text", "v": "}"}


def test_datatype_restriction_range():
    """xsd:integer[>= 0, <= 120]"""
    dt_expr = ox.BlankNode("dt1")
    facet1 = ox.BlankNode("facet1")
    facet2 = ox.BlankNode("facet2")
    head, list_quads = _list_quads([facet1, facet2])
    store = _store(
        (dt_expr, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#Datatype")),
        (dt_expr, _OWL_ON_DT, _XSD_INT),
        (dt_expr, _OWL_WITH_R, head),
        (facet1, _XSD_MIN_INC, _int_lit(0)),
        (facet2, _XSD_MAX_INC, _int_lit(120)),
        *list_quads,
    )
    out = render_class_expression(
        store, _GRAPH, dt_expr, labels={}, known_iris=frozenset(),
    )
    assert _flatten(out) == "xsd:integer[>= 0, <= 120]"


def test_datatype_restriction_pattern():
    """xsd:string[pattern "[A-Z]+"]"""
    dt_expr = ox.BlankNode("dt2")
    facet = ox.BlankNode("facet_p")
    head, list_quads = _list_quads([facet])
    xsd_string = ox.NamedNode("http://www.w3.org/2001/XMLSchema#string")
    xsd_pattern = ox.NamedNode("http://www.w3.org/2001/XMLSchema#pattern")
    store = _store(
        (dt_expr, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#Datatype")),
        (dt_expr, _OWL_ON_DT, xsd_string),
        (dt_expr, _OWL_WITH_R, head),
        (facet, xsd_pattern, ox.Literal("[A-Z]+")),
        *list_quads,
    )
    out = render_class_expression(
        store, _GRAPH, dt_expr, labels={}, known_iris=frozenset(),
    )
    assert _flatten(out) == 'xsd:string[pattern "[A-Z]+"]'


def test_depth_limit_returns_ellipsis():
    """A deeply nested intersection chain renders as `…` once depth exceeds _MAX_DEPTH."""
    p = ox.NamedNode("http://example.org/p")
    a = ox.NamedNode("http://example.org/A")
    quads = []
    # Build 12 nested restrictions: r0 → r1 → r2 → ... → A
    # r_i: p some r_{i+1}
    last = a
    for i in reversed(range(12)):
        r = ox.BlankNode(f"deep_{i}")
        quads.append((r, _RDF_TYPE_N, _OWL_RESTRICTION))
        quads.append((r, _OWL_ON_PROPERTY, p))
        quads.append((r, _OWL_SOME, last))
        last = r
    store = _store(*quads)
    out = render_class_expression(
        store, _GRAPH, last, labels={}, known_iris=frozenset({p.value, a.value}),
    )
    assert "…" in _flatten(out), f"expected depth-limit ellipsis, got: {out}"


from ontoexplorer.modules.diff.manchester import render_axiom, _BUILTIN_ANNOTATION_PROPS

_RDFS_SUB_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
_OWL_EQUIV_CLASS_N = ox.NamedNode("http://www.w3.org/2002/07/owl#equivalentClass")
_OWL_DISJOINT_N = ox.NamedNode("http://www.w3.org/2002/07/owl#disjointWith")
_OWL_DISJOINT_UNION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#disjointUnionOf")


def test_axiom_subclassof_named():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Food")
    store = _store()
    out = render_axiom(
        store, _GRAPH, subj, _RDFS_SUB_N.value, obj, labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "SubClassOf: "},
        {"t": "iri", "label": "Food", "iri": "http://example.org/Food", "in_ontology": False},
    ]


def test_axiom_subclassof_restriction():
    subj = "http://example.org/Pizza"
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Tomato")
    r = ox.BlankNode("axr1")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_SOME, c),
    )
    out = render_axiom(
        store, _GRAPH, subj, _RDFS_SUB_N.value, r, labels={}, known_iris=frozenset(),
    )
    assert out is not None
    assert out[0] == {"t": "text", "v": "SubClassOf: "}
    # filler tokens come from render_class_expression on the restriction bnode
    assert len(out) > 1


def test_axiom_equivalent_class():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Food")
    store = _store()
    out = render_axiom(
        store, _GRAPH, subj, _OWL_EQUIV_CLASS_N.value, obj, labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "EquivalentTo: "},
        {"t": "iri", "label": "Food", "iri": "http://example.org/Food", "in_ontology": False},
    ]


def test_axiom_disjoint_with():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Pasta")
    store = _store()
    out = render_axiom(
        store, _GRAPH, subj, _OWL_DISJOINT_N.value, obj, labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "DisjointWith: "},
        {"t": "iri", "label": "Pasta", "iri": "http://example.org/Pasta", "in_ontology": False},
    ]


def test_axiom_unknown_predicate_returns_none():
    """A predicate outside the coverage table returns None, signalling the caller to fall back."""
    subj = "http://example.org/X"
    obj = ox.NamedNode("http://example.org/Y")
    store = _store()
    out = render_axiom(
        store, _GRAPH, subj, "http://example.org/unknownPred", obj,
        labels={}, known_iris=frozenset(),
    )
    assert out is None


_RDFS_SUBPROP_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subPropertyOf")
_OWL_EQUIV_PROP_N = ox.NamedNode("http://www.w3.org/2002/07/owl#equivalentProperty")
_OWL_INVERSE_OF_N = ox.NamedNode("http://www.w3.org/2002/07/owl#inverseOf")
_RDFS_DOMAIN_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#domain")
_RDFS_RANGE_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#range")
_OWL_SAME_AS_N = ox.NamedNode("http://www.w3.org/2002/07/owl#sameAs")
_OWL_DIFFERENT_N = ox.NamedNode("http://www.w3.org/2002/07/owl#differentFrom")
_OWL_FUNCTIONAL_N = ox.NamedNode("http://www.w3.org/2002/07/owl#FunctionalProperty")
_OWL_TRANSITIVE_N = ox.NamedNode("http://www.w3.org/2002/07/owl#TransitiveProperty")


def test_axiom_subproperty_of():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDFS_SUBPROP_N.value,
        ox.NamedNode("http://example.org/hasIngredient"),
        labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "SubPropertyOf: "},
        {"t": "iri", "label": "hasIngredient", "iri": "http://example.org/hasIngredient", "in_ontology": False},
    ]


def test_axiom_equivalent_property():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _OWL_EQUIV_PROP_N.value,
        ox.NamedNode("http://example.org/hasCovering"),
        labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "EquivalentTo: "},
        {"t": "iri", "label": "hasCovering", "iri": "http://example.org/hasCovering", "in_ontology": False},
    ]


def test_axiom_inverse_of():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _OWL_INVERSE_OF_N.value,
        ox.NamedNode("http://example.org/toppingOf"),
        labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "InverseOf: "},
        {"t": "iri", "label": "toppingOf", "iri": "http://example.org/toppingOf", "in_ontology": False},
    ]


def test_axiom_domain():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDFS_DOMAIN_N.value,
        ox.NamedNode("http://example.org/Pizza"),
        labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "Domain: "},
        {"t": "iri", "label": "Pizza", "iri": "http://example.org/Pizza", "in_ontology": False},
    ]


def test_axiom_range():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDFS_RANGE_N.value,
        ox.NamedNode("http://example.org/Topping"),
        labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "Range: "},
        {"t": "iri", "label": "Topping", "iri": "http://example.org/Topping", "in_ontology": False},
    ]


def test_axiom_characteristics_functional():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDF_TYPE_N.value,
        _OWL_FUNCTIONAL_N,
        labels={}, known_iris=frozenset(),
    )
    assert out == [{"t": "text", "v": "Characteristics: Functional"}]


def test_axiom_characteristics_transitive():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDF_TYPE_N.value,
        _OWL_TRANSITIVE_N,
        labels={}, known_iris=frozenset(),
    )
    assert out == [{"t": "text", "v": "Characteristics: Transitive"}]


def test_axiom_rdf_type_non_characteristic_returns_none():
    """rdf:type whose object isn't one of the 7 OWL property characteristics → None.

    The frame header already shows the entity's declared type; non-characteristic
    rdf:type triples are not surfaced as Manchester axioms.
    """
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _RDF_TYPE_N.value,
        ox.NamedNode("http://www.w3.org/2002/07/owl#Class"),
        labels={}, known_iris=frozenset(),
    )
    assert out is None


def test_axiom_same_as():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", _OWL_SAME_AS_N.value,
        ox.NamedNode("http://example.org/AliceFoo"),
        labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "SameAs: "},
        {"t": "iri", "label": "AliceFoo", "iri": "http://example.org/AliceFoo", "in_ontology": False},
    ]


def test_axiom_different_from():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", _OWL_DIFFERENT_N.value,
        ox.NamedNode("http://example.org/Bob"),
        labels={}, known_iris=frozenset(),
    )
    assert out == [
        {"t": "text", "v": "DifferentFrom: "},
        {"t": "iri", "label": "Bob", "iri": "http://example.org/Bob", "in_ontology": False},
    ]


def test_axiom_individual_types():
    """For an individual, rdf:type X renders as `Types: X`."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", _RDF_TYPE_N.value,
        ox.NamedNode("http://example.org/Person"),
        labels={}, known_iris=frozenset(),
        entity_type="individual",
    )
    assert out == [
        {"t": "text", "v": "Types: "},
        {"t": "iri", "label": "Person", "iri": "http://example.org/Person", "in_ontology": False},
    ]


def test_axiom_individual_property_assertion():
    """For an individual, an arbitrary predicate renders as `Facts: predicate object`."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", "http://example.org/hasFriend",
        ox.NamedNode("http://example.org/Bob"),
        labels={}, known_iris=frozenset(),
        entity_type="individual",
    )
    assert out == [
        {"t": "text", "v": "Facts: "},
        {"t": "iri", "label": "hasFriend", "iri": "http://example.org/hasFriend", "in_ontology": False},
        {"t": "text", "v": " "},
        {"t": "iri", "label": "Bob", "iri": "http://example.org/Bob", "in_ontology": False},
    ]


def test_axiom_individual_property_assertion_literal():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", "http://example.org/age",
        ox.Literal("30", datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer")),
        labels={}, known_iris=frozenset(),
        entity_type="individual",
    )
    assert out == [
        {"t": "text", "v": "Facts: "},
        {"t": "iri", "label": "age", "iri": "http://example.org/age", "in_ontology": False},
        {"t": "text", "v": " "},
        {"t": "text", "v": '"30"^^xsd:integer'},
    ]


def test_axiom_non_individual_unknown_predicate_still_returns_none():
    """For non-individuals, unknown predicates should NOT auto-convert to Facts:."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", "http://example.org/random",
        ox.NamedNode("http://example.org/Bar"),
        labels={}, known_iris=frozenset(),
        entity_type="class",
    )
    assert out is None


from ontoexplorer.modules.diff.manchester import _discover_annotation_props


def test_discover_annotation_props_returns_explicit_annotation_property_iris():
    """SELECT ?p WHERE { ?p a owl:AnnotationProperty } over a graph."""
    custom = ox.NamedNode("http://example.org/myCustomAnnotation")
    other  = ox.NamedNode("http://example.org/notAnAnnotation")
    annotation_property = ox.NamedNode("http://www.w3.org/2002/07/owl#AnnotationProperty")
    class_node          = ox.NamedNode("http://www.w3.org/2002/07/owl#Class")
    store = _store(
        (custom, _RDF_TYPE_N, annotation_property),
        (other,  _RDF_TYPE_N, class_node),
    )
    discovered = _discover_annotation_props(store, _GRAPH)
    assert custom.value in discovered
    assert other.value not in discovered


def test_discover_annotation_props_returns_empty_for_graph_without_any():
    store = _store()
    discovered = _discover_annotation_props(store, _GRAPH)
    assert discovered == frozenset()


from ontoexplorer.modules.diff.manchester import render_frame


def test_render_frame_modified_class_returns_structured_lines():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
    )
    assert frame is not None
    # Header line: op=None, tokens contain the entity-keyword text and the entity-IRI token.
    header = frame["lines"][0]
    assert header["op"] is None
    assert any(t["t"] == "iri" and t["iri"] == iri for t in header["tokens"])
    # Keyword line for SubClassOf: op=None.
    kw_line = next(l for l in frame["lines"] if any(t.get("v") == "SubClassOf:" or "SubClassOf" in t.get("v", "") for t in l["tokens"] if t["t"] == "text"))
    assert kw_line["op"] is None
    # Added body line: op='added', tokens include the food IRI as iri token.
    body = next(
        l for l in frame["lines"]
        if l["op"] == "added"
        and any(t["t"] == "iri" and t["iri"] == food.value for t in l["tokens"])
    )
    assert body is not None


def test_render_frame_op_added_marks_every_line_with_op_added():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
        op="added",
    )
    assert frame is not None
    assert all(line["op"] == "added" for line in frame["lines"]), \
        f"every line must have op='added', got: {frame['lines']}"


def test_render_frame_op_removed_marks_every_line_with_op_removed():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "removed", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
        op="removed",
    )
    assert frame is not None
    assert all(line["op"] == "removed" for line in frame["lines"])


def test_render_frame_bare_added_class_yields_single_header_line():
    bare = "http://example.org/Bare"
    store = _store()
    frame = render_frame(
        store, bare, "class",
        axiom_changes=[],
        labels={},
        known_iris=frozenset({bare}),
        op="added",
    )
    assert frame is not None
    assert len(frame["lines"]) == 1
    header = frame["lines"][0]
    assert header["op"] == "added"
    # Header contains the entity IRI token.
    assert any(t["t"] == "iri" and t["iri"] == bare for t in header["tokens"])


def test_render_frame_annotations_block_appears_before_subclassof():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_LABEL_N.value,
             "object": ox.Literal("Pizza", language="en"), "graph": _GRAPH},
            {"op": "added", "predicate": _RDFS_SUB_N.value,
             "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
        op="added",
    )
    assert frame is not None
    keyword_indices = {}
    for i, line in enumerate(frame["lines"]):
        for t in line["tokens"]:
            if t["t"] == "text":
                if "Annotations:" in t["v"]:
                    keyword_indices.setdefault("Annotations", i)
                if "SubClassOf:" in t["v"]:
                    keyword_indices.setdefault("SubClassOf", i)
    assert "Annotations" in keyword_indices and "SubClassOf" in keyword_indices
    assert keyword_indices["Annotations"] < keyword_indices["SubClassOf"]


_RDFS_LABEL_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
_RDFS_COMMENT_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#comment")
_DC_DESCRIPTION_N = ox.NamedNode("http://purl.org/dc/elements/1.1/description")
_OWL_VERSION_INFO_N = ox.NamedNode("http://www.w3.org/2002/07/owl#versionInfo")
_CUSTOM_ANN_N = ox.NamedNode("http://example.org/myAnn")


def test_render_axiom_rdfs_label_annotation_emits_token_line():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _RDFS_LABEL_N.value,
        ox.Literal("Foo", language="en"),
        labels={},
        known_iris=frozenset(),
        annotation_props=_BUILTIN_ANNOTATION_PROPS,
    )
    assert out is not None
    # tokens: "Annotations: rdfs:label " + literal-text
    assert out[0]["t"] == "text"
    assert out[0]["v"] == "Annotations: rdfs:label "
    assert out[1] == {"t": "text", "v": '"Foo"@en'}


def test_render_axiom_dc_description_annotation():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _DC_DESCRIPTION_N.value,
        ox.Literal("A thing"),
        labels={},
        known_iris=frozenset(),
        annotation_props=_BUILTIN_ANNOTATION_PROPS,
    )
    assert out == [
        {"t": "text", "v": "Annotations: dc:description "},
        {"t": "text", "v": '"A thing"'},
    ]


def test_render_axiom_owl_version_info_annotation():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Ont", _OWL_VERSION_INFO_N.value,
        ox.Literal("1.0.0"),
        labels={},
        known_iris=frozenset(),
        annotation_props=_BUILTIN_ANNOTATION_PROPS,
    )
    assert out == [
        {"t": "text", "v": "Annotations: owl:versionInfo "},
        {"t": "text", "v": '"1.0.0"'},
    ]


def test_render_axiom_custom_annotation_property_emits_iri_token_in_pred_position():
    """Non-CURIE annotation predicate renders as an IRI token (clickable when known)."""
    custom_pred = "http://example.org/myAnn"
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", custom_pred,
        ox.Literal("custom note"),
        labels={},
        known_iris=frozenset({custom_pred}),
        annotation_props=frozenset({custom_pred}),
    )
    assert out is not None
    # tokens: "Annotations: " + IriToken(custom_pred) + " " + text(literal)
    assert out[0] == {"t": "text", "v": "Annotations: "}
    assert out[1]["t"] == "iri"
    assert out[1]["iri"] == custom_pred
    assert out[1]["in_ontology"] is True


def test_render_axiom_subclassof_emits_keyword_text_then_iri_token():
    food = ox.NamedNode("http://example.org/Food")
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Pizza", _RDFS_SUB_N.value, food,
        labels={},
        known_iris=frozenset({food.value}),
    )
    assert out is not None
    assert out[0] == {"t": "text", "v": "SubClassOf: "}
    assert out[1] == {"t": "iri", "label": "Food", "iri": food.value, "in_ontology": True}


def test_render_axiom_custom_predicate_NOT_in_annotation_set_returns_none():
    """If a custom predicate isn't in annotation_props it falls through (None)."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", "http://example.org/randomPred",
        ox.NamedNode("http://example.org/Bar"),
        labels={},
        known_iris=frozenset(),
        annotation_props=frozenset(),  # not declared as annotation
    )
    assert out is None


from ontoexplorer.modules.diff.manchester import _known_iris


def test_known_iris_returns_subjects_and_iri_objects():
    """_known_iris collects every IRI that appears as subject OR as iri-typed object."""
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    c = ox.NamedNode("http://example.org/C")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (a, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2002/07/owl#Class")),
        (a, _RDFS_SUB_N, b),
        (a, label_pred, ox.Literal("A")),
        (b, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2002/07/owl#Class")),
        # c appears only as object, never as subject
    )
    store.add(ox.Quad(a, _RDFS_SUB_N, c, _GRAPH))
    known = _known_iris(store, _GRAPH)
    assert a.value in known
    assert b.value in known
    assert c.value in known
    # rdfs:label predicate IRI should NOT appear because the helper restricts
    # to subjects + iri-typed objects, and we never asked about predicates.
    # (Predicates also aren't in_ontology candidates.)
    # The literal "A" should NOT appear.
    assert '"A"' not in known


def test_known_iris_returns_empty_for_empty_graph():
    store = _store()
    assert _known_iris(store, _GRAPH) == frozenset()


from ontoexplorer.modules.diff.manchester import _iri_token


def test_iri_token_uses_label_when_known_and_marks_in_ontology():
    pizza = "http://example.org/Pizza"
    store = _store(
        (ox.NamedNode(pizza), _RDFS_LABEL_N, ox.Literal("Pizza", language="en")),
    )
    tok = _iri_token(
        store, _GRAPH, pizza,
        labels={pizza: "Pizza"},  # already cached
        known_iris=frozenset({pizza}),
    )
    assert tok == {"t": "iri", "label": "Pizza", "iri": pizza, "in_ontology": True}


def test_iri_token_falls_back_to_local_name_when_no_label():
    iri = "http://example.org/UnlabeledThing"
    tok = _iri_token(
        store=_store(), graph=_GRAPH, iri=iri,
        labels={}, known_iris=frozenset(),
    )
    assert tok == {"t": "iri", "label": "UnlabeledThing", "iri": iri, "in_ontology": False}


def test_iri_token_marks_external_iri_in_ontology_false():
    iri = "http://other.org/X"
    tok = _iri_token(
        store=_store(), graph=_GRAPH, iri=iri,
        labels={}, known_iris=frozenset({"http://example.org/Y"}),
    )
    assert tok["in_ontology"] is False


from ontoexplorer.modules.diff.manchester import _render_literal


def test_render_literal_returns_single_text_token():
    out = _render_literal(ox.Literal("Pizza", language="en"))
    assert out == [{"t": "text", "v": '"Pizza"@en'}]


def test_render_literal_suppresses_xsd_string_datatype():
    out = _render_literal(ox.Literal("Pizza"))
    assert out == [{"t": "text", "v": '"Pizza"'}]


def test_render_literal_renders_xsd_integer():
    out = _render_literal(
        ox.Literal("42", datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer")),
    )
    assert out == [{"t": "text", "v": '"42"^^xsd:integer'}]


def test_render_class_expression_named_class_returns_iri_token():
    pizza = "http://example.org/Pizza"
    store = _store()
    out = render_class_expression(
        store, _GRAPH, ox.NamedNode(pizza),
        labels={pizza: "Pizza"},
        known_iris=frozenset({pizza}),
    )
    assert out == [{"t": "iri", "label": "Pizza", "iri": pizza, "in_ontology": True}]


def test_render_class_expression_some_restriction_emits_iri_text_iri():
    """Restriction (hasTopping some Tomato) → 3 tokens: prop IRI, ' some ', filler IRI."""
    has_topping = ox.NamedNode("http://example.org/hasTopping")
    tomato      = ox.NamedNode("http://example.org/Tomato")
    bnode = ox.BlankNode()
    store = _store(
        (bnode, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction")),
        (bnode, ox.NamedNode("http://www.w3.org/2002/07/owl#onProperty"), has_topping),
        (bnode, ox.NamedNode("http://www.w3.org/2002/07/owl#someValuesFrom"), tomato),
    )
    out = render_class_expression(
        store, _GRAPH, bnode,
        labels={},
        known_iris=frozenset({has_topping.value, tomato.value}),
    )
    assert out == [
        {"t": "iri", "label": "hasTopping", "iri": has_topping.value, "in_ontology": True},
        {"t": "text", "v": " some "},
        {"t": "iri", "label": "Tomato", "iri": tomato.value, "in_ontology": True},
    ]


def test_render_frame_default_source_is_asserted_per_axiom():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    frame = render_frame(
        _store(), iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
    )
    assert frame is not None
    # Axiom body line has source='asserted' (default).
    body_line = next(l for l in frame["lines"] if l["op"] == "added")
    assert body_line["source"] == "asserted"
    # Header/keyword lines have source=None.
    header = frame["lines"][0]
    assert header["source"] is None


def test_render_frame_inferred_source_propagates_to_line():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    frame = render_frame(
        _store(), iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food,
             "graph": _GRAPH, "source": "inferred"},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
    )
    assert frame is not None
    body_line = next(l for l in frame["lines"] if l["op"] == "added")
    assert body_line["source"] == "inferred"


def test_render_class_expression_intersection_emits_with_and_separators():
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    bnode = ox.BlankNode()
    # Build an rdf:List of [a, b].
    n1, n2 = ox.BlankNode(), ox.BlankNode()
    store = _store(
        (bnode, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2002/07/owl#Class")),
        (bnode, ox.NamedNode("http://www.w3.org/2002/07/owl#intersectionOf"), n1),
        (n1, ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first"), a),
        (n1, ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"), n2),
        (n2, ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first"), b),
        (n2, ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"),
            ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#nil")),
    )
    out = render_class_expression(
        store, _GRAPH, bnode,
        labels={},
        known_iris=frozenset({a.value, b.value}),
    )
    # Tokens: (A) " and " (B)
    iri_tokens = [t for t in out if t["t"] == "iri"]
    text_tokens = [t for t in out if t["t"] == "text"]
    assert [t["iri"] for t in iri_tokens] == [a.value, b.value]
    assert " and " in [t["v"] for t in text_tokens]
