"""The _fetch_onto_triples blank-node fallback must NOT adopt a title from a
loaded owl:imports dependency. Imported ontologies have NAMED owl:Ontology
subjects; the fallback is restricted to isBlank(?onto), so an importing ontology
that declares no own title falls back to its shortname instead of bleeding the
imported ontology's title (regression: ~94 ontologies mis-titled from imported
SKOS/BFO/SIO/SWEET nodes)."""
from ontoexplorer.modules.meta_profile import detector

_TITLE = "http://purl.org/dc/terms/title"


class _Lit:
    def __init__(self, v):
        self.value = v
        self.language = None


class _Row:
    def __init__(self, pred, obj):
        self._d = {"pred": _Lit(pred), "obj": obj}

    def __getitem__(self, k):
        return self._d[k]


def test_fallback_restricted_to_blank_nodes(monkeypatch):
    """Host IRI has no title; only a NAMED imported owl:Ontology node exists →
    the isBlank fallback matches nothing → no title bled."""
    captured = []

    def fake_sparql(q):
        captured.append(q)
        if f"<{_TITLE}>" in q and "host.example" in q:
            return []  # host IRI carries no title
        # fallback query: a real store would return nothing because the only
        # owl:Ontology nodes (imported SKOS/BFO/…) are NAMED, not blank.
        return []

    monkeypatch.setattr(detector, "sparql_query", fake_sparql)
    triples = detector._fetch_onto_triples("urn:g", "http://host.example/onto")

    assert _TITLE not in triples          # nothing bled
    # the fallback actually ran and is scoped to blank nodes
    assert any("isBlank(?onto)" in q for q in captured)


def test_blank_node_header_still_resolved(monkeypatch):
    """A genuine blank-node header ([] a owl:Ontology ; dcterms:title "X") is
    still picked up by the fallback."""
    def fake_sparql(q):
        if f"<{_TITLE}>" in q and "host.example" in q:
            return []  # host IRI itself has no title
        if "isBlank(?onto)" in q:
            return [_Row(_TITLE, _Lit("My Vocabulary"))]
        return []

    monkeypatch.setattr(detector, "sparql_query", fake_sparql)
    triples = detector._fetch_onto_triples("urn:g", "http://host.example/onto")

    assert _TITLE in triples
    assert triples[_TITLE][0]["value"] == "My Vocabulary"
