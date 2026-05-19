"""Shared helpers for resolving the latest ready OntologyVersion."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import OntologyVersion


async def latest_ready_version(db: AsyncSession, ontology_id: str) -> OntologyVersion:
    """Return the most-recent non-deprecated ready version for *ontology_id*, or raise HTTP 404."""
    result = await db.execute(
        select(OntologyVersion)
        .where(
            OntologyVersion.ontology_id == ontology_id,
            OntologyVersion.status.notin_(["pending", "failed", "deprecated"]),
        )
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(
            status_code=404,
            detail=f"Ontology '{ontology_id}' not found or has no indexed version",
        )
    return v


async def latest_ready_versions(db: AsyncSession) -> list[OntologyVersion]:
    """Return the most-recently-indexed non-deprecated version for every ontology."""
    result = await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.status.notin_(["pending", "failed", "deprecated"]))
        .order_by(OntologyVersion.ontology_id, OntologyVersion.created_at.desc())
    )
    seen: set[str] = set()
    latest: list[OntologyVersion] = []
    for v in result.scalars():
        if v.ontology_id not in seen:
            seen.add(v.ontology_id)
            latest.append(v)
    return latest
