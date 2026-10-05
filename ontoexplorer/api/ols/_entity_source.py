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
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict
from ontoexplorer.models.db import EntityIndex
from ontoexplorer.modules.search.indexer import _get_redis, _iri_key

logger = logging.getLogger(__name__)


def _redis_hash(version_id: str, iri: str) -> dict | None:
    """The legacy Redis `:iri:` hash for one entity, or None if absent/unreachable.

    The hash is already in the renderer-consumed legacy shape, so it needs no
    adapter — it *is* what `entity_index_to_legacy_dict` reproduces.  Best-effort:
    if Redis is unavailable the entity is simply reported absent (404), never a 500.
    """
    try:
        h = _get_redis().hgetall(_iri_key(version_id, iri))
    except Exception:  # pragma: no cover - transition fallback, Redis optional
        logger.debug("entity_index Redis fallback failed for %s", iri, exc_info=True)
        return None
    return h or None


def _redis_hashes(version_id: str, iris: list[str]) -> dict[str, dict]:
    """Batch-fetch legacy Redis hashes for `iris`; missing/empty/unreachable absent."""
    try:
        r = _get_redis()
        pipe = r.pipeline(transaction=False)
        for iri in iris:
            pipe.hgetall(_iri_key(version_id, iri))
        results = pipe.execute()
    except Exception:  # pragma: no cover - transition fallback, Redis optional
        logger.debug("entity_index Redis batch fallback failed", exc_info=True)
        return {}
    return {iri: h for iri, h in zip(iris, results) if h}


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
    from sqlalchemy import func
    return int((await db.execute(
        select(func.count()).select_from(EntityIndex).where(
            EntityIndex.version_id == version_id, EntityIndex.type.in_(types)
        )
    )).scalar() or 0)


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
