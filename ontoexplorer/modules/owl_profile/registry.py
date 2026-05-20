"""Re-exports from the pyowl2-profiles library.

The OWL 2 profile detector originally lived in this module and was extracted
to the standalone pyowl2-profiles PyPI package (github.com/MaastrichtU-IDS/
pyowl2-profiles). OntoExplorer now consumes it as a dependency; this file
preserves the old import path so internal callers don't need to change.
"""
from pyowl2_profiles.registry import (  # noqa: F401
    PROFILE_NAMES,
    ProfileName,
    ProfileViolation,
)
