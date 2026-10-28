"""Admin stale-review queue for quality-gate-held versions (#364 Phase 3).

A global view of every version the quality gate is holding (``needs_review``),
oldest first, plus a bulk *honest re-check* that re-runs the gate from each
version's stored signals. The re-check is NOT the admin publish override
(``actions.admin_publish_version``, which ignores the gate): it recomputes
license/compliance and publishes only versions that now genuinely pass — useful
after the compliance allowlist is widened, titles are backfilled, or a license
is asserted on the version. Held versions that still fail stay held, with reasons.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.logging_config import get_logger
from ontoexplorer.models.db import Ontology, OntologyVersion, User

from ._common import _require_admin

router = APIRouter()
log = get_logger(__name__)


def _held_row(v: OntologyVersion, o: Ontology, *, min_triples: int, now: datetime) -> dict:
    from ontoexplorer.modules.ingestion.license import held_reasons

    # created_at is tz-aware on Postgres but can round-trip tz-naive (e.g. SQLite);
    # treat a naive value as UTC so the age subtraction never mixes aware/naive.
    created = v.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = (now - created).days if created else None
    return {
        "version_id": v.id,
        "ontology_id": o.id,
        "ontology_title": o.title,
        "ontology_shortname": o.shortname,
        "created_at": created.isoformat() if created else None,
        "age_days": age_days,
        "triple_count": v.triple_count,
        "license": v.license,
        "license_raw": v.license_raw,
        "declared_license": v.declared_license,
        # Recomputed from stored signals so a title fixed since ingest is reflected,
        # matching the per-ontology admin surface (#377).
        "review_reasons": held_reasons(
            license_compliant=v.license_compliant, triple_count=v.triple_count,
            title=o.title, min_triples=min_triples,
        ),
    }


@router.get(
    "/versions/held",
    summary="Held (needs_review) versions across all ontologies, oldest first",
)
async def admin_held_versions(
    min_age_days: int = Query(0, ge=0, le=3650),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """The stale-review queue: every version the gate is holding (``needs_review``),
    oldest first (most overdue first). ``min_age_days`` keeps only versions held at
    least that long — e.g. ``14`` for the "sitting > 2 weeks" backlog; ``0`` lists
    all held. Each row carries the recomputed reasons + license overlay so the UI can
    offer a one-click bulk re-check."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=min_age_days)
    rows = (await db.execute(
        select(OntologyVersion, Ontology)
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        .where(
            OntologyVersion.status == "needs_review",
            OntologyVersion.created_at <= cutoff,
        )
        .order_by(OntologyVersion.created_at.asc())
        .limit(limit)
    )).all()
    min_triples = get_settings().min_triples_for_publish
    return {
        "versions": [_held_row(v, o, min_triples=min_triples, now=now) for v, o in rows],
        "min_age_days": min_age_days,
        "total": len(rows),
    }


class BulkReevaluateRequest(BaseModel):
    version_ids: list[str]


@router.post(
    "/versions/bulk-reevaluate",
    summary="Re-run the quality gate on many held versions (honest re-check, not override)",
)
async def admin_bulk_reevaluate(
    body: BulkReevaluateRequest,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-run the quality gate on each given version from its stored signals, the same
    honest re-check the owner `reevaluate` uses (NOT the publish override): recompute
    license/compliance + overlay, publish those that now pass, leave the rest held
    with their reasons. Unknown ids and already-non-held versions are skipped and
    reported, so the call is safe to run over a stale selection."""
    from ontoexplorer.modules.ingestion.license import reevaluate_from_signals

    ids = list(dict.fromkeys(body.version_ids))  # de-dup, preserve order
    if not ids:
        raise HTTPException(status_code=422, detail="version_ids must not be empty")

    rows = (await db.execute(
        select(OntologyVersion, Ontology)
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        .where(OntologyVersion.id.in_(ids))
    )).all()
    by_id = {v.id: (v, o) for v, o in rows}
    min_triples = get_settings().min_triples_for_publish

    results: list[dict] = []
    published = 0
    for vid in ids:
        pair = by_id.get(vid)
        if pair is None:
            results.append({"version_id": vid, "outcome": "not_found"})
            continue
        v, o = pair
        if v.status != "needs_review":
            results.append({"version_id": vid, "outcome": "skipped", "status": v.status})
            continue
        content_spdx, lic_ok, new_status, reasons = reevaluate_from_signals(
            license_raw=v.license_raw, declared_license=v.declared_license,
            triple_count=v.triple_count, title=o.title, min_triples=min_triples,
        )
        v.license = content_spdx
        v.license_compliant = lic_ok
        if new_status == "ready":
            v.status = "ready"
            published += 1
        results.append({
            "version_id": vid,
            "outcome": "published" if new_status == "ready" else "still_held",
            "status": v.status,
            "review_reasons": reasons,
        })
    await db.commit()

    # Newly-ready versions can become an ontology's public default; drop the cache so
    # the catalogue/default picks them up without waiting for the TTL.
    if published:
        try:
            from ontoexplorer.modules.search.versions import invalidate_latest_ready_versions_cache
            invalidate_latest_ready_versions_cache()
        except Exception:
            pass
    log.info("admin_bulk_reevaluate", requested=len(ids), published=published)
    return {"results": results, "published": published, "requested": len(ids)}
