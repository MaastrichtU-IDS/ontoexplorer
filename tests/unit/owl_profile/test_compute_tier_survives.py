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

    # realistic: horned-owl's Debug string backslash-escapes the inner quotes
    def _boom(content, fmt=None):
        raise ValueError('Failed to open ontology: ValidityError("Invalid annotation '
                         'found [Iri(IRI(\\"http://ex/o\\")), RDF(Type), '
                         'Iri(IRI(\\"http://purl.org/vocommons/voaf#Vocabulary\\"))]", Unknown)')
    monkeypatch.setattr("ontoexplorer.modules.owl_profile.detector.detect_profiles", _boom)

    payload = await compute_owl_profile_payload(_DB(), "v1", "o1")
    assert payload is not None                              # NOT dropped to NULL
    assert payload["language"]["tier"] == "rdfs"           # tier survives the parse gap
    assert payload["profiles_unavailable"] is True
    assert "indexed_at" in payload
    for p in ("el", "ql", "rl", "dl"):                     # profiles not fabricated
        assert p not in payload
    # error captured, wrapper stripped, Debug quote-escaping removed
    assert payload["profiles_error"].startswith("ValidityError")
    assert '\\"' not in payload["profiles_error"]
    assert payload["profiles_error_category"] == "invalid_annotation"
    # the offending element is promoted into a readable, ontology-specific sentence
    assert payload["profiles_error_detail"] == (
        "http://ex/o is typed voaf:Vocabulary, which the strict OWL reader "
        "rejects as an annotation.")


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


async def test_error_detail_extracts_offending_element():
    from ontoexplorer.modules.owl_profile.compute import _error_detail
    # IRIs come de-escaped by the time _error_detail runs (compute de-escapes first).
    assert _error_detail(
        'Invalid annotation found [Iri(IRI("http://ex/o")), RDF(Type), OWL(Thing)]'
    ) == "http://ex/o is typed owl:Thing, which the strict OWL reader rejects as an annotation."
    assert _error_detail(
        'Invalid annotation found [Iri(IRI("http://ex/o")), RDF(Type), Iri(IRI("http://purl.org/vocommons/voaf#Vocabulary"))]'
    ).endswith("is typed voaf:Vocabulary, which the strict OWL reader rejects as an annotation.")
    assert _error_detail(
        'Unknown entity in equivalent class statement: [Iri(IRI("http://ex/A")), OWL(EquivalentClass), BNode(BNode("x"))]'
    ) == "http://ex/A is asserted owl:equivalentClass of an undeclared class."
    assert _error_detail(
        'Types of two properties do not match: IRI("http://purl.org/dc/terms/creator") and IRI("http://xmlns.com/foaf/0.1/maker")'
    ) == "dcterms:creator and foaf:maker have conflicting property kinds (object vs. data vs. annotation)."
    # no extractable IRI -> None (UI falls back to the category hint)
    assert _error_detail("Unexpected property kind in restriction") is None
    assert _error_detail('ParserError(Syntax(RdfSyntaxError(RdfXml(Msg("Unknown prefix http:")))))') is None


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
