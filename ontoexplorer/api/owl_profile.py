"""OWL 2 profile endpoints — durable per-version profile on the version row.

The profile payload is materialized on ``versions.owl_profile`` at index time.
These endpoints read that row; Redis remains a hot-cache fallback for versions
re-indexed before the column was backfilled, and the per-version endpoint
self-heals by recomputing from the stored file. The payload used to live only in
a 30-day-TTL Redis cache, so the fleet rollup and the profile/language catalogue
filters silently dropped every version indexed > 30 days ago.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
from ontoexplorer.modules.owl_profile.compute import compute_owl_profile_payload
from ontoexplorer.modules.owl_profile.registry import PROFILE_NAMES
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["owl-profile"])


async def _fill_indexed_at(payload: dict, version_id: str, db: AsyncSession) -> dict:
    """Profile payloads written before the indexed_at fix lack the key; the UI's
    "Last computed" caption would otherwise read "unknown". Fall back to when the
    version was indexed (its profile is computed during indexing)."""
    if not payload.get("indexed_at"):
        indexed_at = await db.scalar(
            select(OntologyVersion.indexed_at).where(OntologyVersion.id == version_id))
        if indexed_at is not None:
            payload["indexed_at"] = indexed_at.isoformat()
    return payload


@router.get(
    "/ontologies/{ontology_id}/{version_id}/owl-profile",
    summary="Per-version OWL 2 profile classification",
)
async def get_version_profile(
    ontology_id: str, version_id: str, db: AsyncSession = Depends(get_db)
):
    row = (await db.execute(
        select(OntologyVersion.owl_profile).where(OntologyVersion.id == version_id)
    )).first()

    # 1) Durable row.
    if row is not None and isinstance(row.owl_profile, dict):
        return await _fill_indexed_at(dict(row.owl_profile), version_id, db)

    # 2) Redis hot cache (re-indexed before the column was backfilled).
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, owl_profile_cache_key(version_id))
    if raw is not None:
        return await _fill_indexed_at(json.loads(raw), version_id, db)

    # 3) Self-heal: recompute from the stored file and persist. 404 when the
    #    version has no stored file (nothing to classify) or the parse fails —
    #    the ~14% of files horned-owl's strict reader rejects stay uncomputed.
    try:
        payload = await compute_owl_profile_payload(db, version_id, ontology_id)
    except Exception as exc:  # noqa: BLE001 — degrade to the historical 404
        raise HTTPException(
            status_code=404, detail="OWL profile not computed — reindex pending") from exc
    if payload is None:
        raise HTTPException(
            status_code=404, detail="OWL profile not computed — reindex pending")
    try:
        await db.execute(
            update(OntologyVersion).where(OntologyVersion.id == version_id).values(
                owl_profile=payload))
        await db.commit()
    except Exception:
        await db.rollback()
    return await _fill_indexed_at(payload, version_id, db)


@router.get("/owl-profile/public", summary="Fleet OWL profile rollup (no auth)")
async def get_fleet_profile(db: AsyncSession = Depends(get_db)):
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                OntologyVersion.id,
                OntologyVersion.ontology_id,
                Ontology.shortname,
                Ontology.title,
                OntologyVersion.owl_profile,
            )
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
            .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        )
    ).all()

    # Durable source = the row's owl_profile column. Redis is a fallback only for
    # versions not yet backfilled (indexed before the column existed).
    missing = [row.id for row in rows if not isinstance(row.owl_profile, dict)]
    redis_fallback: dict[str, dict] = {}
    if missing:
        r = _get_redis()
        raws = await asyncio.to_thread(
            r.mget, [owl_profile_cache_key(i) for i in missing])
        redis_fallback = {i: json.loads(raw) for i, raw in zip(missing, raws) if raw is not None}

    from ontoexplorer.modules.owl_profile.language import LANGUAGE_TIERS

    ontologies = []
    totals: dict[str, int] = {f"{p}_count": 0 for p in PROFILE_NAMES}
    totals["fleet_size"] = 0
    totals.update({f"tier_{t.replace('-', '_')}_count": 0 for t in LANGUAGE_TIERS})

    for row in rows:
        data = row.owl_profile if isinstance(row.owl_profile, dict) else redis_fallback.get(row.id)
        if data is None:
            continue
        entry: dict = {
            "id": row.ontology_id,
            "shortname": row.shortname,
            "title": row.title,
            "version_id": str(row.id),
        }
        totals["fleet_size"] += 1
        for p in PROFILE_NAMES:
            in_p = data.get(p, {}).get("in_profile", False)
            entry[f"in_{p}"] = in_p
            entry[f"{p}_violations"] = data.get(p, {}).get("total_violations", 0)
            if in_p:
                totals[f"{p}_count"] += 1
        tier = (data.get("language") or {}).get("tier")
        entry["language_tier"] = tier
        if tier in LANGUAGE_TIERS:
            totals[f"tier_{tier.replace('-', '_')}_count"] += 1
        ontologies.append(entry)

    return {"ontologies": ontologies, "totals": totals}


async def _latest_ready_profile_payloads(
    db: AsyncSession, ontology_ids: list[str]
) -> list[tuple[str, dict]]:
    """(ontology_id, owl_profile payload) for each id's latest ready version.

    Prefers the durable ``owl_profile`` column, falling back to the Redis cache
    for rows not yet backfilled. Ontologies with neither are omitted.
    """
    if not ontology_ids:
        return []
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(
            OntologyVersion.ontology_id.in_(ontology_ids),
            OntologyVersion.status == "ready",
        )
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    version_rows = (
        await db.execute(
            select(
                OntologyVersion.id,
                OntologyVersion.ontology_id,
                OntologyVersion.owl_profile,
            )
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
        )
    ).all()
    if not version_rows:
        return []

    missing = [vr.id for vr in version_rows if not isinstance(vr.owl_profile, dict)]
    redis_fallback: dict[str, dict] = {}
    if missing:
        r = _get_redis()
        raws = await asyncio.to_thread(
            r.mget, [owl_profile_cache_key(str(i)) for i in missing])
        redis_fallback = {i: json.loads(raw) for i, raw in zip(missing, raws) if raw is not None}

    out: list[tuple[str, dict]] = []
    for vr in version_rows:
        data = vr.owl_profile if isinstance(vr.owl_profile, dict) else redis_fallback.get(vr.id)
        if data is not None:
            out.append((vr.ontology_id, data))
    return out


async def filter_ontology_ids_by_profile(
    db: AsyncSession,
    ontology_ids: list[str],
    profile: str,
) -> set[str]:
    """Subset of *ontology_ids* whose latest ready version is in OWL 2 *profile*.

    Assumes *profile* has already been validated and lower-cased by the caller.
    """
    matching: set[str] = set()
    for oid, data in await _latest_ready_profile_payloads(db, ontology_ids):
        if data.get(profile, {}).get("in_profile", False):
            matching.add(oid)

    return matching


async def filter_ontology_ids_by_language(
    db: AsyncSession,
    ontology_ids: list[str],
    tier: str,
) -> set[str]:
    """Subset of *ontology_ids* whose latest ready version is in language *tier*
    (rdf | rdfs | rdfs-plus | owl). Assumes *tier* is already validated.
    """
    matching: set[str] = set()
    for oid, data in await _latest_ready_profile_payloads(db, ontology_ids):
        if (data.get("language") or {}).get("tier") == tier:
            matching.add(oid)
    return matching
