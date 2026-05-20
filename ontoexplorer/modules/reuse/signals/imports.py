"""owl:imports closure signal.

Inputs are pre-fetched rows from the OntologyImport table (depth pre-computed
during ingestion by the recursive resolver). We normalize the target IRI via
bioregistry into a stable prefix and emit one ImportEdge per row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


@dataclass(frozen=True)
class ImportEdge:
    target_iri: str
    target_prefix: str | None
    depth: int
    resolved: bool


def build_closure(rows: Iterable[dict]) -> list[ImportEdge]:
    """Map OntologyImport rows to ImportEdges with bioregistry-resolved prefixes.

    `rows` is an iterable of dicts with keys: `import_iri`, `depth`.
    (The caller — typically `detector.detect_reuse` — fetches these from the
    `OntologyImport` SQLAlchemy model.)
    """
    edges: list[ImportEdge] = []
    for row in rows:
        prefix, resolved = iri_to_prefix(row["import_iri"])
        edges.append(ImportEdge(
            target_iri=row["import_iri"],
            target_prefix=prefix,
            depth=int(row.get("depth", 1)),
            resolved=resolved,
        ))
    return edges
