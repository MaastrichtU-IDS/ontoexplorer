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
import uuid as _uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Ontology, OntologyVersion

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


def _compute_from_redis(vids: list[str]) -> dict:
    """Sum per-version totals and union per-version type sets for unique counts.
    Pure Redis; runs in a worker thread (several seconds for the full catalogue)."""
    from ontoexplorer.modules.search.indexer import _get_redis, _stats_cache_key, _type_key

    if not vids:
        return _empty()

    r = _get_redis()

    values = r.mget([_stats_cache_key(vid) for vid in vids])
    classes = obj_props = data_props = ann_props = axioms = individuals = 0
    for raw in values:
        if not raw:
            continue
        try:
            meta = json.loads(raw)
            classes     += int(meta.get("class_count", 0))
            obj_props   += int(meta.get("object_property_count", 0))
            data_props  += int(meta.get("datatype_property_count", 0))
            ann_props   += int(meta.get("annotation_property_count", 0))
            axioms      += int(meta.get("triple_count", 0))
            individuals += int(meta.get("individual_count", 0))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    def _unique(entity_type: str) -> int:
        keys = [_type_key(vid, entity_type) for vid in vids]
        tmp = f"stats:unique:tmp:{_uuid.uuid4().hex}"
        try:
            r.sunionstore(tmp, *keys)
            return r.scard(tmp)
        except Exception:
            return 0
        finally:
            try:
                r.delete(tmp)
            except Exception:
                pass

    return {
        "total_classes":                classes,
        "unique_classes":               _unique("class"),
        "total_object_properties":      obj_props,
        "unique_object_properties":     _unique("object_property"),
        "total_data_properties":        data_props,
        "unique_data_properties":       _unique("data_property"),
        "total_annotation_properties":  ann_props,
        "unique_annotation_properties": _unique("annotation_property"),
        "total_axioms":                 axioms,
        "total_individuals":            individuals,
        "unique_individuals":           _unique("individual"),
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

    result = await asyncio.to_thread(_compute_from_redis, version_ids)
    result["total_ontologies"] = total_ontologies
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
