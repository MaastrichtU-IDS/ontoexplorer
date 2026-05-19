"""Integration tests for the OWL 2 profile endpoints."""
import json
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile_payload(version_id: str, *, in_el: bool = True, in_rl: bool = False,
                      in_ql: bool = False, in_dl: bool = True) -> dict:
    """Build a minimal owl_profile cache payload."""

    def _entry(in_profile: bool, violations: int = 0) -> dict:
        return {
            "in_profile": in_profile,
            "total_violations": violations,
            "violations_by_axiom_type": {} if in_profile else {"owl:disjointWith": violations},
            "sample_violations": [],
        }

    return {
        "el": _entry(in_el, 0 if in_el else 5),
        "rl": _entry(in_rl, 0 if in_rl else 3),
        "ql": _entry(in_ql, 0 if in_ql else 8),
        "dl": _entry(in_dl, 0 if in_dl else 1),
        "indexed_at": "2026-05-19T00:00:00+00:00",
        "version_id": version_id,
    }


# ---------------------------------------------------------------------------
# Test 1: per-version endpoint returns cached payload
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_version_profile_returns_cache(client, db_session):
    ont = Ontology(iri="http://example.org/owlp-test.owl", shortname="owlp", title="OWL Profile Test")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="owlp/test.ttl",
        sha256="owlp_test_001",
        format="turtle",
        status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    payload = _profile_payload(str(ver.id), in_el=True, in_rl=False, in_ql=False, in_dl=True)
    r.set(owl_profile_cache_key(str(ver.id)), json.dumps(payload))

    with patch("ontoexplorer.api.owl_profile._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/owl-profile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["el"]["in_profile"] is True
    assert body["rl"]["in_profile"] is False
    assert body["dl"]["in_profile"] is True
    assert body["indexed_at"] == "2026-05-19T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Test 2: 404 when cache missing
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_version_profile_404_when_missing(client, db_session):
    ont = Ontology(iri="http://example.org/owlp-missing.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="owlp/missing.ttl",
        sha256="owlp_missing_001",
        format="turtle",
        status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.api.owl_profile._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/owl-profile")

    assert resp.status_code == 404
    assert "reindex pending" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Test 3: fleet rollup aggregates in_profile counts
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_fleet_rollup_aggregates_in_profile_counts(client, db_session):
    ont_a = Ontology(iri="http://example.org/fleet-a.owl", shortname="fleeta", title="Fleet A")
    ont_b = Ontology(iri="http://example.org/fleet-b.owl", shortname="fleetb", title="Fleet B")
    ont_c = Ontology(iri="http://example.org/fleet-c.owl", shortname="fleetc", title="Fleet C")
    db_session.add_all([ont_a, ont_b, ont_c])
    await db_session.flush()

    ver_a = OntologyVersion(ontology_id=ont_a.id, minio_key="fa.ttl", sha256="fa001", format="turtle", status="ready")
    ver_b = OntologyVersion(ontology_id=ont_b.id, minio_key="fb.ttl", sha256="fb001", format="turtle", status="ready")
    ver_c = OntologyVersion(ontology_id=ont_c.id, minio_key="fc.ttl", sha256="fc001", format="turtle", status="ready")
    db_session.add_all([ver_a, ver_b, ver_c])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    # ont_a: in EL + DL only
    r.set(owl_profile_cache_key(str(ver_a.id)), json.dumps(_profile_payload(str(ver_a.id), in_el=True,  in_rl=False, in_ql=False, in_dl=True)))
    # ont_b: in EL + RL + DL
    r.set(owl_profile_cache_key(str(ver_b.id)), json.dumps(_profile_payload(str(ver_b.id), in_el=True,  in_rl=True,  in_ql=False, in_dl=True)))
    # ont_c: in DL only
    r.set(owl_profile_cache_key(str(ver_c.id)), json.dumps(_profile_payload(str(ver_c.id), in_el=False, in_rl=False, in_ql=False, in_dl=True)))

    with patch("ontoexplorer.api.owl_profile._get_redis", return_value=r):
        resp = await client.get("/api/v1/owl-profile/public")

    assert resp.status_code == 200
    body = resp.json()

    # All three ontologies have cache entries
    fleet_ids = {e["id"] for e in body["ontologies"]}
    assert ont_a.id in fleet_ids
    assert ont_b.id in fleet_ids
    assert ont_c.id in fleet_ids

    totals = body["totals"]
    assert totals["fleet_size"] == 3
    assert totals["el_count"] == 2   # ont_a + ont_b
    assert totals["rl_count"] == 1   # ont_b only
    assert totals["ql_count"] == 0
    assert totals["dl_count"] == 3   # all three


# ---------------------------------------------------------------------------
# Test 4: fleet rollup skips ontologies without cache
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_fleet_rollup_skips_missing_cache(client, db_session):
    ont = Ontology(iri="http://example.org/fleet-skip.owl", shortname="fleetskip", title="Fleet Skip")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(ontology_id=ont.id, minio_key="fskip.ttl", sha256="fskip001", format="turtle", status="ready")
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    # No cache entry seeded
    with patch("ontoexplorer.api.owl_profile._get_redis", return_value=r):
        resp = await client.get("/api/v1/owl-profile/public")

    assert resp.status_code == 200
    body = resp.json()
    # This ontology should be absent from the response
    ids = {e["id"] for e in body["ontologies"]}
    assert ont.id not in ids


# ---------------------------------------------------------------------------
# Test 5: ?profile= filter on /api/v1/ontologies returns only matching
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_ontologies_with_profile_filter_includes_only_matching(client, db_session):
    uid = "pf5"
    ont_el = Ontology(iri=f"http://example.org/pf5-el.owl", shortname=f"pf5el", title="PF5 EL")
    ont_noel = Ontology(iri=f"http://example.org/pf5-noel.owl", shortname=f"pf5noel", title="PF5 No EL")
    db_session.add_all([ont_el, ont_noel])
    await db_session.flush()

    ver_el   = OntologyVersion(ontology_id=ont_el.id,   minio_key=f"pf5el.ttl",   sha256=f"pf5el001",   format="turtle", status="ready")
    ver_noel = OntologyVersion(ontology_id=ont_noel.id, minio_key=f"pf5noel.ttl", sha256=f"pf5noel001", format="turtle", status="ready")
    db_session.add_all([ver_el, ver_noel])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(owl_profile_cache_key(str(ver_el.id)),   json.dumps(_profile_payload(str(ver_el.id),   in_el=True,  in_dl=True)))
    r.set(owl_profile_cache_key(str(ver_noel.id)), json.dumps(_profile_payload(str(ver_noel.id), in_el=False, in_dl=True)))

    with (
        patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r),
        patch("ontoexplorer.api.owl_profile._get_redis", return_value=r),
    ):
        resp = await client.get("/api/v1/ontologies?profile=el")

    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {o["id"] for o in body["ontologies"]}
    assert ont_el.id in returned_ids
    assert ont_noel.id not in returned_ids


# ---------------------------------------------------------------------------
# Test 6: ?profile=xyz (invalid) returns 422
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_ontologies_profile_filter_invalid_value_returns_422(client, db_session):
    r = fakeredis.FakeRedis(decode_responses=True)
    with (
        patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r),
        patch("ontoexplorer.api.owl_profile._get_redis", return_value=r),
    ):
        resp = await client.get("/api/v1/ontologies?profile=xyz")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 7: OLS HAL v1 list with ?profile= filter
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_ols_v1_list_with_profile_filter(client, db_session):
    uid = "olspf"
    ont_el   = Ontology(iri=f"http://example.org/ols-el.owl",   shortname=f"olsel",   title="OLS EL")
    ont_noel = Ontology(iri=f"http://example.org/ols-noel.owl", shortname=f"olsnoel", title="OLS No EL")
    db_session.add_all([ont_el, ont_noel])
    await db_session.flush()

    ver_el   = OntologyVersion(ontology_id=ont_el.id,   minio_key="olsel.ttl",   sha256="olsel001",   format="turtle", status="ready")
    ver_noel = OntologyVersion(ontology_id=ont_noel.id, minio_key="olsnoel.ttl", sha256="olsnoel001", format="turtle", status="ready")
    db_session.add_all([ver_el, ver_noel])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(owl_profile_cache_key(str(ver_el.id)),   json.dumps(_profile_payload(str(ver_el.id),   in_el=True,  in_dl=True)))
    r.set(owl_profile_cache_key(str(ver_noel.id)), json.dumps(_profile_payload(str(ver_noel.id), in_el=False, in_dl=True)))

    with (
        patch("ontoexplorer.api.ols.ontologies._get_redis", return_value=r),
        patch("ontoexplorer.api.owl_profile._get_redis", return_value=r),
        patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r),
    ):
        resp = await client.get("/ols/api/ontologies?profile=el")

    assert resp.status_code == 200
    body = resp.json()
    returned_ids = {o["ontologyId"] for o in body["_embedded"]["ontologies"]}
    assert ont_el.id in returned_ids
    assert ont_noel.id not in returned_ids
