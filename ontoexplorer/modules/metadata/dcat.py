"""Build a DCAT dcat:Dataset record for an ontology version."""

from datetime import UTC, datetime

import rdflib
from rdflib import Literal, URIRef
from rdflib.namespace import DCAT, DCTERMS, OWL, RDF, VOID, XSD

from ontoexplorer.modules.metadata.void import VoidStats

# Additional namespaces
SCHEMA = rdflib.Namespace("https://schema.org/")
PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")


def build_dcat_record(
    *,
    ontology_id: str,
    version_id: str,
    ontology_iri: str,
    version_iri: str | None,
    minio_download_url: str | None,
    format_ext: str,
    void_stats: VoidStats,
    owner_name: str | None = None,
    license_url: str | None = None,
    app_base_url: str = "http://localhost:8000",
) -> rdflib.Graph:
    """
    Build a DCAT 2 + VoID metadata graph for one ontology version.

    Returns an rdflib.Graph with all metadata triples.
    """
    g = rdflib.Graph()
    g.bind("dcat", DCAT)
    g.bind("dct", DCTERMS)
    g.bind("owl", OWL)
    g.bind("void", VOID)
    g.bind("schema", SCHEMA)
    g.bind("prov", PROV)

    dataset = URIRef(f"{app_base_url}/api/v1/ontologies/{ontology_id}/{version_id}")
    ontology_node = URIRef(ontology_iri)
    now = Literal(datetime.now(UTC).isoformat(), datatype=XSD.dateTime)

    # dcat:Dataset
    g.add((dataset, RDF.type, DCAT.Dataset))
    g.add((dataset, DCTERMS.identifier, Literal(version_id)))
    g.add((dataset, DCTERMS.isVersionOf, ontology_node))
    g.add((dataset, DCTERMS.created, now))

    if version_iri:
        g.add((dataset, OWL.versionIRI, URIRef(version_iri)))

    if owner_name:
        g.add((dataset, DCTERMS.publisher, Literal(owner_name)))

    if license_url:
        g.add((dataset, DCTERMS.license, URIRef(license_url)))

    # dcat:Distribution (downloadable artifact)
    distribution = URIRef(f"{dataset}/download")
    g.add((dataset, DCAT.distribution, distribution))
    g.add((distribution, RDF.type, DCAT.Distribution))
    # Optional: presigning can fail independently of the rest of the record,
    # and one missing triple beats discarding the whole graph.
    if minio_download_url:
        g.add((distribution, DCAT.downloadURL, URIRef(minio_download_url)))
    g.add((distribution, DCAT.mediaType, Literal(_media_type(format_ext))))
    g.add((distribution, DCTERMS.format, Literal(format_ext)))

    # VoID statistics
    g.add((dataset, VOID.triples, Literal(void_stats.triple_count, datatype=XSD.integer)))
    g.add((dataset, VOID.classes, Literal(void_stats.class_count, datatype=XSD.integer)))
    g.add((dataset, VOID.properties, Literal(void_stats.property_count, datatype=XSD.integer)))
    g.add((dataset, VOID.entities, Literal(void_stats.entity_count, datatype=XSD.integer)))
    g.add((dataset, VOID.distinctSubjects, Literal(void_stats.distinct_subjects, datatype=XSD.integer)))
    g.add((dataset, VOID.distinctObjects, Literal(void_stats.distinct_objects, datatype=XSD.integer)))

    # SPARQL endpoint
    sparql_ep = URIRef(f"{app_base_url}/sparql")
    g.add((dataset, VOID.sparqlEndpoint, sparql_ep))

    return g


def _media_type(ext: str) -> str:
    return {
        "owl": "application/owl+xml",
        "rdf": "application/rdf+xml",
        "ttl": "text/turtle",
        "nt": "application/n-triples",
        "jsonld": "application/ld+json",
        "obo": "text/plain",
        "omn": "text/plain",
    }.get(ext.lower(), "application/octet-stream")
