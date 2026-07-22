"""Unit tests for the MOS lark parser."""
import pytest

from ontoexplorer.modules.search.mos_parser import (
    ParseError,
    parse,
    And, Or, Not,
    NamedClass,
    SomeValuesFrom, AllValuesFrom, HasValue, HasSelf,
    MinCardinality, MaxCardinality, ExactCardinality,
    InverseRestriction,
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


def test_parse_inverse_some():
    node = parse("inverse 'has part' some 'cell'")
    assert isinstance(node, InverseRestriction)
    assert node.kind == "some"
    assert isinstance(node.property_ref, NamedClass)
    assert node.property_ref.ref == "has part"
    assert isinstance(node.holder_ref, NamedClass)
    assert node.holder_ref.ref == "cell"


def test_parse_inverse_only():
    node = parse("inverse 'has part' only 'cell'")
    assert isinstance(node, InverseRestriction)
    assert node.kind == "only"


def test_parse_inverse_value():
    node = parse("inverse 'has part' value 'cell'")
    assert isinstance(node, InverseRestriction)
    assert node.kind == "value"


def test_parse_inverse_min():
    node = parse("inverse 'has part' min 2 'cell'")
    assert isinstance(node, InverseRestriction)
    assert node.kind == "min"
    assert node.cardinality == 2
    assert node.holder_ref.ref == "cell"


def test_parse_inverse_max():
    node = parse("inverse 'has part' max 1 'cell'")
    assert isinstance(node, InverseRestriction)
    assert node.kind == "max"
    assert node.cardinality == 1


def test_parse_inverse_exactly():
    node = parse("inverse 'has part' exactly 3 'cell'")
    assert isinstance(node, InverseRestriction)
    assert node.kind == "exactly"
    assert node.cardinality == 3


def test_parse_inverse_some_has_no_cardinality():
    node = parse("inverse 'has part' some 'cell'")
    assert node.cardinality is None


def test_parse_inverse_with_curie_and_bare():
    node = parse("inverse BFO:0000050 some cell")
    assert isinstance(node, InverseRestriction)
    assert node.property_ref.ref == "BFO:0000050"
    assert node.holder_ref.ref == "cell"


def test_parse_inverse_nested_in_conjunction():
    node = parse("'cell' and (inverse 'has part' some 'organelle')")
    assert isinstance(node, And)
    assert isinstance(node.right, InverseRestriction)


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


from ontoexplorer.modules.search.mos_parser import partial_parse


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


def test_partial_parse_captures_restriction_property_after_some():
    r = partial_parse("'has part' some ", len("'has part' some "))
    assert r.token_type == "EXPECT_ENTITY"
    assert r.partial == ""
    assert r.restriction_property == "has part"


def test_partial_parse_captures_restriction_property_after_cardinality():
    q = "'has part' min 1 "
    r = partial_parse(q, len(q))
    assert r.token_type == "EXPECT_ENTITY"
    assert r.restriction_property == "has part"


def test_partial_parse_no_restriction_property_after_boolean():
    q = "'cell' and "
    r = partial_parse(q, len(q))
    assert r.token_type == "EXPECT_ENTITY"
    assert r.restriction_property is None


def test_partial_parse_captures_restriction_keyword_value():
    q = "'has part' value "
    r = partial_parse(q, len(q))
    assert r.token_type == "EXPECT_ENTITY"
    assert r.restriction_property == "has part"
    assert r.restriction_keyword == "value"


def test_partial_parse_captures_restriction_keyword_some():
    q = "'has part' some "
    r = partial_parse(q, len(q))
    assert r.restriction_keyword == "some"


def test_partial_parse_captures_restriction_keyword_cardinality():
    q = "'has part' min 1 "
    r = partial_parse(q, len(q))
    assert r.restriction_keyword == "min"


def test_partial_parse_no_restriction_keyword_after_boolean():
    q = "'cell' and "
    r = partial_parse(q, len(q))
    assert r.restriction_keyword is None


def test_partial_parse_after_inverse_expects_property():
    q = "inverse "
    r = partial_parse(q, len(q))
    assert r.token_type == "EXPECT_ENTITY"
    assert r.after_inverse is True


def test_partial_parse_after_inverse_property_expects_keyword():
    q = "inverse 'has part' "
    r = partial_parse(q, len(q))
    assert r.token_type == "EXPECT_KEYWORD"
    assert r.prev_entity == "has part"
    assert r.after_inverse is False
