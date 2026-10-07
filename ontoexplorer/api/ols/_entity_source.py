"""Load OLS entity payloads from Postgres `entity_index` instead of the Redis
`:iri:` hash (#242 Stage 1 PR 2).

Returns the same Redis-hash-shaped dicts the OLS renderers consume, via
`entity_index_to_legacy_dict`, so call sites swap their `hgetall(_iri_key(...))`
for these without touching the renderers.

Transition fallback (#242 Stage 1): while the indexer still writes the Redis
`:iri:` hash, a handful of entities live only in Redis and have no entity_index
row yet — most notably `owl:Thing` (present in the Redis hash + prefix zset but
never added to a class type-set, so `pg_indexer` creates no row) and any entity
whose best-effort entity_index mirror failed during ingest.  On an entity_index
miss we fall back to the Redis hash so these keep resolving instead of 404ing.
The fallback is removed in Stage 2/3 once the indexer populates entity_index
directly and the Redis `:iri:` hash is purged.
"""
from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict
from ontoexplorer.models.db import EntityIndex
from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

logger = logging.getLogger(__name__)

# owl:Thing is a queryable built-in class that is never declared as owl:Class in
# ontology files, so it has no entity_index row (giving it one would make it a tree
# root + inflate class counts). It is served synthetically here so it keeps
# resolving once the indexer stops writing the Redis `:iri:` hash (#242 Workstream B),
# the same legacy-dict shape the indexer wrote for it.
_OWL_THING_IRI = "http://www.w3.org/2002/07/owl#Thing"
_OWL_THING_HASH: dict = {
    "label": "Thing", "primary_label": "Thing", "type": "class",
    "iri": _OWL_THING_IRI, "short": "owl:Thing", "source": "",
    "labels": json.dumps([{"value": "Thing", "lang": "en"}]),
    "synonyms": "[]", "definitions": "[]",
}


def _redis_hash(version_id: str, iri: str) -> dict | None:
    """Fallback payload for an entity absent from entity_index: a synthetic owl:Thing,
    else the legacy Redis `:iri:` hash (transition), else None.

    The hash is already in the renderer-consumed legacy shape (what
    `entity_index_to_legacy_dict` reproduces). Best-effort: if Redis is unavailable
    the entity is simply reported absent (404), never a 500.
    """
    if iri == _OWL_THING_IRI:
        return dict(_OWL_THING_HASH)
    try:
        h = _get_redis().hgetall(_iri_key(version_id, iri))
    except Exception:  # pragma: no cover - transition fallback, Redis optional
        logger.debug("entity_index Redis fallback failed for %s", iri, exc_info=True)
        return None
    return h or None


def _redis_hashes(version_id: str, iris: list[str]) -> dict[str, dict]:
    """Batch fallback: synthetic owl:Thing + legacy Redis hashes; missing absent."""
    out: dict[str, dict] = {}
    redis_iris = []
    for iri in iris:
        if iri == _OWL_THING_IRI:
            out[iri] = dict(_OWL_THING_HASH)
        else:
            redis_iris.append(iri)
    if redis_iris:
        try:
            r = _get_redis()
            pipe = r.pipeline(transaction=False)
            for iri in redis_iris:
                pipe.hgetall(_iri_key(version_id, iri))
            results = pipe.execute()
            out.update({iri: h for iri, h in zip(redis_iris, results) if h})
        except Exception:  # pragma: no cover - transition fallback, Redis optional
            logger.debug("entity_index Redis batch fallback failed", exc_info=True)
    return out


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

    Falls back to the Redis `:iri:` hash on an entity_index miss (transition —
    see module docstring).
    """
    row = (await db.execute(
        select(EntityIndex).where(
            EntityIndex.version_id == version_id, EntityIndex.iri == iri
        )
    )).scalar_one_or_none()
    if row is not None:
        return entity_index_to_legacy_dict(row)
    return await asyncio.to_thread(_redis_hash, version_id, iri)


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

    IRIs absent from entity_index fall back to the Redis `:iri:` hash (transition —
    see module docstring); IRIs missing from both are absent from the result.
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
    missing = [iri for iri in iris if iri not in out]
    if missing:
        out.update(await asyncio.to_thread(_redis_hashes, version_id, missing))
    return out
