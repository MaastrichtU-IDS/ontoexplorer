from datetime import datetime, UTC
from types import SimpleNamespace
from rdflib import URIRef
from rdflib.namespace import DCTERMS, OWL, RDF

from ontoexplorer.modules.mod.builder import (
    build_catalogue_graph,
    build_artefact_graph,
    build_artefacts_list_graph,
    build_record_graph,
    build_distribution_graph,
    build_resources_summary_graph,
    build_resource_list_graph,
    build_search_results_graph,
    DCAT, MOD, HYDRA,
)


def _ontology(shortname="go", iri="http://purl.obolibrary.org/obo/go.owl", title="Gene Ontology"):
    return SimpleNamespace(
        id="abc1",
        iri=iri,
        shortname=shortname,
        title=title,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _version(ontology_id="abc1", vid="v1", status="ready", format="owl", version_iri=None):
    return SimpleNamespace(
        id=vid,
        ontology_id=ontology_id,
        status=status,
        format=format,
        version_iri=version_iri,
        triple_count=12000,
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
    )


def _meta():
    return {
        "title": "Gene Ontology",
        "description": "A controlled vocabulary for biology",
        "creator": "GO Consortium",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "version_info": "2024-01-01",
        "prefix": "GO",
        "namespace_uri": "http://purl.obolibrary.org/obo/go/",
    }


def _stats():
    return {"class_count": "5000", "property_count": "20", "individual_count": "0", "triple_count": "12000"}


BASE = "http://localhost:8000"


def test_catalogue_graph_type():
    g = build_catalogue_graph(
        base_url=BASE,
        title="Test Catalogue",
        description="desc",
        artefact_count=5,
        sparql_endpoint=f"{BASE}/api/v1/sparql/content",
    )
    cat = URIRef(f"{BASE}/mod/")
    assert (cat, RDF.type, MOD.SemanticArtefactCatalog) in g
    assert (cat, DCTERMS.title, None) in [(s, p, None) for s, p, o in g if str(p) == str(DCTERMS.title)]


def test_artefact_graph_type_and_id():
    g = build_artefact_graph(
        ontology=_ontology(),
        version=_version(),
        meta=_meta(),
        stats=_stats(),
        base_url=BASE,
    )
    artefact = URIRef("http://purl.obolibrary.org/obo/go.owl")
    assert (artefact, RDF.type, MOD.SemanticArtefact) in g
    assert (artefact, RDF.type, OWL.Ontology) in g


def test_artefact_graph_acronym():
    g = build_artefact_graph(ontology=_ontology(), version=_version(), meta=_meta(), stats=_stats(), base_url=BASE)
    acronyms = [str(o) for _, p, o in g if str(p) == str(MOD.acronym)]
    assert "go" in acronyms


def test_artefact_graph_stats():
    g = build_artefact_graph(ontology=_ontology(), version=_version(), meta=_meta(), stats=_stats(), base_url=BASE)
    classes = [str(o) for _, p, o in g if str(p) == str(MOD.numberOfClasses)]
    assert classes == ["5000"]


def test_artefact_graph_no_shortname():
    ont = _ontology(shortname=None)
    g = build_artefact_graph(ontology=ont, version=_version(), meta=_meta(), stats=_stats(), base_url=BASE)
    acronyms = [o for _, p, o in g if str(p) == str(MOD.acronym)]
    assert len(acronyms) == 0


def test_artefacts_list_graph_hydra_collection():
    onts = [(_ontology(), _version(), _meta(), _stats())]
    g = build_artefacts_list_graph(artefacts=onts, total=1, page=1, page_size=10, base_url=BASE)
    col = URIRef(f"{BASE}/mod/artefacts")
    assert (col, RDF.type, HYDRA.Collection) in g


def test_record_graph_type():
    g = build_record_graph(ontology=_ontology(), version=_version(), base_url=BASE)
    from rdflib.namespace import FOAF
    rec = URIRef(f"{BASE}/mod/records/go")
    assert (rec, RDF.type, DCAT.CatalogRecord) in g
    assert (rec, FOAF.primaryTopic, URIRef("http://purl.obolibrary.org/obo/go.owl")) in g


def test_distribution_graph_media_type():
    g = build_distribution_graph(ontology=_ontology(), version=_version(), base_url=BASE)
    dist = URIRef(f"{BASE}/mod/artefacts/go/distributions/v1")
    assert (dist, RDF.type, DCAT.Distribution) in g
    media_types = [str(o) for _, p, o in g if str(p) == str(DCAT.mediaType)]
    assert "application/owl+xml" in media_types


def test_resources_summary_graph():
    stats = {"class_count": "100", "property_count": "10", "individual_count": "5"}
    g = build_resources_summary_graph(ontology=_ontology(), version=_version(), stats=stats, base_url=BASE)
    assert len(list(g)) > 0


def test_resource_list_graph_hydra():
    terms = [{"iri": "http://ex.org/Class1", "label": "Class 1"}]
    g = build_resource_list_graph(
        ontology=_ontology(), version=_version(), terms=terms,
        entity_type="class", total=1, page=1, page_size=10, base_url=BASE,
    )
    collections = [(s, p, o) for s, p, o in g if str(p) == str(RDF.type) and str(o) == str(HYDRA.Collection)]
    assert len(collections) > 0


def test_search_results_graph():
    results = [{"ontology_id": "abc1", "iri": "http://ex.org/C1", "label": "Foo", "score": 1.0}]
    g = build_search_results_graph(results=results, q="foo", total=1, page=1, page_size=10, base_url=BASE)
    assert len(list(g)) > 0
