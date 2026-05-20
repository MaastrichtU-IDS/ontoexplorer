"""Re-export of pyowl2_profiles.detector.detect_profiles.

See `ontoexplorer.modules.owl_profile.registry` for the package-level rationale.

The library version uses pyowl2_profiles' own Manchester renderer (a subset
of OntoExplorer's diff/manchester.py renderer with the same public API). This
keeps the detector free of OntoExplorer-internal dependencies; the diff
feature's richer renderer remains separate in `ontoexplorer.modules.diff.manchester`.
"""
from pyowl2_profiles.detector import detect_profiles  # noqa: F401
