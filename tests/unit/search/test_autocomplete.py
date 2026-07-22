"""Unit tests for the autocomplete engine."""
import fakeredis
from unittest.mock import patch

from ontoexplorer.modules.search.autocomplete import get_completions
from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key


def _setup_redis(version_id: str) -> fakeredis.FakeRedis:
    r = fakeredis.FakeRedis(decode_responses=True)
    key = _prefix_key(version_id)
    # Two "cell death" entries with different IRIs (ambiguous)
    r.zadd(key, {"cell death|class|http://go.org/CD": 0})
    r.zadd(key, {"cell death|class|http://mondo.org/CD": 0})
    r.zadd(key, {"cell division|class|http://go.org/CDV": 0})
    r.zadd(key, {"has part|property|http://bfo.org/HP": 0})
    r.hset(_iri_key(version_id, "http://go.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://go.org/CD", "short": "GO:CD", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://mondo.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://mondo.org/CD", "short": "MONDO:CD", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://go.org/CDV"), mapping={
        "label": "cell division", "type": "class",
        "iri": "http://go.org/CDV", "short": "GO:CDV", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://bfo.org/HP"), mapping={
        "label": "has part", "type": "property",
        "iri": "http://bfo.org/HP", "short": "BFO:HP", "synonyms": "",
    })
    return r


def test_completions_open_quote_returns_entities():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell d", cursor=7, version_id="v1", limit=10)
    texts = [c.text for c in completions]
    assert any("cell death" in t for t in texts)
    assert any("cell division" in t for t in texts)


def test_completions_disambiguated_label_shown_for_ambiguous():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell death", cursor=11, version_id="v1", limit=10)
    # Should see two completions with CURIE disambiguation
    inserts = [c.insert for c in completions if c.type == "class"]
    assert any("GO:CD" in ins for ins in inserts)
    assert any("MONDO:CD" in ins for ins in inserts)
    # Both inserts should end with closing quote
    assert all(ins.endswith("'") for ins in inserts)


def test_completions_unambiguous_label_no_curie():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell div", cursor=9, version_id="v1", limit=10)
    inserts = [c.insert for c in completions]
    assert any(ins == "cell division'" for ins in inserts)


def test_completions_after_entity_returns_only_boolean_keywords():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'Cell'", cursor=6, version_id="v1", limit=20)
    kw_texts = {c.text for c in completions if c.type == "keyword"}
    assert "and" in kw_texts
    assert "or" in kw_texts
    assert "not" in kw_texts
    assert "(" in kw_texts
    assert ")" in kw_texts
    # Restriction keywords must NOT appear after a closed entity
    assert "some" not in kw_texts
    assert "only" not in kw_texts


def test_completions_no_partial_includes_not():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        # After 'and' with no partial — EXPECT_ENTITY with no partial text
        completions = get_completions("'Cell' and ", cursor=11, version_id="v1", limit=20)
    kw_texts = {c.text for c in completions if c.type == "keyword"}
    assert "not" in kw_texts
    assert "'" in kw_texts


def test_completions_after_open_paren_includes_not():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("(", cursor=1, version_id="v1", limit=20)
    kw_texts = {c.text for c in completions if c.type == "keyword"}
    assert "not" in kw_texts


def test_completions_after_close_paren_returns_boolean_keywords():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("('Cell')", cursor=7, version_id="v1", limit=20)
    kw_texts = {c.text for c in completions if c.type == "keyword"}
    assert "and" in kw_texts
    assert "or" in kw_texts
    assert "some" not in kw_texts


def test_completions_after_some_returns_only_classes():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'hasPart' some 'cell", cursor=20, version_id="v1", limit=10)
    types = {c.type for c in completions}
    assert "class" in types
    assert "property" not in types


def test_completions_after_min_returns_int_hint():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'hasPart' min ", cursor=14, version_id="v1", limit=10)
    types = {c.type for c in completions}
    assert "cardinality" in types


def test_completions_excludes_annotation_properties():
    r = fakeredis.FakeRedis(decode_responses=True)
    key = _prefix_key("v1")
    r.zadd(key, {"cell death|class|http://ex.org/CD": 0})
    r.zadd(key, {"comment|annotation_property|http://www.w3.org/2000/01/rdf-schema#comment": 0})
    r.hset(_iri_key("v1", "http://ex.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://ex.org/CD", "short": "CD", "synonyms": "",
    })
    r.hset(_iri_key("v1", "http://www.w3.org/2000/01/rdf-schema#comment"), mapping={
        "label": "comment", "type": "annotation_property",
        "iri": "http://www.w3.org/2000/01/rdf-schema#comment", "short": "rdfs:comment", "synonyms": "",
    })
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'", cursor=1, version_id="v1", limit=10)
    types = {c.type for c in completions}
    assert "class" in types
    assert "annotation_property" not in types


def test_keyword_completion_after_property_offers_restriction_keywords():
    r = _setup_redis("v1")
    q = "'has part' "
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        comps = get_completions(q, cursor=len(q), version_id="v1", limit=10)
    texts = {c.text for c in comps}
    # After an object property, MOS expects a restriction keyword, not and/or.
    assert {"some", "only", "value", "min", "max", "exactly", "Self"} <= texts
    assert "and" not in texts


def test_keyword_completion_after_class_offers_boolean_keywords():
    r = _setup_redis("v1")
    q = "'cell death' "
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        comps = get_completions(q, cursor=len(q), version_id="v1", limit=10)
    texts = {c.text for c in comps}
    assert {"and", "or"} <= texts
    assert "some" not in texts


# ── Unified mos_autocomplete: pure keyword-set logic ──────────────────────────
from ontoexplorer.modules.search.autocomplete import keyword_set_for, _kw_dict  # noqa: E402


def test_keyword_set_for_property_vs_class():
    assert keyword_set_for("EXPECT_KEYWORD", prev_is_property=True) == \
        ["some", "only", "value", "min", "max", "exactly", "Self"]
    assert keyword_set_for("EXPECT_KEYWORD", prev_is_property=False) == \
        ["and", "or", "not", "(", ")"]


def test_keyword_set_for_int_and_entity_open():
    assert keyword_set_for("EXPECT_INT", False) == ["1", "2", "3"]
    assert keyword_set_for("EXPECT_ENTITY", False) == ["not", "'"]


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
