"""Usage statistics API."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import require_auth


def _sum_bucket_bytes(bucket: str) -> int:
    from ontoexplorer.clients.minio import get_minio_client
    try:
        return sum(obj.size or 0 for obj in get_minio_client().list_objects(bucket, recursive=True))
    except Exception:
        return 0

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("/usage/public", summary="Site-wide view/download usage (no auth)")
async def get_usage_public(
    granularity: str = Query("month"),
    periods: int = Query(12, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
):
    """All-time view/download totals (both unique + total) plus a zero-filled
    trend over the last `periods` week/month/year buckets."""
    from datetime import UTC, datetime

    from ontoexplorer.modules.usage.query import (
        GRANULARITIES,
        build_trend,
        period_starts,
        usage_totals,
        usage_trend,
    )

    if granularity not in GRANULARITIES:
        raise HTTPException(status_code=400, detail=f"granularity must be one of {sorted(GRANULARITIES)}")

    today = datetime.now(UTC).date()
    starts = period_starts(granularity, periods, today)
    totals = await usage_totals(db)
    tmap = await usage_trend(db, granularity, starts[0])
    return {
        "granularity": granularity,
        "totals": totals,
        "trend": build_trend(granularity, periods, today, tmap),
    }


@router.get("/usage/timeseries", summary="Per-ontology usage over time (<=5 ontologies)")
async def get_usage_timeseries(
    ontology_ids: str = Query(..., description="Comma-separated ontology ids (max 5)"),
    kind: str = Query("view"),
    granularity: str = Query("month"),
    periods: int = Query(12, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
):
    """One dense zero-filled series per requested ontology, for the widget. Public."""
    from datetime import UTC, datetime

    from ontoexplorer.modules.usage.query import (
        GRANULARITIES,
        build_series,
        period_label,
        period_starts,
        usage_timeseries,
    )

    if granularity not in GRANULARITIES:
        raise HTTPException(status_code=400, detail=f"granularity must be one of {sorted(GRANULARITIES)}")
    if kind not in ("view", "download"):
        raise HTTPException(status_code=400, detail="kind must be 'view' or 'download'")

    ids: list[str] = []
    for x in ontology_ids.split(","):
        x = x.strip()
        if x and x not in ids:
            ids.append(x)
    if not ids:
        raise HTTPException(status_code=400, detail="ontology_ids is required")
    if len(ids) > 5:
        raise HTTPException(status_code=400, detail="at most 5 ontologies")

    today = datetime.now(UTC).date()
    starts = period_starts(granularity, periods, today)
    labels = [period_label(granularity, s) for s in starts]

    # Resolve display names for the requested ids (preserve request order).
    name_rows = (await db.execute(
        select(Ontology.id, Ontology.shortname, Ontology.title).where(Ontology.id.in_(ids))
    )).all()
    names = {oid: (shortname, title) for oid, shortname, title in name_rows}

    ts = await usage_timeseries(db, ids, kind, granularity, starts[0])
    series = []
    for oid in ids:
        if oid not in names:
            continue  # unknown/deleted id — skip silently
        shortname, title = names[oid]
        series.append({
            "ontology_id": oid,
            "shortname": shortname,
            "label": title or shortname or oid,
            "points": build_series(granularity, periods, today, ts.get(oid, {})),
        })
    return {"kind": kind, "granularity": granularity, "periods": labels, "series": series}


@router.get("/usage/mine", summary="Usage for the caller's owned/maintained ontologies")
async def get_usage_mine(
    granularity: str = Query("month"),
    periods: int = Query(12, ge=1, le=60),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """View/download stats scoped to ontologies the caller owns OR maintains:
    totals (both counts), a per-ontology breakdown, and a trend."""
    from datetime import UTC, datetime

    from ontoexplorer.modules.auth.permissions import owned_or_maintained_ontology_ids
    from ontoexplorer.modules.usage.query import (
        GRANULARITIES,
        build_trend,
        period_starts,
        usage_per_ontology,
        usage_totals,
        usage_trend,
    )

    if granularity not in GRANULARITIES:
        raise HTTPException(status_code=400, detail=f"granularity must be one of {sorted(GRANULARITIES)}")

    ids = await owned_or_maintained_ontology_ids(db, user.id)
    today = datetime.now(UTC).date()
    if not ids:
        return {
            "granularity": granularity,
            "totals": {"views": {"unique": 0, "total": 0}, "downloads": {"unique": 0, "total": 0}},
            "per_ontology": [],
            "trend": build_trend(granularity, periods, today, {}),
        }

    starts = period_starts(granularity, periods, today)
    totals = await usage_totals(db, ids)
    tmap = await usage_trend(db, granularity, starts[0], ids)
    per_ontology = await usage_per_ontology(db, ids)
    return {
        "granularity": granularity,
        "totals": totals,
        "per_ontology": per_ontology,
        "trend": build_trend(granularity, periods, today, tmap),
    }


@router.get("/public", summary="Public aggregate statistics (no auth required)")
async def get_public_stats(db: AsyncSession = Depends(get_db)):
    import json
    import uuid as _uuid
    from ontoexplorer.modules.search.indexer import _get_redis, _stats_cache_key, _type_key

    # Latest ready version per ontology (same logic as list endpoint)
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

    def _compute_stats(vids: list[str]) -> dict:
        if not vids:
            return {
                "total_classes": 0, "unique_classes": 0,
                "total_object_properties": 0, "unique_object_properties": 0,
                "total_data_properties": 0, "unique_data_properties": 0,
                "total_annotation_properties": 0, "unique_annotation_properties": 0,
                "total_axioms": 0,
                "total_individuals": 0, "unique_individuals": 0,
            }

        r = _get_redis()

        # Sum totals from stats cache
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

        # Unique counts via SUNIONSTORE into temp keys (deleted immediately)
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
            "total_classes":              classes,
            "unique_classes":             _unique("class"),
            "total_object_properties":    obj_props,
            "unique_object_properties":   _unique("object_property"),
            "total_data_properties":      data_props,
            "unique_data_properties":     _unique("data_property"),
            "total_annotation_properties": ann_props,
            "unique_annotation_properties": _unique("annotation_property"),
            "total_axioms":               axioms,
            "total_individuals":          individuals,
            "unique_individuals":         _unique("individual"),
        }

    result = await asyncio.to_thread(_compute_stats, version_ids)
    result["total_ontologies"] = total_ontologies
    return result


@router.get("", summary="Usage statistics for the authenticated user")
async def get_stats(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    total_ontologies = (await db.execute(
        select(func.count(Ontology.id)).where(Ontology.owner_id == user.id)
    )).scalar_one()

    total_versions = (await db.execute(
        select(func.count(OntologyVersion.id))
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        .where(Ontology.owner_id == user.id)
    )).scalar_one()

    uploads_per_month = (await db.execute(
        text("""
            SELECT to_char(v.created_at, 'YYYY-MM') AS month, COUNT(*) AS count
            FROM versions v
            JOIN ontologies o ON o.id = v.ontology_id
            WHERE o.owner_id = :uid
            GROUP BY month ORDER BY month
        """),
        {"uid": user.id},
    )).all()

    job_durations = (await db.execute(
        text("""
            SELECT to_char(j.started_at, 'YYYY-MM') AS month,
                   AVG(EXTRACT(EPOCH FROM (j.finished_at - j.started_at))) AS avg_seconds
            FROM jobs j
            JOIN versions v ON v.id = j.version_id
            JOIN ontologies o ON o.id = v.ontology_id
            WHERE o.owner_id = :uid AND j.type = 'reason' AND j.status = 'done'
              AND j.started_at IS NOT NULL AND j.finished_at IS NOT NULL
            GROUP BY month ORDER BY month
        """),
        {"uid": user.id},
    )).all()

    s = get_settings()
    storage_bytes = await asyncio.to_thread(_sum_bucket_bytes, s.minio_ontologies_bucket)

    return {
        "total_ontologies": total_ontologies,
        "total_versions": total_versions,
        "storage_bytes": storage_bytes,
        "total_queries": 0,
        "uploads_per_month": [{"month": r.month, "count": r.count} for r in uploads_per_month],
        "queries_per_month": [],
        "job_durations": [{"month": r.month, "avg_seconds": round(float(r.avg_seconds or 0), 1)} for r in job_durations],
    }
