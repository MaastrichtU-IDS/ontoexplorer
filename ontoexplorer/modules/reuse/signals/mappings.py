"""Mapping-predicate extraction.

Enumerates cross-ontology mapping assertions (skos:*Match, oboInOwl:hasDbXref,
owl:sameAs) and groups them by (predicate, target_prefix). Counts every
mapping; caps sample (subject, object) pairs to keep payloads small.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pyoxigraph

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


_SAMPLE_CAP = 5

# Mapping predicates we extract, with CURIE-style keys for the response.
_MAPPING_PREDICATES = {
    "http://www.w3.org/2004/02/skos/core#closeMatch":   "skos:closeMatch",
    "http://www.w3.org/2004/02/skos/core#exactMatch":   "skos:exactMatch",
    "http://www.w3.org/2004/02/skos/core#relatedMatch": "skos:relatedMatch",
    "http://www.w3.org/2004/02/skos/core#broadMatch":   "skos:broadMatch",
    "http://www.w3.org/2004/02/skos/core#narrowMatch":  "skos:narrowMatch",
    "http://www.geneontology.org/formats/oboInOwl#hasDbXref": "oboInOwl:hasDbXref",
    "http://www.w3.org/2002/07/owl#sameAs":             "owl:sameAs",
}


@dataclass
class MappingEntry:
    target_prefix: str | None
    count: int = 0
    sample_pairs: list[tuple[str, str]] = field(default_factory=list)


def extract_mappings(
    store: pyoxigraph.Store,
    graph_iri: str,
    host_prefix: str | None,
) -> dict[str, list[MappingEntry]]:
    """Return mapping assertions per predicate, grouped by target prefix."""
    out: dict[str, list[MappingEntry]] = {}

    values_clause = " ".join(f"<{iri}>" for iri in _MAPPING_PREDICATES)

    q = f"""
        SELECT ?s ?p ?o WHERE {{
            VALUES ?p {{ {values_clause} }}
            GRAPH <{graph_iri}> {{
                ?s ?p ?o .
                FILTER(isIRI(?s) && isIRI(?o))
            }}
        }}
    """
    # buckets[(curie, target_prefix)] -> MappingEntry
    buckets: dict[tuple[str, str | None], MappingEntry] = {}
    for sol in store.query(q):
        pred_iri = sol["p"].value
        curie = _MAPPING_PREDICATES[pred_iri]
        target_iri = sol["o"].value
        target_prefix, _ = iri_to_prefix(target_iri)
        key = (curie, target_prefix)
        entry = buckets.setdefault(key, MappingEntry(target_prefix=target_prefix))
        entry.count += 1
        if len(entry.sample_pairs) < _SAMPLE_CAP:
            entry.sample_pairs.append((sol["s"].value, target_iri))

    for (curie, _tp), entry in buckets.items():
        out.setdefault(curie, []).append(entry)

    return out
