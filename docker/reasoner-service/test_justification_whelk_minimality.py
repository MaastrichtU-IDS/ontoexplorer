"""Regression test for the greedy-shrink minimality fix under the whelk backend.

Background: with the whelk-backed `_entails`, the original single-pass greedy
walk could leave non-load-bearing axioms (e.g. unrelated `<X> a owl:Class`
declarations) in the result. We observed pizza Mozzarella ⊑ Object returning
14 axioms when the canonical chain is 4 — 10 of those 14 were post-hoc
individually removable.

The fix is a fixed-point loop: re-walk the surviving set until a full pass
makes no further removals. This test guards against regressing that.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["CLASSIFIER_BACKEND"] = "whelk"

import pytest
import rdflib

_pywhelk = pytest.importorskip("pywhelk")
_pyhornedowl = pytest.importorskip("pyhornedowl")

EX = "http://example.org/"


def _g(ttl: str) -> rdflib.Graph:
    import io
    graph = rdflib.Graph()
    graph.parse(io.StringIO(ttl), format="turtle")
    return graph


def test_unrelated_class_decls_are_shrunk_away():
    """A graph with the A⊑B⊑C chain PLUS many unrelated `<X> a owl:Class`
    declarations should still produce a minimal 2-axiom justification for
    A ⊑ C — the declarations are not load-bearing.

    The single-pass greedy walk was failing to remove all of them; the
    fixed-point loop must.
    """
    from whelk_classifier import classify_ntriples
    from justification import compute_justifications

    # Chain + 20 unrelated class declarations
    decls = "\n".join(
        f'<{EX}Unrelated{i}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> '
        f'<http://www.w3.org/2002/07/owl#Class> .'
        for i in range(20)
    )
    chain = f"""
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <{EX}> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    graph = _g(chain)
    # Append the 20 unrelated declarations via NT parse
    graph.parse(data=decls, format="nt")

    # Run via whelk (we need a result obj for compute_justifications; build
    # one quickly by classifying)
    nt_body = graph.serialize(format="nt")
    result = classify_ntriples(nt_body, "v-test")

    justs = compute_justifications(graph, result, f"{EX}A", f"{EX}C", max_justifications=1)
    assert len(justs) == 1, f"expected 1 justification, got {len(justs)}"
    j = justs[0]
    # Canonical: A ⊑ B, B ⊑ C  — exactly 2 axioms
    assert len(j) == 2, (
        f"expected 2-axiom canonical chain, got {len(j)}: {j!r}"
    )
