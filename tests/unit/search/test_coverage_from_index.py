"""Unit tests for the entity_index → coverage payload assembly."""
from ontoexplorer.modules.search.coverage import ENTITY_TYPES, _assemble_coverage


def test_assembles_by_type_and_by_lang():
    agg = [
        ("class", 100, 98, 80, 30),
        ("individual", 10, 9, 2, 1),
    ]
    lang = [
        ("class", "en", 98),
        ("class", "fr", 30),
        ("class", "", 5),
        ("individual", "en", 9),
    ]
    out = _assemble_coverage(agg, lang, "vid-1", "2026-11-11T00:00:00+00:00")

    assert out["version_id"] == "vid-1"
    assert out["indexed_at"] == "2026-11-11T00:00:00+00:00"
    assert set(out["by_type"]) == set(ENTITY_TYPES)

    cls = out["by_type"]["class"]
    assert (cls["total"], cls["with_label"], cls["with_definition"], cls["multilingual"]) == (100, 98, 80, 30)
    assert cls["by_lang"] == {"en": 98, "fr": 30, "": 5}

    ind = out["by_type"]["individual"]
    assert ind["total"] == 10 and ind["by_lang"] == {"en": 9}

    # A type with no rows stays zeroed, not absent.
    prop = out["by_type"]["object_property"]
    assert prop == {"total": 0, "with_label": 0, "with_definition": 0, "multilingual": 0, "by_lang": {}}


def test_unknown_types_are_ignored():
    # entity_index.type may hold values outside the coverage ENTITY_TYPES
    # (mirroring compute_coverage's `entity_type not in by_type` skip).
    agg = [("ontology", 5, 5, 0, 0), ("class", 3, 3, 1, 0)]
    lang = [("ontology", "en", 5), ("class", "en", 3)]
    out = _assemble_coverage(agg, lang, "v", None)
    assert "ontology" not in out["by_type"]
    assert out["by_type"]["class"]["total"] == 3
    assert out["by_type"]["class"]["by_lang"] == {"en": 3}


def test_indexed_at_omitted_when_none():
    out = _assemble_coverage([], [], "v", None)
    assert "indexed_at" not in out
    assert out["version_id"] == "v"
    # Every coverage type present and zeroed.
    assert all(out["by_type"][t]["total"] == 0 for t in ENTITY_TYPES)


def test_values_coerced_to_int():
    # DB drivers may hand back Decimal/str for count(*); the payload must be ints.
    agg = [("class", "7", "7", "5", "2")]
    lang = [("class", "en", "7")]
    out = _assemble_coverage(agg, lang, "v", None)
    cls = out["by_type"]["class"]
    assert cls["total"] == 7 and isinstance(cls["total"], int)
    assert cls["by_lang"]["en"] == 7 and isinstance(cls["by_lang"]["en"], int)
