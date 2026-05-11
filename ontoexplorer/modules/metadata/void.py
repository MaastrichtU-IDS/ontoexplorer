"""Compute VoID statistics from an rdflib Graph."""

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
