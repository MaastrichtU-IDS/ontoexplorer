"""Tests for the pre-enqueue admission gate."""

from __future__ import annotations

import pytest

from ontoexplorer.modules.discovery import gate
from ontoexplorer.modules.discovery.gate import admit
from ontoexplorer.modules.discovery.models import Candidate

_ALLOWLIST = {"CC-BY-4.0", "CC0-1.0"}


def _cand(**extra) -> Candidate:
    base = {
        "canonical_iri": "http://example.org/onto",
        "title": "Example",
        "source_catalogue_id": "agroportal",
        "source_catalogue_label": "AgroPortal",
    }
    base.update(extra)
    return Candidate(**base)


@pytest.fixture(autouse=True)
def _gate_env(monkeypatch):
    """Unknown IRI by default and a fixed non-empty allowlist (no DB/settings)."""

    async def _none(db, iri, *, exclude_id=None):
        return None

    monkeypatch.setattr(gate, "find_ontology_by_canonical_iri", _none)
    monkeypatch.setattr(gate, "compliant_license_set", lambda: set(_ALLOWLIST))


async def test_admits_clean_candidate():
    d = await admit(None, _cand(license="http://creativecommons.org/licenses/by/4.0/"))
    assert d.admit is True
    assert d.reason == "ok"


async def test_rejects_known_duplicate(monkeypatch):
    async def _found(db, iri, *, exclude_id=None):
        return object()

    monkeypatch.setattr(gate, "find_ontology_by_canonical_iri", _found)
    d = await admit(None, _cand())
    assert (d.admit, d.reason) == (False, "duplicate")


async def test_rejects_recognised_noncompliant_license():
    d = await admit(None, _cand(license="http://creativecommons.org/licenses/by-nc/4.0/"))
    assert (d.admit, d.reason) == (False, "license_noncompliant")


async def test_admits_license_absent():
    d = await admit(None, _cand(license=None))
    assert (d.admit, d.reason) == (True, "ok")


async def test_admits_unmappable_license():
    d = await admit(None, _cand(license="All rights reserved"))
    assert (d.admit, d.reason) == (True, "ok")


async def test_admits_noncompliant_license_when_allowlist_empty(monkeypatch):
    monkeypatch.setattr(gate, "compliant_license_set", lambda: set())
    d = await admit(None, _cand(license="http://creativecommons.org/licenses/by-nc/4.0/"))
    assert (d.admit, d.reason) == (True, "ok")


async def test_rejects_missing_title():
    for title in ("", "   "):
        d = await admit(None, _cand(title=title))
        assert (d.admit, d.reason) == (False, "no_title")


@pytest.mark.parametrize("iri", ["urn:uuid:1234", "", "ftp://example.org/o"])
async def test_rejects_non_http_iri(iri):
    d = await admit(None, _cand(canonical_iri=iri))
    assert (d.admit, d.reason) == (False, "bad_iri")


async def test_check_order_bad_iri_beats_no_title():
    d = await admit(None, _cand(canonical_iri="urn:x", title=""))
    assert d.reason == "bad_iri"
