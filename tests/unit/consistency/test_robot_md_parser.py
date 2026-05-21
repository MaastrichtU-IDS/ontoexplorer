from ontoexplorer.modules.consistency.robot_md_parser import parse_robot_explanation_md


SAMPLE_MD = """## [C](http://example.org/bad#C) SubClassOf [Nothing](http://www.w3.org/2002/07/owl#Nothing) ##

  - [C](http://example.org/bad#C) SubClassOf [A](http://example.org/bad#A)
  - [C](http://example.org/bad#C) SubClassOf [B](http://example.org/bad#B)
  - [A](http://example.org/bad#A) DisjointWith [B](http://example.org/bad#B)

# Axiom Impact
## Axioms used 1 times
- [C](http://example.org/bad#C) SubClassOf [A](http://example.org/bad#A) [bad]

# Ontologies used:
- bad (http://example.org/bad)
"""


def test_parses_header_axiom_into_class_section():
    out = parse_robot_explanation_md(SAMPLE_MD)
    assert "http://example.org/bad#C" in out


def test_extracts_three_justification_bullets():
    out = parse_robot_explanation_md(SAMPLE_MD)
    axioms = out["http://example.org/bad#C"]
    assert len(axioms) == 3


def test_iri_and_text_tokens_in_first_axiom():
    out = parse_robot_explanation_md(SAMPLE_MD)
    first = out["http://example.org/bad#C"][0]  # "[C](...) SubClassOf [A](...)"
    assert len(first) == 3
    assert first[0] == {"t": "iri", "iri": "http://example.org/bad#C", "label": "C", "in_ontology": True}
    assert first[1]["t"] == "text"
    assert "SubClassOf" in first[1]["v"]
    assert first[2] == {"t": "iri", "iri": "http://example.org/bad#A", "label": "A", "in_ontology": True}


def test_stops_at_axiom_impact_section():
    out = parse_robot_explanation_md(SAMPLE_MD)
    # The `- [C](...) SubClassOf [A](...) [bad]` line under "Axiom Impact" must NOT be double-counted
    axioms = out["http://example.org/bad#C"]
    assert len(axioms) == 3, f"Expected 3, got {len(axioms)}: {axioms}"


def test_handles_trailing_robot_annotation_as_text():
    # `[bad]` without parens is NOT a markdown link; it stays as plain text
    line = """## [X](http://ex.org/X) SubClassOf [Y](http://ex.org/Y) ##

  - [X](http://ex.org/X) SubClassOf [Y](http://ex.org/Y) [bad]
"""
    out = parse_robot_explanation_md(line)
    axioms = out["http://ex.org/X"]
    assert len(axioms) == 1
    last_token = axioms[0][-1]
    assert last_token["t"] == "text"
    assert "[bad]" in last_token["v"]


def test_empty_input_returns_empty_dict():
    assert parse_robot_explanation_md("") == {}


def test_whitespace_only_input_returns_empty_dict():
    assert parse_robot_explanation_md("\n\n   \n") == {}


def test_empty_label_uses_iri_as_label():
    md = """## [C](http://example.org/bad#C) SubClassOf [Nothing](http://www.w3.org/2002/07/owl#Nothing) ##

  - [](http://example.org/anon) DisjointWith [C](http://example.org/bad#C)
"""
    out = parse_robot_explanation_md(md)
    axiom = out["http://example.org/bad#C"][0]
    assert axiom[0]["t"] == "iri"
    assert axiom[0]["iri"] == "http://example.org/anon"
    assert axiom[0]["label"] == "http://example.org/anon"


def test_multiple_class_sections_each_get_their_bullets():
    md = """## [C](http://ex.org/C) SubClassOf [Nothing](http://www.w3.org/2002/07/owl#Nothing) ##

  - [C](http://ex.org/C) SubClassOf [A](http://ex.org/A)

## [D](http://ex.org/D) SubClassOf [Nothing](http://www.w3.org/2002/07/owl#Nothing) ##

  - [D](http://ex.org/D) DisjointWith [E](http://ex.org/E)
"""
    out = parse_robot_explanation_md(md)
    assert set(out.keys()) == {"http://ex.org/C", "http://ex.org/D"}
    assert len(out["http://ex.org/C"]) == 1
    assert len(out["http://ex.org/D"]) == 1
