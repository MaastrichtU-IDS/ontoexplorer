"""The owl-profile and reuse fleet rollups must read the durable version column,
fall back to Redis only for not-yet-backfilled rows, and skip a version only when
it has neither. This is the regression for the "precomputed-value-in-TTL'd-Redis"
anti-pattern that reduced the coverage/owl-profile/reuse fleet views to a handful
of ontologies once the cache aged out.
"""
import asyncio
import json
import types

import fakeredis
import pytest


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Returns a fixed row set for the single select the rollup issues."""
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *a, **k):
        return _Rows(self._rows)


def _row(**kw):
    return types.SimpleNamespace(**kw)


def _profile_payload(in_el: bool, tier: str):
    names = ("el", "ql", "rl", "dl")
    p = {n: {"in_profile": in_el if n == "el" else False, "total_violations": 0}
         for n in names}
    p["language"] = {"tier": tier}
    return p


def test_owl_profile_fleet_prefers_column_falls_back_to_redis(monkeypatch):
    from ontoexplorer.api import owl_profile as mod

    # v1: durable column. v2: NULL column, live Redis. v3: neither → dropped.
    rows = [
        _row(id="v1", ontology_id="o1", shortname="alpha", title="Alpha",
             owl_profile=_profile_payload(True, "owl")),
        _row(id="v2", ontology_id="o2", shortname="beta", title="Beta", owl_profile=None),
        _row(id="v3", ontology_id="o3", shortname="gamma", title="Gamma", owl_profile=None),
    ]
    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(mod.owl_profile_cache_key("v2"), json.dumps(_profile_payload(False, "rdfs")))
    monkeypatch.setattr(mod, "_get_redis", lambda: r)

    out = asyncio.run(mod.get_fleet_profile(_FakeSession(rows)))

    shortnames = {o["shortname"] for o in out["ontologies"]}
    assert shortnames == {"alpha", "beta"}      # v3 (no payload anywhere) dropped
    assert out["totals"]["fleet_size"] == 2
    assert out["totals"]["el_count"] == 1       # only alpha (from the column) is in EL
    alpha = next(o for o in out["ontologies"] if o["shortname"] == "alpha")
    assert alpha["in_el"] is True


def test_reuse_fleet_prefers_column_falls_back_to_redis(monkeypatch):
    from ontoexplorer.api import reuse as mod

    col = {"imports": [{"import_iri": "x"}], "mireot_terms": [],
           "term_iri_reuse": {"obo": {"class_count": 2, "property_count": 1}},
           "mappings": {}}
    cached = {"imports": [], "mireot_terms": ["t1"],
              "term_iri_reuse": {}, "mappings": {}}
    rows = [
        _row(id="v1", ontology_id="o1", shortname="alpha", title="Alpha", reuse=col),
        _row(id="v2", ontology_id="o2", shortname="beta", title="Beta", reuse=None),
        _row(id="v3", ontology_id="o3", shortname="gamma", title="Gamma", reuse=None),
    ]
    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(mod.reuse_cache_key("v2"), json.dumps(cached))
    monkeypatch.setattr(mod, "_get_redis", lambda: r)

    out = asyncio.run(mod.get_fleet_reuse(_FakeSession(rows)))

    shortnames = {o["shortname"] for o in out["ontologies"]}
    assert shortnames == {"alpha", "beta"}      # v3 dropped
    assert out["totals"]["fleet_size"] == 2
    assert out["totals"]["total_import_edges"] == 1       # alpha's column payload
    assert out["totals"]["ontologies_with_mireot"] == 1   # beta's Redis payload
    alpha = next(o for o in out["ontologies"] if o["shortname"] == "alpha")
    assert alpha["term_iri_reused_count"] == 3            # 2 class + 1 property
    assert alpha["source_prefixes"] == ["obo"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
