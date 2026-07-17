from ontoexplorer.config import get_settings


def test_default_reasoner_defaults_to_whelk(monkeypatch):
    monkeypatch.delenv("DEFAULT_REASONER", raising=False)
    get_settings.cache_clear()
    assert get_settings().default_reasoner == "whelk"


def test_default_reasoner_from_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_REASONER", "rustdl")
    get_settings.cache_clear()
    assert get_settings().default_reasoner == "rustdl"
