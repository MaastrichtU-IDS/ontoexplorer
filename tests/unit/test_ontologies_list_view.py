"""The `view=list` lean projection for GET /ontologies.

The list/table view fetches the whole catalog (~1900 rows) in one request, so
the per-row payload dominates load on slow connections. `_leanify_list_row`
trims each row to just what the table renders — roughly halving the response —
without touching the default (full) shape other consumers rely on.
"""

from ontoexplorer.api.ontologies import (
    _LIST_DESC_CAP,
    _LIST_VIEW_FIELDS,
    _leanify_list_row,
    _row_display_name,
    _row_has_language,
    _row_modified,
    _sort_rows,
)


def _full_row(**overrides):
    row = {
        "id": "onto-1",
        "iri": "http://example.org/onto",
        "shortname": "onto",
        "title": "Some Title",
        "label": "Some Ontology",
        "groups": ["obo"],
        "auto_sync": True,
        "current_version_id": "ver-1",
        "created_at": "2026-01-01T00:00:00Z",
        "owner_display_name": "Jane Doe",
        "owner_orcid": "0000-0000-0000-0001",
        "class_count": 10,
        "property_count": 5,
        "object_property_count": 3,
        "datatype_property_count": 2,
        "annotation_property_count": 1,
        "individual_count": 4,
        "triple_count": 100,
        "languages": [{"lang": "en", "label_count": 10}],
        "language_tier": "owl",
        "description": "A short description.",
        "latest_version": {
            "id": "ver-1",
            "ontology_id": "onto-1",
            "version_iri": "http://example.org/onto/1",
            "format": "turtle",
            "status": "ready",
            "sha256": "deadbeef" * 8,
            "triple_count": 100,
            "download_url": "http://example.org/onto/1.ttl",
            "created_at": "2026-02-02T00:00:00Z",
            "reasoner": "whelk",
        },
    }
    row.update(overrides)
    return row


def test_lean_row_drops_unused_siblings():
    lean = _leanify_list_row(_full_row())
    # Heavy / unrendered fields are gone.
    for dropped in ("title", "auto_sync", "current_version_id",
                    "owner_display_name", "owner_orcid", "property_count"):
        assert dropped not in lean
    # Exactly the projected fields plus the two special-cased ones.
    assert set(lean) == set(_LIST_VIEW_FIELDS) | {"latest_version", "description"}


def test_lean_row_keeps_rendered_fields():
    lean = _leanify_list_row(_full_row())
    assert lean["id"] == "onto-1"
    assert lean["iri"] == "http://example.org/onto"
    assert lean["label"] == "Some Ontology"
    assert lean["groups"] == ["obo"]
    assert lean["class_count"] == 10
    assert lean["language_tier"] == "owl"
    assert lean["languages"] == [{"lang": "en", "label_count": 10}]


def test_lean_row_collapses_latest_version_to_created_at():
    lean = _leanify_list_row(_full_row())
    # The row needs only "was it ever released, and when" — not the sha/urls/etc.
    assert lean["latest_version"] == {"created_at": "2026-02-02T00:00:00Z"}


def test_lean_row_handles_no_latest_version():
    lean = _leanify_list_row(_full_row(latest_version=None))
    assert lean["latest_version"] is None


def test_lean_row_caps_long_description():
    long = "word " * 400  # ~2000 chars
    lean = _leanify_list_row(_full_row(description=long))
    assert len(lean["description"]) <= _LIST_DESC_CAP + 1  # +1 for the ellipsis
    assert lean["description"].endswith("…")


def test_lean_row_leaves_short_description_intact():
    lean = _leanify_list_row(_full_row(description="Tiny."))
    assert lean["description"] == "Tiny."


def test_lean_row_tolerates_missing_description():
    lean = _leanify_list_row(_full_row(description=None))
    assert lean["description"] == ""


# ── Server-side sort / filter helpers (used for pagination) ────────────────────


def test_display_name_prefers_shortname():
    assert _row_display_name({"shortname": "BFO", "iri": "http://x/whatever"}) == "BFO"


def test_display_name_falls_back_to_iri_last_segment_stripping_extension():
    assert _row_display_name({"shortname": None, "iri": "http://purl.obolibrary.org/obo/pato.owl"}) == "pato"
    assert _row_display_name({"shortname": "", "iri": "http://example.org/vocab#Thing"}) == "Thing"
    assert _row_display_name({"shortname": None, "iri": "http://example.org/onto/"}) == "onto"


def test_row_modified_prefers_latest_version_then_ontology():
    assert _row_modified({"latest_version": {"created_at": "2026-02-02"}, "created_at": "2020-01-01"}) == "2026-02-02"
    assert _row_modified({"latest_version": None, "created_at": "2020-01-01"}) == "2020-01-01"
    assert _row_modified({}) == ""


def _r(name, created, lv=None):
    return {"shortname": name, "iri": f"http://x/{name}", "created_at": created,
            "latest_version": {"created_at": lv} if lv else None}


def test_sort_rows_by_name_case_insensitive():
    rows = [_r("zebra", "2020"), _r("Alpha", "2020"), _r("mango", "2020")]
    names = [r["shortname"] for r in _sort_rows(rows, "name", "asc")]
    assert names == ["Alpha", "mango", "zebra"]
    names_desc = [r["shortname"] for r in _sort_rows(rows, "name", "desc")]
    assert names_desc == ["zebra", "mango", "Alpha"]


def test_sort_rows_by_date_uses_latest_version_then_created_at():
    rows = [
        _r("a", "2020-01-01", lv="2026-05-05"),  # newest (via latest_version)
        _r("b", "2024-01-01"),                    # 2024 (no ready version)
        _r("c", "2019-01-01", lv="2022-02-02"),  # 2022
    ]
    order = [r["shortname"] for r in _sort_rows(rows, "date", "desc")]
    assert order == ["a", "b", "c"]


def test_row_has_language():
    row = {"languages": [{"lang": "en", "label_count": 5}, {"lang": "fr", "label_count": 2}]}
    assert _row_has_language(row, {"en"})
    assert _row_has_language(row, {"de", "fr"})
    assert not _row_has_language(row, {"de"})
    assert not _row_has_language({"languages": []}, {"en"})
    assert not _row_has_language({}, {"en"})
