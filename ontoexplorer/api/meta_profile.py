from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import require_auth
from ontoexplorer.modules.meta_profile.registry import ALL_META_ROLES

router = APIRouter(prefix="/api/v1", tags=["meta-profile"])


async def _get_meta_profile_or_404(version_id: str, db: AsyncSession) -> OntologyMetaProfile:
    result = await db.execute(
        select(OntologyMetaProfile).where(OntologyMetaProfile.version_id == version_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Metadata profile not found — detection may still be running")
    return row


async def _get_version_or_404(version_id: str, db: AsyncSession) -> OntologyVersion:
    result = await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == version_id)
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return v


def _meta_profile_response(p: OntologyMetaProfile) -> dict:
    d: dict = {"version_id": p.version_id}
    for role in ALL_META_ROLES:
        col = f"{role}_props"
        d[col] = getattr(p, col)
    d["resolved"] = p.resolved
    d["status"] = p.status
    d["updated_at"] = p.updated_at.isoformat() if p.updated_at else None
    return d


@router.get("/ontologies/{ontology_id}/{version_id}/meta")
async def get_meta_profile(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    return _meta_profile_response(await _get_meta_profile_or_404(version_id, db))


class MetaProfilePatch(BaseModel):
    title_props: list[str] | None = None
    shortname_props: list[str] | None = None
    description_props: list[str] | None = None
    creator_props: list[str] | None = None
    contributor_props: list[str] | None = None
    publisher_props: list[str] | None = None
    license_props: list[str] | None = None
    homepage_props: list[str] | None = None
    version_info_props: list[str] | None = None
    prefix_props: list[str] | None = None
    namespace_uri_props: list[str] | None = None
    created_props: list[str] | None = None
    modified_props: list[str] | None = None
    language_props: list[str] | None = None
    citation_props: list[str] | None = None
    funding_props: list[str] | None = None
    status_props: list[str] | None = None
    syntax_props: list[str] | None = None

    @field_validator("title_props")
    @classmethod
    def title_props_not_empty(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError("At least one title property is required")
        return v


@router.patch("/ontologies/{ontology_id}/{version_id}/meta")
async def patch_meta_profile(
    ontology_id: str,
    version_id: str,
    body: MetaProfilePatch,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_meta_profile_or_404(version_id, db)

    updated_any = False
    for role in ALL_META_ROLES:
        col = f"{role}_props"
        val = getattr(body, col, None)
        if val is not None:
            setattr(profile, col, val)
            updated_any = True

    if not updated_any:
        return _meta_profile_response(profile)

    r = await db.execute(
        select(Ontology.iri).join(
            OntologyVersion, OntologyVersion.ontology_id == Ontology.id
        ).where(OntologyVersion.id == version_id)
    )
    onto_iri = r.scalar_one()

    from ontoexplorer.clients.oxigraph import graph_iri
    from ontoexplorer.modules.meta_profile.detector import _fetch_onto_triples, _resolve_values

    named_graph = graph_iri(ontology_id, version_id)
    triples = await asyncio.to_thread(_fetch_onto_triples, named_graph, onto_iri)
    new_role_props = {role: getattr(profile, f"{role}_props") for role in ALL_META_ROLES}
    profile.resolved = _resolve_values(triples, new_role_props)
    profile.status = "user_confirmed"

    await db.commit()
    await db.refresh(profile)
    return _meta_profile_response(profile)


@router.post("/ontologies/{ontology_id}/{version_id}/meta/detect")
async def trigger_meta_detect(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    await _get_version_or_404(version_id, db)
    from ontoexplorer.modules.jobs.tasks import detect_meta_profile
    task = detect_meta_profile.delay(version_id, ontology_id=ontology_id)
    return {"task_id": task.id, "status": "queued"}


@router.get("/ontologies/{ontology_id}/{version_id}/meta/candidates")
async def get_meta_candidates(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_meta_profile_or_404(version_id, db)
    return {"version_id": version_id, **profile.candidates_data}


@router.get("/meta")
async def get_bulk_meta(
    ids: str = Query(..., description="Comma-separated ontology IDs"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    """Return harmonized resolved metadata for multiple ontologies (latest ready version each)."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        return []

    result = await db.execute(
        select(
            OntologyVersion.ontology_id,
            OntologyVersion.id.label("version_id"),
            OntologyMetaProfile.resolved,
            OntologyMetaProfile.status.label("profile_status"),
        )
        .join(OntologyMetaProfile, OntologyMetaProfile.version_id == OntologyVersion.id)
        .where(
            OntologyVersion.ontology_id.in_(id_list),
            OntologyVersion.status == "ready",
        )
        .order_by(OntologyVersion.ontology_id, OntologyVersion.created_at.desc())
    )
    rows = result.all()

    seen: set[str] = set()
    items = []
    for row in rows:
        if row.ontology_id not in seen:
            seen.add(row.ontology_id)
            items.append({
                "ontology_id": row.ontology_id,
                "version_id": row.version_id,
                "profile_status": row.profile_status,
                **(row.resolved or {}),
            })
    return items
