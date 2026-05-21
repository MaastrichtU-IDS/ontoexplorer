"""Ontology reuse analysis: signals, bioregistry-normalized prefixes, caching."""

from ontoexplorer.modules.reuse.detector import ReuseReport, detect_reuse  # noqa: F401
from ontoexplorer.modules.reuse.signals.imports import ImportEdge  # noqa: F401
from ontoexplorer.modules.reuse.signals.mappings import MappingEntry  # noqa: F401
from ontoexplorer.modules.reuse.signals.mireot import MireotTerm  # noqa: F401
from ontoexplorer.modules.reuse.signals.term_iri import TermIRIReuseEntry  # noqa: F401
