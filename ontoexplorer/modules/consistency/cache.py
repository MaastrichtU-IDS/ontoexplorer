"""Redis cache-key helper for consistency reports (mirrors reuse.cache)."""


def consistency_cache_key(version_id: str) -> str:
    return f"consistency:{version_id}"
