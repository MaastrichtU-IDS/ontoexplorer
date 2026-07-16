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
