"""FastAPI dependency injection for authentication."""

import hashlib
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
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


# Methods that only read. Anything else needs a key carrying write or admin.
_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _enforce_key_scopes(api_key: ApiKey, method: str) -> None:
    """Refuse a mutating request made with a read-only API key.

    Scopes were stored at creation and never read anywhere, so a key created
    with ["read"] — which is what the UI issues — carried its owner's full
    authority, including deleting ontologies. The field promised least privilege
    the system did not provide.

    Enforced here, in the one place every authenticated request passes through,
    rather than as a dependency on each mutating route. Authorization in this
    codebase has been opt-in per route, and every gap found so far came from a
    route that simply never opted in.

    A key with no scopes recorded is treated as read-only: failing closed is the
    only safe reading of an absent grant.
    """
    if method in _READ_ONLY_METHODS:
        return
    if {"write", "admin"} & set(api_key.scopes or []):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This API key is read-only. Create a key with the 'write' scope to modify data.",
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    Extract the authenticated user from a Bearer token (JWT or API key).
    Returns None if no valid credentials are present.

    A browser session (JWT) is the user acting directly and carries no scopes.
    An API key is a delegated, narrower credential, so its scopes are enforced.
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
        request.state.auth_method = "session"
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
        request.state.auth_method = "api_key"
        _enforce_key_scopes(api_key, request.method)
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


async def reject_api_key_auth(
    request: Request,
    _user: User | None = Depends(get_current_user),
) -> None:
    """Allow browser traffic; refuse API keys.

    For endpoints that exist to serve the UI and commit real compute per call —
    justification queues work on a single-concurrency worker. Live testing showed
    any account could aim those at any ontology, and registration is open, so a
    key was a standing licence to spend someone else's capacity.

    The line is the credential type, not authentication: the SPA serves anonymous
    visitors, so requiring a login would break ordinary browsing. A browser
    session (or no credential at all) passes; a programmatic key does not.

    This bounds who can call, not how often. Anonymous volume is a rate-limit
    problem and is not addressed here.
    """
    if getattr(request.state, "auth_method", None) == "api_key":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint backs the web interface and is not available to API keys.",
        )
