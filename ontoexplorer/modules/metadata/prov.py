"""Build a PROV-O activity record for an ingestion event."""

from datetime import UTC, datetime

import rdflib
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, XSD

PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")


def prov_subject_iris(version_id: str, app_base_url: str) -> list[str]:
    """The subjects build_ingestion_activity mints for one version.

    The submitted source URL is also a subject in that graph but is deliberately
    excluded: it is shared between every version ingested from the same URL, so
    deleting by it would remove another version's triples.
    """
    base = app_base_url.rstrip("/")   # app_url often has a trailing slash -> avoid //
    return [
        f"{base}/api/v1/versions/{version_id}/provenance",
        f"{base}/api/v1/ontologies/{version_id}",
    ]


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

    app_base_url = app_base_url.rstrip("/")   # app_url often has a trailing slash -> avoid //
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
