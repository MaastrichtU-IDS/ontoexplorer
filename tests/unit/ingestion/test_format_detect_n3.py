"""N3 must be identifiable so it can be parsed as Turtle.

Every LOV distribution is served with content-type `text/n3`, which matched no
MIME entry, and `.n3` was absent from the extension map — so detection fell
through to byte sniffing. Sniffing only matches a signature at the start of the
content, so any N3 file opening with a blank node (`_:genid1 …`) or a bare
subject IRI (`<http://…>`) instead of `@prefix` failed with "Cannot determine
ontology format". These are Turtle-compatible, so they resolve to TURTLE.
"""
import pytest

from ontoexplorer.modules.ingestion.format_detect import OntologyFormat, detect_format

# The two opening shapes that defeated byte sniffing (real LOV vocabularies:
# IIoT opens with a blank node, rdft with a bare subject IRI).
N3_BLANK_NODE = b"_:genid1 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://x> .\n"
N3_BARE_IRI = b"<http://www.w3.org/ns/rdftest> <http://purl.org/dc/terms/title> \"t\" .\n"


@pytest.mark.parametrize("data", [N3_BLANK_NODE, N3_BARE_IRI])
def test_text_n3_content_type_resolves_to_turtle(data):
    """content-type wins first: text/n3 → Turtle regardless of the opening bytes."""
    assert detect_format(data, content_type="text/n3; charset=utf-8") is OntologyFormat.TURTLE


@pytest.mark.parametrize("data", [N3_BLANK_NODE, N3_BARE_IRI])
def test_n3_extension_resolves_to_turtle(data):
    """A .n3 filename resolves to Turtle even when byte sniffing would fail."""
    assert detect_format(data, filename="vocab.n3") is OntologyFormat.TURTLE


def test_n3_without_type_or_extension_still_fails():
    """No content-type and no .n3 filename: a bare-IRI opening still can't be
    sniffed. The fix is the MIME/extension mapping, not new signatures."""
    with pytest.raises(ValueError):
        detect_format(N3_BARE_IRI)
