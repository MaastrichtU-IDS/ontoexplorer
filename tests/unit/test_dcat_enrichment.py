"""DCAT records carry the ontology's declared title/description/license/creator,
and dataset IRIs have no double slash."""
import pyoxigraph
import rdflib
from rdflib.namespace import DCTERMS, RDF
from rdflib import URIRef, Literal

from ontoexplorer.modules.metadata.dcat import build_dcat_record, dcat_subject_iris
from ontoexplorer.modules.metadata.void import VoidStats

_VOID = VoidStats(1, 1, 1, 1, 1, 1)


def _g(**kw):
    return build_dcat_record(
        ontology_id="o1", version_id="v1", ontology_iri="http://ex/o",
        version_iri=None, minio_download_url="http://app/dl", format_ext="owl",
        void_stats=_VOID, app_base_url="https://app.example.org/", **kw,
    )


def test_no_double_slash_in_dataset_iri():
    g = _g()
    ds = next(g.subjects(RDF.type, rdflib.URIRef("http://www.w3.org/ns/dcat#Dataset")))
    assert "//api/v1" not in str(ds), f"double slash in {ds}"
    assert str(ds) == "https://app.example.org/api/v1/ontologies/o1/v1"
    # subject-iri helper (used by delete) must agree exactly, or deletes miss
    assert str(ds) == dcat_subject_iris("o1", "v1", "https://app.example.org/")[0]


def test_title_description_creators_license_emitted():
    g = _g(title="My Ontology", description="A test ont",
           creators=["https://orcid.org/0000-0001", "Jane Doe"],
           license_url="https://creativecommons.org/licenses/by/4.0/")
    ds = next(g.subjects(RDF.type, rdflib.URIRef("http://www.w3.org/ns/dcat#Dataset")))
    assert (ds, DCTERMS.title, Literal("My Ontology")) in g
    assert (ds, DCTERMS.description, Literal("A test ont")) in g
    assert (ds, DCTERMS.creator, URIRef("https://orcid.org/0000-0001")) in g  # IRI creator
    assert (ds, DCTERMS.creator, Literal("Jane Doe")) in g                    # plain-name creator
    assert (ds, DCTERMS.license, URIRef("https://creativecommons.org/licenses/by/4.0/")) in g


def test_absent_annotations_omit_triples():
    g = _g()
    ds = next(g.subjects(RDF.type, rdflib.URIRef("http://www.w3.org/ns/dcat#Dataset")))
    assert not list(g.objects(ds, DCTERMS.title))
    assert not list(g.objects(ds, DCTERMS.creator))


def test_extract_ontology_annotations(monkeypatch):
    from ontoexplorer.modules.metadata import dcat
    store = pyoxigraph.Store()
    O = "http://ex/o"; G = "urn:ontology:o1:v1"
    ttl = f'''<{O}> <http://purl.org/dc/terms/title> "T" ;
        <http://purl.org/dc/terms/description> "D" ;
        <http://purl.org/dc/terms/license> <https://lic.example/1> ;
        <http://purl.org/dc/terms/creator> "Alice" , "Bob" .'''
    store.load(ttl.encode(), pyoxigraph.RdfFormat.TURTLE, to_graph=pyoxigraph.NamedNode(G))
    monkeypatch.setattr(dcat, "sparql_query", lambda q: store.query(q), raising=False)
    # graph_iri is imported inside the function; patch the source
    from ontoexplorer.clients import oxigraph
    monkeypatch.setattr(oxigraph, "sparql_query", lambda q: store.query(q))
    monkeypatch.setattr(oxigraph, "graph_iri", lambda oid, vid, inferred=False: G)
    ann = dcat.extract_ontology_annotations("o1", "v1", O)
    assert ann["title"] == "T" and ann["description"] == "D"
    assert ann["license"] == "https://lic.example/1"
    assert set(ann["creators"]) == {"Alice", "Bob"}


def _extract(monkeypatch, ttl: str, catalogued_iri: str) -> dict:
    """Load TTL into a store and run extract_ontology_annotations against it."""
    from ontoexplorer.modules.metadata import dcat
    from ontoexplorer.clients import oxigraph
    store = pyoxigraph.Store()
    G = "urn:ontology:o1:v1"
    store.load(ttl.encode(), pyoxigraph.RdfFormat.TURTLE, to_graph=pyoxigraph.NamedNode(G))
    monkeypatch.setattr(oxigraph, "sparql_query", lambda q: store.query(q))
    monkeypatch.setattr(oxigraph, "graph_iri", lambda oid, vid, inferred=False: G)
    return dcat.extract_ontology_annotations("o1", "v1", catalogued_iri)


_OWL_T = "http://www.w3.org/2002/07/owl#Ontology"
_IMPORTS = "http://www.w3.org/2002/07/owl#imports"
_LIC = "http://purl.org/dc/terms/license"


def test_license_found_on_trailing_slash_variant(monkeypatch):
    # Catalogued with a trailing slash, declared without one — must still resolve.
    ttl = f'''<http://ex/o> a <{_OWL_T}> ;
        <{_LIC}> <https://creativecommons.org/licenses/by/3.0/> .'''
    ann = _extract(monkeypatch, ttl, "http://ex/o/")
    assert ann["license"] == "https://creativecommons.org/licenses/by/3.0/"


def test_license_not_laundered_from_imported_ontology(monkeypatch):
    # The root ontology has NO license; an imported owl:Ontology does. Reading the
    # import's license as the root's would be laundering — must return None.
    ttl = f'''<http://ex/root> a <{_OWL_T}> ; <{_IMPORTS}> <http://ex/imp> .
        <http://ex/imp> a <{_OWL_T}> ; <{_LIC}> <https://lic.example/imported> .'''
    ann = _extract(monkeypatch, ttl, "http://ex/root")
    assert ann["license"] is None


def test_license_resolved_via_unique_root_when_iri_is_broken(monkeypatch):
    # Catalogued IRI is an unexpanded entity ref (never a real subject); the unique
    # non-imported root owl:Ontology carries the license.
    ttl = f'''<http://ex/real> a <{_OWL_T}> ;
        <{_LIC}> <https://creativecommons.org/licenses/by/3.0/> .'''
    ann = _extract(monkeypatch, ttl, "&oboe-base;oboe.owl")
    assert ann["license"] == "https://creativecommons.org/licenses/by/3.0/"


def test_real_license_wins_over_copyright_rights(monkeypatch):
    # dc:rights holds a copyright notice; dcterms:license holds the real license.
    # The license must win, not the copyright string.
    ttl = f'''<http://ex/o> a <{_OWL_T}> ;
        <{_LIC}> <https://creativecommons.org/licenses/by/4.0/> ;
        <http://purl.org/dc/terms/rights> "Copyright (c) 2021 Someone" .'''
    ann = _extract(monkeypatch, ttl, "http://ex/o")
    assert ann["license"] == "https://creativecommons.org/licenses/by/4.0/"


def test_rights_used_only_as_fallback(monkeypatch):
    # No dcterms:license, but dc:rights names a license URL — surfaced as a fallback.
    ttl = '''<http://ex/o> a <http://www.w3.org/2002/07/owl#Ontology> ;
        <http://purl.org/dc/terms/rights> <https://creativecommons.org/licenses/by/4.0/> .'''
    ann = _extract(monkeypatch, ttl, "http://ex/o")
    assert ann["license"] == "https://creativecommons.org/licenses/by/4.0/"
