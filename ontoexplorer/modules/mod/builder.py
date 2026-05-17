from datetime import UTC, datetime
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, RDF, RDFS, SKOS, XSD

DCAT = Namespace("http://www.w3.org/ns/dcat#")
MOD = Namespace("https://w3id.org/mod#")
VOID = Namespace("http://rdfs.org/ns/void#")
VANN = Namespace("http://purl.org/vocab/vann/")
SCHEMA = Namespace("https://schema.org/")
HYDRA = Namespace("http://www.w3.org/ns/hydra/core#")
SD = Namespace("http://www.w3.org/ns/sparql-service-description#")

MEDIA_TYPES: dict[str, str] = {
    "owl": "application/owl+xml",
    "ttl": "text/turtle",
    "turtle": "text/turtle",
    "rdf": "application/rdf+xml",
    "xml": "application/rdf+xml",
    "nt": "application/n-triples",
    "obo": "text/obo",
    "json": "application/ld+json",
    "jsonld": "application/ld+json",
}

STATUS_URIS: dict[str, str] = {
    "ready": "https://w3id.org/mod#Released",
    "deprecated": "https://w3id.org/mod#Obsolete",
    "ingested": "https://w3id.org/mod#Draft",
    "reasoning": "https://w3id.org/mod#Draft",
}


def _bind(g: Graph) -> None:
    g.bind("dcterms", DCTERMS)
    g.bind("dcat", DCAT)
    g.bind("mod", MOD)
    g.bind("owl", OWL)
    g.bind("foaf", FOAF)
    g.bind("skos", SKOS)
    g.bind("void", VOID)
    g.bind("vann", VANN)
    g.bind("schema", SCHEMA)
    g.bind("hydra", HYDRA)
    g.bind("sd", SD)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)


def _add_str(g: Graph, s: URIRef, p: Any, val: Any) -> None:
    if val:
        g.add((s, p, Literal(str(val))))


def _add_list(g: Graph, s: URIRef, p: Any, vals: list | None) -> None:
    for v in vals or []:
        if v:
            g.add((s, p, Literal(str(v))))


def _add_uri_or_str(g: Graph, s: URIRef, p: Any, val: str | None) -> None:
    if val:
        g.add((s, p, URIRef(val) if val.startswith("http") else Literal(val)))


def _artefact_id(ontology: Any) -> str:
    return ontology.shortname or ontology.id


def build_catalogue_graph(
    *,
    base_url: str,
    title: str,
    description: str,
    artefact_count: int,
    sparql_endpoint: str,
) -> Graph:
    g = Graph()
    _bind(g)
    cat = URIRef(f"{base_url}/mod/")
    g.add((cat, RDF.type, MOD.SemanticArtefactCatalog))
    g.add((cat, RDF.type, DCAT.Catalog))
    g.add((cat, DCTERMS.title, Literal(title)))
    g.add((cat, DCTERMS.description, Literal(description)))
    g.add((cat, MOD.numberOfArtefacts, Literal(artefact_count, datatype=XSD.integer)))
    ep = URIRef(sparql_endpoint)
    g.add((ep, RDF.type, SD.Service))
    g.add((cat, SD.endpoint, ep))
    g.add((cat, DCAT.dataset, URIRef(f"{base_url}/mod/artefacts")))
    return g


def build_artefact_graph(
    *,
    ontology: Any,
    version: Any,
    meta: dict,
    stats: dict,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    a = URIRef(ontology.iri)
    g.add((a, RDF.type, MOD.SemanticArtefact))
    g.add((a, RDF.type, OWL.Ontology))
    if ontology.shortname:
        g.add((a, MOD.acronym, Literal(ontology.shortname)))
    _add_str(g, a, DCTERMS.title, meta.get("title") or ontology.title)
    _add_str(g, a, DCTERMS.description, meta.get("description"))
    _add_list(g, a, DCTERMS.creator, meta.get("creators"))
    _add_list(g, a, DCTERMS.contributor, meta.get("contributors"))
    _add_list(g, a, DCTERMS.publisher, meta.get("publishers"))
    _add_uri_or_str(g, a, DCTERMS.license, meta.get("license"))
    _add_uri_or_str(g, a, FOAF.homepage, meta.get("homepage"))
    _add_str(g, a, OWL.versionInfo, meta.get("version_info"))
    if version.version_iri:
        g.add((a, OWL.versionIRI, URIRef(version.version_iri)))
    _add_str(g, a, DCTERMS.language, meta.get("language"))
    _add_str(g, a, SCHEMA.citation, meta.get("citation"))
    _add_str(g, a, SCHEMA.funding, meta.get("funding"))
    _add_str(g, a, VANN.preferredNamespacePrefix, meta.get("prefix"))
    _add_uri_or_str(g, a, VANN.preferredNamespaceUri, meta.get("namespace_uri"))
    g.add((a, DCTERMS.created, Literal(ontology.created_at.isoformat(), datatype=XSD.dateTime)))
    g.add((a, DCTERMS.modified, Literal(version.created_at.isoformat(), datatype=XSD.dateTime)))
    if (n := stats.get("class_count")) is not None:
        g.add((a, MOD.numberOfClasses, Literal(int(n), datatype=XSD.integer)))
    if (n := stats.get("property_count")) is not None:
        g.add((a, MOD.numberOfProperties, Literal(int(n), datatype=XSD.integer)))
    if (n := stats.get("individual_count")) is not None:
        g.add((a, MOD.numberOfIndividuals, Literal(int(n), datatype=XSD.integer)))
    triple_count = stats.get("triple_count") or getattr(version, "triple_count", None)
    if triple_count is not None:
        g.add((a, VOID.triples, Literal(int(triple_count), datatype=XSD.integer)))
    if status_uri := STATUS_URIS.get(version.status):
        g.add((a, MOD.status, URIRef(status_uri)))
    aid = _artefact_id(ontology)
    dist_uri = URIRef(f"{base_url}/mod/artefacts/{aid}/distributions/{version.id}")
    g.add((a, DCAT.distribution, dist_uri))
    return g


def build_artefacts_list_graph(
    *,
    artefacts: list[tuple[Any, Any, dict, dict]],
    total: int,
    page: int,
    page_size: int,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    col = URIRef(f"{base_url}/mod/artefacts")
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(total, datatype=XSD.integer)))
    g.add((col, HYDRA.itemsPerPage, Literal(page_size, datatype=XSD.integer)))
    _add_pagination(g, col, f"{base_url}/mod/artefacts", total, page, page_size)
    for ontology, version, meta, stats in artefacts:
        artefact_g = build_artefact_graph(
            ontology=ontology, version=version, meta=meta, stats=stats, base_url=base_url
        )
        for triple in artefact_g:
            g.add(triple)
        g.add((col, HYDRA.member, URIRef(ontology.iri)))
    return g


def build_record_graph(*, ontology: Any, version: Any, base_url: str) -> Graph:
    g = Graph()
    _bind(g)
    aid = _artefact_id(ontology)
    rec = URIRef(f"{base_url}/mod/records/{aid}")
    g.add((rec, RDF.type, DCAT.CatalogRecord))
    g.add((rec, FOAF.primaryTopic, URIRef(ontology.iri)))
    g.add((rec, DCTERMS.created, Literal(ontology.created_at.isoformat(), datatype=XSD.dateTime)))
    g.add((rec, DCTERMS.modified, Literal(version.created_at.isoformat(), datatype=XSD.dateTime)))
    return g


def build_records_list_graph(
    *,
    records: list[tuple[Any, Any]],
    total: int,
    page: int,
    page_size: int,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    col = URIRef(f"{base_url}/mod/records")
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(total, datatype=XSD.integer)))
    g.add((col, HYDRA.itemsPerPage, Literal(page_size, datatype=XSD.integer)))
    _add_pagination(g, col, f"{base_url}/mod/records", total, page, page_size)
    for ontology, version in records:
        rec_g = build_record_graph(ontology=ontology, version=version, base_url=base_url)
        for triple in rec_g:
            g.add(triple)
        g.add((col, HYDRA.member, URIRef(f"{base_url}/mod/records/{_artefact_id(ontology)}")))
    return g


def build_distribution_graph(*, ontology: Any, version: Any, base_url: str) -> Graph:
    g = Graph()
    _bind(g)
    aid = _artefact_id(ontology)
    dist = URIRef(f"{base_url}/mod/artefacts/{aid}/distributions/{version.id}")
    g.add((dist, RDF.type, MOD.SemanticArtefactDistribution))
    g.add((dist, RDF.type, DCAT.Distribution))
    download_url = URIRef(f"{base_url}/api/v1/ontologies/{ontology.id}/{version.id}/download")
    g.add((dist, DCAT.accessURL, download_url))
    g.add((dist, DCAT.downloadURL, download_url))
    g.add((dist, DCTERMS.format, Literal(version.format)))
    media_type = MEDIA_TYPES.get(version.format, f"application/{version.format}")
    g.add((dist, DCAT.mediaType, Literal(media_type)))
    g.add((dist, DCTERMS.created, Literal(version.created_at.isoformat(), datatype=XSD.dateTime)))
    return g


def build_distributions_list_graph(
    *, ontology: Any, versions: list[Any], base_url: str
) -> Graph:
    g = Graph()
    _bind(g)
    aid = _artefact_id(ontology)
    col = URIRef(f"{base_url}/mod/artefacts/{aid}/distributions")
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(len(versions), datatype=XSD.integer)))
    for version in versions:
        dist_g = build_distribution_graph(ontology=ontology, version=version, base_url=base_url)
        for triple in dist_g:
            g.add(triple)
        g.add((col, HYDRA.member, URIRef(f"{base_url}/mod/artefacts/{aid}/distributions/{version.id}")))
    return g


ENTITY_TYPE_TO_RDF = {
    "class": OWL.Class,
    "individual": OWL.NamedIndividual,
    "property": RDF.Property,
    "concept": SKOS.Concept,
    "scheme": SKOS.ConceptScheme,
    "collection": SKOS.Collection,
}


def build_resources_summary_graph(*, ontology: Any, version: Any, stats: dict, base_url: str) -> Graph:
    g = Graph()
    _bind(g)
    a = URIRef(ontology.iri)
    if (n := stats.get("class_count")) is not None:
        g.add((a, MOD.numberOfClasses, Literal(int(n), datatype=XSD.integer)))
    if (n := stats.get("property_count")) is not None:
        g.add((a, MOD.numberOfProperties, Literal(int(n), datatype=XSD.integer)))
    if (n := stats.get("individual_count")) is not None:
        g.add((a, MOD.numberOfIndividuals, Literal(int(n), datatype=XSD.integer)))
    return g


def build_resource_list_graph(
    *,
    ontology: Any,
    version: Any,
    terms: list[dict],
    entity_type: str,
    total: int,
    page: int,
    page_size: int,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    aid = _artefact_id(ontology)
    col_url = f"{base_url}/mod/artefacts/{aid}/resources/{entity_type}s"
    col = URIRef(col_url)
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(total, datatype=XSD.integer)))
    g.add((col, HYDRA.itemsPerPage, Literal(page_size, datatype=XSD.integer)))
    _add_pagination(g, col, col_url, total, page, page_size)
    rdf_type = ENTITY_TYPE_TO_RDF.get(entity_type, OWL.Class)
    for term in terms:
        node = URIRef(term["iri"])
        g.add((node, RDF.type, rdf_type))
        if label := term.get("label"):
            g.add((node, RDFS.label, Literal(label)))
        g.add((col, HYDRA.member, node))
    return g


def build_labels_graph(*, ontology: Any, version: Any, terms: list[dict], base_url: str) -> Graph:
    g = Graph()
    _bind(g)
    for term in terms:
        node = URIRef(term["iri"])
        if label := term.get("label"):
            lang = term.get("lang")
            g.add((node, RDFS.label, Literal(label, lang=lang) if lang else Literal(label)))
    return g


def build_search_results_graph(
    *,
    results: list[dict],
    q: str,
    total: int,
    page: int,
    page_size: int,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    col = URIRef(f"{base_url}/mod/search")
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(total, datatype=XSD.integer)))
    g.add((col, HYDRA.itemsPerPage, Literal(page_size, datatype=XSD.integer)))
    for result in results:
        iri = result.get("iri") or result.get("ontology_iri")
        if iri:
            node = URIRef(iri)
            g.add((col, HYDRA.member, node))
            if label := result.get("label"):
                g.add((node, RDFS.label, Literal(label)))
    return g


def _add_pagination(g: Graph, col: URIRef, base: str, total: int, page: int, page_size: int) -> None:
    view = URIRef(f"{base}?page={page}&page_size={page_size}")
    g.add((col, HYDRA.view, view))
    if page > 1:
        g.add((view, HYDRA.previous, URIRef(f"{base}?page={page - 1}&page_size={page_size}")))
    if page * page_size < total:
        g.add((view, HYDRA.next, URIRef(f"{base}?page={page + 1}&page_size={page_size}")))
    g.add((view, HYDRA.first, URIRef(f"{base}?page=1&page_size={page_size}")))
    last_page = max(1, (total + page_size - 1) // page_size)
    g.add((view, HYDRA.last, URIRef(f"{base}?page={last_page}&page_size={page_size}")))
