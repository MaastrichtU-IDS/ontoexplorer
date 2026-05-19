from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key


def test_cache_key_format():
    assert owl_profile_cache_key("abc-123") == "owl_profile:abc-123"
