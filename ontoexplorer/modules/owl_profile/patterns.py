"""Re-exports from the pyowl2-profiles library.

See `ontoexplorer.modules.owl_profile.registry` for the package-level rationale.
This file preserves the old import path for symbols our indexer + API code
referenced directly (`_PREFIXES`, `_OWL`, factory functions, pattern lists).
"""
from pyowl2_profiles.patterns import (  # noqa: F401
    _OWL,
    _PREFIXES,
    EL_PATTERNS,
    QL_PATTERNS,
    RL_PATTERNS,
    Pattern,
    make_el_patterns,
    make_ql_patterns,
    make_rl_patterns,
    run_pattern_count,
)
