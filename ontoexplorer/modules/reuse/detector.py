"""Reuse-analysis aggregator: runs all four signals and returns a ReuseReport."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pyoxigraph

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix
from ontoexplorer.modules.reuse.signals.imports import ImportEdge, build_closure
from ontoexplorer.modules.reuse.signals.mappings import MappingEntry, extract_mappings
from ontoexplorer.modules.reuse.signals.mireot import MireotTerm, detect_mireot
from ontoexplorer.modules.reuse.signals.term_iri import (
    TermIRIReuseEntry,
    classify_terms,
)


@dataclass
class ReuseReport:
    version_id: str
    host_prefix: str | None
    host_iri: str
    imports: list[ImportEdge] = field(default_factory=list)
    term_iri_reuse: dict[str, TermIRIReuseEntry] = field(default_factory=dict)
    mireot_terms: list[MireotTerm] = field(default_factory=list)
    mappings: dict[str, list[MappingEntry]] = field(default_factory=dict)
    indexed_at: str = ""


def _detect_store_host(store: pyoxigraph.Store, graph_iri: str) -> str:
    """The owl:Ontology IRI declared in the graph, or "" — a second host-identity
    signal alongside the registered IRI (covers ontologies whose registered IRI
    is absent/stale)."""
    q = (f"SELECT ?o WHERE {{ GRAPH <{graph_iri}> {{ ?o a "
         f"<http://www.w3.org/2002/07/owl#Ontology> . FILTER(isIRI(?o)) }} }} LIMIT 1")
    try:
        for sol in store.query(q):
            return sol["o"].value
    except Exception:
        pass
    return ""


def detect_reuse(
    store: pyoxigraph.Store,
    *,
    graph_iri: str,
    version_id: str,
    host_iri: str,
    host_namespaces: list[str],
    db_imports: list[dict],
    entities: list[tuple[str, str]],
) -> ReuseReport:
    """Run all four signals and aggregate into a ReuseReport.

    Args:
        store: in-process pyoxigraph store with the version's graph loaded.
        graph_iri: named graph IRI for the version.
        version_id: UUID of the version (for the report and cache key).
        host_iri: ontology IRI (display only; not used for classification).
        host_namespaces: namespaces declared as the host's own — terms whose
            IRI starts with any of these are treated as native.
        db_imports: list of dicts with keys `import_iri`, `depth`, fetched
            from the OntologyImport table by the caller.
        entities: list of (iri, entity_type) from the existing search index;
            the indexer passes this in to avoid a second store traversal.
    """
    host_prefix, _ = iri_to_prefix(host_iri)
    imports = build_closure(db_imports)
    import_prefix_set = {e.target_prefix for e in imports if e.target_prefix}

    # Derive the full host identity (repaired trailing-slash namespaces + the
    # identity tokens that recognise own terms in a divergent namespace, e.g. an
    # OBO product IRI resolving to the generic "obo" while its terms resolve to
    # the specific prefix). Mirrors the coverage/native-term detector so the
    # Reuse report and FAIR R5/R6 agree on what is native. The caller-supplied
    # host_namespaces are merged in as extras for backward compatibility.
    from ontoexplorer.modules.search.indexer import host_identity
    store_host = _detect_store_host(store, graph_iri)
    host_tokens, derived_ns = host_identity([host_iri, store_host])
    all_namespaces = list(dict.fromkeys(derived_ns + list(host_namespaces)))

    term_iri_reuse = classify_terms(entities, host_prefix=host_prefix,
                                    host_namespaces=all_namespaces,
                                    host_tokens=host_tokens)
    mireot_terms = detect_mireot(store, graph_iri=graph_iri,
                                 host_prefix=host_prefix,
                                 host_namespaces=all_namespaces,
                                 import_prefix_set=import_prefix_set,
                                 host_tokens=host_tokens)
    mappings = extract_mappings(store, graph_iri=graph_iri, host_prefix=host_prefix)

    return ReuseReport(
        version_id=version_id,
        host_prefix=host_prefix,
        host_iri=host_iri,
        imports=imports,
        term_iri_reuse=term_iri_reuse,
        mireot_terms=mireot_terms,
        mappings=mappings,
        indexed_at=datetime.now(timezone.utc).isoformat(),
    )
