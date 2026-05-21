import pytest

from ontoexplorer.modules.sparql_starters.parser import (
    StarterDraft,
    detect_format,
    parse_json_library,
    parse_rq_with_metadata,
)


# ── detect_format ──────────────────────────────────────────────────────────

def test_detect_format_json_object():
    assert detect_format('{"starters": []}') == "json"


def test_detect_format_json_with_leading_whitespace():
    assert detect_format('\n  {"starters": []}') == "json"


def test_detect_format_rq_with_comment():
    assert detect_format("# @name foo\nSELECT * WHERE { ?s ?p ?o }") == "rq"


def test_detect_format_bare_sparql():
    assert detect_format("SELECT * WHERE { ?s ?p ?o }") == "rq"


def test_detect_format_empty_string_treated_as_rq():
    assert detect_format("") == "rq"


# ── parse_json_library ─────────────────────────────────────────────────────

def test_parse_json_library_minimal():
    text = '{"starters": [{"name": "n", "query_text": "SELECT *"}]}'
    drafts = parse_json_library(text)
    assert drafts == [StarterDraft(name="n", description=None, category=None, tags=[], query_text="SELECT *")]


def test_parse_json_library_full_fields():
    text = (
        '{"starters": [{'
        '"name": "All classes", "description": "desc", '
        '"category": "Exploration", "tags": ["owl", "class"], '
        '"query_text": "SELECT *"}]}'
    )
    drafts = parse_json_library(text)
    assert drafts == [StarterDraft(
        name="All classes",
        description="desc",
        category="Exploration",
        tags=["owl", "class"],
        query_text="SELECT *",
    )]


def test_parse_json_library_rejects_missing_starters_key():
    with pytest.raises(ValueError, match="starters"):
        parse_json_library('{"items": []}')


def test_parse_json_library_rejects_non_array_starters():
    with pytest.raises(ValueError, match="array"):
        parse_json_library('{"starters": "nope"}')


def test_parse_json_library_skips_entries_missing_name():
    text = '{"starters": [{"query_text": "X"}, {"name": "ok", "query_text": "Y"}]}'
    drafts = parse_json_library(text)
    assert len(drafts) == 1
    assert drafts[0].name == "ok"


def test_parse_json_library_skips_entries_missing_query_text():
    text = '{"starters": [{"name": "no query"}]}'
    assert parse_json_library(text) == []


def test_parse_json_library_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_json_library("not json")


# ── parse_rq_with_metadata ─────────────────────────────────────────────────

def test_parse_rq_with_only_name():
    text = "# @name Hello\nSELECT * WHERE { ?s ?p ?o }"
    draft = parse_rq_with_metadata(text)
    assert draft == StarterDraft(
        name="Hello", description=None, category=None, tags=[],
        query_text="SELECT * WHERE { ?s ?p ?o }",
    )


def test_parse_rq_with_full_metadata():
    text = (
        "# @name Subclasses\n"
        "# @description Replace <URI_HERE>.\n"
        "# @category Term lookup\n"
        "# @tags subclass, hierarchy\n"
        "\n"
        "SELECT ?s WHERE { ?s rdfs:subClassOf <URI_HERE> }"
    )
    draft = parse_rq_with_metadata(text)
    assert draft.name == "Subclasses"
    assert draft.description == "Replace <URI_HERE>."
    assert draft.category == "Term lookup"
    assert draft.tags == ["subclass", "hierarchy"]
    assert draft.query_text == "SELECT ?s WHERE { ?s rdfs:subClassOf <URI_HERE> }"


def test_parse_rq_tolerates_blank_lines_between_metadata():
    text = "# @name X\n\n# @category C\n\nSELECT *"
    draft = parse_rq_with_metadata(text)
    assert draft.name == "X"
    assert draft.category == "C"
    assert draft.query_text == "SELECT *"


def test_parse_rq_rejects_missing_name():
    with pytest.raises(ValueError, match="name"):
        parse_rq_with_metadata("# @category Foo\nSELECT *")


def test_parse_rq_ignores_unknown_metadata_keys():
    text = "# @name X\n# @author Bob\nSELECT *"
    draft = parse_rq_with_metadata(text)
    assert draft.name == "X"
    assert draft.query_text == "SELECT *"
