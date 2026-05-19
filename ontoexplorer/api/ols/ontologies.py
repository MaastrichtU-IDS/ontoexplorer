"""OLS4-compat ontology endpoints.

Implements:
  GET /ols/api/ontologies                    — HAL paged list
  GET /ols/api/ontologies/{ontology_id}      — HAL detail
  GET /ols/api/v2/ontologies                 — v2 flat paged list
  GET /ols/api/v2/ontologies/{ontology_id}   — v2 flat detail
  GET /ols/api/ontologies/{ontology_id}/download  — 302 redirect to internal download route
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology
from ontoexplorer.modules.search.indexer import _get_redis, _meta_key  # noqa: F401 — patched in tests
from ontoexplorer.modules.owl_profile.registry import PROFILE_NAMES
from ontoexplorer.api.ols._envelope import hal_page, v2_page
from ontoexplorer.api.ols._shapes import ontology_to_v1, ontology_to_v2
from ontoexplorer.api.ols._common import (
    get_latest_version_or_404,
    get_ontology_or_404,
    hal_page_params,
    page_to_offset,
)

router = APIRouter()


async def _ontology_shape(
    db: AsyncSession,
    o: Ontology,
    request: Request,
    *,
    v2: bool,
) -> dict:
    """Resolve the latest version, fetch Redis meta counts + langs, and build an OLS shape."""
    from ontoexplorer.modules.search.indexer import _langs_key

    version = await get_latest_version_or_404(db, o.id)

    def _read_redis() -> tuple[dict, list[str]]:
        r = _get_redis()
        meta = r.hgetall(_meta_key(str(version.id)))
        langs_counts = r.hgetall(_langs_key(str(version.id)))
        # Drop empty-string key (entries without a lang tag) and sort by descending
        # frequency so the first item is the dominant language.
        langs = [k for k, _ in sorted(
            ((k, int(v)) for k, v in langs_counts.items() if k),
            key=lambda kv: -kv[1],
        )]
        return meta, langs

    meta, langs = await asyncio.to_thread(_read_redis)
    if v2:
        return ontology_to_v2(o, version, meta, request=request, languages=langs)
    return ontology_to_v1(o, version, meta, request=request, languages=langs)


# ---------------------------------------------------------------------------
# HAL (v1) endpoints
# ---------------------------------------------------------------------------

@router.get("/api/ontologies")
async def list_ontologies_hal(
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    profile: str | None = Query(None, description="Filter by OWL 2 profile: el | rl | ql | dl"),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    offset = page_to_offset(page, size)

    if profile is not None:
        profile = profile.lower()
        if profile not in PROFILE_NAMES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid profile '{profile}'. Must be one of: {', '.join(PROFILE_NAMES)}",
            )

    if profile:
        # Load all ontologies, filter by profile, then page-slice on the filtered list
        from ontoexplorer.api.owl_profile import filter_ontology_ids_by_profile
        all_rows = (
            await db.execute(select(Ontology).order_by(Ontology.id))
        ).scalars().all()
        all_ids = [o.id for o in all_rows]
        matching_ids = await filter_ontology_ids_by_profile(db, all_ids, profile)
        filtered_rows = [o for o in all_rows if o.id in matching_ids]
        total = len(filtered_rows)
        rows = filtered_rows[offset: offset + size]
    else:
        total = (await db.execute(select(func.count(Ontology.id)))).scalar_one()
        rows = (
            await db.execute(select(Ontology).order_by(Ontology.id).limit(size).offset(offset))
        ).scalars().all()

    items = [await _ontology_shape(db, o, request, v2=False) for o in rows]
    return hal_page(items, request, total=total, page=page, size=size, embedded_key="ontologies")


@router.get("/api/ontologies/{ontology_id}/download")
async def download_proxy(
    ontology_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Redirect to the internal download route for the latest version."""
    version = await get_latest_version_or_404(db, ontology_id)
    return RedirectResponse(
        url=f"/api/v1/ontologies/{ontology_id}/{version.id}/download",
        status_code=302,
    )


@router.get("/api/ontologies/{ontology_id}")
async def get_ontology_hal(
    ontology_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    o = await get_ontology_or_404(db, ontology_id)
    return await _ontology_shape(db, o, request, v2=False)


# ---------------------------------------------------------------------------
# V2 flat endpoints
# ---------------------------------------------------------------------------

@router.get("/api/v2/ontologies")
async def list_ontologies_v2(
    request: Request,
    page_size: tuple[int, int] = Depends(hal_page_params),
    profile: str | None = Query(None, description="Filter by OWL 2 profile: el | rl | ql | dl"),
    db: AsyncSession = Depends(get_db),
):
    page, size = page_size
    offset = page_to_offset(page, size)

    if profile is not None:
        profile = profile.lower()
        if profile not in PROFILE_NAMES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid profile '{profile}'. Must be one of: {', '.join(PROFILE_NAMES)}",
            )

    if profile:
        # Load all ontologies, filter by profile, then page-slice on the filtered list
        from ontoexplorer.api.owl_profile import filter_ontology_ids_by_profile
        all_rows = (
            await db.execute(select(Ontology).order_by(Ontology.id))
        ).scalars().all()
        all_ids = [o.id for o in all_rows]
        matching_ids = await filter_ontology_ids_by_profile(db, all_ids, profile)
        filtered_rows = [o for o in all_rows if o.id in matching_ids]
        total = len(filtered_rows)
        rows = filtered_rows[offset: offset + size]
    else:
        total = (await db.execute(select(func.count(Ontology.id)))).scalar_one()
        rows = (
            await db.execute(select(Ontology).order_by(Ontology.id).limit(size).offset(offset))
        ).scalars().all()

    items = [await _ontology_shape(db, o, request, v2=True) for o in rows]
    return v2_page(items, request, total=total, page=page, size=size)


@router.get("/api/v2/ontologies/{ontology_id}")
async def get_ontology_v2(
    ontology_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    o = await get_ontology_or_404(db, ontology_id)
    return await _ontology_shape(db, o, request, v2=True)
