"""MIREOT-pattern detection.

A term is MIREOT'd into the host ontology when:
  1. its IRI namespace is foreign (not the host's own),
  2. the source ontology is NOT in the host's owl:imports closure, and
  3. the term carries only minimal axiomatization in the host
     (label + at most one subClassOf/subPropertyOf, plus a known set of
     metadata annotation predicates, and no equivalentClass / disjointWith /
     domain / range / restriction / property-characteristic axioms).
"""
from __future__ import annotations

from dataclasses import dataclass

import pyoxigraph

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


# Allowed predicates that DON'T disqualify a term from being minimal.
_ALLOWED_ANNOTATION_PREDS = {
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://www.w3.org/2000/01/rdf-schema#isDefinedBy",
    "http://www.w3.org/2000/01/rdf-schema#seeAlso",
    "http://purl.obolibrary.org/obo/IAO_0000412",  # imported from
    "http://purl.obolibrary.org/obo/IAO_0000115",  # definition (allowed as predicate)
    "http://purl.obolibrary.org/obo/IAO_0000118",  # alternative term
    "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasDbXref",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
}

# Predicates whose presence disqualifies a term from being minimal.
_DISQUALIFYING_PREDS = (
    "http://www.w3.org/2002/07/owl#equivalentClass",
    "http://www.w3.org/2002/07/owl#disjointWith",
    "http://www.w3.org/2000/01/rdf-schema#domain",
    "http://www.w3.org/2000/01/rdf-schema#range",
    "http://www.w3.org/2002/07/owl#inverseOf",
    "http://www.w3.org/2002/07/owl#equivalentProperty",
)


@dataclass(frozen=True)
class MireotTerm:
    iri: str
    source_prefix: str
    has_imported_from: bool  # whether IAO:0000412 is present (strong MIREOT signal)


def detect_mireot(
    store: pyoxigraph.Store,
    graph_iri: str,
    host_prefix: str | None,
    host_namespaces: list[str],
    import_prefix_set: set[str],
) -> list[MireotTerm]:
    """Find foreign-namespace terms with minimal axiomatization and no covering import.

    `host_namespaces` is the authoritative native-skip — bioregistry may not
    recognize a custom host base IRI, so we can't rely on host_prefix matching
    alone. Subjects whose IRI starts with any of these namespaces are native
    and skipped.
    """
    found: list[MireotTerm] = []

    # Step 1: enumerate distinct foreign subjects.
    # Use a SPARQL ASK-style enumeration constrained to the named graph.
    subjects_q = f"""
        SELECT DISTINCT ?s WHERE {{
            GRAPH <{graph_iri}> {{
                ?s ?p ?o .
                FILTER(isIRI(?s))
            }}
        }}
    """
    subject_iris = [
        sol["s"].value for sol in store.query(subjects_q)
    ]

    for s in subject_iris:
        if any(s.startswith(ns) for ns in host_namespaces):
            continue  # native — host's own namespace
        prefix, _ = iri_to_prefix(s)
        if prefix is None:
            continue
        if prefix == host_prefix:
            continue  # also native (mixed-namespace forms of the host prefix)
        if prefix in import_prefix_set:
            continue  # source IS imported → not MIREOT

        # Step 2: fetch all predicates with this subject in this graph.
        preds_q = f"""
            SELECT ?p (COUNT(*) AS ?n) WHERE {{
                GRAPH <{graph_iri}> {{
                    <{s}> ?p ?o .
                }}
            }} GROUP BY ?p
        """
        pred_counts: dict[str, int] = {}
        for sol in store.query(preds_q):
            pred_counts[sol["p"].value] = int(sol["n"].value)

        # Step 3: check minimal-axiomatization rules.
        if any(p in pred_counts for p in _DISQUALIFYING_PREDS):
            continue
        sub_class_count = pred_counts.get(
            "http://www.w3.org/2000/01/rdf-schema#subClassOf", 0
        )
        sub_prop_count = pred_counts.get(
            "http://www.w3.org/2000/01/rdf-schema#subPropertyOf", 0
        )
        if sub_class_count > 1 or sub_prop_count > 1:
            continue
        # Any unknown predicate (not in allowed set, not the structural ones we just counted)?
        for p in pred_counts:
            if p in _ALLOWED_ANNOTATION_PREDS:
                continue
            if p == "http://www.w3.org/2000/01/rdf-schema#subClassOf":
                continue
            if p == "http://www.w3.org/2000/01/rdf-schema#subPropertyOf":
                continue
            # Unknown predicate → not minimal; bail.
            break
        else:
            has_imp = "http://purl.obolibrary.org/obo/IAO_0000412" in pred_counts
            found.append(MireotTerm(iri=s, source_prefix=prefix, has_imported_from=has_imp))

    return found
