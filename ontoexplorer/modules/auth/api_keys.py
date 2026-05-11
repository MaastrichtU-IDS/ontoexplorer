"""API key creation, verification, and revocation."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import ApiKey


def generate_api_key() -> tuple[str, str]:
    """
    Generate a new API key. Returns (raw_key, key_hash).
    raw_key is shown to the user exactly once; key_hash is stored.
    """
    raw = f"oe_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_hash


async def create_api_key(
    db: AsyncSession,
    user_id: str,
    name: str,
    scopes: list[str],
) -> tuple[ApiKey, str]:
    """Create and persist a new API key. Returns (ApiKey record, raw_key)."""
    raw_key, key_hash = generate_api_key()
    api_key = ApiKey(
        id=str(uuid.uuid4()),
        user_id=user_id,
        key_hash=key_hash,
        name=name,
        scopes=scopes,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key, raw_key


async def revoke_api_key(db: AsyncSession, key_id: str, user_id: str) -> bool:
    """Revoke an API key. Returns True if found and revoked, False if not found."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
    )
    key = result.scalar_one_or_none()
    if not key:
        return False
    key.revoked_at = datetime.now(UTC)
    await db.commit()
    return True


async def list_api_keys(db: AsyncSession, user_id: str) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())
