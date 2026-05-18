"""Cross-ontology comparison.

run_comparison builds two graph IRIs from two (ontology_id, version_id) pairs
and delegates to the existing _run_diff_core helper. Identity is IRI-based.
"""
import pyoxigraph as ox

from ontoexplorer.clients.oxigraph import graph_iri
from ontoexplorer.modules.diff.compute import _run_diff_core


def run_comparison(
    store: ox.Store,
    from_ontology_id: str,
    from_vid: str,
    to_ontology_id: str,
    to_vid: str,
) -> tuple[dict, dict]:
    """Compute a diff between two ontology versions, possibly from different
    ontologies. Same JSON shape as `run_diff` (added/removed/modified buckets
    plus Manchester frames on modified entities). Two entities are "the same"
    iff they share an IRI.
    """
    from_graph = ox.NamedNode(graph_iri(from_ontology_id, from_vid))
    to_graph   = ox.NamedNode(graph_iri(to_ontology_id,   to_vid))
    return _run_diff_core(store, from_graph, to_graph)
