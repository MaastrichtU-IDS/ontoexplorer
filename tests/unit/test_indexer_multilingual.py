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
