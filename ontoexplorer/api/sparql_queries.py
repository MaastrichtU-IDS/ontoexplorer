"""Saved SPARQL queries endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.admin._common import _require_admin
from ontoexplorer.database import get_db
from ontoexplorer.models.db import SavedQuery, User
from ontoexplorer.modules.auth.dependencies import get_current_user, require_auth
from ontoexplorer.modules.sparql_starters.parser import (
    StarterDraft,
    detect_format,
    parse_json_library,
    parse_rq_with_metadata,
)

router = APIRouter(prefix="/api/v1/sparql/queries", tags=["sparql-queries"])
starters_router = APIRouter(prefix="/api/v1/sparql", tags=["sparql-starters"])

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"
_MAX_URL_BYTES = 1_048_576  # 1 MB
_URL_TIMEOUT_SECONDS = 5.0


async def _fetch_starter_url(url: str) -> str:
    """Fetch the body of `url` with a size cap, timeout, and SSRF guard.

    The guard is the shared async_guarded_transport(): it refuses any target
    resolving to a non-public address — on the initial request and every
    redirect hop — and pins the connection to the validated IP against DNS
    rebinding. This replaced a scheme-only guard that allowed https:// to *any*
    host (internal endpoints included) and http:// to localhost, i.e. the api
    pod's own loopback. Body is streamed under a hard byte cap.
    """
    from ontoexplorer.clients.fetch_guard import async_guarded_transport

    async with httpx.AsyncClient(
        timeout=_URL_TIMEOUT_SECONDS,
        follow_redirects=True,
        transport=async_guarded_transport(),
    ) as http:
        async with http.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise ValueError(f"Upstream returned HTTP {resp.status_code}")
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > _MAX_URL_BYTES:
                    raise ValueError(f"Response exceeded {_MAX_URL_BYTES} byte cap")
            return bytes(buf).decode("utf-8", errors="replace")


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
        "is_starter": sq.is_starter,
        "category": sq.category,
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
        .where(SavedQuery.is_starter == False)  # noqa: E712
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
        .where(SavedQuery.is_starter == False)  # noqa: E712
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


@starters_router.get("/starters")
async def list_starters(db: AsyncSession = Depends(get_db)):
    """Return the curated starter-query library. No authentication required."""
    result = await db.execute(
        select(SavedQuery)
        .where(SavedQuery.is_starter == True)  # noqa: E712
        .order_by(SavedQuery.category, SavedQuery.name)
    )
    return {"starters": [_serialize(q) for q in result.scalars().all()]}


@starters_router.post("/starters/import")
async def import_starters(
    text: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only import. Accepts one of: text body field, source_url field,
    or file upload. Auto-detects JSON-library vs .rq-with-metadata format.
    """
    # Resolve the source text
    if file is not None:
        text_content = (await file.read()).decode("utf-8", errors="replace")
    elif source_url:
        try:
            text_content = await _fetch_starter_url(source_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    elif text:
        text_content = text
    else:
        raise HTTPException(status_code=400, detail="No text, source_url, or file provided")

    fmt = detect_format(text_content)
    drafts: list[StarterDraft]
    errors: list[dict] = []
    if fmt == "json":
        try:
            drafts = parse_json_library(text_content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"JSON parse error: {exc}")
    else:
        try:
            drafts = [parse_rq_with_metadata(text_content)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"rq parse error: {exc}")

    # Look up which names already exist among starters
    existing_names_q = await db.execute(
        select(SavedQuery.name).where(SavedQuery.is_starter == True)  # noqa: E712
    )
    existing_names = {row for (row,) in existing_names_q.all()}

    created = 0
    skipped = 0
    for i, draft in enumerate(drafts):
        if draft.name in existing_names:
            skipped += 1
            errors.append({"index": i, "name": draft.name, "reason": "duplicate name"})
            continue
        sq = SavedQuery(
            id=str(uuid.uuid4()),
            user_id=SYSTEM_USER_ID,
            name=draft.name,
            description=draft.description,
            query_text=draft.query_text,
            tags=draft.tags,
            is_public=True,
            is_starter=True,
            category=draft.category,
        )
        db.add(sq)
        existing_names.add(draft.name)  # dedup within this batch too
        created += 1
    await db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}
