"""Load OLS entity payloads from Postgres `entity_index` (#242 Stage 1 PR 2).

Returns the same legacy-hash-shaped dicts the OLS renderers consume, via
`entity_index_to_legacy_dict`, so call sites that used to `hgetall(_iri_key(...))`
read these instead without touching the renderers.

`owl:Thing` is a queryable built-in that is never declared as owl:Class, so it has
no entity_index row (giving it one would make it a tree root + inflate class
counts). It is served synthetically here — the only entity without a row. The
Redis `:iri:` hash miss-fallback that briefly backed other unmirrored entities was
removed in #242 Stage 3 once the Postgres index became authoritative and the Redis
search index was purged.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict
from ontoexplorer.models.db import EntityIndex

logger = logging.getLogger(__name__)

# owl:Thing is a queryable built-in class with no entity_index row; served
# synthetically in the legacy-dict shape so it keeps resolving.
_OWL_THING_IRI = "http://www.w3.org/2002/07/owl#Thing"
_OWL_THING_HASH: dict = {
    "label": "Thing", "primary_label": "Thing", "type": "class",
    "iri": _OWL_THING_IRI, "short": "owl:Thing", "source": "",
    "labels": json.dumps([{"value": "Thing", "lang": "en"}]),
    "synonyms": "[]", "definitions": "[]",
}


def _iri_order(db: AsyncSession):
    """IRI ordering that matches the old `sorted(smembers(...))` byte order.

    On PostgreSQL the default collation is locale-aware, so it diverges from the
    codepoint order the Redis sorted-set paging produced; `COLLATE "C"` restores
    byte order.  SQLite's default collation is already binary/codepoint, and it
    has no `"C"` collation, so apply the collate only on PostgreSQL (keeps the
    sqlite test lane working).
    """
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        return EntityIndex.iri.collate("C")
    return EntityIndex.iri


async def load_entity(db: AsyncSession, version_id: str, iri: str) -> dict | None:
    """One entity's legacy-shaped payload, or None if not indexed.

    owl:Thing has no entity_index row and is served synthetically; anything else
    absent from entity_index is reported as None (#242 Stage 3 — no Redis fallback).
    """
    row = (await db.execute(
        select(EntityIndex).where(
            EntityIndex.version_id == version_id, EntityIndex.iri == iri
        )
    )).scalar_one_or_none()
    if row is not None:
        return entity_index_to_legacy_dict(row)
    if iri == _OWL_THING_IRI:
        return dict(_OWL_THING_HASH)
    return None


async def count_entities(db: AsyncSession, version_id: str, types: list[str]) -> int:
    """Count entity_index rows of the given type(s) for a version (replaces `scard`)."""
    return int((await db.execute(
        select(func.count()).select_from(EntityIndex).where(
            EntityIndex.version_id == version_id, EntityIndex.type.in_(types)
        )
    )).scalar() or 0)


async def individuals_of_class(
    db: AsyncSession, version_id: str, class_iri: str, *, limit: int, offset: int
) -> tuple[int, list[dict]]:
    """Individuals of `version_id` whose rdf:type includes `class_iri`, IRI-ordered
    and paged. Returns `(total, page_of_legacy_dicts)`.

    Reads `entity_index.types` (#242 Stage 1 PR 5). Returns 0 for versions indexed
    before the types backfill (column still `[]`) — callers keep a SPARQL fallback.
    """
    base = select(EntityIndex).where(
        EntityIndex.version_id == version_id, EntityIndex.is_individual.is_(True)
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        # JSONB containment: types @> '["<class_iri>"]' — an index range scan over
        # the version's individuals, filtered by the planner, not an app-side N+1.
        matched = base.where(EntityIndex.types.contains([class_iri]))
        total = int((await db.execute(
            select(func.count()).select_from(matched.subquery())
        )).scalar() or 0)
        rows = (await db.execute(
            matched.order_by(EntityIndex.iri.collate("C")).limit(limit).offset(offset)
        )).scalars().all()
        return total, [entity_index_to_legacy_dict(r) for r in rows]
    # sqlite (tests): JSONB @> is unavailable; the per-version individual set is small.
    rows = (await db.execute(base.order_by(EntityIndex.iri))).scalars().all()
    matched_rows = [r for r in rows if class_iri in (r.types or [])]
    page = matched_rows[offset:offset + limit]
    return len(matched_rows), [entity_index_to_legacy_dict(r) for r in page]


async def list_entities(
    db: AsyncSession, version_id: str, types: list[str], *, limit: int, offset: int
) -> list[dict]:
    """A page of entities of the given type(s), IRI-ordered, as legacy dicts.

    Replaces the `sorted(smembers(type_set))` + slice + per-IRI `hgetall` dance with
    one query (enumerate + load together). IRI order matches the old sorted-set paging
    (byte order — see `_iri_order`).
    """
    rows = (await db.execute(
        select(EntityIndex)
        .where(EntityIndex.version_id == version_id, EntityIndex.type.in_(types))
        .order_by(_iri_order(db))
        .limit(limit).offset(offset)
    )).scalars().all()
    return [entity_index_to_legacy_dict(r) for r in rows]


async def version_lang_counts(db: AsyncSession, version_id: str) -> dict[str, int]:
    """`{lang: count}` of entities carrying a label in each language, from
    entity_index.labels (#242 Stage 2 — replaces the Redis `:langs` hash).

    Counts distinct-language-per-entity: entity_index.labels keeps one label per
    language (last-wins), so an entity labelled twice in `en` counts once — the same
    accepted lossiness as the rest of the entity_index mirror. Keys are raw language
    subtags (""/"en"/"en-GB"); callers collapse to canonical form.
    """
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        from sqlalchemy import text as _text
        rows = (await db.execute(_text(
            "SELECT k AS lang, count(*) AS n "
            "FROM entity_index, jsonb_object_keys(labels) AS k "
            "WHERE version_id = :vid GROUP BY k"
        ), {"vid": version_id})).all()
        return {lang: int(n) for lang, n in rows}
    # sqlite (tests): labels is a JSON object; tally language keys in Python.
    label_dicts = (await db.execute(
        select(EntityIndex.labels).where(EntityIndex.version_id == version_id)
    )).scalars().all()
    out: dict[str, int] = {}
    for labels in label_dicts:
        if isinstance(labels, dict):
            for lang in labels:
                out[lang] = out.get(lang, 0) + 1
    return out


async def _version_lang_counts_aggregate(
    db: AsyncSession, version_ids: list[str]
) -> dict[str, dict[str, int]]:
    """`{version_id: {lang: count}}` by aggregating entity_index.labels, in ONE query.
    The fallback for versions whose `lang_counts` column isn't materialized yet."""
    if not version_ids:
        return {}
    out: dict[str, dict[str, int]] = {}
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        from sqlalchemy import text as _text
        rows = (await db.execute(_text(
            "SELECT version_id, k AS lang, count(*) AS n "
            "FROM entity_index, jsonb_object_keys(labels) AS k "
            "WHERE version_id = ANY(:vids) GROUP BY version_id, k"
        ), {"vids": list(version_ids)})).all()
        for version_id, lang, n in rows:
            out.setdefault(version_id, {})[lang] = int(n)
        return out
    rows2 = (await db.execute(
        select(EntityIndex.version_id, EntityIndex.labels)
        .where(EntityIndex.version_id.in_(list(version_ids)))
    )).all()
    for version_id, labels in rows2:
        if isinstance(labels, dict):
            d = out.setdefault(version_id, {})
            for lang in labels:
                d[lang] = d.get(lang, 0) + 1
    return out


async def version_lang_counts_bulk(
    db: AsyncSession, version_ids: list[str]
) -> dict[str, dict[str, int]]:
    """`{version_id: {lang: count}}` for several versions.

    Reads the materialized `versions.lang_counts` (#286) — an O(1) batch — and
    aggregates entity_index only for versions whose column isn't populated yet
    (NULL), so it's correct before the backfill and fast after. Running the
    aggregation per version over the whole catalogue is what made catalogue search
    ~100s (one agg is ~638ms on a large ontology).
    """
    if not version_ids:
        return {}
    vids = list(version_ids)
    out: dict[str, dict[str, int]] = {}
    from ontoexplorer.models.db import OntologyVersion as _OV
    rows = (await db.execute(
        select(_OV.id, _OV.lang_counts).where(_OV.id.in_(vids))
    )).all()
    for vid, lc in rows:
        if lc is not None:
            out[vid] = {k: int(v) for k, v in lc.items()}
    # Aggregate for any vid whose column isn't materialized yet (NULL, or — in
    # tests — no versions row at all).
    missing = [vid for vid in vids if vid not in out]
    if missing:
        out.update(await _version_lang_counts_aggregate(db, missing))
    for vid in vids:
        out.setdefault(vid, {})
    return out


def _local_name(iri: str) -> str:
    """Human-readable fallback label: the IRI's local name."""
    fragment = iri.rstrip("/")
    return fragment.split("#")[-1] if "#" in fragment else fragment.rsplit("/", 1)[-1]


async def version_label_map(db: AsyncSession, version_id: str) -> dict[str, tuple[str, str]]:
    """`{iri: (label, source)}` for every entity in a version, in one query.

    For the `api/ontologies.py` + widgets tree/graph/usage builders, which resolve
    labels lazily inside sync/threaded walkers and so used cheap Redis point-lookups
    (#242 Stage 2). Prefetching the whole version's labels into a dict gives those
    sync helpers an in-memory lookup off entity_index instead — one query per request
    rather than an hget per IRI. `source` is "" when absent. IRIs not in entity_index
    (e.g. unindexed external imports) are simply absent; callers fall back to the
    local name via `label_for`.
    """
    rows = (await db.execute(
        select(EntityIndex.iri, EntityIndex.primary_label, EntityIndex.source)
        .where(EntityIndex.version_id == version_id)
    )).all()
    return {iri: (plabel or _local_name(iri), src or "") for iri, plabel, src in rows}


def label_for(lmap: dict[str, tuple[str, str]], iri: str) -> str:
    """Label for `iri` from a `version_label_map`, or the IRI local name if absent."""
    hit = lmap.get(iri)
    return hit[0] if hit else _local_name(iri)


def source_for(lmap: dict[str, tuple[str, str]], iri: str) -> str:
    """Import-source short-name for `iri` from a `version_label_map`, else ""."""
    hit = lmap.get(iri)
    return hit[1] if hit else ""


async def load_entity_global(
    db: AsyncSession, version_ids: list[str], iri: str,
) -> list[tuple[dict, str]]:
    """All rows for `iri` across `version_ids` (the latest-ready set), in ONE query
    instead of a per-version `load_entity` fan-out. Returns `[(legacy_dict,
    ontology_id)]`, version_id-ordered. entity_index only (no Redis fallback — a
    cross-version lookup of a Redis-only built-in like owl:Thing is not meaningful).
    """
    if not version_ids:
        return []
    rows = (await db.execute(
        select(EntityIndex)
        .where(EntityIndex.iri == iri, EntityIndex.version_id.in_(version_ids))
        .order_by(EntityIndex.version_id)
    )).scalars().all()
    return [(entity_index_to_legacy_dict(r), r.ontology_id) for r in rows]


async def page_entities_global(
    db: AsyncSession, version_ids: list[str], types: list[str], *,
    limit: int, offset: int, search: str | None = None,
) -> tuple[int, list[tuple[dict, str]]]:
    """A cross-version page of entities across `version_ids` (the latest-ready set),
    of the given type(s), paged in SQL instead of enumerating every version into
    memory and slicing (#242 Stage 1).

    Ordered by IRI (byte order — see `_iri_order`) then version_id for a stable page.
    `search`, when given, matches primary_label or iri case-insensitively. Returns
    `(total, [(legacy_dict, ontology_id)])` so the caller can resolve each row's
    ontology for rendering.
    """
    if not version_ids:
        return 0, []
    conds = [EntityIndex.version_id.in_(version_ids), EntityIndex.type.in_(types)]
    if search:
        like = f"%{search}%"
        conds.append(or_(EntityIndex.primary_label.ilike(like), EntityIndex.iri.ilike(like)))
    total = int((await db.execute(
        select(func.count()).select_from(EntityIndex).where(*conds)
    )).scalar() or 0)
    rows = (await db.execute(
        select(EntityIndex).where(*conds)
        .order_by(_iri_order(db), EntityIndex.version_id)
        .limit(limit).offset(offset)
    )).scalars().all()
    return total, [(entity_index_to_legacy_dict(r), r.ontology_id) for r in rows]


async def load_entities(db: AsyncSession, version_id: str, iris) -> dict[str, dict]:
    """Batch-load {iri: legacy_dict} for `iris` in one query.

    owl:Thing (no entity_index row) is served synthetically; any other IRI absent
    from entity_index is simply missing from the result (#242 Stage 3 — no Redis).
    """
    iris = list(iris)
    if not iris:
        return {}
    rows = (await db.execute(
        select(EntityIndex).where(
            EntityIndex.version_id == version_id, EntityIndex.iri.in_(iris)
        )
    )).scalars().all()
    out = {r.iri: entity_index_to_legacy_dict(r) for r in rows}
    if _OWL_THING_IRI in iris and _OWL_THING_IRI not in out:
        out[_OWL_THING_IRI] = dict(_OWL_THING_HASH)
    return out
