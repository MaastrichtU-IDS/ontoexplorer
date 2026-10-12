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


# ── _is_timeout_failure: which reasoner-service failures trigger the EL fallback ──
#
# The EL-saturation fallback must fire on a TIMEOUT reported by either surface
# (client-poll give-up -> TimeoutError; reasoner-service inner 3300s deadline ->
# ReasoningFailed 'Classification failed: classification timed out …') but NOT on
# a parse/backend crash (also ReasoningFailed) — EL shares the parser and would
# just fail again. _is_timeout_failure is the message-level discriminator for the
# ReasoningFailed case (TimeoutError is matched by type, not this helper).


def test_timeout_failure_service_internal_deadline():
    # The exact message creno failed with (reasoner-service inner 3300s deadline).
    exc = Exception("Classification failed: classification timed out after 3300s")
    assert tasks._is_timeout_failure(exc) is True


def test_timeout_failure_client_giveup_message():
    exc = Exception("ELK classification for abc did not complete within 3600s")
    assert tasks._is_timeout_failure(exc) is True


def test_timeout_failure_case_insensitive():
    exc = Exception("Classification failed: Request TIMEOUT")
    assert tasks._is_timeout_failure(exc) is True


def test_crash_is_not_timeout_failure():
    # The exact message mexperf failed with — a genuine classifier crash.
    exc = Exception("Classification failed: classifier process exited 1")
    assert tasks._is_timeout_failure(exc) is False


def test_parse_error_is_not_timeout_failure():
    for msg in (
        "Classification failed: invalid annotation found",
        "Classification failed: types of two properties clash (punning)",
        "Classification failed: unsupported restriction",
    ):
        assert tasks._is_timeout_failure(Exception(msg)) is False
