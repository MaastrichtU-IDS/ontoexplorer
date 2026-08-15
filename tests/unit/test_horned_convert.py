"""Unit tests for the horned-convert ingestion helper (Manchester/OBO → N-Triples)."""

import shutil

import pytest

from ontoexplorer.modules.ingestion.format_detect import OntologyFormat
from ontoexplorer.modules.ingestion.horned_convert import (
    CONVERTIBLE,
    HornedConvertError,
    to_ntriples,
)

_OMN = b"""Prefix: : <http://example.org/>
Ontology: <http://example.org/test>
Class: Animal
Class: Dog
    SubClassOf: Animal
"""

_OBO = b"""format-version: 1.2
ontology: test

[Term]
id: TEST:0001
name: animal

[Term]
id: TEST:0002
name: dog
is_a: TEST:0001 ! animal
"""


def test_convertible_set():
    assert CONVERTIBLE == frozenset({OntologyFormat.MANCHESTER, OntologyFormat.OBO})


def test_rejects_non_convertible_format():
    with pytest.raises(HornedConvertError):
        to_ntriples(b"", OntologyFormat.TURTLE)


def test_missing_binary_raises(monkeypatch):
    monkeypatch.setenv("HORNED_CONVERT_BIN", "definitely-not-a-real-binary-xyz")
    # Re-read the env at call time by patching the module-level default too.
    import ontoexplorer.modules.ingestion.horned_convert as hc
    monkeypatch.setattr(hc, "_BIN", "definitely-not-a-real-binary-xyz")
    with pytest.raises(HornedConvertError, match="not found"):
        to_ntriples(_OMN, OntologyFormat.MANCHESTER)


@pytest.mark.skipif(
    shutil.which("horned-convert") is None,
    reason="horned-convert binary not on PATH (present in the built image)",
)
def test_manchester_converts_to_ntriples():
    nt = to_ntriples(_OMN, OntologyFormat.MANCHESTER).decode()
    assert "http://example.org/Dog" in nt
    assert "http://www.w3.org/2000/01/rdf-schema#subClassOf" in nt


@pytest.mark.skipif(
    shutil.which("horned-convert") is None,
    reason="horned-convert binary not on PATH (present in the built image)",
)
def test_obo_converts_to_ntriples():
    nt = to_ntriples(_OBO, OntologyFormat.OBO).decode()
    # horned-owl emits canonical OBO PURLs + oboInOwl annotations.
    assert "http://purl.obolibrary.org/obo/TEST_0002" in nt
    assert "http://www.w3.org/2000/01/rdf-schema#subClassOf" in nt
