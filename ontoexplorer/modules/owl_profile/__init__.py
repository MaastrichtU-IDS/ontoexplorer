"""OWL 2 profile detection for OntoExplorer.

The detector core (registry/patterns/structural/detector) is provided by the
pyowl2-profiles PyPI package (github.com/MaastrichtU-IDS/pyowl2-profiles).
This module wraps that library with OntoExplorer-specific helpers:

- cache.py — Redis cache key for owl_profile:{version_id}
- The indexer hook + Celery refresh task live in ontoexplorer.modules.search
  and ontoexplorer.modules.jobs respectively.
"""
from ontoexplorer.modules.owl_profile.registry import (  # noqa: F401
    PROFILE_NAMES,
    ProfileName,
    ProfileViolation,
)
