"""Oxigraph triplestore client via pyoxigraph.

Stores one named graph per ontology version:
  urn:ontology:{ontology_id}:{version_id}            — asserted triples
  urn:ontology:{ontology_id}:{version_id}:inferred   — reasoning output (Phase 6)
"""

import logging
from io import BytesIO
from pathlib import Path

import pyoxigraph
import rdflib

from ontoexplorer.config import get_settings

logger = logging.getLogger(__name__)

_store: pyoxigraph.Store | None = None


def get_store() -> pyoxigraph.Store:
    global _store
    if _store is None:
        settings = get_settings()
        path = settings.oxigraph_data_path
        Path(path).mkdir(parents=True, exist_ok=True)
        if settings.oxigraph_read_only:
            _store = pyoxigraph.Store.read_only(path)
        else:
            _store = pyoxigraph.Store(path)
    return _store


def graph_iri(ontology_id: str, version_id: str, inferred: bool = False) -> str:
    base = f"urn:ontology:{ontology_id}:{version_id}"
    return f"{base}:inferred" if inferred else base


def load_graph(ontology_id: str, version_id: str, graph: rdflib.Graph) -> int:
    """
    Load an rdflib Graph into a named Oxigraph graph.

    Returns the number of triples loaded.
    Replaces any existing content in the named graph.
    """
    store = get_store()
    iri = graph_iri(ontology_id, version_id)
    named_graph = pyoxigraph.NamedNode(iri)

    # Serialise rdflib graph to N-Triples for fast bulk load
    nt_bytes = graph.serialize(format="nt").encode("utf-8")

    # Clear existing content in this named graph
    store.remove_graph(named_graph)
    store.add_graph(named_graph)

    # Bulk-load via N-Triples
    store.bulk_load(BytesIO(nt_bytes), "application/n-triples", base_iri=iri, to_graph=named_graph)

    count = sum(1 for _ in store.quads_for_pattern(None, None, None, named_graph))
    logger.info("Loaded %d triples into <%s>", count, iri)
    return count


def delete_graph(ontology_id: str, version_id: str, inferred: bool = False) -> None:
    store = get_store()
    iri = graph_iri(ontology_id, version_id, inferred)
    store.remove_graph(pyoxigraph.NamedNode(iri))


def sparql_query(query: str) -> pyoxigraph.QuerySolutions | pyoxigraph.QueryTriples | bool:
    """Execute a SPARQL query against the full store (all named graphs)."""
    return get_store().query(query)


def graph_exists(ontology_id: str, version_id: str) -> bool:
    store = get_store()
    iri = graph_iri(ontology_id, version_id)
    return pyoxigraph.NamedNode(iri) in store
