"""Per-ontology version listing endpoint."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import User

from ._common import (
    _diff_status_for_pair,
    _reasoning_status,
    _require_admin,
    _search_redis,
)

router = APIRouter()


@router.get(
    "/ontologies/{ontology_id}/versions",
    summary="List all versions of an ontology with per-version pipeline state",
)
async def admin_ontology_versions(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Returns every version of an ontology (newest first), each with the same
    pipeline fields as AdminOntologyEntry plus a diff_vs_prev block for the
    diff against the immediately-older version (None for the oldest)."""
    from sqlalchemy import func, select
    from ontoexplorer.models.db import Ontology, OntologyVersion, TermEmbedding

    ont = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()
    if ont is None:
        raise HTTPException(status_code=404, detail="Ontology not found")

    versions = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .order_by(OntologyVersion.created_at.desc())
    )).scalars().all()

    if not versions:
        return {"ontology_id": ontology_id, "versions": []}

    version_ids = [v.id for v in versions]
    count_rows = (await db.execute(
        select(TermEmbedding.version_id, func.count().label("cnt"))
        .where(TermEmbedding.version_id.in_(version_ids))
        .group_by(TermEmbedding.version_id)
    )).all()
    embed_counts = {str(r.version_id): int(r.cnt) for r in count_rows}

    search_r = await asyncio.to_thread(_search_redis)
    # Pin-aware, version-aware default (not merely the newest by created_at), so
    # the admin "latest" marker matches the rest of the app.
    from ontoexplorer.modules.search.versions import latest_versions_for
    _default = (await latest_versions_for(db, [ontology_id])).get(ontology_id)
    latest_id = _default.id if _default is not None else versions[0].id

    async def _entry(idx: int, v: OntologyVersion) -> dict:
        vid = v.id
        indexed = await asyncio.to_thread(
            lambda: bool(search_r.exists(f"search:meta:{vid}"))
        )
        profile_computed = await asyncio.to_thread(
            lambda: bool(search_r.exists(f"owl_profile:{vid}"))
        )
        reasoning = await _reasoning_status(vid)

        prev_version_id = versions[idx + 1].id if idx + 1 < len(versions) else None
        if prev_version_id is not None:
            diff_vs_prev = await _diff_status_for_pair(db, prev_version_id, vid)
            diff_vs_prev["previous_version_id"] = prev_version_id
        else:
            diff_vs_prev = {
                "previous_version_id": None,
                "status": "missing",
                "diff_id": None,
                "computed_at": None,
            }

        return {
            "version_id": vid,
            "version_iri": v.version_iri,
            "triple_count": v.triple_count,
            "ingestion_status": v.status,
            "indexed": indexed,
            "profile_computed": profile_computed,
            "embed_count": embed_counts.get(vid, 0),
            "reasoning_status": reasoning,
            "version_created_at": v.created_at.isoformat() if v.created_at else None,
            "source_url": v.source_url,
            "is_latest": vid == latest_id,
            "diff_vs_prev": diff_vs_prev,
        }

    entries = await asyncio.gather(*[_entry(i, v) for i, v in enumerate(versions)])
    return {"ontology_id": ontology_id, "versions": list(entries)}
