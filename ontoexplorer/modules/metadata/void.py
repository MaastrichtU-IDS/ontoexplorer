"""Compute VoID statistics from an rdflib Graph or via Oxigraph SPARQL."""

from dataclasses import dataclass



@dataclass
class VoidStats:
    triple_count: int
    class_count: int
    property_count: int
    entity_count: int
    distinct_subjects: int
    distinct_objects: int


def compute_void_stats_sparql(ontology_id: str, version_id: str) -> VoidStats:
    """Compute VoID statistics by running SPARQL queries on the already-loaded Oxigraph graph."""
    from ontoexplorer.clients.oxigraph import sparql_query, graph_iri

    g = graph_iri(ontology_id, version_id)

    def _int(solutions) -> int:
        row = next(iter(solutions), None)
        if row is None:
            return 0
        val = row["n"]
        return int(val.value) if hasattr(val, "value") else int(str(val))

    triple_count = _int(sparql_query(
        f"SELECT (COUNT(*) AS ?n) FROM <{g}> WHERE {{ ?s ?p ?o }}"
    ))
    class_count = _int(sparql_query(f"""
        SELECT (COUNT(DISTINCT ?s) AS ?n) FROM <{g}> WHERE {{
            {{ ?s a <http://www.w3.org/2002/07/owl#Class> }}
            UNION {{ ?s a <http://www.w3.org/2000/01/rdf-schema#Class> }}
        }}
    """))
    property_count = _int(sparql_query(f"""
        SELECT (COUNT(DISTINCT ?s) AS ?n) FROM <{g}> WHERE {{
            {{ ?s a <http://www.w3.org/2002/07/owl#ObjectProperty> }}
            UNION {{ ?s a <http://www.w3.org/2002/07/owl#DatatypeProperty> }}
            UNION {{ ?s a <http://www.w3.org/2002/07/owl#AnnotationProperty> }}
            UNION {{ ?s a <http://www.w3.org/1999/02/22-rdf-syntax-ns#Property> }}
        }}
    """))
    entity_count = _int(sparql_query(f"""
        SELECT (COUNT(DISTINCT ?s) AS ?n) FROM <{g}> WHERE {{
            ?s a <http://www.w3.org/2002/07/owl#NamedIndividual> .
        }}
    """))
    distinct_subjects = _int(sparql_query(
        f"SELECT (COUNT(DISTINCT ?s) AS ?n) FROM <{g}> WHERE {{ ?s ?p ?o }}"
    ))
    distinct_objects = _int(sparql_query(f"""
        SELECT (COUNT(DISTINCT ?o) AS ?n) FROM <{g}> WHERE {{
            ?s ?p ?o . FILTER(isIRI(?o) || isBlank(?o))
        }}
    """))

    return VoidStats(
        triple_count=triple_count,
        class_count=class_count,
        property_count=property_count,
        entity_count=entity_count,
        distinct_subjects=distinct_subjects,
        distinct_objects=distinct_objects,
    )
