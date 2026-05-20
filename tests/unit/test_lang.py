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

def test_ontology_override_wins_over_user():
    assert resolve_lang(None, _ontology("de"), _user("en")) == "de"

def test_user_pref_used_when_no_override():
    assert resolve_lang(None, _ontology(None), _user("en")) == "en"

def test_none_when_no_preference():
    assert resolve_lang(None, _ontology(None), _user(None)) is None

def test_empty_string_query_param_treated_as_none():
    assert resolve_lang("", _ontology("de"), _user("en")) == "de"


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
