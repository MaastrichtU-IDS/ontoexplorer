from ontoexplorer.config import Settings


def test_embedding_settings_defaults_and_env_override(monkeypatch):
    for k in ("EMBEDDING_BASE_URL", "EMBEDDING_MODEL"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.embedding_base_url == ""
    assert s.embedding_api_key == ""
    assert s.embedding_model == "nomic-embed-text"
    assert s.embedding_fallback_base_url == "http://localhost:8090/v1"
    assert s.embedding_timeout_s == 30.0
    assert s.embedding_fallback_timeout_s == 120.0
    assert s.embedding_dim == 768
    assert s.embedding_doc_prefix == "search_document: "
    assert s.embedding_query_prefix == "search_query: "

    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://litellm:4000/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "other-model")
    s2 = Settings(_env_file=None)
    assert s2.embedding_base_url == "http://litellm:4000/v1"
    assert s2.embedding_model == "other-model"
