from pathlib import Path

import pytest

from ontoexplorer.modules.consistency.robot_explain import (
    RobotExplainUnavailable,
    explain_unsatisfiability,
)


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


def test_explain_returns_per_class_dict(tmp_path):
    fixture = tmp_path / "bad.owl"
    fixture.write_text(INCONSISTENT_OWL)
    try:
        out = explain_unsatisfiability(fixture, timeout_seconds=120)
    except RobotExplainUnavailable:
        pytest.skip("ROBOT not installed")
    assert isinstance(out, dict)
    assert "http://example.org/bad#C" in out
    axioms = out["http://example.org/bad#C"]
    assert len(axioms) >= 3  # header + at least 3 justification bullets, or 3 bullets if header dropped


def test_explain_axiom_contains_typed_tokens(tmp_path):
    fixture = tmp_path / "bad.owl"
    fixture.write_text(INCONSISTENT_OWL)
    try:
        out = explain_unsatisfiability(fixture, timeout_seconds=120)
    except RobotExplainUnavailable:
        pytest.skip("ROBOT not installed")
    for axiom in out["http://example.org/bad#C"]:
        for tok in axiom:
            assert tok.get("t") in ("text", "iri")
            if tok["t"] == "iri":
                assert "iri" in tok and "label" in tok


def test_missing_robot_raises(tmp_path):
    fixture = tmp_path / "bad.owl"
    fixture.write_text(INCONSISTENT_OWL)
    with pytest.raises(RobotExplainUnavailable):
        explain_unsatisfiability(fixture, robot_cmd="this-binary-does-not-exist-xyz")
