"""The public SPARQL endpoints must not become a request-forgery primitive.

Both /sparql and /sparql/content are anonymous. SPARQL SERVICE makes the
evaluating process open an outbound connection to a host named in the query, and
NO_PROXY covers .svc.cluster.local, so an in-namespace target is dialled
directly rather than through egress-proxy. pyoxigraph exposes no switch to
disable federation and no parser to inspect, so this lexical guard is the only
in-process control on the Oxigraph side.
"""

import pytest

from ontoexplorer.api.sparql import _check_query_guard


def _blocked(query: str) -> bool:
    try:
        _check_query_guard(query)
        return False
    except ValueError:
        return True


@pytest.mark.parametrize("query", [
    "SELECT * WHERE { SERVICE <http://collector.invalid/> { ?s ?p ?o } }",
    "select * where { service <http://collector.invalid/> { ?s ?p ?o } }",
    "SELECT * WHERE { SERVICE SILENT <http://169.254.169.254/> { ?s ?p ?o } }",
])
def test_federation_is_refused(query):
    assert _blocked(query), "SERVICE reached the store — this is anonymous SSRF"


@pytest.mark.parametrize("query", [
    "INSERT DATA { <urn:a> <urn:b> <urn:c> }",
    "DROP SILENT GRAPH <urn:meta>",
    "LOAD <http://evil.invalid/g> INTO GRAPH <urn:meta>",
])
def test_update_verbs_are_refused(query):
    assert _blocked(query)


def test_keyword_cannot_hide_behind_an_unterminated_iri():
    """The strip order was IRIs first with `<[^>]*>`, whose class spans newlines.
    A lone `<` in a not-yet-removed comment swallowed everything to the next `>`,
    taking the keyword with it."""
    assert _blocked("# <\nINSERT DATA { <urn:a> <urn:b> <urn:c> }\n#>")
    assert _blocked("# <\nSELECT * WHERE { SERVICE <http://c.invalid/> { ?s ?p ?o } }\n#>")


@pytest.mark.parametrize("query", [
    "SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 10",
    'SELECT ?s WHERE { ?s ?p "a service record" }',
    'SELECT ?s WHERE { ?s ?p "we INSERT nothing here" }',
    "SELECT ?s WHERE { ?s <http://ex/inserted-at> ?o }",
    "# a comment mentioning SERVICE and INSERT\nSELECT ?s WHERE { ?s ?p ?o }",
])
def test_legitimate_queries_are_allowed(query):
    assert not _blocked(query), "guard rejected a valid read query"
