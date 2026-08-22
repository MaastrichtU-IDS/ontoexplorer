from unittest.mock import MagicMock
from ontoexplorer.modules.search.lang import canonical_lang, resolve_lang


def _user(lang):
    u = MagicMock()
    u.preferred_lang = lang
    return u

def _ontology(lang):
    o = MagicMock()
    o.preferred_lang = lang
    return o


def test_query_param_wins_over_all():
    assert resolve_lang("fr", _ontology("de"), _user("en")) == "fr"

def test_user_pref_beats_any_ontology_setting():
    """Reversed deliberately. The ontology default used to win, so a reader who
    had chosen English saw German because an owner had set it — a dataset
    default overriding a stated personal preference."""
    assert resolve_lang(None, _ontology("de"), _user("en")) == "en"

def test_user_pref_used_when_nothing_is_requested():
    assert resolve_lang(None, _ontology(None), _user("en")) == "en"

def test_none_when_no_preference():
    assert resolve_lang(None, _ontology(None), _user(None)) is None

def test_empty_string_query_param_treated_as_none():
    assert resolve_lang("", _ontology(None), _user("en")) == "en"


def test_canonical_lang_strips_subtag():
    assert canonical_lang("en-US") == "en"
    assert canonical_lang("en-GB") == "en"
    assert canonical_lang("pt-BR") == "pt"

def test_canonical_lang_lowercases():
    assert canonical_lang("EN") == "en"
    assert canonical_lang("Fr-FR") == "fr"

def test_canonical_lang_preserves_empty():
    assert canonical_lang("") == ""
    assert canonical_lang("   ") == ""

def test_canonical_lang_handles_already_canonical():
    assert canonical_lang("de") == "de"
    assert canonical_lang("zh") == "zh"


# ── pick_label ────────────────────────────────────────────────────────────────
# The term-detail endpoint picked entries[0] when the requested language was
# absent — arbitrary source order, with no preference for English or untagged.
# On a class whose profile also treats skos:altLabel as a label, the synonym
# came first and won: asking for Portuguese on a class labelled in nine
# languages returned the German *synonym* "Nahrung". It then reported that as
# lang="pt", because the response echoed the requested language rather than the
# language of the label it actually chose.

from ontoexplorer.modules.search.lang import pick_label

ENTRIES = [
    {"value": "Nahrung", "lang": "de"},      # a synonym, listed first
    {"value": "food", "lang": "en"},
    {"value": "aliment", "lang": "fr"},
    {"value": "plain", "lang": ""},
]


def test_requested_language_wins():
    assert pick_label(ENTRIES, "fr") == ("aliment", "fr")


def test_falls_back_to_english_not_to_whatever_is_first():
    assert pick_label(ENTRIES, "pt") == ("food", "en")


def test_falls_back_to_untagged_before_another_language():
    entries = [{"value": "Nahrung", "lang": "de"}, {"value": "plain", "lang": ""}]
    assert pick_label(entries, "pt") == ("plain", None)


def test_falls_back_to_any_language_as_a_last_resort():
    entries = [{"value": "Nahrung", "lang": "de"}]
    assert pick_label(entries, "pt") == ("Nahrung", "de")


def test_reports_the_language_actually_chosen_not_the_one_requested():
    _, lang = pick_label(ENTRIES, "pt")
    assert lang == "en", "must not echo the requested language back"


def test_regional_tags_match_their_primary_subtag():
    entries = [{"value": "colour", "lang": "en-GB"}]
    assert pick_label(entries, "en") == ("colour", "en")


def test_no_entries_yields_nothing():
    assert pick_label([], "en") == (None, None)


def test_no_language_requested_keeps_source_order():
    """Without a preference there is nothing to score, so the first entry — the
    order the profile's label properties were queried in — stands."""
    assert pick_label(ENTRIES, None) == ("Nahrung", "de")


# ── resolve_lang precedence ───────────────────────────────────────────────────
# An ontology-wide default used to sit *above* the user's own preference, so
# someone who set French in their profile was shown English anyway if an owner
# had set the ontology to English. A dataset default overriding a person's
# stated preference is backwards, and the concept is gone: language is a
# property of the reader, not of the ontology.


class _User:
    def __init__(self, lang):
        self.preferred_lang = lang


def test_an_explicit_request_wins():
    assert resolve_lang("fr", None, _User("de")) == "fr"


def test_the_user_preference_is_used_when_nothing_is_requested():
    assert resolve_lang(None, None, _User("de")) == "de"


def test_an_empty_request_is_treated_as_absent():
    assert resolve_lang("", None, _User("de")) == "de"


def test_no_request_and_no_user_preference_means_all_languages():
    assert resolve_lang(None, None, None) is None
    assert resolve_lang(None, None, _User(None)) is None


def test_the_ontology_argument_no_longer_influences_anything():
    """Kept in the signature so the three call sites need not change shape, but
    it must not be consulted: it was overriding the reader's own choice."""
    class _Ontology:
        preferred_lang = "es"
    assert resolve_lang(None, _Ontology(), _User("de")) == "de"
    assert resolve_lang(None, _Ontology(), None) is None
