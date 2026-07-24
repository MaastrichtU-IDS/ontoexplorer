"""Regression test for the individuals branch of `list_terms`.

Guards against a closure-scoping bug where `_run_individuals` referenced
`_label_score`, which was `def`-ed *after* the individuals branch in the
enclosing `list_terms`. Python therefore treated `_label_score` as a local of
`list_terms` that was unbound when the individuals path ran, so any ontology
with >=1 named individual raised:

    NameError: cannot access free variable '_label_score' where it is not
    associated with a value in enclosing scope

The error only fires when the store returns at least one row (the call sits
inside the result loop), so the mock store below must yield a row.
"""
import pytest

from ontoexplorer.api import ontologies as ont_api


class _Node:
    """Minimal stand-in for a pyoxigraph term node."""
    def __init__(self, value, language=None):
        self.value = value
        self.language = language


class _FakeStore:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _q):
        return iter(self._rows)


@pytest.mark.anyio
async def test_list_terms_individuals_returns_rows(monkeypatch):
    async def _fake_version(*_a, **_k):
        return object()

    monkeypatch.setattr(ont_api, "_get_version_or_404", _fake_version)
    # get_store / graph_iri are imported inside list_terms from this module
    from ontoexplorer.clients import oxigraph as ox
    rows = [{"entity": _Node("http://example.org/family#alice"),
             "label": _Node("Alice", "en")}]
    monkeypatch.setattr(ox, "get_store", lambda: _FakeStore(rows))
    monkeypatch.setattr(ox, "graph_iri", lambda *_a, **_k: "urn:g")

    result = await ont_api.list_terms(
        ontology_id="o1",
        version_id="v1",
        parent=None,
        entity_type="individual",
        db=None,
    )

    iris = [t["iri"] for t in result["terms"]]
    assert "http://example.org/family#alice" in iris
    alice = next(t for t in result["terms"] if t["iri"].endswith("alice"))
    assert alice["label"] == "Alice"
    assert alice["lang"] == "en"
    assert alice["has_children"] is False
