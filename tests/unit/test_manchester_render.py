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
