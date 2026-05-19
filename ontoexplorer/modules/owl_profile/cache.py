"""Redis cache key helpers for OWL profile detection."""


def owl_profile_cache_key(version_id: str) -> str:
    return f"owl_profile:{version_id}"
