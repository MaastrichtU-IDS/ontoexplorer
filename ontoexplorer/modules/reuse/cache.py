"""Redis cache-key helper for reuse analysis (mirrors owl_profile.cache)."""


def reuse_cache_key(version_id: str) -> str:
    return f"reuse:{version_id}"
