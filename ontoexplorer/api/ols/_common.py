"""Shared dependencies for OLS-compat routes."""
from fastapi import HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.versions import latest_ready_version


async def get_latest_version_or_404(db: AsyncSession, ontology_id: str) -> OntologyVersion:
    """Resolve the latest ready version by ontology shortname OR UUID.

    Wraps the canonical `latest_ready_version` helper (which expects a UUID
    FK) so OLS routes can be called with either form transparently.
    """
    ontology = await get_ontology_or_404(db, ontology_id)
    return await latest_ready_version(db, ontology.id)


async def get_ontology_or_404(db: AsyncSession, ontology_id: str) -> Ontology:
    """Resolve an ontology by shortname OR UUID.

    OLS4 convention uses short codes (e.g. 'efo', 'go') in URL paths. We
    accept both forms: try shortname first (the canonical user-facing
    identifier), fall back to UUID for any client still using internal IDs.
    """
    o = (await db.execute(
        select(Ontology).where(Ontology.shortname == ontology_id)
    )).scalar_one_or_none()
    if o is None:
        o = (await db.execute(
            select(Ontology).where(Ontology.id == ontology_id)
        )).scalar_one_or_none()
    if o is None:
        raise HTTPException(status_code=404, detail=f"Ontology '{ontology_id}' not found")
    return o


def hal_page_params(
    page: int = Query(0, ge=0, description="Page number (0-based)"),
    size: int = Query(20, ge=1, le=500, description="Items per page"),
) -> tuple[int, int]:
    return page, size


def page_to_offset(page: int, size: int) -> int:
    return page * size
