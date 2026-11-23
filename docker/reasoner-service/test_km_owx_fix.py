"""Tests for the km OWL/XML input preparation (km_owx_fix).

Covers the pure OWL/XML transforms (header IRIs and annotations stripped,
missing declarations injected) and end-to-end km classifications that fail or
return wrong IRIs without them.
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET

import pytest

import km_owx_fix as kof

ONTO = "http://ex/onto"
A = f"{ONTO}/A"
B = f"{ONTO}/B"
C = f"{ONTO}/C"
P = "http://ex/p"
IAO_NOTE = "http://purl.obolibrary.org/obo/IAO_0000116"
DC_DATE = "http://purl.org/dc/terms/date"
RDFS_SUB = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
OWL = "http://www.w3.org/2002/07/owl#"
XSD_DATE = "http://www.w3.org/2001/XMLSchema#date"


def _owx(body: str, attrs: str = "", head: str = "") -> str:
    return ('<?xml version="1.0"?>\n'
            f'<Ontology xmlns="{OWL}"{attrs}>{head}{body}</Ontology>')


def _root(owx: str):
    return ET.fromstring(owx)


# ── pure OWL/XML transforms (no RDF / km deps) ──────────────────────────────────

def test_finds_used_but_undeclared_entities_by_kind():
    owx = _owx(
        f'<SubClassOf><Class IRI="{A}"/>'
        f'<ObjectSomeValuesFrom><ObjectProperty IRI="{P}"/><Class IRI="{B}"/>'
        "</ObjectSomeValuesFrom></SubClassOf>"
        f'<DataPropertyAssertion><DataProperty IRI="{IAO_NOTE}"/>'
        f'<NamedIndividual IRI="{A}"/><Literal>note</Literal></DataPropertyAssertion>'
    )
    assert kof.undeclared_entities(_root(owx)) == sorted([
        ("Class", A), ("Class", B), ("DataProperty", IAO_NOTE), ("ObjectProperty", P),
    ])


def test_declared_builtin_and_individual_entities_are_not_reported():
    owx = _owx(
        f'<Declaration><Class IRI="{A}"/></Declaration>'
        f'<SubClassOf><Class IRI="{A}"/><Class IRI="{OWL}Thing"/></SubClassOf>'
        f'<ClassAssertion><Class IRI="{A}"/><NamedIndividual IRI="http://ex/i"/></ClassAssertion>'
    )
    assert kof.undeclared_entities(_root(owx)) == []


def test_declaration_must_match_kind():
    owx = _owx(
        f'<Declaration><Class IRI="{A}"/></Declaration>'
        f'<ObjectPropertyDomain><ObjectProperty IRI="{A}"/><Class IRI="{A}"/></ObjectPropertyDomain>'
    )
    assert kof.undeclared_entities(_root(owx)) == [("ObjectProperty", A)]


def test_abbreviated_iris_are_resolved_through_prefixes():
    owx = _owx(
        f'<SubClassOf><Class abbreviatedIRI="ex:A"/><Class IRI="{B}"/></SubClassOf>',
        head=f'<Prefix name="ex" IRI="{ONTO}/"/>'
             '<Declaration><Class abbreviatedIRI="ex:B"/></Declaration>',
    )
    assert kof.undeclared_entities(_root(owx)) == [("Class", A)]


def test_strip_removes_header_iris_and_every_annotation():
    owx = _owx(
        f'<Annotation><AnnotationProperty IRI="{OWL}versionIRI"/><IRI>{ONTO}/1.0</IRI></Annotation>'
        f'<Declaration><Class IRI="{A}"/></Declaration>'
        f'<SubClassOf><Annotation><AnnotationProperty IRI="{RDFS_LABEL}"/><Literal>x</Literal></Annotation>'
        f'<Class IRI="{A}"/><Class IRI="{B}"/></SubClassOf>'
        f'<AnnotationAssertion><AnnotationProperty IRI="{DC_DATE}"/><IRI>{A}</IRI>'
        f'<Literal datatypeIRI="{XSD_DATE}">2025-06-02</Literal></AnnotationAssertion>'
        f'<SubAnnotationPropertyOf><AnnotationProperty IRI="{IAO_NOTE}"/>'
        f'<AnnotationProperty IRI="{RDFS_LABEL}"/></SubAnnotationPropertyOf>',
        attrs=f' xml:base="{ONTO}" ontologyIRI="{ONTO}" versionIRI="{ONTO}/1.0"',
    )
    root = _root(owx)
    assert kof.strip_header_and_annotations(root) == 4
    assert root.attrib == {}
    tags = [kof._local(e.tag) for e in root.iter()]
    for gone in ("Annotation", "AnnotationAssertion", "SubAnnotationPropertyOf", "Literal"):
        assert gone not in tags
    assert tags.count("SubClassOf") == 1  # the logical axiom itself survives


def test_drops_declarations_of_builtin_iris_only():
    owx = _owx(
        f'<Declaration><Datatype IRI="{XSD_DATE}"/></Declaration>'
        f'<Declaration><Class IRI="{OWL}Thing"/></Declaration>'
        f'<Declaration><Class IRI="{A}"/></Declaration>'
        f'<SubClassOf><Class IRI="{A}"/><Class IRI="{OWL}Thing"/></SubClassOf>'
    )
    root = _root(owx)
    assert kof.drop_builtin_declarations(root) == 2
    decls = [kof._resolve(next(iter(d)), {}) for d in root if kof._local(d.tag) == "Declaration"]
    assert decls == [A]
    assert sum(1 for e in root if kof._local(e.tag) == "SubClassOf") == 1


def test_expand_prefixes_rewrites_abbreviations_and_drops_prefix_elements():
    owx = _owx(
        '<Declaration><Class abbreviatedIRI="ex:A"/></Declaration>'
        '<SubClassOf><Class abbreviatedIRI="ex:A"/><Class abbreviatedIRI="owl:Thing"/></SubClassOf>'
        '<SubClassOf><Class abbreviatedIRI="nope:X"/><Class IRI="http://ex/B"/></SubClassOf>',
        head=f'<Prefix name="ex" IRI="{ONTO}/"/>',
    )
    root = _root(owx)
    assert kof.expand_prefixes(root) == 3  # ex:A twice, owl:Thing via the standard prefix
    assert not [e for e in root if kof._local(e.tag) == "Prefix"]
    iris = [e.get("IRI") for e in root.iter() if e.get("IRI")]
    assert iris == [A, A, f"{OWL}Thing", "http://ex/B"]
    # An unknown prefix is left for km to report rather than guessed.
    assert [e.get("abbreviatedIRI") for e in root.iter() if e.get("abbreviatedIRI")] == ["nope:X"]


def test_prepare_strips_injects_and_round_trips():
    owx = _owx(f'<SubClassOf><Class IRI="{A}"/><Class IRI="{B}"/></SubClassOf>',
               attrs=f' ontologyIRI="{ONTO}" versionIRI="{ONTO}/1.0"')
    out, injected = kof.prepare_owx_for_km(owx)
    assert injected == [("Class", A), ("Class", B)]
    root = _root(out)
    assert root.tag == f"{{{OWL}}}Ontology"
    assert "ontologyIRI" not in root.attrib and "versionIRI" not in root.attrib
    assert kof.undeclared_entities(root) == []
    assert 'xmlns="http://www.w3.org/2002/07/owl#"' in out  # default ns kept, no ns0:


def test_prepare_escapes_iris():
    iri = 'http://ex/a?x=1&y="2"'
    owx = _owx('<SubClassOf><Class IRI="http://ex/a?x=1&amp;y=&quot;2&quot;"/>'
               f'<Class IRI="{B}"/></SubClassOf>')
    out, injected = kof.prepare_owx_for_km(owx)
    assert ("Class", iri) in injected
    assert kof.undeclared_entities(_root(out)) == []


def test_prepare_reports_nothing_when_fully_declared():
    owx = _owx(f'<Declaration><Class IRI="{A}"/></Declaration>'
               f'<SubClassOf><Class IRI="{A}"/><Class IRI="{OWL}Thing"/></SubClassOf>')
    _, injected = kof.prepare_owx_for_km(owx)
    assert injected == []


def test_prepare_leaves_malformed_input_untouched():
    bad = "<Ontology><SubClassOf>"
    assert kof.prepare_owx_for_km(bad) == (bad, [])


# ── end-to-end through KmBackend (needs pyoxigraph + pyhornedowl + km) ───────────

def _km_backend():
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("pyhornedowl")
    if shutil.which("km") is None:
        pytest.skip("km binary not on PATH")
    from km_backend import KmBackend
    return KmBackend()


def _decl(iri: str) -> str:
    return f"<{iri}> <{RDF_TYPE}> <{OWL}Class> .\n"


def test_km_returns_full_iris_when_classes_extend_the_ontology_iri():
    """Classes under the ontology IRI (Pizza's layout). km mangles IRIs that
    start with the ontology IRI unless the header IRIs are stripped: km v1.3.0
    returned '/A'-style IRIs, km v1.5.3 failed to parse its own output."""
    backend = _km_backend()
    nt = (f"<{ONTO}> <{RDF_TYPE}> <{OWL}Ontology> .\n"
          f"<{ONTO}> <{OWL}versionIRI> <{ONTO}/1.0> .\n"
          + _decl(A) + _decl(B) + _decl(C)
          + f"<{A}> <{RDFS_SUB}> <{B}> .\n<{B}> <{RDFS_SUB}> <{C}> .\n")
    result = backend.classify_ntriples(nt, "test-km-onto-iri")
    assert result.superclasses.get(A) == [C]
    every_iri = set(result.superclasses) | {o for v in result.superclasses.values() for o in v}
    assert all(i.startswith("http://") for i in every_iri)


def test_km_ignores_annotations_with_non_owl2_datatypes():
    """OBO-style metadata: an xsd:date literal (not in the OWL 2 datatype map)
    on the ontology and on a class. km >= v1.4.4 rejects such literals unless
    annotations are stripped; annotations have no logical meaning."""
    backend = _km_backend()
    nt = (f"<{ONTO}> <{RDF_TYPE}> <{OWL}Ontology> .\n"
          f'<{ONTO}> <{DC_DATE}> "2025-06-02"^^<{XSD_DATE}> .\n'
          f"<{DC_DATE}> <{RDF_TYPE}> <{OWL}AnnotationProperty> .\n"
          + _decl(A) + _decl(B) + _decl(C)
          + f'<{A}> <{DC_DATE}> "2025-06-02"^^<{XSD_DATE}> .\n'
          + f"<{A}> <{RDFS_SUB}> <{B}> .\n<{B}> <{RDFS_SUB}> <{C}> .\n")
    result = backend.classify_ntriples(nt, "test-km-xsd-date")
    assert result.superclasses.get(A) == [C]


def test_km_classifies_undeclared_classes_after_injection():
    """A ⊑ B ⊑ C with no owl:Class declarations: km >= v1.4.4 rejects this
    ('used as Class but has no matching declaration') unless declarations are
    injected. The inferred A ⊑ C must come back and the repair be reported."""
    backend = _km_backend()
    nt = f"<{A}> <{RDFS_SUB}> <{B}> .\n<{B}> <{RDFS_SUB}> <{C}> .\n"
    result = backend.classify_ntriples(nt, "test-km-undeclared")
    assert result.superclasses.get(A) == [C]
    assert result.repairs == {"injected_km_declarations": 3}


def test_km_classifies_with_undeclared_obo_annotation_property():
    backend = _km_backend()
    nt = (_decl(A) + _decl(B)
          + f"<{A}> <{RDFS_SUB}> <{B}> .\n"
          + f'<{A}> <{IAO_NOTE}> "note" .\n')
    result = backend.classify_ntriples(nt, "test-km-obo-annotation")
    assert result.direct_superclasses.get(A) == [B]


def test_km_fully_declared_input_reports_no_repair():
    backend = _km_backend()
    nt = (_decl(A) + _decl(B) + _decl(C)
          + f"<{A}> <{RDFS_SUB}> <{B}> .\n<{B}> <{RDFS_SUB}> <{C}> .\n")
    result = backend.classify_ntriples(nt, "test-km-declared")
    assert result.superclasses.get(A) == [C]
    assert result.repairs == {}


def test_km_classifies_unqualified_cardinality_on_data_property():
    """IAO's shape: C ⊑ ≥1 d with d an owl:DatatypeProperty and no qualifier.
    The OWL 2 RDF mapping makes that DataMinCardinality; py-horned-owl < 2.0
    read it as ObjectMinCardinality(1 d owl:Thing), so km saw d as both a data
    and an object property and rejected the ontology."""
    backend = _km_backend()
    d = "http://ex/d"
    nt = (_decl(A) + _decl(B) + _decl(C)
          + f"<{d}> <{RDF_TYPE}> <{OWL}DatatypeProperty> .\n"
          + f"<{A}> <{RDFS_SUB}> <{B}> .\n<{B}> <{RDFS_SUB}> <{C}> .\n"
          + f"<{A}> <{RDFS_SUB}> _:r .\n"
          + f"_:r <{RDF_TYPE}> <{OWL}Restriction> .\n"
          + f"_:r <{OWL}onProperty> <{d}> .\n"
          + f'_:r <{OWL}minCardinality> "1"^^<http://www.w3.org/2001/XMLSchema#nonNegativeInteger> .\n')
    result = backend.classify_ntriples(nt, "test-km-data-cardinality")
    assert result.superclasses.get(A) == [C]


def test_km_ignores_declared_builtin_datatype():
    """OWL API output for OBO ontologies (IAO): xsd:date declared as an
    rdfs:Datatype because annotation literals use it. km >= v1.4.4 refuses
    declaring a reserved IRI; the declaration has no logical meaning."""
    backend = _km_backend()
    nt = (f"<{XSD_DATE}> <{RDF_TYPE}> <http://www.w3.org/2000/01/rdf-schema#Datatype> .\n"
          f"<{DC_DATE}> <{RDF_TYPE}> <{OWL}AnnotationProperty> .\n"
          + _decl(A) + _decl(B) + _decl(C)
          + f'<{A}> <{DC_DATE}> "2025-06-02"^^<{XSD_DATE}> .\n'
          + f"<{A}> <{RDFS_SUB}> <{B}> .\n<{B}> <{RDFS_SUB}> <{C}> .\n")
    result = backend.classify_ntriples(nt, "test-km-builtin-datatype")
    assert result.superclasses.get(A) == [C]


def test_backend_feeds_km_functional_syntax_with_full_iris(monkeypatch):
    """km <= v1.6.5 routes OWL/XML with DL-safe rules to a slow route (IAO:
    1,238 s vs ~1 s as functional syntax, km #7), and echoes prefixed names
    back (km #8). The backend must hand km prefix-free functional syntax.
    Runs without the km binary: subprocess.run is replaced."""
    pytest.importorskip("pyoxigraph")
    pytest.importorskip("pyhornedowl")
    import json
    import subprocess

    from km_backend import KmBackend

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        with open(cmd[-1]) as fh:
            seen["input"] = fh.read()
        out = {"consistent": True, "subsumptions": [[A, B], [A, C], [B, C]],
               "unsatisfiable": [], "dropped": 0}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    nt = (f"<{ONTO}> <{RDF_TYPE}> <{OWL}Ontology> .\n"
          f"<{A}> <{RDFS_SUB}> <{B}> .\n<{B}> <{RDFS_SUB}> <{C}> .\n")
    result = KmBackend().classify_ntriples(nt, "test-km-functional", {"route": "auto"})

    cmd = seen["cmd"]
    assert cmd[1:6] == ["classify", "--route", "auto", "--format", "functional"]
    assert cmd[-1].endswith(".ofn")
    text = seen["input"]
    assert text.lstrip().startswith("Ontology(")
    assert "Prefix(" not in text
    assert f"SubClassOf(<{A}> <{B}>)" in text
    assert ONTO + ">" not in text  # header IRI stripped (km #6)
    assert result.superclasses.get(A) == [C]
