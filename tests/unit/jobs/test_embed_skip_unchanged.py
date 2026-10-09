"""embed_ontology must not re-run the embedding model on entities whose text is
unchanged (same text_hash already stored). A re-embed of an unchanged version
should embed nothing — only new/changed entities get re-embedded."""
from ontoexplorer.modules.jobs.tasks import _filter_unchanged_records


def test_keeps_new_and_changed_drops_unchanged():
    # record = (iri, etype, text, text_hash)
    records = [
        ("http://x/a", "class", "A text", "h-a"),   # unchanged (same hash stored)
        ("http://x/b", "class", "B text", "h-b2"),  # changed (stored hash differs)
        ("http://x/c", "class", "C text", "h-c"),   # new (not stored)
    ]
    existing = {"http://x/a": "h-a", "http://x/b": "h-b1"}
    out = _filter_unchanged_records(records, existing)
    assert [r[0] for r in out] == ["http://x/b", "http://x/c"]


def test_all_unchanged_returns_empty():
    records = [("http://x/a", "class", "A", "h-a"), ("http://x/b", "class", "B", "h-b")]
    existing = {"http://x/a": "h-a", "http://x/b": "h-b"}
    assert _filter_unchanged_records(records, existing) == []


def test_no_existing_keeps_all():
    records = [("http://x/a", "class", "A", "h-a")]
    assert _filter_unchanged_records(records, {}) == records
