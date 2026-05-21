from ontoexplorer.modules.consistency.cache import consistency_cache_key


def test_consistency_cache_key_format():
    assert consistency_cache_key("abc-123") == "consistency:abc-123"


def test_consistency_cache_key_handles_uuid():
    vid = "550e8400-e29b-41d4-a716-446655440000"
    assert consistency_cache_key(vid) == f"consistency:{vid}"
