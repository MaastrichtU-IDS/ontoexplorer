"""Saved SPARQL queries endpoints."""

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import SavedQuery, User
from ontoexplorer.modules.auth.dependencies import get_current_user, require_auth

router = APIRouter(prefix="/api/v1/sparql/queries", tags=["sparql-queries"])


class SavedQueryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    query_text: str
    tags: list[str] = []
    is_public: bool = False


class SavedQueryPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    query_text: Optional[str] = None
    tags: Optional[list[str]] = None
    is_public: Optional[bool] = None


def _serialize(sq: SavedQuery, user_display_name: Optional[str] = None) -> dict:
    d = {
        "id": sq.id,
        "user_id": sq.user_id,
        "name": sq.name,
        "description": sq.description,
        "query_text": sq.query_text,
        "tags": sq.tags or [],
        "is_public": sq.is_public,
        "created_at": sq.created_at.isoformat() if sq.created_at else None,
        "updated_at": sq.updated_at.isoformat() if sq.updated_at else None,
    }
    if user_display_name is not None:
        d["user_display_name"] = user_display_name
    return d


@router.post("", status_code=201)
async def create_saved_query(
    body: SavedQueryCreate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    sq = SavedQuery(
        user_id=user.id,
        name=body.name.strip(),
        description=body.description,
        query_text=body.query_text,
        tags=body.tags,
        is_public=body.is_public,
    )
    db.add(sq)
    await db.commit()
    await db.refresh(sq)
    return _serialize(sq)


@router.get("")
async def list_saved_queries(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SavedQuery)
        .where(SavedQuery.user_id == user.id)
        .order_by(SavedQuery.updated_at.desc())
    )
    return {"queries": [_serialize(q) for q in result.scalars().all()]}


@router.get("/public")
async def list_public_queries(
    q: Optional[str] = Query(None),
    ontology: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(SavedQuery, User.display_name)
        .join(User, SavedQuery.user_id == User.id)
        .where(SavedQuery.is_public == True)  # noqa: E712
    )
    if user_id:
        stmt = stmt.where(SavedQuery.user_id == user_id)

    rows = (await db.execute(stmt)).all()

    out = []
    for sq, display_name in rows:
        if q:
            haystack = f"{sq.name} {sq.description or ''} {' '.join(sq.tags or [])}"
            if q.lower() not in haystack.lower():
                continue
        if ontology and ontology not in (sq.tags or []):
            continue
        out.append(_serialize(sq, display_name))

    out.sort(key=lambda x: x["updated_at"] or "", reverse=True)
    return {"queries": out[offset: offset + limit], "total": len(out)}


@router.get("/{query_id}")
async def get_saved_query(
    query_id: str,
    user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SavedQuery).where(SavedQuery.id == query_id))
    sq = result.scalar_one_or_none()
    if sq is None or (not sq.is_public and (user is None or user.id != sq.user_id)):
        raise HTTPException(status_code=404, detail="Query not found or not accessible")
    return _serialize(sq)


@router.patch("/{query_id}")
async def update_saved_query(
    query_id: str,
    body: SavedQueryPatch,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SavedQuery).where(SavedQuery.id == query_id))
    sq = result.scalar_one_or_none()
    if sq is None or sq.user_id != user.id:
        raise HTTPException(status_code=404, detail="Query not found or not accessible")

    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="name cannot be empty")
        sq.name = body.name.strip()
    if body.description is not None:
        sq.description = body.description
    if body.query_text is not None:
        sq.query_text = body.query_text
    if body.tags is not None:
        sq.tags = body.tags
    if body.is_public is not None:
        sq.is_public = body.is_public

    sq.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(sq)
    return _serialize(sq)


@router.delete("/{query_id}", status_code=204)
async def delete_saved_query(
    query_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SavedQuery).where(SavedQuery.id == query_id))
    sq = result.scalar_one_or_none()
    if sq is None or sq.user_id != user.id:
        raise HTTPException(status_code=404, detail="Query not found or not accessible")
    await db.delete(sq)
    await db.commit()
