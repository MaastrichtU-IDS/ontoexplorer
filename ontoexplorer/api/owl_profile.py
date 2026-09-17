"""OWL 2 profile endpoints — read-only views over the Redis owl_profile cache."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
from ontoexplorer.modules.owl_profile.registry import PROFILE_NAMES
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["owl-profile"])


@router.get(
    "/ontologies/{ontology_id}/{version_id}/owl-profile",
    summary="Per-version OWL 2 profile classification",
)
async def get_version_profile(ontology_id: str, version_id: str):
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, owl_profile_cache_key(version_id))
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="OWL profile not computed — reindex pending",
        )
    return json.loads(raw)


@router.get("/owl-profile/public", summary="Fleet OWL profile rollup (no auth)")
async def get_fleet_profile(db: AsyncSession = Depends(get_db)):
    # Subquery: latest ready version per ontology (mirrors coverage.py pattern)
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
            )
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
            .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        )
    ).all()

    r = _get_redis()
    keys = [owl_profile_cache_key(str(row.id)) for row in rows]
    payloads = await asyncio.to_thread(r.mget, keys) if keys else []

    from ontoexplorer.modules.owl_profile.language import LANGUAGE_TIERS

    ontologies = []
    totals: dict[str, int] = {f"{p}_count": 0 for p in PROFILE_NAMES}
    totals["fleet_size"] = 0
    totals.update({f"tier_{t.replace('-', '_')}_count": 0 for t in LANGUAGE_TIERS})

    for row, raw in zip(rows, payloads):
        if not raw:
            continue
        data = json.loads(raw)
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

    Fleet-rollup pattern: one SQL round-trip for the latest ready versions, then
    one Redis mget for the cached payloads. Ontologies without a cached payload
    are omitted.
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
            select(OntologyVersion.id, OntologyVersion.ontology_id)
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
        )
    ).all()
    if not version_rows:
        return []
    r = _get_redis()
    keys = [owl_profile_cache_key(str(vr.id)) for vr in version_rows]
    raws = await asyncio.to_thread(r.mget, keys)
    return [
        (vr.ontology_id, json.loads(raw))
        for vr, raw in zip(version_rows, raws)
        if raw
    ]


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
