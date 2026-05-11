"""Build a PROV-O activity record for an ingestion event."""

from datetime import UTC, datetime

import rdflib
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, XSD

PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")


def build_ingestion_activity(
    *,
    version_id: str,
    ontology_iri: str,
    source_url: str | None,
    mode: str,  # "iri" | "url" | "bytes"
    sha256: str,
    triple_count: int,
    app_base_url: str = "http://localhost:8000",
) -> rdflib.Graph:
    """
    Build a PROV-O prov:Activity graph recording the ingestion of one ontology version.
    """
    g = rdflib.Graph()
    g.bind("prov", PROV)

    activity = URIRef(f"{app_base_url}/api/v1/versions/{version_id}/provenance")
    entity = URIRef(f"{app_base_url}/api/v1/ontologies/{version_id}")
    now = Literal(datetime.now(UTC).isoformat(), datatype=XSD.dateTime)

    g.add((activity, RDF.type, PROV.Activity))
    g.add((activity, PROV.endedAtTime, now))
    g.add((activity, PROV.generated, entity))
    g.add((entity, RDF.type, PROV.Entity))
    g.add((entity, PROV.wasGeneratedBy, activity))

    if source_url:
        source_entity = URIRef(source_url)
        g.add((source_entity, RDF.type, PROV.Entity))
        g.add((activity, PROV.used, source_entity))

    g.add((activity, URIRef(f"{app_base_url}/vocab#sha256"), Literal(sha256)))
    g.add((activity, URIRef(f"{app_base_url}/vocab#tripleCount"), Literal(triple_count, datatype=XSD.integer)))
    g.add((activity, URIRef(f"{app_base_url}/vocab#registrationMode"), Literal(mode)))

    return g
