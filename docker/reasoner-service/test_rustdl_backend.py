import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest

pytest.importorskip("rustdl")
pytest.importorskip("pyoxigraph")
from rustdl_backend import RustdlBackend

EX = "http://example.org/"
NT = f"""\
<{EX}A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}B> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}C> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}B> .
<{EX}B> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}C> .
"""


def test_transitive_superclass_inferred_not_asserted():
    r = RustdlBackend().classify_ntriples(NT, "v-test")
    sups = r.superclasses.get(f"{EX}A", [])
    assert f"{EX}C" in sups          # inferred transitive
    assert f"{EX}B" not in sups      # asserted, excluded from inferred set
    assert r.direct_superclasses.get(f"{EX}A", []) == [f"{EX}B"]


def test_result_has_frozen_field_shape():
    r = RustdlBackend().classify_ntriples(NT, "v-test")
    for field in ("version_id", "classified_at", "class_count", "superclasses",
                  "subclasses", "direct_superclasses", "direct_subclasses",
                  "unsatisfiable", "proof_traces", "duration_ms"):
        assert hasattr(r, field)
    assert r.proof_traces == {}


NT_EQUIV = f"""\
<{EX}A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}B> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}C> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}D> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}B> .
<{EX}B> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}C> .
<{EX}A> <http://www.w3.org/2002/07/owl#equivalentClass> <{EX}D> .
"""


def test_equivalent_class_excluded_from_inferred_superclasses():
    r = RustdlBackend().classify_ntriples(NT_EQUIV, "v-test")
    sups_a = r.superclasses.get(f"{EX}A", [])
    # D is asserted equivalent to A, not an inferred superclass in either direction.
    assert f"{EX}D" not in sups_a
    sups_d = r.superclasses.get(f"{EX}D", [])
    assert f"{EX}A" not in sups_d
    # The equivalence partner is asserted, so it shows up in direct_superclasses.
    assert f"{EX}D" in r.direct_superclasses.get(f"{EX}A", [])
    # Existing transitive inference (A -> C via B) still holds.
    assert f"{EX}C" in sups_a
    assert f"{EX}B" not in sups_a


def test_justify_returns_manchester_axiom_set():
    sets, fmt = RustdlBackend().justify(NT, f"{EX}A", f"{EX}C", 1)
    assert fmt == "manchester"
    assert len(sets) >= 1
    joined = " ".join(sets[0])
    # The A⊑B, B⊑C axioms are the responsible set for A⊑C.
    assert "A" in joined and "B" in joined and "C" in joined


def test_justify_builds_then_reuses_cached_ofn(monkeypatch):
    # rustdl.justify has no reuse API, so justify feeds it a per-version .ofn
    # cached in Redis: built once on a miss, reused on subsequent calls.
    pytest.importorskip("pyhornedowl")
    import cache

    state = {"stored": None, "writes": 0}

    def fake_load(vid):
        return state["stored"]

    def fake_store(vid, ofn):
        state["writes"] += 1
        state["stored"] = ofn

    monkeypatch.setattr(cache, "load_ontology_ofn", fake_load)
    monkeypatch.setattr(cache, "store_ontology_ofn", fake_store)

    b = RustdlBackend()
    sets1, _ = b.justify(NT, f"{EX}A", f"{EX}C", 1, version_id="v1")  # miss → build+store
    assert len(sets1) >= 1
    assert state["writes"] == 1 and state["stored"] is not None

    sets2, _ = b.justify(NT, f"{EX}A", f"{EX}C", 1, version_id="v1")  # hit → reuse
    assert len(sets2) >= 1
    assert state["writes"] == 1  # not rebuilt or re-stored
