"""refresh_owl_profile was a no-op/raise after the horned-profile rewrite (it called
detect_profiles with the old store-based signature). This verifies the fixed task:
it loads the stored file, runs the content-based detector, and writes a SLIM payload
(no sample_violations) with indexed_at.
"""
import json

import fakeredis
import pytest

pytest.importorskip("pyhornedowl")

from ontoexplorer.modules.jobs import tasks
from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key

_OFN = (
    "Ontology(<http://ex.org/o>\n"
    "  SubClassOf(<http://purl.obolibrary.org/obo/GO_0008150> <http://ex.org/B>))"
).encode()


class _Row:
    minio_key = "o/v.ofn"
    format = "ofn"


class _Result:
    def first(self):
        return _Row()


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _Result()


def test_refresh_owl_profile_writes_slim_payload(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("ontoexplorer.database.make_celery_db_session",
                        lambda: (lambda: _Session()))
    monkeypatch.setattr("ontoexplorer.clients.minio.download_bytes",
                        lambda bucket, key: _OFN)
    monkeypatch.setattr("ontoexplorer.modules.owl_profile.language.detect_language",
                        lambda *a, **k: {"tier": "owl", "label": "OWL", "construct": None})
    monkeypatch.setattr("ontoexplorer.clients.oxigraph.get_store", lambda: object())
    monkeypatch.setattr("ontoexplorer.modules.search.indexer._get_redis", lambda: r)

    out = tasks.refresh_owl_profile("v1", "o1")
    assert out["status"] == "done"

    payload = json.loads(r.get(owl_profile_cache_key("v1")))
    assert payload["language"] == "owl" or payload.get("language")  # tier recorded
    assert "indexed_at" in payload
    for key in ("el", "rl", "ql", "dl"):
        assert "sample_violations" not in payload[key]  # slim
        assert "violations_by_axiom_type" in payload[key]
    assert payload["dl"]["violations_by_axiom_type"].get("UseOfUndeclaredClass", 0) >= 1


def test_refresh_owl_profile_skips_when_no_file(monkeypatch):
    class _NoRow(_Result):
        def first(self):
            return None

    class _NoFileSession(_Session):
        async def execute(self, *a, **k):
            return _NoRow()

    monkeypatch.setattr("ontoexplorer.database.make_celery_db_session",
                        lambda: (lambda: _NoFileSession()))
    out = tasks.refresh_owl_profile("v1", "o1")
    assert out["status"] == "skipped"
