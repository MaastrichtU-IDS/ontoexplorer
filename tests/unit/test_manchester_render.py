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


def test_render_named_class_returns_label():
    iri = "http://example.org/Pizza"
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Pizza", language="en")),
    )
    out = render_class_expression(store, _GRAPH, ox.NamedNode(iri), labels={})
    assert out == "Pizza"


def test_render_named_class_uses_local_name_when_no_label():
    iri = "http://example.org/Pizza"
    store = _store()
    out = render_class_expression(store, _GRAPH, ox.NamedNode(iri), labels={})
    assert out == "Pizza"


def test_render_literal_object_renders_with_quotes_and_lang():
    lit = ox.Literal("hello", language="en")
    store = _store()
    out = render_class_expression(store, _GRAPH, lit, labels={})
    assert out == '"hello"@en'


def test_render_literal_object_typed_renders_with_datatype():
    lit = ox.Literal(
        "42",
        datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer"),
    )
    store = _store()
    out = render_class_expression(store, _GRAPH, lit, labels={})
    assert out == '"42"^^xsd:integer'


def test_render_xsd_string_literal_omits_datatype():
    lit = ox.Literal(
        "hello",
        datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#string"),
    )
    store = _store()
    out = render_class_expression(store, _GRAPH, lit, labels={})
    assert out == '"hello"'


def test_render_unknown_bnode_returns_bnode_placeholder():
    # Bnode with no recognized class-expression predicate falls through to fallback.
    bnode = ox.BlankNode("unknown_xyz")
    store = _store(
        (bnode,
         ox.NamedNode("http://example.org/randomPred"),
         ox.NamedNode("http://example.org/Whatever")),
    )
    out = render_class_expression(store, _GRAPH, bnode, labels={})
    assert out.startswith("[bnode:")


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
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping some Tomato"


def test_restriction_all_values_from():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Tomato")
    r = ox.BlankNode("r2")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_ALL, c),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping only Tomato"


def test_restriction_has_value_iri():
    p = ox.NamedNode("http://example.org/hasTopping")
    v = ox.NamedNode("http://example.org/SpecificTomato")
    r = ox.BlankNode("r3")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_VALUE, v),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping value SpecificTomato"


def test_restriction_has_value_literal():
    p = ox.NamedNode("http://example.org/hasName")
    v = ox.Literal("Salty", language="en")
    r = ox.BlankNode("r4")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_VALUE, v),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == 'hasName value "Salty"@en'


def test_restriction_has_self_true():
    p = ox.NamedNode("http://example.org/hasPartOf")
    r = ox.BlankNode("r5")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_SELF, _XSD_TRUE),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasPartOf Self"


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
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert "Self" not in out
    assert out.startswith("[restriction:") or out.startswith("hasPartOf")


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
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert "Self" not in out


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
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping exactly 3"


def test_restriction_min_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    r = ox.BlankNode("rc2")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MIN_CARD, _int_lit(1)),
    )
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping min 1"


def test_restriction_max_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    r = ox.BlankNode("rc3")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MAX_CARD, _int_lit(5)),
    )
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping max 5"


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
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping min 2 Vegetable"


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
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping max 4 Vegetable"


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
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping exactly 2 Vegetable"


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
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping exactly 3", \
        f"unqualified cardinality must not absorb onClass, got: {out}"


_OWL_INTERSECTION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#intersectionOf")
_OWL_UNION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#unionOf")
_OWL_COMPLEMENT_N = ox.NamedNode("http://www.w3.org/2002/07/owl#complementOf")


def test_intersection_of_named_classes():
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    head, list_quads = _list_quads([a, b])
    expr = ox.BlankNode("expr1")
    store = _store(
        (expr, _OWL_INTERSECTION_N, head),
        *list_quads,
    )
    assert render_class_expression(store, _GRAPH, expr, labels={}) == "(A and B)"


def test_union_of_named_classes():
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    c = ox.NamedNode("http://example.org/C")
    head, list_quads = _list_quads([a, b, c])
    expr = ox.BlankNode("expr2")
    store = _store(
        (expr, _OWL_UNION_N, head),
        *list_quads,
    )
    assert render_class_expression(store, _GRAPH, expr, labels={}) == "(A or B or C)"


def test_complement_of_named_class():
    a = ox.NamedNode("http://example.org/A")
    expr = ox.BlankNode("expr3")
    store = _store((expr, _OWL_COMPLEMENT_N, a))
    assert render_class_expression(store, _GRAPH, expr, labels={}) == "not A"


def test_intersection_inside_restriction():
    """Nested: hasTopping some (A and B)."""
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
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping some (A and B)"


def test_complement_of_restriction_is_parenthesized():
    """not (hasTopping some Meat) — restriction inside complement must be wrapped."""
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
    out = render_class_expression(store, _GRAPH, expr, labels={})
    assert out == "not (hasTopping some Meat)"


def test_complement_of_junction_does_not_double_parenthesize():
    """not (A and B) — junction already self-parenthesizes; complement must not double-wrap."""
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
    out = render_class_expression(store, _GRAPH, expr, labels={})
    assert out == "not (A and B)"


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
    assert render_class_expression(store, _GRAPH, expr, labels={}) == "{Alice, Bob, Carol}"


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
    out = render_class_expression(store, _GRAPH, dt_expr, labels={})
    assert out == "xsd:integer[>= 0, <= 120]"


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
    out = render_class_expression(store, _GRAPH, dt_expr, labels={})
    assert out == 'xsd:string[pattern "[A-Z]+"]'


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
    out = render_class_expression(store, _GRAPH, last, labels={})
    assert "…" in out, f"expected depth-limit ellipsis, got: {out}"


from ontoexplorer.modules.diff.manchester import render_axiom

_RDFS_SUB_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
_OWL_EQUIV_CLASS_N = ox.NamedNode("http://www.w3.org/2002/07/owl#equivalentClass")
_OWL_DISJOINT_N = ox.NamedNode("http://www.w3.org/2002/07/owl#disjointWith")
_OWL_DISJOINT_UNION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#disjointUnionOf")


def test_axiom_subclassof_named():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Food")
    store = _store()
    out = render_axiom(
        store, _GRAPH, subj, _RDFS_SUB_N.value, obj, labels={}
    )
    assert out == "SubClassOf: Food"


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
    out = render_axiom(store, _GRAPH, subj, _RDFS_SUB_N.value, r, labels={})
    assert out == "SubClassOf: hasTopping some Tomato"


def test_axiom_equivalent_class():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Food")
    store = _store()
    out = render_axiom(store, _GRAPH, subj, _OWL_EQUIV_CLASS_N.value, obj, labels={})
    assert out == "EquivalentTo: Food"


def test_axiom_disjoint_with():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Pasta")
    store = _store()
    out = render_axiom(store, _GRAPH, subj, _OWL_DISJOINT_N.value, obj, labels={})
    assert out == "DisjointWith: Pasta"


def test_axiom_unknown_predicate_returns_none():
    """A predicate outside the coverage table returns None, signalling the caller to fall back."""
    subj = "http://example.org/X"
    obj = ox.NamedNode("http://example.org/Y")
    store = _store()
    out = render_axiom(
        store, _GRAPH, subj, "http://example.org/unknownPred", obj, labels={}
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
        labels={},
    )
    assert out == "SubPropertyOf: hasIngredient"


def test_axiom_equivalent_property():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _OWL_EQUIV_PROP_N.value,
        ox.NamedNode("http://example.org/hasCovering"),
        labels={},
    )
    assert out == "EquivalentTo: hasCovering"


def test_axiom_inverse_of():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _OWL_INVERSE_OF_N.value,
        ox.NamedNode("http://example.org/toppingOf"),
        labels={},
    )
    assert out == "InverseOf: toppingOf"


def test_axiom_domain():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDFS_DOMAIN_N.value,
        ox.NamedNode("http://example.org/Pizza"),
        labels={},
    )
    assert out == "Domain: Pizza"


def test_axiom_range():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDFS_RANGE_N.value,
        ox.NamedNode("http://example.org/Topping"),
        labels={},
    )
    assert out == "Range: Topping"


def test_axiom_characteristics_functional():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDF_TYPE_N.value,
        _OWL_FUNCTIONAL_N,
        labels={},
    )
    assert out == "Characteristics: Functional"


def test_axiom_characteristics_transitive():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDF_TYPE_N.value,
        _OWL_TRANSITIVE_N,
        labels={},
    )
    assert out == "Characteristics: Transitive"


def test_axiom_rdf_type_non_characteristic_returns_none():
    """rdf:type whose object isn't one of the 7 OWL property characteristics → None.

    The frame header already shows the entity's declared type; non-characteristic
    rdf:type triples are not surfaced as Manchester axioms.
    """
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _RDF_TYPE_N.value,
        ox.NamedNode("http://www.w3.org/2002/07/owl#Class"),
        labels={},
    )
    assert out is None


def test_axiom_same_as():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", _OWL_SAME_AS_N.value,
        ox.NamedNode("http://example.org/AliceFoo"),
        labels={},
    )
    assert out == "SameAs: AliceFoo"


def test_axiom_different_from():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", _OWL_DIFFERENT_N.value,
        ox.NamedNode("http://example.org/Bob"),
        labels={},
    )
    assert out == "DifferentFrom: Bob"
