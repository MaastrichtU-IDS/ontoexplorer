from ontoexplorer.config import get_settings


def test_new_env_name_wins(monkeypatch):
    monkeypatch.setenv("REASONER_SERVICE_URL", "http://reasoner-service:8001")
    get_settings.cache_clear()
    assert get_settings().reasoner_service_url == "http://reasoner-service:8001"


def test_old_env_alias_still_works(monkeypatch):
    monkeypatch.delenv("REASONER_SERVICE_URL", raising=False)
    monkeypatch.setenv("ELK_SERVICE_URL", "http://legacy:8001")
    get_settings.cache_clear()
    assert get_settings().reasoner_service_url == "http://legacy:8001"
