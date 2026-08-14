"""User-facing reasoner-profile listing.

Returns the non-archived, dashboard-selectable profiles for the add-ontology and
re-index selectors. Admins manage profiles via /api/v1/admin/reasoner-profiles.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import ReasonerProfile, User
from ontoexplorer.modules.auth.dependencies import require_auth

router = APIRouter(prefix="/api/v1", tags=["reasoner-profiles"])


@router.get("/reasoner-profiles", summary="Selectable reasoner profiles (dashboard)")
async def list_selectable_reasoner_profiles(
    _: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(ReasonerProfile)
        .where(
            ReasonerProfile.archived.is_(False),
            ReasonerProfile.dashboard_selectable.is_(True),
        )
        .order_by(ReasonerProfile.is_default.desc(), ReasonerProfile.name)
    )).scalars().all()
    return {
        "profiles": [
            {
                "id": p.id,
                "name": p.name,
                "reasoner": p.reasoner,
                "params": p.params or {},
                "is_default": p.is_default,
                "description": p.description,
            }
            for p in rows
        ]
    }
