"""Per-version coverage computation: pure function operating on indexer dicts."""
from __future__ import annotations

from typing import Iterable

ENTITY_TYPES: tuple[str, ...] = (
    "class",
    "object_property",
    "data_property",
    "annotation_property",
    "individual",
)


def coverage_cache_key(version_id: str) -> str:
    return f"coverage:{version_id}"


def _empty_bucket() -> dict:
    return {"total": 0, "with_label": 0, "with_definition": 0, "multilingual": 0, "by_lang": {}}


def compute_coverage(
    entities: dict[str, str],
    deprecated_iris: set[str],
    labels_by_iri: dict[str, list[dict]],
    defs_by_iri: dict[str, list[dict]],
) -> dict:
    """Compute per-entity-type coverage from the indexer's in-memory dicts.

    Returns a dict shaped as:
        {"by_type": {<entity_type>: {"total", "with_label", "with_definition",
                                     "multilingual", "by_lang": {<lang>: int}}}}
    Empty lang tag ("") is preserved as its own bucket.
    """
    by_type: dict[str, dict] = {t: _empty_bucket() for t in ENTITY_TYPES}

    for iri, entity_type in entities.items():
        if iri in deprecated_iris or entity_type not in by_type:
            continue

        bucket = by_type[entity_type]
        bucket["total"] += 1

        labels: Iterable[dict] = labels_by_iri.get(iri, [])
        lang_tags = {entry.get("lang", "") for entry in labels}
        if labels:
            bucket["with_label"] += 1
        if len(lang_tags) >= 2:
            bucket["multilingual"] += 1
        for tag in lang_tags:
            bucket["by_lang"][tag] = bucket["by_lang"].get(tag, 0) + 1

        if defs_by_iri.get(iri):
            bucket["with_definition"] += 1

    return {"by_type": by_type}
