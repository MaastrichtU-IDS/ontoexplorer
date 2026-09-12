"""Per-ontology and per-version pipeline action endpoints.

Every endpoint here just queues a Celery task. The per-ontology endpoints
operate on the latest non-deprecated version; the per-version endpoints
take an explicit version_id.
"""
from __future__ import annotations

import hashlib

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import User

from ._common import _RDF_ACCEPT, _load_version, _require_admin

router = APIRouter()


# ── Per-ontology: check for upstream change (compares SHA-256) ────────────────

@router.post("/ontologies/{ontology_id}/check-update", summary="Check if a remote ontology has changed")
async def admin_check_update(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the latest version and compare SHA-256.

    Falls back to the ontology IRI (with RDF content negotiation) when no
    source_url is stored (e.g. the version was uploaded as a file).
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    version = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .where(OntologyVersion.status != "deprecated")
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="No version found for this ontology")

    ont = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one()

    fetch_url = version.source_url
    use_iri_negotiation = False
    if not fetch_url:
        if not ont.iri:
            return {"status": "no_source_url"}
        fetch_url = ont.iri
        use_iri_negotiation = True

    headers = {"Accept": _RDF_ACCEPT} if use_iri_negotiation else {}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), follow_redirects=True) as client:
            async with client.stream("GET", fetch_url, headers=headers) as resp:
                resp.raise_for_status()
                h = hashlib.sha256()
                async for chunk in resp.aiter_bytes(65536):
                    h.update(chunk)
                new_sha256 = h.hexdigest()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Source returned HTTP {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch source: {exc}")

    if new_sha256 == version.sha256:
        return {"status": "up_to_date"}

    task = ingest_ontology.delay(
        iri=fetch_url if use_iri_negotiation else None,
        url=fetch_url if not use_iri_negotiation else None,
        raw_bytes_hex=None,
        filename=None,
        content_type=None,
        owner_id=ont.owner_id,
        groups=list(ont.groups or []),
    )
    return {"status": "update_queued", "task_id": task.id}


# ── Per-ontology: queue actions against the latest non-deprecated version ─────

@router.post("/ontologies/{ontology_id}/ingest", summary="Queue re-ingestion of an ontology")
async def admin_queue_ingest(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Directly queue re-ingestion using source_url (URL) or IRI (content negotiation).

    No SHA-256 comparison — always queues a new ingest job.
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    version = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .where(OntologyVersion.status != "deprecated")
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    ont = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one()

    fetch_url = version.source_url if version else None
    use_iri = False
    if not fetch_url:
        if not ont.iri:
            raise HTTPException(status_code=422, detail="No source URL or IRI available for this ontology")
        fetch_url = ont.iri
        use_iri = True

    task = ingest_ontology.delay(
        iri=fetch_url if use_iri else None,
        url=fetch_url if not use_iri else None,
        raw_bytes_hex=None,
        filename=None,
        content_type=None,
        owner_id=ont.owner_id,
        groups=list(ont.groups or []),
    )
    return {"status": "queued", "task_id": task.id, "method": "iri" if use_iri else "url"}


@router.post("/ontologies/{ontology_id}/index", summary="Queue search re-index for one ontology")
async def admin_queue_index(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue index_ontology for the latest ingested version of an ontology."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyVersion
    from ontoexplorer.modules.jobs.tasks import index_ontology

    version = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .where(OntologyVersion.status != "deprecated")
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="No non-deprecated version found for this ontology")

    task = index_ontology.delay(version_id=str(version.id), ontology_id=ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post("/ontologies/{ontology_id}/embed", summary="Queue embedding generation for one ontology")
async def admin_queue_embed(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue embed_ontology for the latest non-deprecated version of an ontology."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyVersion
    from ontoexplorer.modules.jobs.tasks import embed_ontology

    version = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .where(OntologyVersion.status != "deprecated")
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="No non-deprecated version found for this ontology")

    task = embed_ontology.delay(version_id=str(version.id), ontology_id=ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post("/ontologies/{ontology_id}/reason", summary="Queue OWL reasoning for one ontology")
async def admin_queue_reason(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue reason_ontology for the latest non-deprecated version of an ontology."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyVersion
    from ontoexplorer.modules.jobs.tasks import reason_ontology

    version = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .where(OntologyVersion.status != "deprecated")
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="No non-deprecated version found for this ontology")

    task = reason_ontology.delay(version_id=str(version.id))
    return {"status": "queued", "task_id": task.id}


@router.put("/ontologies/{ontology_id}/current-version",
             summary="Pin (or clear) the default version of an ontology")
async def admin_set_current_version(
    ontology_id: str,
    body: dict = Body(default={}),
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pin the ontology's default ("latest") version to `version_id`, overriding
    the automatic version-aware selection. Pass `version_id: null` to clear the
    pin and return to automatic selection."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache

    ont = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()
    if not ont:
        raise HTTPException(status_code=404, detail="Ontology not found")

    version_id = body.get("version_id")
    if version_id is not None:
        v = (await db.execute(
            select(OntologyVersion).where(
                OntologyVersion.id == version_id,
                OntologyVersion.ontology_id == ontology_id,
            )
        )).scalar_one_or_none()
        if not v:
            raise HTTPException(status_code=404, detail="Version not found for this ontology")
        if v.status in ("pending", "failed", "deprecated"):
            raise HTTPException(status_code=422, detail=f"Version is not ready (status={v.status})")

    ont.current_version_id = version_id  # None clears the pin
    await db.commit()
    invalidate_latest_ready_versions_cache()
    return {"ontology_id": ontology_id, "current_version_id": version_id}


@router.post("/ontologies/{ontology_id}/detect-profile", summary="Queue OWL profile detection for one ontology")
async def admin_queue_detect_profile(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue detect_profile for the latest non-deprecated version of an ontology."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyVersion
    from ontoexplorer.modules.jobs.tasks import detect_profile

    version = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .where(OntologyVersion.status != "deprecated")
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="No non-deprecated version found for this ontology")

    task = detect_profile.delay(str(version.id), ontology_id=ontology_id)
    return {"status": "queued", "task_id": task.id}


# ── Per-version: queue actions against an explicit version_id ─────────────────

@router.post(
    "/versions/{version_id}/index",
    summary="Queue search re-index for a specific version",
)
async def admin_queue_index_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tasks import index_ontology
    v = await _load_version(db, version_id)
    task = index_ontology.delay(version_id=v.id, ontology_id=v.ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post(
    "/versions/{version_id}/embed",
    summary="Queue embedding generation for a specific version",
)
async def admin_queue_embed_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tasks import embed_ontology
    v = await _load_version(db, version_id)
    task = embed_ontology.delay(version_id=v.id, ontology_id=v.ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post(
    "/versions/{version_id}/reason",
    summary="Queue OWL reasoning for a specific version",
)
async def admin_queue_reason_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tasks import reason_ontology
    v = await _load_version(db, version_id)
    task = reason_ontology.delay(version_id=v.id)
    return {"status": "queued", "task_id": task.id}


@router.post(
    "/versions/{version_id}/detect-profile",
    summary="Queue OWL profile detection for a specific version",
)
async def admin_queue_detect_profile_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tasks import detect_profile
    v = await _load_version(db, version_id)
    task = detect_profile.delay(v.id, ontology_id=v.ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post(
    "/versions/{version_id}/ingest",
    summary="Re-fetch a specific version's source URL (creates a new version if bytes have changed)",
)
async def admin_queue_ingest_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Dispatches ingest_ontology against this version's source_url (or the
    ontology's IRI via content negotiation when no source_url is set).

    Important: the ingestion pipeline is content-addressed by SHA-256, so if
    the bytes haven't changed, the existing version is returned and nothing
    happens. If they have changed, a NEW version is created — versions are
    immutable.
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    v = await _load_version(db, version_id)
    ont = (await db.execute(
        select(Ontology).where(Ontology.id == v.ontology_id)
    )).scalar_one()

    fetch_url = v.source_url
    use_iri = False
    if not fetch_url:
        if not ont.iri:
            raise HTTPException(
                status_code=422,
                detail="Version has no source_url and parent ontology has no IRI",
            )
        fetch_url = ont.iri
        use_iri = True

    task = ingest_ontology.delay(
        iri=fetch_url if use_iri else None,
        url=fetch_url if not use_iri else None,
        raw_bytes_hex=None,
        filename=None,
        content_type=None,
        owner_id=ont.owner_id,
        groups=list(ont.groups or []),
    )
    return {"status": "queued", "task_id": task.id, "method": "iri" if use_iri else "url"}


# ── Bulk: re-index everything ────────────────────────────────────────────────

@router.post("/reindex", summary="Queue search re-index for all ingested versions")
async def admin_reindex(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue index_ontology for every ingested version and detect_meta_profile for all versions.

    Safe to run multiple times.
    """
    from ontoexplorer.modules.jobs.tasks import detect_meta_profile, index_ontology

    all_rows = (await db.execute(
        text("""
            SELECT v.id AS version_id, v.ontology_id, v.status
            FROM versions v
            ORDER BY v.created_at DESC
        """)
    )).mappings().all()

    meta_queued = 0
    index_queued = 0
    for row in all_rows:
        vid = str(row["version_id"])
        oid = str(row["ontology_id"])
        detect_meta_profile.delay(vid, ontology_id=oid)
        meta_queued += 1
        if row["status"] != "deprecated":
            index_ontology.delay(version_id=vid, ontology_id=oid)
            index_queued += 1

    return {
        "meta_detection_queued": meta_queued,
        "index_queued": index_queued,
        "message": (
            f"Queued {meta_queued} detect_meta_profile tasks "
            f"and {index_queued} index_ontology tasks"
        ),
    }


# ── Jobs: clear recent terminal jobs ─────────────────────────────────────────

@router.delete("/jobs", summary="Clear completed/failed job rows from the recent-jobs log")
async def admin_clear_jobs(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete job rows in a terminal state (done | failed). Running and pending rows are kept."""
    result = await db.execute(
        text("DELETE FROM jobs WHERE status IN ('done', 'failed')")
    )
    await db.commit()
    return {"deleted": result.rowcount or 0}


@router.post("/metadata/backfill", summary="Re-derive FAIR metadata for all versions into the metadata store")
async def admin_backfill_metadata(_: User = Depends(_require_admin)):
    """Queue a one-shot backfill that regenerates DCAT/VoID/PROV for every
    non-deprecated version. Used after the Fuseki -> in-process-store migration."""
    from ontoexplorer.modules.jobs.tasks import backfill_metadata
    task = backfill_metadata.delay()
    return {"status": "queued", "task_id": task.id}
