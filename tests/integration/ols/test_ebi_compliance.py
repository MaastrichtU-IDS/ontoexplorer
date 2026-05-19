"""Shape-conformance contract tests against real EBI OLS4 responses.

Snapshots of representative EBI OLS4 responses live in
`tests/fixtures/ols4_ebi_samples/`. For each, we hit the equivalent endpoint
on our `/ols/api` server and assert that every key EBI returns is also
present in our response (we may add extra keys — only missing keys count
as a compliance gap).

This suite is marked `ols_compliance` and is DESELECTED by default. Run on
demand with:

    pytest -m ols_compliance tests/integration/ols/test_ebi_compliance.py -v

The test currently surfaces several known gaps vs EBI (especially in the
v2 flat surface and search facets). See the `KNOWN_GAPS` dict below for
each fixture's current expected-failure count. Fix the underlying mapper /
endpoint to close a gap, then update KNOWN_GAPS — the test will fail if
the actual gap count diverges from the documented one in either direction.

When EBI evolves the protocol, re-snapshot the fixtures:
    bash scripts/refresh_ebi_ols_fixtures.sh
"""
from __future__ import annotations

import json
import pathlib

import pytest
from httpx import AsyncClient


FIXTURES = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "ols4_ebi_samples"


def _read(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _collect_missing_keys(
    expected: object, actual: object, *, path: str = "", out: list[str] | None = None,
) -> list[str]:
    """Recursively collect dotted-paths of keys present in `expected` but not in `actual`.

    Lists are compared element-wise on the first element only (EBI returns
    arrays of homogeneous objects).
    """
    if out is None:
        out = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            out.append(f"{path}: type mismatch (expected dict, got {type(actual).__name__})")
            return out
        for k, v in expected.items():
            sub = f"{path}.{k}" if path else k
            if k not in actual:
                out.append(sub)
            else:
                _collect_missing_keys(v, actual[k], path=sub, out=out)
    elif isinstance(expected, list):
        if not isinstance(actual, list):
            out.append(f"{path}: type mismatch (expected list, got {type(actual).__name__})")
            return out
        if expected and actual:
            _collect_missing_keys(expected[0], actual[0], path=f"{path}[0]", out=out)
    # Scalars: presence is enough; we don't compare values.
    return out


# ---------------------------------------------------------------------------
# Test catalog: (fixture-name, our-endpoint, top-level-keys-only-or-deep)
# ---------------------------------------------------------------------------
#
# A fixture is "deep-compared" if EBI's response contains complex nested objects
# we want to verify in full (e.g. _embedded[].config). Otherwise we only check
# top-level keys.

CONTRACT_CASES: list[tuple[str, str]] = [
    ("ontologies_list_v1",  "/ols/api/ontologies?size=2"),
    ("ontology_detail_v1",  "/ols/api/ontologies/{ont}"),
    ("terms_list_v1",       "/ols/api/ontologies/{ont}/terms?size=2"),
    ("term_roots_v1",       "/ols/api/ontologies/{ont}/terms/roots?size=2"),
    ("search_solr",         "/ols/api/search?q={term}&rows=2"),
    ("ontologies_list_v2",  "/ols/api/v2/ontologies?size=2"),
    ("ontology_detail_v2",  "/ols/api/v2/ontologies/{ont}"),
]


# Documented baseline gap count per fixture. Updated as gaps are closed.
# Test fails if the actual gap count differs in either direction — closing a
# gap requires also reducing this count.
KNOWN_GAPS: dict[str, int] = {
    "ontologies_list_v1":   1,  # only _links.next missing (test DB has 1 ontology, no next page)
    "ontology_detail_v1":   0,  # fully compliant
    "terms_list_v1":        2,  # annotation.database_cross_reference + _links.next (test-data driven)
    "term_roots_v1":        4,  # missing annotation keys (created_by etc) — test-data driven
    "search_solr":          0,  # fully compliant
    # v2 remaining gaps fall into 3 buckets, all empty in the local test env
    # because there's no Oxigraph store reachable:
    #   - bare-IRI annotation passthrough (~9 keys per fixture) — populated
    #     in production from the owl:Ontology block document metadata
    #   - linkedEntities.<IRI> sub-keys — would require enumerating every
    #     predicate used in the ontology's terms (real new computation)
    #   - elements[0].* gaps mirror the ontology-level ones in the list shape
    "ontologies_list_v2":   8,
    "ontology_detail_v2":  22,
}


@pytest.mark.ols_compliance
@pytest.mark.parametrize("fixture_name,our_url_tmpl", CONTRACT_CASES, ids=[c[0] for c in CONTRACT_CASES])
@pytest.mark.anyio
async def test_response_shape_matches_ebi(
    client: AsyncClient,
    sample_ontology,
    sample_term,
    fixture_name: str,
    our_url_tmpl: str,
):
    """Our endpoint's response must include every key EBI returns.

    Extra keys in our response are FINE — EBI may add fields we don't have yet
    (and that's an upstream concern, not a compliance violation on our end);
    fields they have that we don't are the real gaps.

    Gap count must match `KNOWN_GAPS[fixture_name]` so we notice regressions
    (gap count increased) AND know to update the dict when we close a gap
    (gap count decreased).
    """
    expected = _read(fixture_name)
    # `sample_term` is a Redis-stored fixture; its label is the sub-key "Foo".
    url = our_url_tmpl.format(ont=sample_ontology.shortname, term="Foo")
    resp = await client.get(url)
    assert resp.status_code == 200, f"{url} returned {resp.status_code}: {resp.text[:200]}"
    actual = resp.json()
    missing = _collect_missing_keys(expected, actual)
    expected_count = KNOWN_GAPS.get(fixture_name, 0)
    if len(missing) != expected_count:
        formatted = "\n  - ".join(missing) if missing else "(none)"
        verdict = (
            f"increased — REGRESSION: {len(missing)} gaps (was {expected_count})"
            if len(missing) > expected_count
            else f"decreased — please update KNOWN_GAPS['{fixture_name}'] to {len(missing)}"
        )
        pytest.fail(
            f"OLS4 contract gap count {verdict} for fixture '{fixture_name}'\n"
            f"  Current missing key paths:\n  - {formatted}"
        )
