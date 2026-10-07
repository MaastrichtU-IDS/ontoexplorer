"""Unit tests for the autocomplete engine."""
from unittest.mock import patch


# ── Unified mos_autocomplete: pure keyword-set logic ──────────────────────────
from ontoexplorer.modules.search.autocomplete import keyword_set_for, _kw_dict  # noqa: E402


def test_keyword_set_for_property_vs_class():
    assert keyword_set_for("EXPECT_KEYWORD", prev_is_property=True) == \
        ["some", "only", "value", "min", "max", "exactly", "Self"]
    assert keyword_set_for("EXPECT_KEYWORD", prev_is_property=False) == \
        ["and", "or", "not", "(", ")"]


def test_keyword_set_for_int_and_entity_open():
    assert keyword_set_for("EXPECT_INT", False) == ["1", "2", "3"]
    # `inverse` starts an inverse-property restriction, valid anywhere a class
    # expression can begin.
    assert keyword_set_for("EXPECT_ENTITY", False) == ["not", "inverse", "'"]


def test_keyword_set_for_after_inverse_offers_paren_and_quote():
    # Right after `inverse`, a property is expected — offer `(` (Protégé-style
    # `inverse (P)`) or a quote; not / inverse are invalid.
    assert keyword_set_for("EXPECT_ENTITY", False, after_inverse=True) == ["(", "'"]


def test_kw_dict_insert_and_type():
    assert _kw_dict("some")["insert"] == "some "        # trailing space
    assert _kw_dict("(")["insert"] == "("               # opening token: no space
    assert _kw_dict("'")["insert"] == "'"
    assert _kw_dict("1")["type"] == "cardinality"
    assert _kw_dict("and")["type"] == "keyword"


def test_observed_filler_iris_queries_all_scoped_graphs():
    """Filler lookup fans out over every graph in scope via a VALUES clause,
    so the front-page (multi-ontology) path finds fillers too."""
    from ontoexplorer.modules.search import autocomplete as ac

    captured = {}

    class _FakeStore:
        def query(self, q):
            captured["q"] = q
            return []

    with patch("ontoexplorer.clients.oxigraph.get_store", lambda: _FakeStore()):
        ac._observed_filler_iris(
            "http://bfo.org/HP",
            ["http://g/sulo", "http://g/go"],
            10,
        )

    q = captured["q"]
    assert "VALUES ?g {" in q
    assert "<http://g/sulo>" in q and "<http://g/go>" in q
    assert "GRAPH ?g" in q
    assert "<http://bfo.org/HP>" in q


def test_observed_filler_iris_ranks_by_frequency():
    """Fillers are aggregated and ordered most-used-first, so the SPARQL counts
    usages and sorts descending (IRI as the deterministic tiebreaker)."""
    from ontoexplorer.modules.search import autocomplete as ac

    captured = {}

    class _FakeStore:
        def query(self, q):
            captured["q"] = q
            return []

    with patch("ontoexplorer.clients.oxigraph.get_store", lambda: _FakeStore()):
        ac._observed_filler_iris("http://bfo.org/HP", ["http://g/sulo"], 10)

    q = captured["q"]
    assert "COUNT(DISTINCT ?r)" in q
    assert "GROUP BY ?f" in q
    assert "ORDER BY DESC(?n)" in q


def test_observed_filler_iris_value_queries_hasvalue_individuals():
    """For a `value` restriction the fillers are INDIVIDUALS drawn from
    owl:hasValue, not classes — the query must use hasValue, not
    someValuesFrom/onClass."""
    from ontoexplorer.modules.search import autocomplete as ac

    captured = {}

    class _FakeStore:
        def query(self, q):
            captured["q"] = q
            return []

    with patch("ontoexplorer.clients.oxigraph.get_store", lambda: _FakeStore()):
        ac._observed_filler_iris("http://bfo.org/HP", ["http://g/sulo"], 10, keyword="value")

    q = captured["q"]
    assert "hasValue" in q
    assert "someValuesFrom" not in q
    assert "onClass" not in q


def test_observed_filler_iris_default_keyword_queries_classes():
    """Non-value keywords keep the class-restriction query."""
    from ontoexplorer.modules.search import autocomplete as ac

    captured = {}

    class _FakeStore:
        def query(self, q):
            captured["q"] = q
            return []

    with patch("ontoexplorer.clients.oxigraph.get_store", lambda: _FakeStore()):
        ac._observed_filler_iris("http://bfo.org/HP", ["http://g/sulo"], 10, keyword="some")

    q = captured["q"]
    assert "someValuesFrom" in q
    assert "hasValue" not in q
