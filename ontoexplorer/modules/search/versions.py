"""Shared helpers for resolving the latest ready OntologyVersion."""
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import OntologyVersion

# In-process cache for the latest-ready-versions list. Invalidated implicitly by TTL;
# new ingests become visible within _LATEST_TTL seconds.
_LATEST_TTL = 30.0
_latest_cache: tuple[float, list[OntologyVersion]] | None = None


def invalidate_latest_ready_versions_cache() -> None:
    """Call after a new version becomes ready so the next search sees it immediately."""
    global _latest_cache
    _latest_cache = None


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
    """Return the most-recently-indexed non-deprecated version for every ontology.

    Cached in-process for _LATEST_TTL seconds — new ingests become visible after TTL
    expiry (or immediately via invalidate_latest_ready_versions_cache()).
    """
    global _latest_cache
    now = time.monotonic()
    if _latest_cache is not None and now - _latest_cache[0] < _LATEST_TTL:
        return _latest_cache[1]

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
    # Detach from the SQLAlchemy session so cached rows survive after the session closes.
    db.expunge_all()
    _latest_cache = (now, latest)
    return latest
