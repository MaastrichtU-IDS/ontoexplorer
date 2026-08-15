"""App-facing incremental EL++ reasoning (km) — a thin authenticated proxy over
the reasoner-service /incremental endpoints.

A session is a live km reasoner over one ontology version: ask arbitrary
subsumption questions on demand, and assert hypothetical axioms to watch the
entailments change — without re-classifying. EL++ only (non-EL versions get 422).
Sessions are transient (reasoner-service memory).
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients import reasoning as _reasoning
from ontoexplorer.database import get_db
from ontoexplorer.models.db import OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import require_auth

router = APIRouter(prefix="/api/v1", tags=["incremental-reasoning"])


class _Pair(BaseModel):
    sub: str
    sup: str


class _ClauseIds(BaseModel):
    clause_ids: list[int]


async def _version_reasoner(db: AsyncSession, ontology_id: str, version_id: str) -> str:
    v = (await db.execute(
        select(OntologyVersion).where(
            OntologyVersion.id == version_id, OntologyVersion.ontology_id == ontology_id
        )
    )).scalar_one_or_none()
    if v is None:
        raise HTTPException(404, "version not found")
    return v.reasoner


def _proxy_error(exc: httpx.HTTPStatusError) -> HTTPException:
    detail = "reasoner-service error"
    try:
        detail = exc.response.json().get("detail", detail)
    except Exception:
        detail = (exc.response.text or detail)[:300]
    return HTTPException(exc.response.status_code, detail)


@router.post("/ontologies/{ontology_id}/{version_id}/incremental",
             summary="Start an incremental EL++ reasoning session for a version")
async def start_session(
    ontology_id: str, version_id: str,
    _: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    reasoner = await _version_reasoner(db, ontology_id, version_id)
    try:
        return await _reasoning.incremental_create(version_id, reasoner)
    except httpx.HTTPStatusError as exc:
        raise _proxy_error(exc)


@router.post("/ontologies/{ontology_id}/{version_id}/incremental/{session_id}/subsumed",
             summary="Query whether sub ⊑ sup in the session")
async def query_subsumed(
    ontology_id: str, version_id: str, session_id: str, body: _Pair,
    _: User = Depends(require_auth),
):
    try:
        return await _reasoning.incremental_subsumed(session_id, body.sub, body.sup)
    except httpx.HTTPStatusError as exc:
        raise _proxy_error(exc)


@router.post("/ontologies/{ontology_id}/{version_id}/incremental/{session_id}/assert",
             summary="Assert a hypothetical sub ⊑ sup axiom into the session")
async def assert_axiom(
    ontology_id: str, version_id: str, session_id: str, body: _Pair,
    _: User = Depends(require_auth),
):
    try:
        return await _reasoning.incremental_assert(session_id, body.sub, body.sup)
    except httpx.HTTPStatusError as exc:
        raise _proxy_error(exc)


@router.post("/ontologies/{ontology_id}/{version_id}/incremental/{session_id}/retract",
             summary="Retract previously-asserted axioms by their clause ids")
async def retract_axioms(
    ontology_id: str, version_id: str, session_id: str, body: _ClauseIds,
    _: User = Depends(require_auth),
):
    try:
        return await _reasoning.incremental_retract(session_id, body.clause_ids)
    except httpx.HTTPStatusError as exc:
        raise _proxy_error(exc)


@router.delete("/ontologies/{ontology_id}/{version_id}/incremental/{session_id}",
               summary="Close an incremental reasoning session")
async def close_session(
    ontology_id: str, version_id: str, session_id: str,
    _: User = Depends(require_auth),
):
    try:
        return await _reasoning.incremental_close(session_id)
    except httpx.HTTPStatusError as exc:
        raise _proxy_error(exc)
