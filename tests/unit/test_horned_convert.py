"""Unit tests for the horned-convert ingestion helper (Manchester/OBO/OWL-Functional → Turtle)."""

import io
import shutil

import pyoxigraph
import pytest

from ontoexplorer.modules.ingestion.format_detect import OntologyFormat
from ontoexplorer.modules.ingestion.horned_convert import (
    CONVERTIBLE,
    HornedConvertError,
    to_turtle,
)

_OMN = b"""Prefix: : <http://example.org/>
Ontology: <http://example.org/test>
Class: Animal
Class: Dog
    SubClassOf: Animal
"""

_OBO = b"""format-version: 1.2
ontology: httptest-obo

[Term]
id: TEST:0001
name: animal

[Term]
id: TEST:0002
name: dog
is_a: TEST:0001 ! animal
"""

_OFN = b"""Prefix(:=<http://example.org/>)
Ontology(<http://example.org/test>
  Declaration(Class(:Animal))
  Declaration(Class(:Dog))
  SubClassOf(:Dog :Animal)
)
"""

_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


def _load(ttl: bytes) -> pyoxigraph.Store:
    """Load the converted Turtle exactly as the pipeline does — with a base_iri
    so any relative IRI (e.g. an OBO ontology node) resolves."""
    store = pyoxigraph.Store()
    store.bulk_load(
        io.BytesIO(ttl), format=pyoxigraph.RdfFormat.TURTLE,
        base_iri="urn:ontology:test:v1",
    )
    return store


def test_convertible_set():
    assert CONVERTIBLE == frozenset({
        OntologyFormat.MANCHESTER, OntologyFormat.OBO, OntologyFormat.OWL_FUNCTIONAL,
    })


def test_rejects_non_convertible_format():
    with pytest.raises(HornedConvertError):
        to_turtle(b"", OntologyFormat.TURTLE)


def test_missing_binary_raises(monkeypatch):
    import ontoexplorer.modules.ingestion.horned_convert as hc
    monkeypatch.setattr(hc, "_BIN", "definitely-not-a-real-binary-xyz")
    with pytest.raises(HornedConvertError, match="not found"):
        to_turtle(_OMN, OntologyFormat.MANCHESTER)


@pytest.mark.skipif(
    shutil.which("horned-convert") is None,
    reason="horned-convert binary not on PATH (present in the built image)",
)
def test_manchester_converts():
    store = _load(to_turtle(_OMN, OntologyFormat.MANCHESTER))
    iris = {q.subject.value for q in store}
    assert "http://example.org/Dog" in iris
    assert any(q.predicate.value == _SUBCLASS for q in store)


@pytest.mark.skipif(
    shutil.which("horned-convert") is None,
    reason="horned-convert binary not on PATH (present in the built image)",
)
def test_obo_converts():
    # OBO ids -> canonical PURLs; the `ontology:` value is relative here and must
    # resolve against base_iri (regression: it broke N-Triples loading).
    store = _load(to_turtle(_OBO, OntologyFormat.OBO))
    subjects = {q.subject.value for q in store}
    assert "http://purl.obolibrary.org/obo/TEST_0002" in subjects
    assert any(q.predicate.value == _SUBCLASS for q in store)


@pytest.mark.skipif(
    shutil.which("horned-convert") is None,
    reason="horned-convert binary not on PATH (present in the built image)",
)
def test_owl_functional_converts():
    store = _load(to_turtle(_OFN, OntologyFormat.OWL_FUNCTIONAL))
    iris = {q.subject.value for q in store}
    assert "http://example.org/Dog" in iris
    assert any(q.predicate.value == _SUBCLASS for q in store)
