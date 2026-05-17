from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import OntologyProfile, OntologyVersion
from ontoexplorer.modules.auth.dependencies import require_auth
from ontoexplorer.models.db import User

router = APIRouter(prefix="/api/v1/ontologies", tags=["profile"])


async def _get_version_or_404(version_id: str, db: AsyncSession) -> OntologyVersion:
    result = await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == version_id)
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


async def _get_profile_or_404(version_id: str, db: AsyncSession) -> OntologyProfile:
    result = await db.execute(
        select(OntologyProfile).where(OntologyProfile.version_id == version_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found — detection may still be running")
    return profile


def _profile_response(p: OntologyProfile) -> dict:
    return {
        "version_id": p.version_id,
        "label_props": p.label_props,
        "definition_props": p.definition_props,
        "synonym_props": p.synonym_props,
        "deprecated_props": p.deprecated_props,
        "example_props": p.example_props,
        "status": p.status,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/{ontology_id}/{version_id}/profile")
async def get_profile(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_profile_or_404(version_id, db)
    return _profile_response(profile)


class ProfilePatch(BaseModel):
    label_props: list[str] | None = None
    definition_props: list[str] | None = None
    synonym_props: list[str] | None = None
    deprecated_props: list[str] | None = None
    example_props: list[str] | None = None



@router.patch("/{ontology_id}/{version_id}/profile")
async def patch_profile(
    ontology_id: str,
    version_id: str,
    body: ProfilePatch,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_profile_or_404(version_id, db)
    if body.label_props is not None:
        profile.label_props = body.label_props
    if body.definition_props is not None:
        profile.definition_props = body.definition_props
    if body.synonym_props is not None:
        profile.synonym_props = body.synonym_props
    if body.deprecated_props is not None:
        profile.deprecated_props = body.deprecated_props
    if body.example_props is not None:
        profile.example_props = body.example_props
    profile.status = "user_confirmed"
    profile.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(profile)

    from ontoexplorer.modules.jobs.tasks import index_ontology
    index_ontology.delay(version_id, ontology_id=ontology_id)

    return _profile_response(profile)


@router.post("/{ontology_id}/{version_id}/profile/detect")
async def trigger_detect(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    await _get_version_or_404(version_id, db)

    from ontoexplorer.modules.profile.detector import run_detection
    await run_detection(db, version_id, ontology_id=ontology_id)
    profile = await _get_profile_or_404(version_id, db)
    return _profile_response(profile)


@router.get("/{ontology_id}/{version_id}/profile/candidates")
async def get_candidates(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_profile_or_404(version_id, db)
    return {"version_id": version_id, **profile.candidates_data}
