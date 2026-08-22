"""Language handling on the SQL-backed tree paths.

Those paths read entity_index, which stored one primary_label and no record of
its language. So they were gated on `lang is None` and any language selection
fell back to Oxigraph — DRON's tree went from 0.033 s to 12.0 s — and every node
reported lang=null, which silently removed the tree's language badges.

The resolution order has to match the SPARQL path's `_label_score`:
requested language > English > untagged > anything else.
"""
import pytest

from ontoexplorer.modules.hierarchy.edges import fetch_roots, resolve_label

LABELS = {"en": "food", "fr": "aliment", "de": "Lebensmittel", "": "untagged form"}


def test_requested_language_wins():
    assert resolve_label(LABELS, "primary", "en", "fr") == ("aliment", "fr")


def test_falls_back_to_english_when_the_language_is_absent():
    assert resolve_label(LABELS, "primary", "en", "ja") == ("food", "en")


def test_falls_back_to_untagged_before_another_language():
    labels = {"fr": "poire", "": "plain"}
    assert resolve_label(labels, "primary", None, "ja") == ("plain", None)


def test_falls_back_to_any_language_as_a_last_resort():
    labels = {"fr": "poire", "de": "Birne"}
    value, lang = resolve_label(labels, "primary", "fr", "ja")
    assert (value, lang) in {("poire", "fr"), ("Birne", "de")}


def test_no_language_requested_uses_the_primary_label():
    """Without a request there is nothing to prefer, and primary_label is
    already the indexer's choice — English if the entity has one."""
    assert resolve_label(LABELS, "food", "en", None) == ("food", "en")


def test_empty_label_map_falls_back_to_the_primary_label():
    """Versions indexed before labels were recorded have an empty map; they must
    still render, and report the primary label's language if it is known."""
    assert resolve_label({}, "fallback", "en", "fr") == ("fallback", "en")
    assert resolve_label({}, "fallback", None, "fr") == ("fallback", None)


def test_untagged_is_reported_as_no_language():
    """An untagged label has no tag to badge, so it must report None rather
    than the empty string the map keys it under."""
    assert resolve_label({"": "plain"}, "plain", None, "ja") == ("plain", None)


# ── through the query ─────────────────────────────────────────────────────────

async def _seed(db, version_id, iri, primary, labels, primary_lang, is_root=True):
    from ontoexplorer.models.db import EntityIndex
    db.add(EntityIndex(
        version_id=version_id, iri=iri, ontology_id="o1", type="class",
        primary_label=primary, primary_label_norm=primary.lower(),
        short=iri.rsplit("/", 1)[-1], search_text=primary, deprecated=False,
        is_root=is_root, is_individual=False, labels=labels,
        primary_lang=primary_lang,
    ))
    await db.commit()


@pytest.mark.anyio
async def test_roots_return_the_requested_language(db_session):
    v = "v-lang"
    await _seed(db_session, v, "http://x/Food", "food",
                {"en": "food", "fr": "aliment"}, "en")

    en = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=10, offset=0)
    fr = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=10, offset=0,
                           lang="fr")
    assert (en[0]["label"], en[0]["lang"]) == ("food", "en")
    assert (fr[0]["label"], fr[0]["lang"]) == ("aliment", "fr")


@pytest.mark.anyio
async def test_roots_report_a_language_so_the_tree_can_badge_it(db_session):
    """ClassTree renders its badge only when a node reports a lang; the SQL
    paths returned null for every node, so the badges vanished."""
    v = "v-badge"
    await _seed(db_session, v, "http://x/A", "apple", {"en": "apple"}, "en")
    rows = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=10, offset=0)
    assert rows[0]["lang"] == "en"


@pytest.mark.anyio
async def test_roots_sort_by_the_language_being_displayed(db_session):
    """Ordering follows the labels actually shown, or the list looks unsorted."""
    v = "v-sort-lang"
    await _seed(db_session, v, "http://x/1", "apple", {"en": "apple", "fr": "zebre"}, "en")
    await _seed(db_session, v, "http://x/2", "zebra", {"en": "zebra", "fr": "abricot"}, "en")

    en = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=10, offset=0)
    fr = await fetch_roots(db_session, v, "class", hide_obsolete=True, limit=10, offset=0,
                           lang="fr")
    assert [r["label"] for r in en] == ["apple", "zebra"]
    assert [r["label"] for r in fr] == ["abricot", "zebre"]


def test_labels_may_arrive_as_a_json_string():
    """Raw text() SQL declares no column types, so the driver returns JSON as a
    string. Both asyncpg and sqlite do it; the resolver must cope either way."""
    import json
    as_str = json.dumps({"en": "food", "fr": "aliment"})
    assert resolve_label(as_str, "primary", "en", "fr") == ("aliment", "fr")
    assert resolve_label("not json at all", "primary", "en", "fr") == ("primary", "en")


def test_regional_tags_are_matched_by_their_primary_subtag():
    """Requests carry canonical tags ("en") but ontologies label with regional
    ones ("en-GB"). Without collapsing, asking for English on a class labelled
    only en-GB/en-US fell through to whatever sorted first — German, in the
    fixture. /languages already collapses these, so the map must too.
    """
    labels = {"en": "aubergine", "de": "Aubergine", "es": "berenjena"}
    assert resolve_label(labels, "aubergine", "en", "en") == ("aubergine", "en")
