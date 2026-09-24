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
