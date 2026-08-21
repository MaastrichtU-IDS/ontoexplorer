"""Per-class classification lookups, so a class page does not parse the whole result.

`load_classification` gzip-decompresses and JSON-parses the entire
ClassificationResult on every request, with no in-process cache. Measured on
DRON (771,512 classes): the blob is 21 MB gzipped, 539 MB decompressed, 1.19 s
to decompress and 7.31 s to parse. Viewing any class page issues two such
requests concurrently (sub- and superclasses), which is ~1 GB of transient
allocation per page view — the service's worker processes were dying and
restarting in a loop, and the API swallowed the failure, so pages rendered
silently missing their inferred hierarchy.

Storing each class's entry under its own hash field turns those requests into a
single HGET. The blob is still written, because consistency, justification and
classify-status genuinely need whole-ontology data.
"""
import json

import fakeredis
import pytest

import cache as cache_mod
from classifier import ClassificationResult


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    r = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)
    return r


def _result(**over) -> ClassificationResult:
    base = dict(
        version_id="v1",
        classified_at="2026-08-21T00:00:00Z",
        class_count=3,
        superclasses={"http://x/C": ["http://x/B", "http://x/A"]},
        subclasses={"http://x/A": ["http://x/B", "http://x/C"]},
        direct_superclasses={"http://x/C": ["http://x/B"]},
        direct_subclasses={"http://x/A": ["http://x/B"]},
        unsatisfiable=["http://x/Bad"],
        proof_traces={},
        duration_ms=12.5,
    )
    base.update(over)
    return ClassificationResult(**base)


def test_storing_also_writes_per_class_entries(fake_redis):
    cache_mod.store_classification(_result(), "rustdl")

    assert cache_mod.load_class_entry("v1", "rustdl", "subclasses", "http://x/A") == [
        "http://x/B", "http://x/C"]
    assert cache_mod.load_class_entry("v1", "rustdl", "superclasses", "http://x/C") == [
        "http://x/B", "http://x/A"]
    assert cache_mod.load_class_entry("v1", "rustdl", "direct_subclasses", "http://x/A") == [
        "http://x/B"]
    assert cache_mod.load_class_entry("v1", "rustdl", "direct_superclasses", "http://x/C") == [
        "http://x/B"]


def test_absent_class_is_none_not_empty(fake_redis):
    """None means "no entry"; [] would be a real answer meaning "no subclasses",
    and the endpoint distinguishes them to decide on a 404."""
    cache_mod.store_classification(_result(), "rustdl")
    assert cache_mod.load_class_entry("v1", "rustdl", "subclasses", "http://x/Nope") is None
    assert cache_mod.load_class_entry("v1", "rustdl", "subclasses", "http://x/C") is None


def test_entries_are_scoped_per_reasoner(fake_redis):
    cache_mod.store_classification(_result(), "rustdl")
    assert cache_mod.load_class_entry("v1", "km", "subclasses", "http://x/A") is None


def test_per_class_index_reports_whether_it_exists(fake_redis):
    """The endpoints fall back to the blob when a version predates this, so
    presence has to be checkable without loading anything."""
    assert cache_mod.has_per_class_index("v1", "rustdl") is False
    cache_mod.store_classification(_result(), "rustdl")
    assert cache_mod.has_per_class_index("v1", "rustdl") is True


def test_membership_is_checkable_without_loading_the_blob(fake_redis):
    """Used for the endpoint's 404: is this class known to the classification?"""
    cache_mod.store_classification(_result(), "rustdl")
    assert cache_mod.class_is_known("v1", "rustdl", "http://x/A") is True
    assert cache_mod.class_is_known("v1", "rustdl", "http://x/C") is True
    assert cache_mod.class_is_known("v1", "rustdl", "http://x/Unrelated") is False


def test_restoring_a_version_replaces_stale_entries(fake_redis):
    cache_mod.store_classification(_result(), "rustdl")
    cache_mod.store_classification(
        _result(subclasses={"http://x/A": ["http://x/Z"]},
                direct_subclasses={}, superclasses={}, direct_superclasses={}),
        "rustdl",
    )
    assert cache_mod.load_class_entry("v1", "rustdl", "subclasses", "http://x/A") == ["http://x/Z"]
    assert cache_mod.load_class_entry("v1", "rustdl", "direct_subclasses", "http://x/A") is None


def test_the_blob_is_still_written(fake_redis):
    """Consistency, justification and classify-status still need it."""
    cache_mod.store_classification(_result(), "rustdl")
    loaded = cache_mod.load_classification("v1", "rustdl")
    assert loaded is not None
    assert loaded.class_count == 3
    assert loaded.unsatisfiable == ["http://x/Bad"]


def test_per_class_values_are_json_lists(fake_redis):
    """Stored as JSON per field so a single HGET needs no whole-map parse."""
    cache_mod.store_classification(_result(), "rustdl")
    raw = fake_redis.hget(
        cache_mod._per_class_key("v1", "rustdl", "subclasses"), "http://x/A")
    assert json.loads(raw) == ["http://x/B", "http://x/C"]


# ── endpoints ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(fake_redis, monkeypatch):
    from fastapi.testclient import TestClient
    import main as main_mod
    monkeypatch.setattr(main_mod, "default_reasoner", lambda: "rustdl")
    return TestClient(main_mod.app)


def test_subclasses_endpoint_answers_from_the_per_class_entry(client, fake_redis, monkeypatch):
    """It must not touch the blob: on DRON that read is 8.5 s and ~539 MB."""
    cache_mod.store_classification(_result(), "rustdl")

    import main as main_mod
    def _boom(*a, **k):
        raise AssertionError("loaded the whole classification blob")
    monkeypatch.setattr(main_mod, "load_classification", _boom)

    r = client.get("/classify/v1/subclasses", params={"cls": "http://x/A", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert r.json()["subclasses"] == ["http://x/B", "http://x/C"]


def test_superclasses_endpoint_answers_from_the_per_class_entry(client, fake_redis, monkeypatch):
    cache_mod.store_classification(_result(), "rustdl")
    import main as main_mod
    monkeypatch.setattr(main_mod, "load_classification",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("blob loaded")))

    r = client.get("/classify/v1/superclasses", params={"cls": "http://x/C", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert r.json()["superclasses"] == ["http://x/B", "http://x/A"]


def test_direct_flag_reads_the_direct_map(client, fake_redis):
    cache_mod.store_classification(_result(), "rustdl")
    r = client.get("/classify/v1/subclasses",
                   params={"cls": "http://x/A", "direct": "true", "reasoner": "rustdl"})
    assert r.json() == {"class": "http://x/A", "subclasses": ["http://x/B"], "direct": True}


def test_known_class_with_no_entry_returns_empty_not_404(client, fake_redis):
    """http://x/C is a known class with no subclasses — a real empty answer."""
    cache_mod.store_classification(_result(), "rustdl")
    r = client.get("/classify/v1/subclasses", params={"cls": "http://x/C", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert r.json()["subclasses"] == []


def test_unknown_class_still_404s(client, fake_redis):
    cache_mod.store_classification(_result(), "rustdl")
    r = client.get("/classify/v1/subclasses",
                   params={"cls": "http://x/Unrelated", "reasoner": "rustdl"})
    assert r.status_code == 404


def test_falls_back_to_the_blob_when_there_is_no_per_class_index(client, fake_redis):
    """A classification cached before this shipped has only the blob; it must
    keep working rather than reporting every class as unknown."""
    cache_mod.store_classification(_result(), "rustdl")
    for which in cache_mod._PER_CLASS_MAPS:
        fake_redis.delete(cache_mod._per_class_key("v1", "rustdl", which))
    fake_redis.delete(cache_mod._per_class_index_key("v1", "rustdl"))

    r = client.get("/classify/v1/subclasses", params={"cls": "http://x/A", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert r.json()["subclasses"] == ["http://x/B", "http://x/C"]


def test_the_fallback_backfills_so_only_the_first_request_pays(client, fake_redis):
    """A classification cached before this shipped would otherwise reload the
    539 MB blob on every request forever. The one request that does pay writes
    the per-class entries on its way out, so the next one is an HGET."""
    cache_mod.store_classification(_result(), "rustdl")
    for which in cache_mod._PER_CLASS_MAPS:
        fake_redis.delete(cache_mod._per_class_key("v1", "rustdl", which))
    fake_redis.delete(cache_mod._per_class_index_key("v1", "rustdl"))
    assert cache_mod.has_per_class_index("v1", "rustdl") is False

    r = client.get("/classify/v1/subclasses", params={"cls": "http://x/A", "reasoner": "rustdl"})
    assert r.status_code == 200

    assert cache_mod.has_per_class_index("v1", "rustdl") is True
    assert cache_mod.load_class_entry("v1", "rustdl", "subclasses", "http://x/A") == [
        "http://x/B", "http://x/C"]
