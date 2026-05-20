"""Term-IRI reuse signal.

For each indexed entity in a version, classify the IRI's namespace as
native (matches the host ontology's base IRI) or reused-from-X (resolves
to a different bioregistry prefix). Counts are aggregated per source
prefix; sample IRIs are capped to keep the cache payload small.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


_SAMPLE_CAP = 5


@dataclass
class TermIRIReuseEntry:
    class_count: int = 0
    property_count: int = 0
    sample_iris: list[str] = field(default_factory=list)
    resolved: bool = True


def classify_terms(
    entities: Iterable[tuple[str, str]],
    host_prefix: str | None,
    host_namespaces: list[str],
) -> dict[str, TermIRIReuseEntry]:
    """Bucket entity IRIs by reused-from prefix.

    Args:
        entities: iterable of (iri, entity_type) where entity_type is one of
            "class", "object_property", "data_property", "annotation_property",
            "individual".
        host_prefix: bioregistry prefix of the host ontology (for skip-self).
        host_namespaces: raw namespaces declared as the host's own (skip-native).

    Returns:
        dict keyed by source bioregistry prefix → TermIRIReuseEntry. Native
        terms are dropped (we report reuse, not totals).
    """
    out: dict[str, TermIRIReuseEntry] = {}
    for iri, etype in entities:
        if any(iri.startswith(ns) for ns in host_namespaces):
            continue  # native
        prefix, resolved = iri_to_prefix(iri)
        if prefix is None:
            continue
        if prefix == host_prefix:
            continue  # also native (host's own prefix used in mixed-namespace form)
        entry = out.setdefault(prefix, TermIRIReuseEntry(resolved=resolved))
        if etype == "class":
            entry.class_count += 1
        elif etype in ("object_property", "data_property", "annotation_property"):
            entry.property_count += 1
        if len(entry.sample_iris) < _SAMPLE_CAP:
            entry.sample_iris.append(iri)
    return out
