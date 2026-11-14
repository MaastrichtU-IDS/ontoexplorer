"""compute_owl_profile_payload must not let a strict-parser rejection (the ~14% of
files horned-owl's reader can't open) discard the store-based language tier. The
tier is computed from the triple store (independent of the file parse), so a
parse failure yields a tier-only payload (profiles_unavailable) rather than a
NULL row — and never fabricates EL/QL/RL/DL verdicts.
"""
import pytest

from ontoexplorer.modules.owl_profile.compute import compute_owl_profile_payload

pytestmark = pytest.mark.anyio


class _Row:
    minio_key = "o/v.owl"
    format = "owl"


class _Result:
    def first(self):
        return _Row()


class _DB:
    async def execute(self, *a, **k):
        return _Result()


def _patch_common(monkeypatch, tier="rdfs"):
    monkeypatch.setattr("ontoexplorer.clients.minio.download_bytes",
                        lambda bucket, key: b"<content>")
    monkeypatch.setattr("ontoexplorer.modules.owl_profile.language.detect_language",
                        lambda *a, **k: {"tier": tier, "label": tier.upper(), "construct": None})
    monkeypatch.setattr("ontoexplorer.clients.oxigraph.get_store", lambda: object())
    monkeypatch.setattr("ontoexplorer.clients.oxigraph.graph_iri", lambda o, v: "urn:g")


async def test_tier_persists_when_strict_parse_fails(monkeypatch):
    _patch_common(monkeypatch, tier="rdfs")

    def _boom(content, fmt=None):
        raise ValueError("Failed to open ontology")
    monkeypatch.setattr("ontoexplorer.modules.owl_profile.detector.detect_profiles", _boom)

    payload = await compute_owl_profile_payload(_DB(), "v1", "o1")
    assert payload is not None                              # NOT dropped to NULL
    assert payload["language"]["tier"] == "rdfs"           # tier survives the parse gap
    assert payload["profiles_unavailable"] is True
    assert "indexed_at" in payload
    for p in ("el", "ql", "rl", "dl"):                     # profiles not fabricated
        assert p not in payload


async def test_success_keeps_profiles_and_tier(monkeypatch):
    _patch_common(monkeypatch, tier="owl")
    slim = {"in_profile": True, "total_violations": 0, "violations_by_axiom_type": {}}
    monkeypatch.setattr("ontoexplorer.modules.owl_profile.detector.detect_profiles",
                        lambda content, fmt=None: {k: dict(slim) for k in ("el", "ql", "rl", "dl")})

    payload = await compute_owl_profile_payload(_DB(), "v1", "o1")
    assert payload["el"]["in_profile"] is True
    assert payload["language"]["tier"] == "owl"
    assert "profiles_unavailable" not in payload           # only set on the failure path
    assert "indexed_at" in payload
