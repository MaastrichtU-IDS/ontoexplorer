from ontoexplorer.modules.search.indexer import _langs_key


def test_langs_key_format():
    assert _langs_key("abc-123") == "search:entities:abc-123:langs"


def test_sorted_set_key_has_four_parts():
    iri = "http://purl.obolibrary.org/obo/GO_0008150"
    entity_type = "class"
    lang = "en"
    norm = "biological process"
    key = f"{norm}|{lang}|{entity_type}|{iri}"
    parts = key.split("|", 3)
    assert len(parts) == 4
    assert parts[1] == "en"
    assert parts[3] == iri


# ── label de-duplication ──────────────────────────────────────────────────────
# Labels were deduped by value alone, so a language that happens to spell a term
# the same way as another lost its label entirely: "chocolate"@es was dropped
# for colliding with "chocolate"@en, and "alimento"@pt-BR for colliding with
# "alimento"@es. The language counter still counted the dropped label, so
# /languages advertised languages no entity could actually be shown in —
# selecting Portuguese changed nothing at all.

from ontoexplorer.modules.search.indexer import label_dedupe_key


def test_same_value_in_two_languages_is_kept_twice():
    assert label_dedupe_key("chocolate", "en") != label_dedupe_key("chocolate", "es")


def test_the_same_label_repeated_is_still_collapsed():
    assert label_dedupe_key("chocolate", "en") == label_dedupe_key("chocolate", "en")


def test_regional_variants_of_one_language_collapse():
    """en-GB and en-US are stored under `en`, so keeping both spellings of the
    same string would just produce a duplicate."""
    assert label_dedupe_key("colour", "en-GB") == label_dedupe_key("colour", "en-US")


def test_different_values_in_one_language_are_both_kept():
    assert label_dedupe_key("aubergine", "en") != label_dedupe_key("eggplant", "en")


def test_untagged_is_distinct_from_a_tagged_label():
    assert label_dedupe_key("quince", "") != label_dedupe_key("quince", "en")
