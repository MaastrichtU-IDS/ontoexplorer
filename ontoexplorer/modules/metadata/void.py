"""Compute VoID statistics from an rdflib Graph or via Oxigraph SPARQL."""

from dataclasses import dataclass

import rdflib
from rdflib.namespace import OWL, RDF


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


def compute_void_stats(graph: rdflib.Graph) -> VoidStats:
    """Compute VoID statistics over the full graph."""
    triples = list(graph)
    subjects = {str(s) for s, _, _ in triples}
    objects = {str(o) for _, _, o in triples if isinstance(o, (rdflib.URIRef, rdflib.BNode))}

    classes = set()
    for s in graph.subjects(RDF.type, OWL.Class):
        classes.add(str(s))
    for s in graph.subjects(RDF.type, rdflib.RDFS.Class):
        classes.add(str(s))

    properties = set()
    for p_type in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty, RDF.Property):
        for s in graph.subjects(RDF.type, p_type):
            properties.add(str(s))

    # Entities = named individuals + class instances
    entities = set()
    for s in graph.subjects(RDF.type, OWL.NamedIndividual):
        entities.add(str(s))

    return VoidStats(
        triple_count=len(triples),
        class_count=len(classes),
        property_count=len(properties),
        entity_count=len(entities),
        distinct_subjects=len(subjects),
        distinct_objects=len(objects),
    )
