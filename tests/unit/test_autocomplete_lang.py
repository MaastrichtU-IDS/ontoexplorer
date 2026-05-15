from ontoexplorer.modules.search.autocomplete import _parse_lang_from_member


def test_parse_lang_from_four_part_key():
    member = "cell death|en|class|http://purl.obolibrary.org/obo/GO_0008150"
    norm, lang, etype, iri = _parse_lang_from_member(member)
    assert norm == "cell death"
    assert lang == "en"
    assert etype == "class"
    assert iri == "http://purl.obolibrary.org/obo/GO_0008150"


def test_parse_lang_untagged_literal():
    member = "cell death||class|http://example.org/Cell"
    norm, lang, etype, iri = _parse_lang_from_member(member)
    assert lang == ""


def test_parse_lang_v1_fallback():
    member = "cell death|class|http://example.org/Cell"
    norm, lang, etype, iri = _parse_lang_from_member(member)
    assert lang == ""
    assert etype == "class"
    assert iri == "http://example.org/Cell"
