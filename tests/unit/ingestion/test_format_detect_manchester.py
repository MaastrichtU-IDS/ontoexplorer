"""Manchester Syntax must be identifiable from bytes alone.

`.omn` uploads already resolve by file extension, but pasted content carries no
filename, so detection falls through to byte sniffing — and Manchester had no
signature there. Pasting a Manchester ontology failed with "Cannot determine
ontology format", with no way to force it because the paste form's Format
selector was never actually consulted (it was sent as a Content-Type and no
value in it is a real MIME type).

The signatures must not collide with the neighbouring syntaxes:
  Manchester  `Prefix: : <…>`   / `Ontology: <…>`  / `Class: :C`
  Functional  `Prefix(:=<…>)`   / `Ontology(<…>`
  Turtle      `@prefix …`       / `PREFIX …` (SPARQL-style, uppercase)
"""
import pytest

from ontoexplorer.modules.ingestion.format_detect import OntologyFormat, detect_format

MANCHESTER = (
    b"Prefix: : <http://example.org/o#>\n"
    b"Ontology: <http://example.org/o>\n"
    b"Class: :Person\n"
)
MANCHESTER_NO_PREFIX = b"Ontology: <http://example.org/o>\nClass: :Person\n"
MANCHESTER_BARE_CLASS = b"Class: :Person\n    SubClassOf: :Agent\n"
FUNCTIONAL = (
    b"Prefix(:=<http://example.org/o#>)\n"
    b"Ontology(<http://example.org/o>\n"
    b"  Declaration(Class(:Person)))\n"
)
TURTLE_AT = b"@prefix : <http://example.org/o#> .\n:Person a owl:Class .\n"
TURTLE_SPARQL = b"PREFIX : <http://example.org/o#>\n:Person a owl:Class .\n"


@pytest.mark.parametrize("data", [MANCHESTER, MANCHESTER_NO_PREFIX, MANCHESTER_BARE_CLASS])
def test_manchester_detected_from_bytes(data):
    assert detect_format(data) is OntologyFormat.MANCHESTER


def test_functional_still_detected_from_bytes():
    """`Prefix(` must not be captured by the new `Prefix:` signature."""
    assert detect_format(FUNCTIONAL) is OntologyFormat.OWL_FUNCTIONAL


@pytest.mark.parametrize("data", [TURTLE_AT, TURTLE_SPARQL])
def test_turtle_still_detected_from_bytes(data):
    assert detect_format(data) is OntologyFormat.TURTLE


def test_leading_blank_lines_do_not_defeat_detection():
    assert detect_format(b"\n\n  " + MANCHESTER) is OntologyFormat.MANCHESTER


def test_extension_still_wins_over_bytes():
    """A .ofn file holding Manchester-looking text is still trusted as OFN."""
    assert detect_format(MANCHESTER, filename="o.ofn") is OntologyFormat.OWL_FUNCTIONAL
