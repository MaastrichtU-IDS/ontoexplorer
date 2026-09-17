"""Unit tests for the RDF/RDFS/RDFS-Plus/OWL language-tier detector.

The tier is the *heaviest* modelling construct present, checked most-expressive
first, so an RDFS vocabulary is identified as RDFS instead of surfacing only as
"OWL 2 DL" / "OWL Full".
"""
import pyoxigraph as ox

from ontoexplorer.modules.owl_profile.language import LANGUAGE_TIERS, detect_language

_OWL = "http://www.w3.org/2002/07/owl#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_G = ox.NamedNode("urn:g")


def _store(*triples: tuple) -> ox.Store:
    s = ox.Store()
    s.add_graph(_G)
    for su, p, o in triples:
        s.add(ox.Quad(su, p, o, _G))
    return s


def _n(iri: str) -> ox.NamedNode:
    return ox.NamedNode(iri)


def test_tiers_are_the_expected_ladder():
    assert LANGUAGE_TIERS == ("rdf", "rdfs", "rdfs-plus", "owl")


def test_rdf_tier_no_schema():
    # Only instance data (a typed individual) — no schema constructs at all.
    s = _store((_n("urn:a"), _n(_RDF + "type"), _n("urn:Thing")),
               (_n("urn:a"), _n("urn:knows"), _n("urn:b")))
    assert detect_language(s, "urn:g")["tier"] == "rdf"


def test_rdfs_tier_schema_only():
    s = _store(
        (_n("urn:A"), _n(_RDF + "type"), _n(_RDFS + "Class")),
        (_n("urn:B"), _n(_RDFS + "subClassOf"), _n("urn:A")),
        (_n("urn:p"), _n(_RDFS + "domain"), _n("urn:A")),
    )
    r = detect_language(s, "urn:g")
    assert r["tier"] == "rdfs"
    assert r["construct"].startswith("rdfs:") or r["construct"] == "rdf:Property"


def test_owl_annotation_header_does_not_elevate_rdfs():
    # owl:Ontology header + an annotation property must NOT push an RDFS vocab to OWL.
    s = _store(
        (_n("urn:onto"), _n(_RDF + "type"), _n(_OWL + "Ontology")),
        (_n("urn:note"), _n(_RDF + "type"), _n(_OWL + "AnnotationProperty")),
        (_n("urn:A"), _n(_RDF + "type"), _n(_RDFS + "Class")),
        (_n("urn:B"), _n(_RDFS + "subClassOf"), _n("urn:A")),
    )
    assert detect_language(s, "urn:g")["tier"] == "rdfs"


def test_rdfs_plus_tier_named_owl_declarations():
    # owl:Class / owl:ObjectProperty declarations + a property characteristic, but
    # no restriction / negation / cardinality — the "taxonomy-level" case.
    s = _store(
        (_n("urn:A"), _n(_RDF + "type"), _n(_OWL + "Class")),
        (_n("urn:p"), _n(_RDF + "type"), _n(_OWL + "ObjectProperty")),
        (_n("urn:p"), _n(_RDF + "type"), _n(_OWL + "TransitiveProperty")),
        (_n("urn:B"), _n(_RDFS + "subClassOf"), _n("urn:A")),
    )
    assert detect_language(s, "urn:g")["tier"] == "rdfs-plus"


def test_owl_tier_restriction():
    r = ox.BlankNode()
    s = _store(
        (_n("urn:A"), _n(_RDF + "type"), _n(_OWL + "Class")),
        (_n("urn:A"), _n(_RDFS + "subClassOf"), r),
        (r, _n(_RDF + "type"), _n(_OWL + "Restriction")),
        (r, _n(_OWL + "onProperty"), _n("urn:p")),
        (r, _n(_OWL + "someValuesFrom"), _n("urn:B")),
    )
    res = detect_language(s, "urn:g")
    assert res["tier"] == "owl"
    assert res["construct"] in ("owl:Restriction", "owl:onProperty", "owl:someValuesFrom")


def test_owl_tier_beats_rdfs_plus_when_both_present():
    # A vocab that has owl:Class declarations AND a union → must be OWL, not RDFS-Plus.
    lst = ox.BlankNode()
    s = _store(
        (_n("urn:A"), _n(_RDF + "type"), _n(_OWL + "Class")),
        (_n("urn:A"), _n(_OWL + "unionOf"), lst),
    )
    assert detect_language(s, "urn:g")["tier"] == "owl"
