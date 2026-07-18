"""SP3 task 2: whelk-backed justifications render to Manchester via rustdl.

_WhelkBackend.justify used to return (nt_axiom_sets, "ntriples") — raw
N-Triple strings straight out of compute_justifications. rustdl 0.3.23
ships `render_manchester(path) -> list[str]` (SP3 task 1); this test pins
that whelk's justify path now renders each N-Triple justification through
that renderer and reports format "manchester", matching what rustdl's own
native justify already returns (see test_rustdl_backend.py::
test_justify_returns_manchester_axiom_set).

Requires pywhelk (the in-process EL reasoner) — absent on the dev mac host,
so this skips there. Real validation is in-container (docker build +
smoke test against the running reasoner-service), per the SP3 task-2 brief.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["CLASSIFIER_BACKEND"] = "whelk"

import pytest

_pywhelk = pytest.importorskip("pywhelk")
_pyhornedowl = pytest.importorskip("pyhornedowl")
_rustdl = pytest.importorskip("rustdl")
_pyoxigraph = pytest.importorskip("pyoxigraph")

import registry

EX = "http://example.org/"
NT = f"""\
<{EX}A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}B> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}C> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}B> .
<{EX}B> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}C> .
"""


def test_whelk_justify_returns_manchester_format():
    backend = registry.get_backend("whelk")
    sets, fmt = backend.justify(NT, f"{EX}A", f"{EX}C", 1)

    assert fmt == "manchester"
    assert len(sets) >= 1
    assert len(sets[0]) > 0


def test_whelk_justify_manchester_strings_not_ntriples():
    """The rendered axioms should read as Manchester syntax (SubClassOf:
    keyword, or at minimum bare class names) — not N-Triple `<...>` triples
    with rdf-schema#subClassOf predicates."""
    backend = registry.get_backend("whelk")
    sets, fmt = backend.justify(NT, f"{EX}A", f"{EX}C", 1)

    joined = " ".join(sets[0])
    assert "<http://www.w3.org/2000/01/rdf-schema#subClassOf>" not in joined
    assert "SubClassOf" in joined or ("A" in joined and "B" in joined and "C" in joined)
