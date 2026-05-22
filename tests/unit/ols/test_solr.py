"""Unit tests for the Solr-style response envelope helper (_solr.py)."""

from ontoexplorer.api.ols._solr import solr_envelope


def test_solr_envelope_empty():
    """Empty docs list produces numFound=0 and correct top-level keys."""
    out = solr_envelope(
        [],
        total=0,
        start=0,
        rows=10,
        q_params={"q": "nothing"},
        qtime_ms=5,
    )
    assert out["responseHeader"]["status"] == 0
    assert out["responseHeader"]["QTime"] == 5
    assert out["responseHeader"]["params"] == {"q": "nothing"}
    assert out["response"]["numFound"] == 0
    assert out["response"]["start"] == 0
    assert out["response"]["docs"] == []
    # OLS4 always emits 6 facet field arrays; empty when no faceting requested.
    assert sorted(out["facet_counts"]["facet_fields"].keys()) == [
        "isDefiningOntology", "isObsolete",
        "ontologyId", "ontologyIri", "ontologyPreferredPrefix", "type",
    ]
    assert all(v == [] for v in out["facet_counts"]["facet_fields"].values())
    assert out["highlighting"] == {}


def test_solr_envelope_populated():
    """Three docs in → numFound=3, docs returned correctly."""
    docs = [
        {"iri": "http://example.org/A", "label": "A"},
        {"iri": "http://example.org/B", "label": "B"},
        {"iri": "http://example.org/C", "label": "C"},
    ]
    out = solr_envelope(
        docs,
        total=3,
        start=0,
        rows=10,
        q_params={"q": "foo", "rows": "10"},
        qtime_ms=12,
    )
    assert out["response"]["numFound"] == 3
    assert out["response"]["start"] == 0
    assert len(out["response"]["docs"]) == 3
    assert out["response"]["docs"][0]["label"] == "A"
    assert out["responseHeader"]["QTime"] == 12


def test_solr_envelope_facets_passthrough():
    """Facet data provided is embedded in facet_counts.facet_fields unchanged."""
    facets = {"ontology_name": ["go", 5, "chebi", 3]}
    out = solr_envelope(
        [],
        total=0,
        start=0,
        rows=10,
        q_params={"q": "test"},
        qtime_ms=1,
        facets=facets,
    )
    # Supplied facets are merged on top of the 6 default keys.
    assert out["facet_counts"]["facet_fields"]["ontology_name"] == facets["ontology_name"]
    # Defaults are still present (empty when not overridden).
    assert out["facet_counts"]["facet_fields"]["isObsolete"] == []


def test_solr_envelope_highlighting_passthrough():
    """Highlighting data provided is embedded in highlighting unchanged."""
    hl = {"http://example.org/A": {"label": ["<em>Foo</em>"]}}
    out = solr_envelope(
        [],
        total=0,
        start=0,
        rows=10,
        q_params={"q": "foo"},
        qtime_ms=2,
        highlighting=hl,
    )
    assert out["highlighting"] == hl


def test_solr_envelope_start_offset_reflected():
    """start value is reflected in response.start."""
    out = solr_envelope(
        [],
        total=50,
        start=20,
        rows=10,
        q_params={"q": "bar", "start": "20"},
        qtime_ms=3,
    )
    assert out["response"]["start"] == 20
    assert out["response"]["numFound"] == 50
