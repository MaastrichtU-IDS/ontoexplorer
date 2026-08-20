"""An explicit format must be honoured, and an unrecognised one must be refused.

The paste form's Format selector never took effect: it was sent as the request's
`content_type`, and none of its values ("turtle", "obo", …) are MIME types, so
`_MIME_MAP` never matched and detection silently fell through to byte sniffing.
Choosing "obo" for Turtle content still ingested it as Turtle.

`parse_format` is the single place that turns whatever a caller supplies —
a format key, a friendly alias, or a real MIME type — into an OntologyFormat,
and rejects anything else rather than ignoring it.
"""
import pytest

from ontoexplorer.modules.ingestion.format_detect import (
    OntologyFormat,
    parse_format,
)


def test_none_means_auto_detect():
    assert parse_format(None) is None
    assert parse_format("") is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("ttl", OntologyFormat.TURTLE),
        ("omn", OntologyFormat.MANCHESTER),
        ("ofn", OntologyFormat.OWL_FUNCTIONAL),
        ("obo", OntologyFormat.OBO),
        ("rdf", OntologyFormat.RDF_XML),
        ("owl", OntologyFormat.OWL_XML),
    ],
)
def test_canonical_format_keys(value, expected):
    assert parse_format(value) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        # The labels the paste form used to send, kept working for API callers.
        ("turtle", OntologyFormat.TURTLE),
        ("n-triples", OntologyFormat.N_TRIPLES),
        ("json-ld", OntologyFormat.JSON_LD),
        ("manchester", OntologyFormat.MANCHESTER),
        ("functional", OntologyFormat.OWL_FUNCTIONAL),
        ("TURTLE", OntologyFormat.TURTLE),
        ("  turtle  ", OntologyFormat.TURTLE),
    ],
)
def test_aliases(value, expected):
    assert parse_format(value) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("text/turtle", OntologyFormat.TURTLE),
        ("application/rdf+xml", OntologyFormat.RDF_XML),
    ],
)
def test_real_mime_types_accepted(value, expected):
    assert parse_format(value) is expected


def test_unknown_format_is_refused_not_ignored():
    with pytest.raises(ValueError, match="Unknown ontology format"):
        parse_format("not-a-format")


def test_error_names_the_accepted_values():
    """The message has to be actionable — it is surfaced to the caller as a 422."""
    with pytest.raises(ValueError) as exc:
        parse_format("nope")
    assert "ttl" in str(exc.value) and "omn" in str(exc.value)
