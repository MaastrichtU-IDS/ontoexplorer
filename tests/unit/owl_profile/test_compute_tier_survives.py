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
        raise ValueError('Failed to open ontology: ValidityError("Invalid annotation '
                         'found [Iri(IRI(\\"http://ex#\\")), RDF(Type), Iri(IRI(\\"voaf#Vocabulary\\"))]", Unknown)')
    monkeypatch.setattr("ontoexplorer.modules.owl_profile.detector.detect_profiles", _boom)

    payload = await compute_owl_profile_payload(_DB(), "v1", "o1")
    assert payload is not None                              # NOT dropped to NULL
    assert payload["language"]["tier"] == "rdfs"           # tier survives the parse gap
    assert payload["profiles_unavailable"] is True
    assert "indexed_at" in payload
    for p in ("el", "ql", "rl", "dl"):                     # profiles not fabricated
        assert p not in payload
    # the error is captured + categorized, and the generic wrapper is stripped
    assert payload["profiles_error"].startswith("ValidityError")
    assert "Invalid annotation found" in payload["profiles_error"]
    assert payload["profiles_error_category"] == "invalid_annotation"


async def test_error_category_mapping():
    from ontoexplorer.modules.owl_profile.compute import _error_category
    assert _error_category('ValidityError("Invalid annotation found [...]")') == "invalid_annotation"
    assert _error_category("Unknown entity in equivalent class statement: [...]") == "equivalent_class_undeclared"
    assert _error_category("Types of two properties do not match: ...") == "property_kind"
    assert _error_category("Unexpected property kind in restriction") == "property_kind"
    assert _error_category("Cannot distinguish the types of {r} and {s}") == "property_kind"
    assert _error_category("Annotation properties cannot be equivalent: ...") == "annotation_property_equivalent"
    assert _error_category('ParserError(Syntax(RdfSyntaxError(...)))') == "rdf_syntax"
    assert _error_category("something else entirely") == "other"


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
