"""FastAPI dependency injection for authentication."""

import hashlib
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import can_upload, get_settings, is_admin
from ontoexplorer.database import get_db
from ontoexplorer.models.db import ApiKey, User
from ontoexplorer.modules.auth.session import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def _get_or_create_dev_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.email == "dev@localhost"))
    dev_user = result.scalar_one_or_none()
    if not dev_user:
        dev_user = User(email="dev@localhost", display_name="Dev User")
        db.add(dev_user)
        await db.commit()
        await db.refresh(dev_user)
    return dev_user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    Extract the authenticated user from a Bearer token (JWT or API key).
    Returns None if no valid credentials are present.
    """
    if get_settings().auth_bypass:
        return await _get_or_create_dev_user(db)

    if not credentials:
        return None

    token = credentials.credentials

    # Try JWT first
    try:
        user_id = decode_access_token(token)
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    except JWTError:
        pass

    # Try API key
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key:
        # Update last_used_at
        await db.execute(
            update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=datetime.now(UTC))
        )
        await db.commit()
        result2 = await db.execute(select(User).where(User.id == api_key.user_id))
        return result2.scalar_one_or_none()

    return None


async def require_auth(user: User | None = Depends(get_current_user)) -> User:
    """Dependency that raises 401 if the user is not authenticated."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_uploader(user: User = Depends(require_auth)) -> User:
    """Dependency for ontology uploads: 401 if anonymous, 403 if the (authenticated)
    user isn't an admin or on the UPLOAD_ALLOWED_EMAILS allowlist."""
    if not can_upload(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not allowed to add ontologies. Contact an admin to be added to the uploader allowlist.",
        )
    return user


async def require_admin(user: User = Depends(require_auth)) -> User:
    """Dependency that raises 403 if the authenticated user is not an admin."""
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
