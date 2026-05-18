"""Unit tests for the pure coverage-computation helper."""
from ontoexplorer.modules.search.coverage import compute_coverage, ENTITY_TYPES


def _empty_by_type():
    return {t: {"total": 0, "with_label": 0, "with_definition": 0, "multilingual": 0, "by_lang": {}}
            for t in ENTITY_TYPES}


def test_empty_input_returns_zeroed_buckets_for_all_types():
    result = compute_coverage(entities={}, deprecated_iris=set(), labels_by_iri={}, defs_by_iri={})
    assert result["by_type"] == _empty_by_type()


def test_label_and_definition_counts_per_entity_type():
    entities = {"C1": "class", "C2": "class", "P1": "object_property"}
    labels = {
        "C1": [{"value": "Foo", "lang": "en"}],
        "C2": [],
        "P1": [{"value": "hasPart", "lang": ""}],
    }
    defs = {"C1": [{"value": "...", "lang": "en"}]}
    result = compute_coverage(entities, set(), labels, defs)

    cls = result["by_type"]["class"]
    assert cls["total"] == 2
    assert cls["with_label"] == 1
    assert cls["with_definition"] == 1

    op = result["by_type"]["object_property"]
    assert op["total"] == 1
    assert op["with_label"] == 1
    assert op["with_definition"] == 0


def test_multilingual_counts_distinct_lang_tags_including_empty():
    entities = {"C1": "class", "C2": "class", "C3": "class"}
    labels = {
        "C1": [{"value": "Foo", "lang": "en"}, {"value": "Voo", "lang": "fr"}],
        "C2": [{"value": "Bar", "lang": "en"}, {"value": "Baz", "lang": "en"}],
        "C3": [{"value": "Untagged", "lang": ""}, {"value": "Tagged", "lang": "en"}],
    }
    result = compute_coverage(entities, set(), labels, {})
    cls = result["by_type"]["class"]
    # C1 (en+fr) and C3 (""+en) are multilingual; C2 is not
    assert cls["multilingual"] == 2


def test_by_lang_counts_entities_not_labels():
    entities = {"C1": "class", "C2": "class"}
    labels = {
        "C1": [{"value": "Foo", "lang": "en"}, {"value": "Foo2", "lang": "en"}],
        "C2": [{"value": "Bar", "lang": "en"}, {"value": "Bär", "lang": "de"}],
    }
    result = compute_coverage(entities, set(), labels, {})
    by_lang = result["by_type"]["class"]["by_lang"]
    # Each entity contributes at most 1 per language even with multiple labels in that lang
    assert by_lang == {"en": 2, "de": 1}


def test_deprecated_entities_excluded_from_all_counts():
    entities = {"C1": "class", "C2": "class"}
    deprecated = {"C2"}
    labels = {
        "C1": [{"value": "Foo", "lang": "en"}],
        "C2": [{"value": "OldFoo", "lang": "en"}, {"value": "Vieux", "lang": "fr"}],
    }
    defs = {"C2": [{"value": "deprecated def", "lang": "en"}]}
    result = compute_coverage(entities, deprecated, labels, defs)
    cls = result["by_type"]["class"]
    assert cls["total"] == 1
    assert cls["with_label"] == 1
    assert cls["with_definition"] == 0
    assert cls["multilingual"] == 0
    assert cls["by_lang"] == {"en": 1}


def test_unknown_entity_type_is_ignored():
    # If for some reason `entities` contains a type not in ENTITY_TYPES, it's silently dropped
    entities = {"C1": "class", "X1": "weird_type"}
    result = compute_coverage(entities, set(), {"C1": [{"value": "C", "lang": "en"}]}, {})
    assert result["by_type"]["class"]["total"] == 1
    assert "weird_type" not in result["by_type"]
