"""API key management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import ApiKey, User
from ontoexplorer.modules.auth.api_keys import create_api_key, list_api_keys, revoke_api_key
from ontoexplorer.modules.auth.dependencies import require_auth

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])

VALID_SCOPES = {"read", "write", "admin"}


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str] = ["read"]


@router.post("", summary="Create API key")
async def create_key(
    body: ApiKeyCreate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    invalid = set(body.scopes) - VALID_SCOPES
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid scopes: {invalid}")

    api_key, raw_key = await create_api_key(db, user.id, body.name, body.scopes)
    return {
        **_key_dict(api_key),
        "key": raw_key,  # shown exactly once
    }


@router.get("", summary="List active API keys")
async def list_keys(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    keys = await list_api_keys(db, user.id)
    return {"api_keys": [_key_dict(k) for k in keys]}


@router.delete("/{key_id}", summary="Revoke API key")
async def revoke_key(key_id: str, user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    revoked = await revoke_api_key(db, key_id, user.id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"detail": "API key revoked"}


def _key_dict(k: ApiKey) -> dict:
    return {
        "id": k.id,
        "name": k.name,
        "scopes": k.scopes,
        "created_at": k.created_at.isoformat(),
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
    }
