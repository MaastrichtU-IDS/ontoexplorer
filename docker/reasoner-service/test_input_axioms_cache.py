"""Tests for the input-axioms cache used to drive justifications under any backend.

The whelk classifier emits no proof traces, so the justification endpoint can
no longer reconstruct the input graph from `ClassificationResult.proof_traces`.
Instead we cache the original N-Triples body submitted to /classify, keyed by
version_id, and load it back at justification time.

These tests pin the round-trip semantics + miss behaviour so the cache stays
stable across backend changes.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))


def test_input_axioms_round_trip(monkeypatch):
    """store_input_axioms / load_input_axioms preserves the exact bytes."""
    import fakeredis
    import cache as cache_mod
    r = fakeredis.FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)

    nt = (
        '<http://example.org/A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> '
        '<http://example.org/B> .\n'
    )
    cache_mod.store_input_axioms("v-test", nt, "whelk")
    loaded = cache_mod.load_input_axioms("v-test", "whelk")
    assert loaded == nt


def test_input_axioms_miss_returns_none(monkeypatch):
    import fakeredis
    import cache as cache_mod
    r = fakeredis.FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)
    assert cache_mod.load_input_axioms("never-seen", "whelk") is None


def test_invalidate_version_removes_input_axioms(monkeypatch):
    """invalidate_version must also clear the input-axioms key so the next
    classification submission isn't shadowed by stale bytes."""
    import fakeredis
    import cache as cache_mod
    r = fakeredis.FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)

    cache_mod.store_input_axioms("v-gone", "<a> <b> <c> .\n", "whelk")
    assert cache_mod.load_input_axioms("v-gone", "whelk") is not None
    cache_mod.invalidate_version("v-gone")
    assert cache_mod.load_input_axioms("v-gone", "whelk") is None
