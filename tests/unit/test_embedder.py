def test_term_embedding_model_importable():
    from ontoexplorer.models.db import TermEmbedding
    assert TermEmbedding.__tablename__ == "term_embeddings"
