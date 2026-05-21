"""Joint-reasoning consistency analysis (Konclude + ROBOT explain)."""

from ontoexplorer.modules.consistency.cache import consistency_cache_key  # noqa: F401
from ontoexplorer.modules.consistency.detector import (  # noqa: F401
    ConsistencyReport,
    JustificationAxiom,
    ScopeResult,
    UnsatisfiableClass,
    detect_consistency,
)
