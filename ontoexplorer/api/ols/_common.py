"""Shared dependencies for OLS-compat routes."""
from fastapi import HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.versions import latest_ready_version as get_latest_version_or_404  # noqa: F401


async def get_ontology_or_404(db: AsyncSession, ontology_id: str) -> Ontology:
    o = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail=f"Ontology '{ontology_id}' not found")
    return o


def hal_page_params(
    page: int = Query(0, ge=0, description="Page number (0-based)"),
    size: int = Query(20, ge=1, le=500, description="Items per page"),
) -> tuple[int, int]:
    return page, size


def page_to_offset(page: int, size: int) -> int:
    return page * size
