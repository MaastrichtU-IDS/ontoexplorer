import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import fakeredis
import pytest
import cache as cache_mod
from classifier import ClassificationResult


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    r = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)
    return r


def _result(vid="v1"):
    return ClassificationResult(
        version_id=vid, classified_at="t", class_count=0,
        superclasses={}, subclasses={}, direct_superclasses={},
        direct_subclasses={}, unsatisfiable=[], proof_traces={}, duration_ms=1.0,
    )


def test_two_reasoners_do_not_collide():
    cache_mod.store_classification(_result("v1"), "whelk")
    cache_mod.store_classification(_result("v1"), "rustdl")
    # Overwriting under rustdl must not affect whelk's entry.
    assert cache_mod.load_classification("v1", "whelk") is not None
    assert cache_mod.load_classification("v1", "rustdl") is not None
    assert cache_mod.load_classification("v1", "konclude") is None


def test_invalidate_clears_all_reasoner_variants():
    cache_mod.store_classification(_result("v1"), "whelk")
    cache_mod.store_classification(_result("v1"), "rustdl")
    cache_mod.store_input_axioms("v1", "<a> <b> <c> .", "whelk")
    cache_mod.invalidate_version("v1")
    assert cache_mod.load_classification("v1", "whelk") is None
    assert cache_mod.load_classification("v1", "rustdl") is None
    assert cache_mod.load_input_axioms("v1", "whelk") is None


def test_justification_scoped_by_reasoner():
    cache_mod.store_justification("v1", "sub", "sup", 3, "rustdl", {"ok": True})
    assert cache_mod.load_justification("v1", "sub", "sup", 3, "rustdl") == {"ok": True}
    assert cache_mod.load_justification("v1", "sub", "sup", 3, "whelk") is None
