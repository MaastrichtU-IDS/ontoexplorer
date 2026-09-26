"""OWL 2 profile detection for OntoExplorer.

Profiles are classified by the native horned-profile checker (py-horned-owl),
wrapped here for OntoExplorer:

- detector.py — loads the stored ontology into the horned-owl model and runs the
  EL/QL/RL/DL conformance checks (#149).
- registry.py — the PROFILE_NAMES constant API routes validate against.
- language.py — coarser RDF/RDFS/RDFS-Plus/OWL expressivity tier.
- cache.py — Redis cache key for owl_profile:{version_id}.

The indexer hook / Celery refresh live in ontoexplorer.modules.search and
ontoexplorer.modules.jobs respectively.
"""
from ontoexplorer.modules.owl_profile.registry import (  # noqa: F401
    PROFILE_NAMES,
    ProfileName,
)
