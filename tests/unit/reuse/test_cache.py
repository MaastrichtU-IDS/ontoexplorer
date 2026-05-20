from ontoexplorer.modules.reuse.cache import reuse_cache_key


def test_reuse_cache_key_format():
    assert reuse_cache_key("abc-123") == "reuse:abc-123"


def test_reuse_cache_key_handles_uuid():
    vid = "550e8400-e29b-41d4-a716-446655440000"
    assert reuse_cache_key(vid) == f"reuse:{vid}"
