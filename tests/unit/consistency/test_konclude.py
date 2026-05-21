from pathlib import Path

import pytest

from ontoexplorer.modules.consistency.konclude import (
    KoncludeResult,
    KoncludeUnavailable,
    _parse_unsatisfiable_classes,
    run_konclude_consistency,
)


# Sample Konclude classify-output (OWL/XML functional-style with EquivalentClasses)
# matching what Konclude v0.7.0 actually emits.
KONCLUDE_CLASSIFY_OWL_XML = """<?xml version="1.0"?>
<Ontology xmlns="http://www.w3.org/2002/07/owl#"
          xml:base="http://example.org/bad"
          ontologyIRI="http://example.org/bad">
    <Declaration>
        <Class IRI="http://www.w3.org/2002/07/owl#Nothing"/>
    </Declaration>
    <Declaration>
        <Class IRI="http://example.org/bad#MineralAnimal"/>
    </Declaration>
    <Declaration>
        <Class IRI="http://example.org/bad#SuperMineralAnimal"/>
    </Declaration>
    <Declaration>
        <Class IRI="http://example.org/bad#Animal"/>
    </Declaration>
    <EquivalentClasses>
        <Class IRI="http://www.w3.org/2002/07/owl#Nothing"/>
        <Class IRI="http://example.org/bad#MineralAnimal"/>
        <Class IRI="http://example.org/bad#SuperMineralAnimal"/>
    </EquivalentClasses>
    <SubClassOf>
        <Class IRI="http://example.org/bad#Animal"/>
        <Class IRI="http://www.w3.org/2002/07/owl#Thing"/>
    </SubClassOf>
</Ontology>
"""


def test_parser_extracts_unsat_classes_from_owl_xml_equivalent_classes_form(tmp_path):
    """Konclude v0.7.0 emits unsat classes via <EquivalentClasses> grouping with owl:Nothing.

    All other Class IRIs in that group must be returned as unsatisfiable; the
    owl:Nothing IRI itself must NOT appear in the result.
    """
    classify_path = tmp_path / "classified.owl"
    classify_path.write_text(KONCLUDE_CLASSIFY_OWL_XML)
    unsat = _parse_unsatisfiable_classes(classify_path)
    assert unsat == [
        "http://example.org/bad#MineralAnimal",
        "http://example.org/bad#SuperMineralAnimal",
    ]


def test_parser_ignores_equivalent_classes_groups_without_nothing(tmp_path):
    """A regular EquivalentClasses axiom (no owl:Nothing involved) must not be flagged."""
    classify_path = tmp_path / "classified.owl"
    classify_path.write_text("""<?xml version="1.0"?>
<Ontology xmlns="http://www.w3.org/2002/07/owl#" xml:base="http://example.org/ok">
    <EquivalentClasses>
        <Class IRI="http://example.org/ok#Mammal"/>
        <Class IRI="http://example.org/ok#WarmBloodedVertebrate"/>
    </EquivalentClasses>
</Ontology>
""")
    assert _parse_unsatisfiable_classes(classify_path) == []


# Trivial consistent fixture: empty ontology
CONSISTENT_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xml:base="http://example.org/ok">
  <owl:Ontology rdf:about="http://example.org/ok"/>
  <owl:Class rdf:about="http://example.org/ok#A"/>
</rdf:RDF>
"""

# Inconsistent fixture: A and B are disjoint, but C is both A and B
INCONSISTENT_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xml:base="http://example.org/bad">
  <owl:Ontology rdf:about="http://example.org/bad"/>
  <owl:Class rdf:about="http://example.org/bad#A">
    <owl:disjointWith rdf:resource="http://example.org/bad#B"/>
  </owl:Class>
  <owl:Class rdf:about="http://example.org/bad#B"/>
  <owl:Class rdf:about="http://example.org/bad#C">
    <rdfs:subClassOf rdf:resource="http://example.org/bad#A"/>
    <rdfs:subClassOf rdf:resource="http://example.org/bad#B"/>
  </owl:Class>
</rdf:RDF>
"""


def _write_fixture(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def test_consistent_ontology_classified_as_consistent(tmp_path):
    fixture = _write_fixture(tmp_path, "ok.owl", CONSISTENT_OWL)
    try:
        result = run_konclude_consistency(fixture, timeout_seconds=60)
    except KoncludeUnavailable:
        pytest.skip("Konclude binary not installed in this environment")
    assert isinstance(result, KoncludeResult)
    assert result.consistent is True
    assert result.unsatisfiable_class_iris == []


def test_inconsistent_ontology_yields_unsatisfiable_classes(tmp_path):
    fixture = _write_fixture(tmp_path, "bad.owl", INCONSISTENT_OWL)
    try:
        result = run_konclude_consistency(fixture, timeout_seconds=60)
    except KoncludeUnavailable:
        pytest.skip("Konclude binary not installed in this environment")
    # `C` is unsatisfiable because it's subClass of two disjoint classes.
    # Konclude flags this either as global inconsistency OR as `C subClassOf owl:Nothing`.
    assert (result.consistent is False) or (
        "http://example.org/bad#C" in result.unsatisfiable_class_iris
    )


def test_missing_binary_raises_konclude_unavailable(tmp_path, monkeypatch):
    fixture = _write_fixture(tmp_path, "ok.owl", CONSISTENT_OWL)
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(KoncludeUnavailable):
        run_konclude_consistency(fixture, timeout_seconds=10, konclude_cmd="this-binary-does-not-exist-xyz")
