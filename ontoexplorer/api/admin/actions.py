"""Per-ontology and per-version pipeline action endpoints.

Every endpoint here just queues a Celery task. The per-ontology endpoints
operate on the latest non-deprecated version; the per-version endpoints
take an explicit version_id.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.logging_config import get_logger
from ontoexplorer.models.db import User

from ._common import _load_version, _require_admin

router = APIRouter()
log = get_logger(__name__)


# ── Per-ontology: check for upstream change (compares SHA-256) ────────────────

@router.post("/ontologies/{ontology_id}/check-update", summary="Check if a remote ontology has changed")
async def admin_check_update(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Poll the ontology's canonical IRI (content-negotiated) for a newer release
    and compare against its *version-aware* default version.

    We poll the resolvable IRI, not a past version's ``source_url`` — for
    aggregator ingests that source_url is a frozen snapshot that never changes
    (see ingestion.update_check). source_url is used only when there is no IRI.
    A newer release is queued for ingestion; an upstream that is byte-identical,
    or carries a strictly OLDER version, is reported as up to date.
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.ingestion.update_check import check_for_update
    from ontoexplorer.modules.jobs.tasks import ingest_ontology
    from ontoexplorer.modules.search.versions import _choose

    ont = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()
    if ont is None:
        raise HTTPException(status_code=404, detail="Ontology not found")

    versions = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == ontology_id)
    )).scalars().all()
    # The version-aware default (highest version_iri, honouring a pin) — the right
    # baseline to compare upstream against, not merely the newest-ingested row.
    default = _choose(versions, ont.current_version_id)
    if default is None and not ont.iri:
        raise HTTPException(status_code=404, detail="No version or IRI for this ontology")

    result = await check_for_update(ont, default)

    if result["status"] == "no_source":
        return {"status": "no_source_url"}
    if result["status"] == "fetch_error":
        raise HTTPException(status_code=502, detail=f"Failed to fetch source: {result.get('detail')}")
    if result["status"] in ("up_to_date", "older_skipped"):
        return {"status": "up_to_date", "detail": result.get("fetched_version")
                if result["status"] == "older_skipped" else None}

    # update_available -> queue ingestion from the same (canonical) location.
    task = ingest_ontology.delay(
        iri=result["fetch_url"] if result["use_conneg"] else None,
        url=result["fetch_url"] if not result["use_conneg"] else None,
        raw_bytes_hex=None,
        filename=None,
        content_type=None,
        owner_id=ont.owner_id,
        groups=list(ont.groups or []),
    )
    return {"status": "update_queued", "task_id": task.id,
            "detected_version": result.get("fetched_version")}


# ── Per-ontology: queue actions against the latest non-deprecated version ─────

@router.post("/ontologies/{ontology_id}/ingest", summary="Queue re-ingestion of an ontology")
async def admin_queue_ingest(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Directly queue re-ingestion from the ontology's canonical IRI (content
    negotiation), falling back to the default version's source_url only when there
    is no IRI. No SHA-256 comparison — always queues a new ingest job.

    Prefers the IRI over source_url for the same reason as check-update: a past
    version's source_url can be a frozen aggregator snapshot, so re-ingesting it
    would just re-pull the old release (see ingestion.update_check.fetch_target).
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.ingestion.update_check import fetch_target
    from ontoexplorer.modules.jobs.tasks import ingest_ontology
    from ontoexplorer.modules.search.versions import _choose

    ont = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one_or_none()
    if ont is None:
        raise HTTPException(status_code=404, detail="Ontology not found")
    versions = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id == ontology_id)
    )).scalars().all()
    default = _choose(versions, ont.current_version_id)

    fetch_url, use_iri = fetch_target(ont, default)
    if not fetch_url:
        raise HTTPException(status_code=422, detail="No source URL or IRI available for this ontology")

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


class _BulkActionRequest(BaseModel):
    action: str  # index | embed | reason | detect_profile | ingest
    ontology_ids: list[str]


_BULK_ACTIONS = {"index", "embed", "reason", "detect_profile", "ingest"}


@router.post("/ontologies/bulk", summary="Queue a pipeline action for many ontologies")
async def admin_bulk_action(
    body: _BulkActionRequest,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queue one pipeline action (index/embed/reason/detect_profile/ingest) for each
    ontology's latest non-deprecated version. Powers the admin table's bulk-action
    bar. Latest versions resolved in one query; returns per-ontology outcomes."""
    from sqlalchemy import bindparam, select, text

    from ontoexplorer.models.db import Ontology
    from ontoexplorer.modules.jobs.tasks import (
        detect_profile,
        embed_ontology,
        index_ontology,
        ingest_ontology,
        reason_ontology,
    )

    action = body.action
    if action not in _BULK_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Unknown action: {action}")
    ids = list(dict.fromkeys(body.ontology_ids))  # dedup, keep order
    if not ids:
        return {"action": action, "queued": [], "skipped": [], "errors": {}}

    # Latest non-deprecated version per ontology — one window-function pass.
    rows = (await db.execute(
        text("""
            WITH ranked AS (
                SELECT id, ontology_id, source_url,
                       row_number() OVER (PARTITION BY ontology_id ORDER BY created_at DESC) AS rn
                FROM versions WHERE status <> 'deprecated' AND ontology_id IN :ids
            )
            SELECT id, ontology_id, source_url FROM ranked WHERE rn = 1
        """).bindparams(bindparam("ids", expanding=True)), {"ids": ids},
    )).all()
    latest = {str(r.ontology_id): (str(r.id), r.source_url) for r in rows}

    onts = {}
    if action == "ingest":
        onts = {str(o.id): o for o in (await db.execute(
            select(Ontology).where(Ontology.id.in_(ids)))).scalars().all()}

    queued: list[str] = []
    skipped: list[str] = []
    errors: dict[str, str] = {}
    for oid in ids:
        info = latest.get(oid)
        # index/embed/reason/detect_profile need a version; ingest can use the IRI.
        if info is None and action != "ingest":
            skipped.append(oid)
            continue
        vid = info[0] if info else None
        try:
            if action == "index":
                index_ontology.delay(version_id=vid, ontology_id=oid)
            elif action == "embed":
                embed_ontology.delay(version_id=vid, ontology_id=oid)
            elif action == "reason":
                reason_ontology.delay(version_id=vid)
            elif action == "detect_profile":
                detect_profile.delay(version_id=vid, ontology_id=oid)
            elif action == "ingest":
                ont = onts.get(oid)
                if ont is None:
                    skipped.append(oid)
                    continue
                src = info[1] if info else None
                use_iri = not src
                if use_iri and not ont.iri:
                    errors[oid] = "no source_url or iri"
                    continue
                fetch = src or ont.iri
                ingest_ontology.delay(
                    iri=fetch if use_iri else None,
                    url=fetch if not use_iri else None,
                    raw_bytes_hex=None, filename=None, content_type=None,
                    owner_id=ont.owner_id, groups=list(ont.groups or []),
                )
            queued.append(oid)
        except Exception as exc:  # one bad enqueue must not drop the rest
            errors[oid] = str(exc)[:200]

    return {"action": action, "queued": queued, "skipped": skipped, "errors": errors}


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


@router.post(
    "/versions/{version_id}/publish",
    summary="Publish a held (needs_review) version — admin override of the quality gate",
)
async def admin_publish_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Clear the #364 quality gate for one version: flip `needs_review` -> `ready`
    so it enters the public catalogue. Admin override — use after reviewing the
    held version's reasons; to reject instead, delete the version. Idempotent-ish:
    only a held version is publishable (409 otherwise)."""
    from sqlalchemy import update as _update
    from ontoexplorer.models.db import OntologyVersion

    v = await _load_version(db, version_id)
    if v.status != "needs_review":
        raise HTTPException(
            status_code=409,
            detail=f"Version is '{v.status}', not 'needs_review'; nothing to publish.",
        )
    await db.execute(
        _update(OntologyVersion).where(OntologyVersion.id == v.id).values(status="ready")
    )
    await db.commit()
    # A newly-ready version can become the ontology's default; drop the cache so
    # the catalogue/default picks it up without waiting for the TTL.
    try:
        from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache
        invalidate_latest_ready_versions_cache()
    except Exception:
        pass
    log.info("version_published_from_review", version_id=v.id, ontology_id=v.ontology_id)
    return {"status": "ready", "version_id": v.id}


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


@router.patch("/ontologies/{ontology_id}/owner", summary="Reassign (or clear) an ontology's owner")
async def admin_set_ontology_owner(
    ontology_id: str,
    user_id: str | None = Body(None, embed=True),
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set (or clear, with null) an ontology's owner.

    The only path to un-orphan an ontology: owner_id is ON DELETE SET NULL, so a
    deleted account leaves ontologies ownerless, and since #118 those are
    admin/maintainer-only to edit. This lets an admin hand one to a real owner
    (or deliberately clear it) without a direct DB edit.
    """
    from ontoexplorer.models.db import Ontology

    ont = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one_or_none()
    if ont is None:
        raise HTTPException(status_code=404, detail="Ontology not found")

    if user_id is not None:
        target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=422, detail=f"No such user: {user_id}")

    ont.owner_id = user_id
    await db.commit()
    return {"ontology_id": ontology_id, "owner_id": user_id}
