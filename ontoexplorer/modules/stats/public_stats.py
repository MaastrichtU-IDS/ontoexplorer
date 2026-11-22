"""Public aggregate statistics for the home page.

The unique-entity counts fan 5x SUNIONSTORE across ~1900 per-version Redis sets
(to de-dup ~2.8M class IRIs etc.) — several seconds server-side. Stats only
change on (re)index but the home page loads them on every visit, so the whole
result is cached.

Shared between the `/stats/public` endpoint and the `refresh_public_stats` beat
task. The beat task recomputes the cache OFF the request path (well within the
TTL), so the home page always reads a warm cache and never eats the cold
recompute; the endpoint recomputes only on a genuine cold miss (first boot or
cache eviction). This module has no FastAPI deps so the celery worker can import
it without pulling in the API layer.
"""
from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import EntityIndex, Ontology, OntologyVersion

PUBLIC_STATS_CACHE_KEY = "stats:public:v1"
# TTL is a safety net only: the beat task refreshes every few minutes, well
# within this, so the key never actually expires in steady state. If beat stalls,
# the data is at most this stale before one request pays for a cold recompute.
PUBLIC_STATS_TTL = 1800  # 30 min


def _empty() -> dict:
    return {
        "total_classes": 0, "unique_classes": 0,
        "total_object_properties": 0, "unique_object_properties": 0,
        "total_data_properties": 0, "unique_data_properties": 0,
        "total_annotation_properties": 0, "unique_annotation_properties": 0,
        "total_axioms": 0,
        "total_individuals": 0, "unique_individuals": 0,
    }


# graph_counts sub-key -> public-stats total field. graph_counts is the durable
# VoID count payload written at index time (OntologyVersion.graph_counts).
_TOTAL_FIELDS = {
    "class_count":               "total_classes",
    "object_property_count":     "total_object_properties",
    "datatype_property_count":   "total_data_properties",
    "annotation_property_count": "total_annotation_properties",
    "triple_count":              "total_axioms",
    "individual_count":          "total_individuals",
}


async def _totals_from_graph_counts(db: AsyncSession, version_ids: list[str]) -> dict:
    """Sum per-version totals (class/property/axiom/individual counts) from the
    DURABLE `graph_counts` column, written at index time on every version.

    This used to read the per-version `version_stats` Redis cache, but those keys
    carry a 30-day TTL and don't survive a Redis restart/eviction — so aged or
    wiped versions silently contributed 0 and the home page showed total_* = 0
    even though the data was intact. graph_counts is the same count payload made
    durable in #399 (the identical fix landed for coverage/owl_profile in
    #400/#401). A version with graph_counts still NULL (not yet indexed) counts 0
    and self-heals on its next index — strictly better than the all-or-nothing
    Redis path. One query."""
    out = {dst: 0 for dst in _TOTAL_FIELDS.values()}
    if not version_ids:
        return out
    rows = (await db.execute(
        select(OntologyVersion.graph_counts).where(OntologyVersion.id.in_(version_ids))
    )).scalars().all()
    for gc in rows:
        if not gc:
            continue
        for src, dst in _TOTAL_FIELDS.items():
            try:
                out[dst] += int(gc.get(src, 0) or 0)
            except (ValueError, TypeError):
                pass
    return out


async def _unique_counts(db: AsyncSession, version_ids: list[str]) -> dict:
    """Distinct-IRI counts per entity type across the latest-ready versions, from
    entity_index (#242 Stage 2 — replaces the 5× SUNIONSTORE over the Redis type
    sets). One grouped query."""
    empty = {
        "unique_classes": 0, "unique_object_properties": 0, "unique_data_properties": 0,
        "unique_annotation_properties": 0, "unique_individuals": 0, "unique_concepts": 0,
    }
    if not version_ids:
        return empty
    rows = (await db.execute(
        select(EntityIndex.type, func.count(func.distinct(EntityIndex.iri)))
        .where(EntityIndex.version_id.in_(version_ids))
        .group_by(EntityIndex.type)
    )).all()
    by_type = {t: int(c) for t, c in rows}
    return {
        "unique_classes":               by_type.get("class", 0),
        "unique_object_properties":     by_type.get("object_property", 0),
        "unique_data_properties":       by_type.get("data_property", 0),
        "unique_annotation_properties": by_type.get("annotation_property", 0),
        "unique_individuals":           by_type.get("individual", 0),
        "unique_concepts":              by_type.get("concept", 0),
    }


async def compute_public_stats(db: AsyncSession) -> dict:
    """Full recompute (several seconds). Callers should prefer read_public_stats
    (cache-aware) or the beat task; this is the uncached path."""
    # Latest ready version per ontology (same logic as the list endpoint).
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    vr = await db.execute(
        select(OntologyVersion.id).join(
            subq,
            (OntologyVersion.ontology_id == subq.c.ontology_id)
            & (OntologyVersion.created_at == subq.c.max_created),
        )
    )
    version_ids = list(vr.scalars().all())

    total_ontologies = await db.scalar(select(func.count(Ontology.id)))

    totals = await _totals_from_graph_counts(db, version_ids)
    uniques = await _unique_counts(db, version_ids)
    result = {**_empty(), **totals, **uniques, "total_ontologies": total_ontologies}
    return result


async def refresh_public_stats_cache(db: AsyncSession) -> dict:
    """Recompute and write the cache. Called by the beat task off the request path
    (and by the endpoint on a cold miss)."""
    from ontoexplorer.modules.search.indexer import _get_redis

    result = await compute_public_stats(db)
    try:
        await asyncio.to_thread(
            _get_redis().set, PUBLIC_STATS_CACHE_KEY, json.dumps(result), ex=PUBLIC_STATS_TTL
        )
    except Exception:
        pass
    return result


async def read_public_stats(db: AsyncSession) -> dict:
    """Home-page stats: return the warm cache instantly; recompute+cache only on a
    cold miss (first boot or eviction — the beat task keeps this from happening)."""
    from ontoexplorer.modules.search.indexer import _get_redis

    cached = await asyncio.to_thread(_get_redis().get, PUBLIC_STATS_CACHE_KEY)
    if cached:
        return json.loads(cached)
    return await refresh_public_stats_cache(db)
