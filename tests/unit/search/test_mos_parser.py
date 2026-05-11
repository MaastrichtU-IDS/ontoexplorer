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
