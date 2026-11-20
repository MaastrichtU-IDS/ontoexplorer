"""Per-version coverage computation.

Two producers write the SAME payload shape:
  * ``compute_coverage`` — the pure function the indexer calls with its in-memory
    dicts, written to Redis at index time.
  * ``compute_coverage_from_index`` — recomputes it from the durable
    ``entity_index`` table (which mirrors every entity's type/labels/definitions/
    deprecated flag). Used to persist coverage on the version row at index time
    and to backfill versions whose Redis key has expired.

Coverage used to live ONLY in that 30-day-TTL Redis cache, so once the bulk of
the fleet aged past the TTL the /coverage rollup silently dropped them (only the
handful re-indexed recently survived). Persisting it on the version row via
``compute_coverage_from_index`` makes it durable.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ENTITY_TYPES: tuple[str, ...] = (
    "class",
    "object_property",
    "data_property",
    "annotation_property",
    "individual",
    "concept",
)


def coverage_cache_key(version_id: str) -> str:
    return f"coverage:{version_id}"


def _empty_bucket() -> dict:
    return {"total": 0, "with_label": 0, "with_definition": 0, "multilingual": 0, "by_lang": {},
            "native_total": 0, "native_with_label": 0, "native_with_definition": 0}


def compute_coverage(
    entities: dict[str, str],
    deprecated_iris: set[str],
    labels_by_iri: dict[str, list[dict]],
    defs_by_iri: dict[str, list[dict]],
    sources_by_iri: dict[str, str] | None = None,
) -> dict:
    """Compute per-entity-type coverage from the indexer's in-memory dicts.

    Returns a dict shaped as:
        {"by_type": {<entity_type>: {"total", "with_label", "with_definition",
                                     "multilingual", "by_lang": {<lang>: int},
                                     "native_total", "native_with_label",
                                     "native_with_definition"}}}
    Empty lang tag ("") is preserved as its own bucket.

    ``native_*`` count only terms **minted in this ontology's own namespace** —
    an entity whose ``source`` tag is empty (``entity_index.source == ''``). Terms
    reused from external vocabularies (``dcterms:title``, ``foaf:homepage`` …) or
    pulled in via ``owl:imports`` carry a non-empty source and are excluded, so a
    documentation-coverage metric built on ``native_*`` measures what the ontology
    is responsible for, not predicates it merely references. ``sources_by_iri`` maps
    each entity IRI to its source tag; when omitted (caller has no source info) the
    ``native_*`` counts stay 0.
    """
    by_type: dict[str, dict] = {t: _empty_bucket() for t in ENTITY_TYPES}

    for iri, entity_type in entities.items():
        if iri in deprecated_iris or entity_type not in by_type:
            continue

        bucket = by_type[entity_type]
        bucket["total"] += 1

        labels: Iterable[dict] = labels_by_iri.get(iri, [])
        lang_tags = {entry.get("lang", "") for entry in labels}
        has_label = bool(labels)
        has_def = bool(defs_by_iri.get(iri))
        if has_label:
            bucket["with_label"] += 1
        if len(lang_tags) >= 2:
            bucket["multilingual"] += 1
        for tag in lang_tags:
            bucket["by_lang"][tag] = bucket["by_lang"].get(tag, 0) + 1

        if has_def:
            bucket["with_definition"] += 1

        if sources_by_iri is not None and sources_by_iri.get(iri, "") == "":
            bucket["native_total"] += 1
            if has_label:
                bucket["native_with_label"] += 1
            if has_def:
                bucket["native_with_definition"] += 1

    return {"by_type": by_type}


def _assemble_coverage(
    agg_rows: Iterable,
    lang_rows: Iterable,
    version_id: str,
    indexed_at: str | None,
) -> dict:
    """Build the coverage payload from the two entity_index aggregate result sets.

    Pure (no DB) so it can be unit-tested. ``agg_rows`` yields
    (type, total, with_label, with_definition, multilingual) and MAY carry three
    further columns (native_total, native_with_label, native_with_definition); a
    5-tuple leaves the ``native_*`` counts at 0 (pre-native payloads). ``lang_rows``
    yields (type, lang, n). Rows whose type is not a coverage ENTITY_TYPE are
    ignored — mirroring ``compute_coverage``'s ``entity_type not in by_type`` skip.
    """
    by_type: dict[str, dict] = {t: _empty_bucket() for t in ENTITY_TYPES}
    for row in agg_rows:
        typ, total, with_label, with_definition, multilingual = row[:5]
        native_total, native_with_label, native_with_definition = (
            row[5:8] if len(row) >= 8 else (0, 0, 0)
        )
        b = by_type.get(typ)
        if b is None:
            continue
        b["total"] = int(total)
        b["with_label"] = int(with_label)
        b["with_definition"] = int(with_definition)
        b["multilingual"] = int(multilingual)
        b["native_total"] = int(native_total)
        b["native_with_label"] = int(native_with_label)
        b["native_with_definition"] = int(native_with_definition)
    for typ, lang, n in lang_rows:
        b = by_type.get(typ)
        if b is None:
            continue
        b["by_lang"][lang] = int(n)
    payload: dict = {"by_type": by_type, "version_id": version_id}
    if indexed_at:
        payload["indexed_at"] = indexed_at
    return payload


# Per-type aggregates over a version's non-deprecated entity_index rows. labels is
# {lang: label} (untagged under ""), definitions a jsonb array. multilingual = the
# label dict has >= 2 language keys — the same test compute_coverage applies to the
# distinct lang tags. Postgres-only (jsonb functions); callers guard for sqlite.
_COVERAGE_AGG_SQL = """
    SELECT type,
           count(*) AS total,
           count(*) FILTER (WHERE labels <> '{}'::jsonb) AS with_label,
           count(*) FILTER (
               WHERE jsonb_typeof(definitions) = 'array'
                 AND jsonb_array_length(definitions) > 0) AS with_definition,
           count(*) FILTER (
               WHERE (SELECT count(*) FROM jsonb_object_keys(labels)) >= 2) AS multilingual,
           count(*) FILTER (WHERE coalesce(source, '') = '') AS native_total,
           count(*) FILTER (
               WHERE coalesce(source, '') = '' AND labels <> '{}'::jsonb) AS native_with_label,
           count(*) FILTER (
               WHERE coalesce(source, '') = ''
                 AND jsonb_typeof(definitions) = 'array'
                 AND jsonb_array_length(definitions) > 0) AS native_with_definition
    FROM entity_index
    WHERE version_id = :vid AND deprecated = false
    GROUP BY type
"""

_COVERAGE_LANG_SQL = """
    SELECT ei.type AS type, k AS lang, count(*) AS n
    FROM entity_index AS ei, jsonb_object_keys(ei.labels) AS k
    WHERE ei.version_id = :vid AND ei.deprecated = false
    GROUP BY ei.type, k
"""


async def compute_coverage_from_index(
    db: "AsyncSession",
    version_id: str,
    indexed_at: str | None = None,
) -> dict:
    """Recompute a version's coverage payload from entity_index (Postgres).

    Same payload shape and semantics as ``compute_coverage``, sourced from the
    durable mirror instead of the indexer's in-memory dicts, so it works for any
    already-indexed version. Postgres-only.
    """
    from sqlalchemy import text

    agg = (await db.execute(text(_COVERAGE_AGG_SQL), {"vid": version_id})).all()
    langs = (await db.execute(text(_COVERAGE_LANG_SQL), {"vid": version_id})).all()
    return _assemble_coverage(
        ((r.type, r.total, r.with_label, r.with_definition, r.multilingual,
          r.native_total, r.native_with_label, r.native_with_definition) for r in agg),
        ((r.type, r.lang, r.n) for r in langs),
        version_id,
        indexed_at,
    )
