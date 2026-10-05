"""#242 Stage 1 PR 2: entity_index -> OLS renderer parity.

The entity payload moves from the Redis `:iri:` hash to entity_index. This proves
the adapter feeds the existing renderers an input that yields byte-identical output
to the Redis-hash input, so response shape is preserved.
"""
import json
from types import SimpleNamespace

from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict, entity_to_v1_term


def _ontology():
    return SimpleNamespace(shortname="go", id="onto-uuid", iri="http://purl.obolibrary.org/obo/go.owl")


def _request():
    return SimpleNamespace(base_url="http://test/")


def test_adapter_shapes_labels_synonyms_definitions():
    row = SimpleNamespace(
        iri="http://x/Foo", primary_label="Foo", short="Foo", type="class", source="go",
        labels={"en": "Foo", "": "Untagged"},
        synonyms=[{"value": "F", "lang": "en"}],
        definitions=[{"value": "a foo", "lang": "en"}],
    )
    d = entity_index_to_legacy_dict(row)
    assert d["iri"] == "http://x/Foo"
    assert d["label"] == d["primary_label"] == "Foo"     # back-compat alias
    assert d["short"] == "Foo" and d["type"] == "class" and d["source"] == "go"
    assert json.loads(d["labels"]) == [{"value": "Foo", "lang": "en"}, {"value": "Untagged", "lang": ""}]
    assert json.loads(d["synonyms"]) == [{"value": "F", "lang": "en"}]
    assert json.loads(d["definitions"]) == [{"value": "a foo", "lang": "en"}]


def test_adapter_defaults_empty():
    row = SimpleNamespace(iri="http://x/Bar", primary_label=None, short=None, type=None,
                          source=None, labels=None, synonyms=None, definitions=None)
    d = entity_index_to_legacy_dict(row)
    assert d["label"] == "" and d["short"] == "" and d["source"] == ""
    assert json.loads(d["labels"]) == [] and json.loads(d["synonyms"]) == []


def test_renderer_parity_entity_index_vs_redis_hash():
    """Same vocabulary content, two sources → identical v1 term output."""
    onto, req = _ontology(), _request()
    # entity_index row
    row = SimpleNamespace(
        iri="http://purl.obolibrary.org/obo/GO_0008150", primary_label="biological process",
        short="GO_0008150", type="class", source="go",
        labels={"en": "biological process"},
        synonyms=[{"value": "physiological process", "lang": "en"}],
        definitions=[{"value": "A biological process...", "lang": "en"}],
    )
    # the equivalent Redis `:iri:` hash (JSON-string fields), as the indexer wrote it
    redis_hash = {
        "iri": "http://purl.obolibrary.org/obo/GO_0008150",
        "primary_label": "biological process", "label": "biological process",
        "short": "GO_0008150", "type": "class", "source": "go",
        "labels": json.dumps([{"value": "biological process", "lang": "en"}]),
        "synonyms": json.dumps([{"value": "physiological process", "lang": "en"}]),
        "definitions": json.dumps([{"value": "A biological process...", "lang": "en"}]),
    }
    from_index = entity_to_v1_term(entity_index_to_legacy_dict(row), onto, request=req,
                                   is_obsolete=False, is_root=False, has_children=True, lang="en")
    from_redis = entity_to_v1_term(redis_hash, onto, request=req,
                                   is_obsolete=False, is_root=False, has_children=True, lang="en")
    assert from_index == from_redis
