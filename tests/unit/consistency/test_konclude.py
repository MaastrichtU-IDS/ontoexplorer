from pathlib import Path

import pytest

from ontoexplorer.modules.consistency.konclude import (
    KoncludeCrashed,
    KoncludeResult,
    KoncludeUnavailable,
    _parse_consistency_verdict,
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


_KONCLUDE_OOM_TRUNCATED_STDOUT = (
    "{info} 14:52:34:084 >> Starting Konclude ...\n"
    "{info} 14:52:34:084 >> Konclude - Uni Ulm Parallel Reasoner\n"
    "{info} 14:52:34:086 >> Starting consistency checking for '/tmp/cl-asserted.nt'.\n"
    "{info} 14:52:34:088 >> Reasoner initialized with 1 processing unit(s).\n"
    "{info} 14:52:39:055 >> Query 'UnnamedConsistencyQuery' processed in '0' ms.\n"
    "{info} 14:52:39:056 >> Preprocessing ontology 'http://konclude.com/test/kb'.\n"
    "{info} 14:52:40:781 >> Finished preprocessing in 1725 ms for ontology 'http://konclude.com/test/kb'.\n"
    "{info} 14:52:40:781 >> Precomputing ontology 'http://konclude.com/test/kb', expressiveness 'SROIQ'.\n"
)


def test_parse_verdict_recognises_consistent_line():
    assert _parse_consistency_verdict(
        "{info} >> Ontology '/x.nt' is consistent.\n", returncode=0, stderr=""
    ) is True


def test_parse_verdict_recognises_inconsistent_line():
    assert _parse_consistency_verdict(
        "{info} >> Ontology '/x.nt' is inconsistent.\n", returncode=0, stderr=""
    ) is False


def test_parse_verdict_raises_crashed_on_oom_kill():
    """Regression: Konclude OOM-killed (exit 137) mid-SROIQ-precomputation
    used to be silently classified as 'inconsistent'. It must now raise."""
    with pytest.raises(KoncludeCrashed):
        _parse_consistency_verdict(_KONCLUDE_OOM_TRUNCATED_STDOUT, returncode=-9, stderr="")


def test_parse_verdict_raises_crashed_on_empty_output():
    with pytest.raises(KoncludeCrashed):
        _parse_consistency_verdict("", returncode=137, stderr="Killed")


def test_missing_binary_raises_konclude_unavailable(tmp_path, monkeypatch):
    fixture = _write_fixture(tmp_path, "ok.owl", CONSISTENT_OWL)
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(KoncludeUnavailable):
        run_konclude_consistency(fixture, timeout_seconds=10, konclude_cmd="this-binary-does-not-exist-xyz")
