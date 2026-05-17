"""Unit tests for the MOS lark parser."""
import pytest

from ontoexplorer.modules.search.mos_parser import (
    ParseError,
    parse,
    And, Or, Not,
    NamedClass,
    SomeValuesFrom, AllValuesFrom, HasValue, HasSelf,
    MinCardinality, MaxCardinality, ExactCardinality,
)


def test_parse_quoted_label():
    node = parse("'cell death'")
    assert isinstance(node, NamedClass)
    assert node.ref == "cell death"
    assert node.curie is None


def test_parse_quoted_label_with_curie():
    node = parse("'cell death (GO:0008219)'")
    assert isinstance(node, NamedClass)
    assert node.ref == "cell death"
    assert node.curie == "GO:0008219"


def test_parse_curie_direct():
    node = parse("GO:0008219")
    assert isinstance(node, NamedClass)
    assert node.ref == "GO:0008219"
    assert node.curie is None


def test_parse_full_iri():
    node = parse("<http://purl.obolibrary.org/obo/GO_0008219>")
    assert isinstance(node, NamedClass)
    assert node.ref == "http://purl.obolibrary.org/obo/GO_0008219"


def test_parse_and():
    node = parse("'Cell' and 'Nucleus'")
    assert isinstance(node, And)
    assert isinstance(node.left, NamedClass)
    assert isinstance(node.right, NamedClass)


def test_parse_or():
    node = parse("'Disease' or 'Disorder'")
    assert isinstance(node, Or)


def test_parse_not():
    node = parse("not 'Neuron'")
    assert isinstance(node, Not)
    assert isinstance(node.operand, NamedClass)


def test_parse_some_values_from():
    node = parse("'hasPart' some 'Nucleus'")
    assert isinstance(node, SomeValuesFrom)
    assert isinstance(node.property_ref, NamedClass)
    assert isinstance(node.filler, NamedClass)


def test_parse_only():
    node = parse("'hasPart' only 'Cell'")
    assert isinstance(node, AllValuesFrom)


def test_parse_min_cardinality():
    node = parse("'hasPart' min 2 'Protein'")
    assert isinstance(node, MinCardinality)
    assert node.cardinality == 2


def test_parse_max_cardinality():
    node = parse("'hasPart' max 3 'Gene'")
    assert isinstance(node, MaxCardinality)
    assert node.cardinality == 3


def test_parse_exactly_cardinality():
    node = parse("'hasPart' exactly 1 'Nucleus'")
    assert isinstance(node, ExactCardinality)
    assert node.cardinality == 1


def test_parse_has_self():
    node = parse("'loves' Self")
    assert isinstance(node, HasSelf)


def test_parse_has_value():
    node = parse("'hasColor' value GO:0000001")
    assert isinstance(node, HasValue)


def test_parse_nested():
    node = parse("'Cell' and 'hasPart' some ('Nucleus' or 'Mitochondrion')")
    assert isinstance(node, And)
    assert isinstance(node.right, SomeValuesFrom)
    assert isinstance(node.right.filler, Or)


def test_parse_error_raises():
    with pytest.raises(ParseError):
        parse("and and and")


def test_parse_error_unclosed_quote():
    with pytest.raises(ParseError):
        parse("'cell death")


from ontoexplorer.modules.search.mos_parser import partial_parse, PartialParseResult


def test_partial_parse_open_quote_at_start():
    result = partial_parse("'cell d", 7)
    assert result.token_type == "OPEN_QUOTE"
    assert result.partial == "cell d"


def test_partial_parse_open_quote_mid_expression():
    result = partial_parse("'Cell' and 'nuc", 15)
    assert result.token_type == "OPEN_QUOTE"
    assert result.partial == "nuc"


def test_partial_parse_closed_quote_expect_keyword():
    result = partial_parse("'Cell'", 6)
    assert result.token_type == "EXPECT_KEYWORD"
    assert result.partial == ""


def test_partial_parse_after_some_expect_entity():
    result = partial_parse("'hasPart' some ", 15)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_after_min_expect_int():
    result = partial_parse("'hasPart' min ", 14)
    assert result.token_type == "EXPECT_INT"
    assert result.partial == ""


def test_partial_parse_after_int_expect_entity():
    result = partial_parse("'hasPart' min 2 ", 16)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_after_not_expect_entity():
    result = partial_parse("not ", 4)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_empty_input():
    result = partial_parse("", 0)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_after_and_expect_entity():
    result = partial_parse("'Cell' and ", 11)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


# ── Additional partial_parse state coverage (drift-catching) ─────────────────

def test_partial_parse_after_close_paren_expect_keyword():
    result = partial_parse("('Cell')", 7)
    assert result.token_type == "EXPECT_KEYWORD"
    assert result.partial == ""


def test_partial_parse_after_open_paren_expect_entity():
    result = partial_parse("(", 1)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_after_curie_expect_keyword():
    result = partial_parse("GO:0008219 ", 11)
    assert result.token_type == "EXPECT_KEYWORD"
    assert result.partial == ""


def test_partial_parse_after_full_iri_expect_keyword():
    result = partial_parse("<http://example.org/Cell> ", 26)
    assert result.token_type == "EXPECT_KEYWORD"
    assert result.partial == ""


def test_partial_parse_word_in_progress_returns_partial():
    result = partial_parse("'Cell' and nuc", 14)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == "nuc"
    assert result.token_start == 11


def test_partial_parse_hyphen_in_bare_word_breaks_token():
    # Grammar's BARE_LABEL has no hyphens; tokenizer must agree and break at the hyphen.
    # "some-prop" → tokenizes as WORD("some") then skips "-" then WORD("prop")
    # Last completed token is WORD("prop"), so still EXPECT_KEYWORD (word + space would be)
    # Without trailing space the word is still in progress → EXPECT_ENTITY with partial "prop"
    result = partial_parse("some-prop", 9)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == "prop"


def test_partial_parse_and_not_expect_entity():
    result = partial_parse("'Cell' and not ", 15)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_nested_paren_not():
    result = partial_parse("('Cell' and (not ", 17)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_token_start_open_quote():
    result = partial_parse("'Cell' and 'nuc", 15)
    assert result.token_type == "OPEN_QUOTE"
    assert result.partial == "nuc"
    assert result.token_start == 12  # index after the opening quote


def test_partial_parse_or_expect_entity():
    result = partial_parse("'Cell' or ", 10)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_curie_treated_as_complete():
    # CURIE tokens are always classified as complete (unlike bare WORDs which have
    # in-progress detection). Typing GO:000 with no trailing space returns EXPECT_KEYWORD,
    # not EXPECT_ENTITY — so partial-CURIE completions are not offered.
    result = partial_parse("GO:000", 6)
    assert result.token_type == "EXPECT_KEYWORD"
    assert result.partial == ""
