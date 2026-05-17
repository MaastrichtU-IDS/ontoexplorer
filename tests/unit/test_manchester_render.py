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
