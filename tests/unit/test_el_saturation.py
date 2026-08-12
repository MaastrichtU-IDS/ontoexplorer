"""rustdl EL fast-path: _version_is_el_profile drives saturation_only.

When a version is in the OWL 2 EL profile, the reasoning task asks rustdl to
classify via EL saturation only (fast, complete for EL) instead of the SROIQ
tableau that blows up on large EL ontologies like GO.
"""
import json

from ontoexplorer.modules.jobs import tasks


class _FakeRedis:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, key):
        return self._m.get(key)


def _patch_redis(monkeypatch, mapping):
    from ontoexplorer.modules.search import indexer
    monkeypatch.setattr(indexer, "_get_redis", lambda: _FakeRedis(mapping))


def _key(vid):
    from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
    return owl_profile_cache_key(vid)


def test_el_profile_true(monkeypatch):
    _patch_redis(monkeypatch, {_key("v1"): json.dumps({"el": {"in_profile": True}, "dl": {"in_profile": True}})})
    assert tasks._version_is_el_profile("v1") is True


def test_el_profile_false(monkeypatch):
    _patch_redis(monkeypatch, {_key("v1"): json.dumps({"el": {"in_profile": False}, "dl": {"in_profile": True}})})
    assert tasks._version_is_el_profile("v1") is False


def test_el_profile_missing_report(monkeypatch):
    # No cached profile → safe default: not EL (full DL path).
    _patch_redis(monkeypatch, {})
    assert tasks._version_is_el_profile("v1") is False


def test_el_profile_malformed(monkeypatch):
    _patch_redis(monkeypatch, {_key("v1"): b"not json"})
    assert tasks._version_is_el_profile("v1") is False
