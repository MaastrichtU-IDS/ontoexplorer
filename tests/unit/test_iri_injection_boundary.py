"""Raw IRIs from the request must not reach a SPARQL template.

These are the read-path twins of the injection fixed in 0.3.85: the same raw
`<{iri}>` interpolation, but on anonymous routes. Validation happens at the
boundary — the path parameter and the OLS double-decoder — because each value
fans out to a dozen query templates downstream.
"""

import pytest
from fastapi import HTTPException

from ontoexplorer.api.ols._iri import double_decode_iri

# Escapes the graph scope, then comments out the template's remainder.
SCOPE_BREAK = "urn:x> ?p ?o } UNION { GRAPH ?g { ?s ?p ?o } #"
FEDERATION = "urn:x> { SERVICE <http://collector.invalid/> } #"


@pytest.mark.parametrize("payload", [SCOPE_BREAK, FEDERATION, "urn:x\nmore"])
def test_ols_decoder_refuses_injection(payload):
    import urllib.parse
    doubly = urllib.parse.quote(urllib.parse.quote(payload, safe=""), safe="")
    with pytest.raises(HTTPException) as e:
        double_decode_iri(doubly)
    assert e.value.status_code == 400


def test_ols_decoder_still_round_trips_a_real_iri():
    import urllib.parse
    iri = "http://www.w3.org/2004/02/skos/core#Concept"
    doubly = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
    assert double_decode_iri(doubly) == iri


@pytest.mark.anyio
@pytest.mark.parametrize("route", [
    "/api/v1/ontologies/{o}/{v}/terms/{iri}",
    "/api/v1/ontologies/{o}/{v}/term-usage/{iri}",
    "/api/v1/ontologies/{o}/{v}/term-expanded/{iri}",
])
async def test_term_routes_refuse_injection_before_querying(client, route):
    """400 rather than 200-with-cross-graph-rows, and never a 500 from a
    malformed query reaching the store."""
    url = route.format(o="00000000-0000-0000-0000-000000000000",
                       v="11111111-1111-1111-1111-111111111111",
                       iri=SCOPE_BREAK)
    r = await client.get(url)
    # 400 specifically: the guard runs before the version lookup, so a 404 here
    # would mean the payload passed validation and the test proved nothing.
    assert r.status_code == 400, f"expected 400, got {r.status_code} for an injection payload"
