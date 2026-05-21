"""Consistency-analysis endpoints — read-only views over the Redis consistency cache."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.consistency.cache import consistency_cache_key
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["consistency"])


@router.get(
    "/ontologies/{ontology_id}/{version_id}/consistency",
    summary="Per-version consistency report",
)
async def get_version_consistency(ontology_id: str, version_id: str):
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, consistency_cache_key(version_id))
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="Consistency report not computed — reindex pending",
        )
    return json.loads(raw)


@router.post(
    "/ontologies/{ontology_id}/{version_id}/consistency/refresh",
    summary="Re-enqueue consistency check (admin/owner only)",
)
async def refresh_consistency(ontology_id: str, version_id: str):
    """Re-run the Celery check_consistency task without re-indexing."""
    from ontoexplorer.modules.jobs.tasks import check_consistency
    check_consistency.delay(version_id, ontology_id)
    return {"status": "enqueued", "version_id": version_id}


@router.get("/consistency/fleet", summary="Fleet consistency rollup (no auth)")
async def get_fleet_consistency(db: AsyncSession = Depends(get_db)):
    """Aggregate per-ontology consistency reports across the fleet."""
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
    keys = [consistency_cache_key(str(row.id)) for row in rows]
    payloads = await asyncio.to_thread(r.mget, keys) if keys else []

    ontologies: list[dict] = []
    totals = {
        "fleet_size": 0,
        "pending_or_running": 0,
        "consistent_all_scopes": 0,
        "inconsistent_any_scope": 0,
    }

    for row, raw in zip(rows, payloads):
        if not raw:
            continue
        data = json.loads(raw)
        totals["fleet_size"] += 1
        if data.get("job_status") in ("pending", "running"):
            totals["pending_or_running"] += 1
            entry = {
                "id": row.ontology_id,
                "shortname": row.shortname,
                "title": row.title,
                "version_id": str(row.id),
                "job_status": data.get("job_status"),
                "host_only": None,
                "host_plus_imports": None,
                "host_plus_imports_plus_mireot": None,
            }
            ontologies.append(entry)
            continue

        scopes = data.get("scopes", {})
        host_only = scopes.get("host_only", {}).get("status")
        host_plus_imports = scopes.get("host_plus_imports", {}).get("status")
        host_plus_imports_plus_mireot = scopes.get(
            "host_plus_imports_plus_mireot", {}
        ).get("status")

        all_consistent = (
            host_only == "consistent"
            and host_plus_imports == "consistent"
            and host_plus_imports_plus_mireot in ("consistent", "partial")
        )
        any_inconsistent = "inconsistent" in {
            host_only, host_plus_imports, host_plus_imports_plus_mireot
        }
        if all_consistent:
            totals["consistent_all_scopes"] += 1
        if any_inconsistent:
            totals["inconsistent_any_scope"] += 1

        ontologies.append({
            "id": row.ontology_id,
            "shortname": row.shortname,
            "title": row.title,
            "version_id": str(row.id),
            "job_status": data.get("job_status"),
            "host_only": host_only,
            "host_plus_imports": host_plus_imports,
            "host_plus_imports_plus_mireot": host_plus_imports_plus_mireot,
            "total_unsat": sum(
                len(scopes.get(s, {}).get("unsatisfiable_classes", []))
                for s in ("host_only", "host_plus_imports", "host_plus_imports_plus_mireot")
            ),
        })

    return {"ontologies": ontologies, "totals": totals}


async def filter_ontology_ids_by_consistency(
    db: AsyncSession,
    ontology_ids: list[str],
    value: str,
) -> set[str]:
    """Subset of ontology_ids whose latest ready version matches the consistency filter.

    Supported values: 'inconsistent' (inconsistent in any scope), 'consistent' (consistent
    in all three scopes, allowing 'partial' on the MIREOT scope).
    """
    if not ontology_ids or value not in ("inconsistent", "consistent"):
        return set()

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
        return set()

    r = _get_redis()
    keys = [consistency_cache_key(str(vr.id)) for vr in version_rows]
    raws = await asyncio.to_thread(r.mget, keys)

    matching: set[str] = set()
    for vr, raw in zip(version_rows, raws):
        if not raw:
            continue
        data = json.loads(raw)
        if data.get("job_status") != "done":
            continue
        scopes = data.get("scopes", {})
        statuses = {scopes.get(s, {}).get("status")
                    for s in ("host_only", "host_plus_imports", "host_plus_imports_plus_mireot")}
        if value == "inconsistent" and "inconsistent" in statuses:
            matching.add(vr.ontology_id)
        elif value == "consistent":
            ok_set = {"consistent", "partial"}
            if statuses <= ok_set:
                matching.add(vr.ontology_id)
    return matching
