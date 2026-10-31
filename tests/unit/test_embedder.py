import json
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


def test_build_entity_text_caps_length_to_bound_token_sequence():
    """Regression (#229): a pathologically long definition must not produce an
    unbounded embedding text. the backend pads each batch to its longest sequence,
    so one multi-thousand-token text makes attention memory (O(batch x seq^2))
    explode and OOM-kills worker-embed at its 32Gi limit — even on tiny
    ontologies. build_entity_text caps its output so no single sequence is huge."""
    from ontoexplorer.modules.search.embedder import MAX_ENTITY_TEXT_CHARS
    huge_def = "A " + ("very long clinical description. " * 2000)  # ~64k chars
    entity = {
        "primary_label": "lung",
        "definitions": json.dumps([{"value": huge_def, "lang": "en"}]),
        "synonyms": "[]",
    }
    text = build_entity_text(entity, [], [])
    assert len(text) <= MAX_ENTITY_TEXT_CHARS
    # The label (the primary retrieval signal) is preserved at the front.
    assert text.startswith("lung.")


def test_build_entity_text_short_text_unchanged_by_cap():
    """The cap only trims pathological inputs; normal entities are untouched."""
    entity = {
        "primary_label": "lung",
        "definitions": json.dumps([{"value": "A respiratory organ.", "lang": "en"}]),
        "synonyms": json.dumps([{"value": "pulmo", "lang": "la"}]),
    }
    text = build_entity_text(entity, ["organ"], ["left lung"])
    assert "respiratory organ" in text
    assert "pulmo" in text
    assert "Superclasses: organ" in text


def test_embed_texts_default_batch_size_is_memory_safe():
    """Regression (#229): the default embed batch size is bounded so that
    batch x heads x seq^2 attention memory stays well under the worker's limit.
    128 (the old default) x a long-sequence batch OOM'd at 32Gi."""
    import inspect
    from ontoexplorer.modules.search import embedder
    default_bs = inspect.signature(embedder.embed_texts).parameters["batch_size"].default
    assert default_bs <= 32


def test_text_hash_deterministic():
    entity = {"primary_label": "lung", "definitions": "[]", "synonyms": "[]"}
    t = build_entity_text(entity, [], [])
    assert text_hash(t) == text_hash(t)
    assert len(text_hash(t)) == 64  # SHA-256 hex


def test_text_hash_differs_on_different_text():
    entity_a = {"primary_label": "lung", "definitions": "[]", "synonyms": "[]"}
    entity_b = {"primary_label": "heart", "definitions": "[]", "synonyms": "[]"}
    assert text_hash(build_entity_text(entity_a, [], [])) != text_hash(build_entity_text(entity_b, [], []))


def test_embed_query_returns_768_floats():
    from ontoexplorer.modules.search.embedder import embed_query
    result = embed_query("cardiac muscle cell")
    assert len(result) == 768
    assert all(isinstance(x, float) for x in result)


def test_embed_texts_returns_correct_shape():
    from ontoexplorer.modules.search.embedder import embed_texts
    results = embed_texts(["heart failure", "lung cancer"])
    assert len(results) == 2
    assert len(results[0]) == 768


def test_embed_texts_uses_doc_prefix(monkeypatch):
    from ontoexplorer.modules.search import embed_client, embedder
    calls = []

    def fake(texts, *, prefix):
        calls.append((list(texts), prefix))
        return [[1.0] for _ in texts]

    monkeypatch.setattr(embed_client, "embed_batch", fake)
    out = embedder.embed_texts(["a", "b", "c"], batch_size=2)
    assert out == [[1.0], [1.0], [1.0]]
    assert calls == [(["a", "b"], "search_document: "), (["c"], "search_document: ")]


def test_embed_query_uses_query_prefix(monkeypatch):
    from ontoexplorer.modules.search import embed_client, embedder
    calls = []

    def fake(texts, *, prefix):
        calls.append((list(texts), prefix))
        return [[0.5, 0.5]]

    monkeypatch.setattr(embed_client, "embed_batch", fake)
    assert embedder.embed_query("x") == [0.5, 0.5]
    assert calls == [(["x"], "search_query: ")]


def test_embedder_has_no_fastembed_import():
    import inspect
    from ontoexplorer.modules.search import embedder
    assert "fastembed" not in inspect.getsource(embedder).lower()
    assert not hasattr(embedder, "get_embedder")
