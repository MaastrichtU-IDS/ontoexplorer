"""Admin CRUD for reasoner profiles (named reasoner + params configurations).

Mounted under the admin router (/api/v1/admin). Deletion is soft (archive).
Params are validated against the selected reasoner's param_schema, which the
reasoner-service advertises via /reasoners.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.reasoning import list_reasoners
from ontoexplorer.database import get_db
from ontoexplorer.models.db import ReasonerProfile, User

from ._common import _require_admin

router = APIRouter()


class _ProfileCreate(BaseModel):
    name: str
    reasoner: str
    params: dict = {}
    dashboard_selectable: bool = False
    is_default: bool = False
    description: str | None = None


class _ProfileUpdate(BaseModel):
    name: str | None = None
    reasoner: str | None = None
    params: dict | None = None
    dashboard_selectable: bool | None = None
    is_default: bool | None = None
    description: str | None = None


def _serialize(p: ReasonerProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "reasoner": p.reasoner,
        "params": p.params or {},
        "dashboard_selectable": p.dashboard_selectable,
        "is_default": p.is_default,
        "archived": p.archived,
        "description": p.description,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


async def _validate_reasoner_and_params(reasoner: str, params: dict) -> None:
    """Reject an unknown reasoner or params that don't match its advertised
    param_schema. If the reasoner-service is unreachable we skip strict checks
    rather than block admin edits."""
    try:
        catalog = {r["name"]: r for r in await list_reasoners()}
    except Exception:
        catalog = {}
    if not catalog:
        return  # reasoner-service down — don't block
    if reasoner not in catalog:
        raise HTTPException(422, f"unknown reasoner '{reasoner}'; known: {sorted(catalog)}")
    schema = {p["key"]: p for p in (catalog[reasoner].get("param_schema") or [])}
    for key, val in (params or {}).items():
        spec = schema.get(key)
        if spec is None:
            raise HTTPException(422, f"reasoner '{reasoner}' has no parameter '{key}'")
        t = spec.get("type")
        if t == "bool" and not isinstance(val, bool):
            raise HTTPException(422, f"parameter '{key}' must be a boolean")
        if t == "int":
            if isinstance(val, bool) or not isinstance(val, int):
                raise HTTPException(422, f"parameter '{key}' must be an integer")
            if "min" in spec and val < spec["min"]:
                raise HTTPException(422, f"parameter '{key}' must be >= {spec['min']}")
            if "max" in spec and val > spec["max"]:
                raise HTTPException(422, f"parameter '{key}' must be <= {spec['max']}")
        if t == "enum" and val not in (spec.get("choices") or []):
            raise HTTPException(422, f"parameter '{key}' must be one of {spec.get('choices')}")


async def _assert_name_free(db: AsyncSession, name: str, exclude_id: str | None = None) -> None:
    q = select(ReasonerProfile).where(
        ReasonerProfile.name == name, ReasonerProfile.archived.is_(False)
    )
    existing = (await db.execute(q)).scalars().first()
    if existing is not None and existing.id != exclude_id:
        raise HTTPException(409, f"a reasoner profile named '{name}' already exists")


async def _clear_other_defaults(db: AsyncSession, keep_id: str | None) -> None:
    stmt = update(ReasonerProfile).where(ReasonerProfile.is_default.is_(True)).values(is_default=False)
    if keep_id is not None:
        stmt = stmt.where(ReasonerProfile.id != keep_id)
    await db.execute(stmt)


@router.get("/reasoner-profiles", summary="List all reasoner profiles (admin)")
async def admin_list_reasoner_profiles(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(ReasonerProfile).order_by(
            ReasonerProfile.archived, ReasonerProfile.is_default.desc(), ReasonerProfile.name
        )
    )).scalars().all()
    return {"profiles": [_serialize(p) for p in rows]}


@router.post("/reasoner-profiles", summary="Create a reasoner profile (admin)")
async def admin_create_reasoner_profile(
    body: _ProfileCreate,
    user: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _validate_reasoner_and_params(body.reasoner, body.params)
    await _assert_name_free(db, body.name)
    if body.is_default:
        await _clear_other_defaults(db, keep_id=None)
    p = ReasonerProfile(
        name=body.name, reasoner=body.reasoner, params=body.params,
        dashboard_selectable=body.dashboard_selectable, is_default=body.is_default,
        description=body.description, created_by=user.id,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _serialize(p)


async def _load_profile(db: AsyncSession, profile_id: str) -> ReasonerProfile:
    p = (await db.execute(
        select(ReasonerProfile).where(ReasonerProfile.id == profile_id)
    )).scalars().first()
    if p is None:
        raise HTTPException(404, "reasoner profile not found")
    return p


@router.patch("/reasoner-profiles/{profile_id}", summary="Update a reasoner profile (admin)")
async def admin_update_reasoner_profile(
    profile_id: str,
    body: _ProfileUpdate,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    p = await _load_profile(db, profile_id)
    new_reasoner = body.reasoner if body.reasoner is not None else p.reasoner
    new_params = body.params if body.params is not None else (p.params or {})
    if body.reasoner is not None or body.params is not None:
        await _validate_reasoner_and_params(new_reasoner, new_params)
    if body.name is not None and body.name != p.name:
        await _assert_name_free(db, body.name, exclude_id=p.id)

    if body.name is not None:
        p.name = body.name
    if body.reasoner is not None:
        p.reasoner = body.reasoner
    if body.params is not None:
        p.params = body.params
    if body.dashboard_selectable is not None:
        p.dashboard_selectable = body.dashboard_selectable
    if body.description is not None:
        p.description = body.description
    if body.is_default is not None:
        p.is_default = body.is_default
        if body.is_default:
            await _clear_other_defaults(db, keep_id=p.id)
    await db.commit()
    await db.refresh(p)
    return _serialize(p)


@router.delete("/reasoner-profiles/{profile_id}", summary="Archive a reasoner profile (admin, soft-delete)")
async def admin_archive_reasoner_profile(
    profile_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    p = await _load_profile(db, profile_id)
    p.archived = True
    p.is_default = False  # an archived profile must not remain the default
    await db.commit()
    return {"id": p.id, "archived": True}
