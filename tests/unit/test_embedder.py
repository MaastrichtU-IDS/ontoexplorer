import json
import pytest
from ontoexplorer.modules.search.embedder import build_entity_text, text_hash


def test_term_embedding_model_importable():
    from ontoexplorer.models.db import TermEmbedding
    assert TermEmbedding.__tablename__ == "term_embeddings"


def test_build_entity_text_full():
    entity = {
        "primary_label": "lung",
        "definitions": json.dumps([{"value": "A respiratory organ.", "lang": "en"}]),
        "synonyms": json.dumps([{"value": "pulmo", "lang": "la"}]),
    }
    text = build_entity_text(entity, ["organ", "thoracic structure"], ["left lung", "right lung"])
    assert "lung." in text
    assert "respiratory organ" in text
    assert "pulmo" in text
    assert "Superclasses: organ, thoracic structure" in text
    assert "Subclasses: left lung, right lung" in text


def test_build_entity_text_minimal():
    entity = {"primary_label": "Thing", "definitions": "[]", "synonyms": "[]"}
    text = build_entity_text(entity, [], [])
    assert text == "Thing."


def test_build_entity_text_no_definition_skips_sentence():
    entity = {"primary_label": "Foo", "definitions": "[]", "synonyms": "[]"}
    text = build_entity_text(entity, [], [])
    assert "." not in text.replace("Foo.", "")


def test_build_entity_text_caps_parents_at_5():
    entity = {"primary_label": "X", "definitions": "[]", "synonyms": "[]"}
    parents = ["A", "B", "C", "D", "E", "F", "G"]
    text = build_entity_text(entity, parents, [])
    assert "F" not in text
    assert "G" not in text


def test_build_entity_text_caps_children_at_10():
    entity = {"primary_label": "X", "definitions": "[]", "synonyms": "[]"}
    children = [f"Child{i}" for i in range(15)]
    text = build_entity_text(entity, [], children)
    assert "Child10" not in text
    assert "Child9" in text


def test_text_hash_deterministic():
    entity = {"primary_label": "lung", "definitions": "[]", "synonyms": "[]"}
    t = build_entity_text(entity, [], [])
    assert text_hash(t) == text_hash(t)
    assert len(text_hash(t)) == 64  # SHA-256 hex


def test_text_hash_differs_on_different_text():
    entity_a = {"primary_label": "lung", "definitions": "[]", "synonyms": "[]"}
    entity_b = {"primary_label": "heart", "definitions": "[]", "synonyms": "[]"}
    assert text_hash(build_entity_text(entity_a, [], [])) != text_hash(build_entity_text(entity_b, [], []))


@pytest.mark.slow
def test_embed_query_returns_768_floats():
    from ontoexplorer.modules.search.embedder import embed_query
    result = embed_query("cardiac muscle cell")
    assert len(result) == 768
    assert all(isinstance(x, float) for x in result)


@pytest.mark.slow
def test_embed_texts_returns_correct_shape():
    from ontoexplorer.modules.search.embedder import embed_texts
    results = embed_texts(["heart failure", "lung cancer"])
    assert len(results) == 2
    assert len(results[0]) == 768
