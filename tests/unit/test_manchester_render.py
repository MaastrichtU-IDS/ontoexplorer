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
