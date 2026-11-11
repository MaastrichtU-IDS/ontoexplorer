"""Graph-level VoID counts for an ontology version.

The six counts shown on the ontology page — triples, classes, the three OWL
property kinds, and named individuals — are intrinsic to the stored RDF graph,
so they are computed ONCE at index time and persisted to ``versions.graph_counts``
(a jsonb ``{name: count}``). The stats endpoint then serves them with an O(1)
row read instead of six live SPARQL COUNT queries against Oxigraph.

Why this exists: on a stats-cache miss the endpoint used to run those six
queries live. The full-graph ``COUNT(*)`` and the ``owl:Class`` count are
O(graph size) — ~6.8s and ~5.5s respectively on NCIt (10.7M triples) — so a
cold request took 13–30s on large ontologies and timed out (HTTP 500) on the
biggest. That 500 cached nothing, so every first viewer paid it again.

``compute_graph_counts`` is the single source of those queries, shared by:
  * the index task, which writes the row at index time (no visitor ever waits);
  * the backfill, which populates existing rows;
  * the stats endpoint's self-healing fallback — a version indexed before this
    column existed computes once, persists, and is instant thereafter.

The query text is identical to what the endpoint computed before, so the stored
values match the previously displayed numbers exactly.
"""
from __future__ import annotations

# Count keys in the order the stats payload lists them. ``triple_count`` is also
# stored on its own ``versions.triple_count`` column; it is included here so the
# jsonb blob is self-contained (the endpoint can serve entirely from it).
GRAPH_COUNT_KEYS: tuple[str, ...] = (
    "triple_count",
    "class_count",
    "object_property_count",
    "datatype_property_count",
    "annotation_property_count",
    "individual_count",
)

_OWL = "http://www.w3.org/2002/07/owl#"


def _count_queries(graph: str) -> dict[str, str]:
    """SPARQL for each count over the named ``graph``. Keys = GRAPH_COUNT_KEYS."""
    def typed(cls: str, var: str) -> str:
        return (
            f"PREFIX owl: <{_OWL}> "
            f"SELECT (COUNT(DISTINCT ?{var}) AS ?n) WHERE {{ "
            f"GRAPH <{graph}> {{ ?{var} a owl:{cls} . FILTER(isIRI(?{var})) }} }}"
        )
    return {
        "triple_count": f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}",
        "class_count": typed("Class", "c"),
        "object_property_count": typed("ObjectProperty", "p"),
        "datatype_property_count": typed("DatatypeProperty", "p"),
        "annotation_property_count": typed("AnnotationProperty", "p"),
        "individual_count": typed("NamedIndividual", "i"),
    }


def compute_graph_counts(store, graph: str) -> dict[str, int]:
    """Run the six VoID COUNT queries against ``graph`` and return ``{key: int}``.

    Synchronous — one blocking ``store.query`` per count; callers inside an event
    loop wrap this in a thread. Propagates store errors so callers decide how to
    react (the index task logs and skips; the endpoint falls back to the live
    path it already had).
    """
    def _count(sparql: str) -> int:
        rows = list(store.query(sparql))
        if rows:
            v = rows[0]["n"]
            return int(v.value) if v is not None else 0
        return 0

    return {key: _count(q) for key, q in _count_queries(graph).items()}
