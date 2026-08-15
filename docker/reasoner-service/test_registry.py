import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import registry


def test_reasoners_registered():
    names = {r.name for r in registry.list_reasoners()}
    assert {"rustdl", "konclude", "km"} <= names


def test_capabilities_are_correct():
    caps = {r.name: r.capabilities for r in registry.list_reasoners()}
    assert "justify" in caps["whelk"]
    assert "justify" in caps["rustdl"]
    assert "justify" not in caps["konclude"]      # Konclude cannot explain
    assert "classify" in caps["konclude"]


def test_default_reasoner_env(monkeypatch):
    monkeypatch.delenv("DEFAULT_REASONER", raising=False)
    assert registry.default_reasoner() == "whelk"
    monkeypatch.setenv("DEFAULT_REASONER", "rustdl")
    assert registry.default_reasoner() == "rustdl"


def test_unknown_backend_raises():
    with pytest.raises(KeyError):
        registry.get_backend("hermit")


def test_konclude_justify_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        registry.get_backend("konclude").justify("", "s", "o", 1)


def test_whelk_justify_passes_real_classification_result(monkeypatch):
    """Regression test for the bug where _WhelkBackend.justify built a
    fabricated EMPTY ClassificationResult and passed it to
    compute_justifications. compute_justifications' entry guard checks the
    PASSED-IN result's unsatisfiable/superclasses/direct_superclasses to
    confirm the inference exists before doing any work; an empty result
    always fails that guard, so justify would silently return [] for every
    input. This asserts justify now classifies first and forwards a result
    whose superclasses actually contain the queried pair.

    The fake compute_justifications below returns a non-N-Triple stub
    string ("stub-axiom"), which cannot round-trip through pyoxigraph as
    N-Triples — justify's Manchester-rendering step must catch that and
    fall back to the original (stub) axiom set rather than raising, while
    still reporting format "manchester" (SP3 task 2: whelk justify always
    renders/falls back to that format now).
    """
    from classifier import ClassificationResult

    ntriples = (
        '<http://example.org#A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> '
        '<http://example.org#B> .'
    )
    sub, sup = "http://example.org#A", "http://example.org#B"

    canned = ClassificationResult(
        version_id="_justify", classified_at="", class_count=2,
        superclasses={sub: [sup]}, subclasses={}, direct_superclasses={sub: [sup]},
        direct_subclasses={}, unsatisfiable=[], proof_traces={}, duration_ms=0.0,
    )

    monkeypatch.setattr(
        registry._WhelkBackend, "classify_ntriples",
        lambda self, nt, version_id: canned,
    )

    captured = {}

    def fake_compute_justifications(g, result, sub_, sup_, max_justifications):
        captured["result"] = result
        return [["stub-axiom"]]

    import justification
    monkeypatch.setattr(justification, "compute_justifications", fake_compute_justifications)

    backend = registry.get_backend("whelk")
    sets, fmt = backend.justify(ntriples, sub, sup, 1)

    assert captured["result"] is canned
    assert captured["result"].superclasses.get(sub) == [sup]
    assert sets == [["stub-axiom"]]  # fell back to the N-Triple stub set
    assert fmt == "manchester"
