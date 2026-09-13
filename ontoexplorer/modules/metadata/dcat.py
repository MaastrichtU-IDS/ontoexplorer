"""Build a DCAT dcat:Dataset record for an ontology version."""

from datetime import UTC, datetime

import rdflib
from rdflib import Literal, URIRef
from rdflib.namespace import DCAT, DCTERMS, OWL, RDF, VOID, XSD

from ontoexplorer.modules.metadata.void import VoidStats

# Additional namespaces
SCHEMA = rdflib.Namespace("https://schema.org/")
PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")


def dcat_subject_iris(ontology_id: str, version_id: str, app_base_url: str) -> list[str]:
    """The subjects build_dcat_record mints for one version.

    Deletion needs these and cannot re-derive them by parsing, so they live
    beside the builder rather than being spelled out a second time elsewhere.
    """
    base = app_base_url.rstrip("/")   # app_url often has a trailing slash -> avoid //
    dataset = f"{base}/api/v1/ontologies/{ontology_id}/{version_id}"
    return [dataset, f"{dataset}/download"]


# Ontology-level annotation predicates to surface into DCAT, in preference order.
_TITLE_PREDS = [
    "http://purl.org/dc/terms/title", "http://purl.org/dc/elements/1.1/title",
    "http://www.w3.org/2004/02/skos/core#prefLabel", "http://www.w3.org/2000/01/rdf-schema#label",
]
_DESC_PREDS = [
    "http://purl.org/dc/terms/description", "http://purl.org/dc/elements/1.1/description",
    "http://www.w3.org/2000/01/rdf-schema#comment",
]
_LICENSE_PREDS = ["http://purl.org/dc/terms/license", "http://purl.org/dc/elements/1.1/rights"]
_CREATOR_PREDS = ["http://purl.org/dc/terms/creator", "http://purl.org/dc/elements/1.1/creator"]


def extract_ontology_annotations(ontology_id: str, version_id: str, ontology_iri: str) -> dict:
    """Read the ontology node's own title/description/license/creator from the
    content store, so the FAIR record reflects what the ontology declares rather
    than being a bare stats stub. Best-effort — missing values are simply omitted.
    """
    from ontoexplorer.clients.oxigraph import graph_iri, sparql_query

    g = graph_iri(ontology_id, version_id)

    def _query(preds: list[str], limit: int) -> list[str]:
        values = " ".join(f"<{p}>" for p in preds)
        try:
            rows = sparql_query(
                f"SELECT DISTINCT ?o WHERE {{ GRAPH <{g}> {{ <{ontology_iri}> ?p ?o . "
                f"VALUES ?p {{ {values} }} }} }} LIMIT {limit}"
            )
        except Exception:
            return []
        return [(r["o"].value if hasattr(r["o"], "value") else str(r["o"])) for r in rows]

    title = _query(_TITLE_PREDS, 1)
    desc = _query(_DESC_PREDS, 1)
    lic = _query(_LICENSE_PREDS, 1)
    return {
        "title": title[0] if title else None,
        "description": desc[0] if desc else None,
        "license": lic[0] if lic else None,
        "creators": _query(_CREATOR_PREDS, 20),
    }


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
    title: str | None = None,
    description: str | None = None,
    creators: list[str] | None = None,
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

    base = app_base_url.rstrip("/")   # app_url often has a trailing slash -> avoid //
    dataset = URIRef(f"{base}/api/v1/ontologies/{ontology_id}/{version_id}")
    ontology_node = URIRef(ontology_iri)
    now = Literal(datetime.now(UTC).isoformat(), datatype=XSD.dateTime)

    # dcat:Dataset
    g.add((dataset, RDF.type, DCAT.Dataset))
    g.add((dataset, DCTERMS.identifier, Literal(version_id)))
    g.add((dataset, DCTERMS.isVersionOf, ontology_node))
    g.add((dataset, DCTERMS.created, now))

    # Descriptive metadata the ontology declares about itself (surfaced from the
    # content store), falling back to the app's shortname/title for dct:title so a
    # record is never title-less.
    if title:
        g.add((dataset, DCTERMS.title, Literal(title)))
    if description:
        g.add((dataset, DCTERMS.description, Literal(description)))
    for creator in (creators or []):
        # A creator can be an IRI (ORCID, a URL) or a plain name.
        node = URIRef(creator) if creator.startswith(("http://", "https://")) else Literal(creator)
        g.add((dataset, DCTERMS.creator, node))

    if version_iri:
        g.add((dataset, OWL.versionIRI, URIRef(version_iri)))

    if owner_name:
        g.add((dataset, DCTERMS.publisher, Literal(owner_name)))

    # License: prefer an explicit URL, else what the ontology declares (which may
    # be an IRI or a plain string).
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
