"""IRIs are interpolated into SPARQL all over this codebase; this is the guard."""

import pytest

from ontoexplorer.clients.sparql_iri import UnsafeIri, iri_term, is_safe_iri


@pytest.mark.parametrize("iri", [
    "http://www.w3.org/2004/02/skos/core#Concept",
    "urn:ontology:abc:def",
    "http://purl.obolibrary.org/obo/GO_0008150",
    "http://example.org/x?a=1&b=2",
])
def test_ordinary_iris_pass_through(iri):
    assert is_safe_iri(iri)
    assert iri_term(iri) == f"<{iri}>"


@pytest.mark.parametrize("payload", [
    "urn:x> ?p ?o } UNION { GRAPH ?g { ?s ?p ?o } #",   # escape the graph scope
    "urn:x> } }; DROP SILENT GRAPH <urn:meta> ; #",      # the 0.3.85 update shape
    "urn:x> { SERVICE <http://collector.invalid/> } #",  # federation gadget
    "urn:x\n?s ?p ?o",                                   # newline
    "urn:x with space",
    'urn:x"quote',
    "urn:x{brace}",
    "urn:x\\backslash",
    "",
])
def test_injection_shapes_are_refused(payload):
    assert not is_safe_iri(payload)
    with pytest.raises(UnsafeIri):
        iri_term(payload)


def test_rejection_message_does_not_echo_the_whole_payload():
    """Error text reaches clients; keep it bounded."""
    with pytest.raises(UnsafeIri) as e:
        iri_term("urn:" + "A" * 5000 + ">")
    assert len(str(e.value)) < 200
