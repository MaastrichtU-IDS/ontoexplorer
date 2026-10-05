"""Load OLS entity payloads from Postgres `entity_index` instead of the Redis
`:iri:` hash (#242 Stage 1 PR 2).

Returns the same Redis-hash-shaped dicts the OLS renderers consume, via
`entity_index_to_legacy_dict`, so call sites swap their `hgetall(_iri_key(...))`
for these without touching the renderers.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict
from ontoexplorer.models.db import EntityIndex


async def load_entity(db: AsyncSession, version_id: str, iri: str) -> dict | None:
    """One entity's legacy-shaped payload, or None if not indexed."""
    row = (await db.execute(
        select(EntityIndex).where(
            EntityIndex.version_id == version_id, EntityIndex.iri == iri
        )
    )).scalar_one_or_none()
    return entity_index_to_legacy_dict(row) if row is not None else None


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
    one query (enumerate + load together). IRI order matches the old sorted-set paging.
    """
    rows = (await db.execute(
        select(EntityIndex)
        .where(EntityIndex.version_id == version_id, EntityIndex.type.in_(types))
        .order_by(EntityIndex.iri)
        .limit(limit).offset(offset)
    )).scalars().all()
    return [entity_index_to_legacy_dict(r) for r in rows]


async def load_entities(db: AsyncSession, version_id: str, iris) -> dict[str, dict]:
    """Batch-load {iri: legacy_dict} for `iris` in one query. Missing IRIs are absent."""
    iris = list(iris)
    if not iris:
        return {}
    rows = (await db.execute(
        select(EntityIndex).where(
            EntityIndex.version_id == version_id, EntityIndex.iri.in_(iris)
        )
    )).scalars().all()
    return {r.iri: entity_index_to_legacy_dict(r) for r in rows}
