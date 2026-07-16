import sys, os, shutil
sys.path.insert(0, os.path.dirname(__file__))

import pytest

# NOTE: this whole module skips on hosts without the Konclude binary (e.g. this
# macOS dev machine). Task 8 (container-based integration test, run where the
# binary is actually present) should additionally assert that
# owl:Nothing does NOT appear as a value in *any* class's `subclasses` list —
# regression coverage for the owl:Nothing-as-subject leak fixed in
# KoncludeBackend.classify_ntriples (see su == OWL_NOTHING guard).
if shutil.which("Konclude") is None:
    pytest.skip("Konclude binary not on PATH", allow_module_level=True)
pytest.importorskip("pyhornedowl")
pytest.importorskip("pyoxigraph")
from konclude_backend import KoncludeBackend

EX = "http://example.org/"
NT = f"""\
<{EX}A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}B> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}C> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}B> .
<{EX}B> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}C> .
"""


def test_konclude_infers_transitive_superclass():
    r = KoncludeBackend().classify_ntriples(NT, "v-test")
    assert f"{EX}C" in r.superclasses.get(f"{EX}A", [])
    assert r.proof_traces == {}
