"""JWT session management: issue, verify, refresh, revoke."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.models.db import OAuthAccount, Session, User


def _settings():
    return get_settings()


# ── Token creation ─────────────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    s = _settings()
    expire = datetime.now(UTC) + timedelta(minutes=s.jwt_access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire, "type": "access"}
    return jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def create_refresh_token() -> str:
    """Generate a cryptographically random refresh token (opaque, stored hashed)."""
    return secrets.token_urlsafe(48)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── Token verification ─────────────────────────────────────────────────────────

def decode_access_token(token: str) -> str:
    """Decode and verify a JWT access token. Returns user_id or raises JWTError."""
    s = _settings()
    payload = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    if payload.get("type") != "access":
        raise JWTError("Not an access token")
    user_id: str = payload["sub"]
    return user_id


# ── Session CRUD ───────────────────────────────────────────────────────────────

async def create_session(db: AsyncSession, user_id: str) -> tuple[str, str]:
    """
    Create a new session. Returns (access_token, refresh_token).
    The refresh token is stored hashed in Postgres.
    """
    s = _settings()
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token()
    token_hash = _hash_token(refresh_token)
    expires_at = datetime.now(UTC) + timedelta(days=s.jwt_refresh_token_expire_days)

    session = Session(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()
    return access_token, refresh_token


async def refresh_session(db: AsyncSession, refresh_token: str) -> tuple[str, str]:
    """
    Validate refresh token, issue new access + refresh token pair (rotation).
    Raises ValueError if token is invalid or expired.
    """
    token_hash = _hash_token(refresh_token)
    result = await db.execute(select(Session).where(Session.token_hash == token_hash))
    session = result.scalar_one_or_none()

    if not session:
        raise ValueError("Invalid refresh token")
    if session.expires_at < datetime.now(UTC):
        raise ValueError("Refresh token expired")

    # Rotate: delete old session, create new one
    await db.delete(session)
    await db.flush()
    return await create_session(db, session.user_id)


async def revoke_session(db: AsyncSession, refresh_token: str) -> None:
    token_hash = _hash_token(refresh_token)
    result = await db.execute(select(Session).where(Session.token_hash == token_hash))
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        await db.commit()


# ── User management ────────────────────────────────────────────────────────────

async def get_or_create_user(
    db: AsyncSession,
    provider: str,
    provider_user_id: str,
    email: str | None,
    display_name: str | None,
    access_token: str | None,
    refresh_token: str | None,
    expires_at: datetime | None,
) -> User:
    """Find existing user by OAuth account, or create a new one."""
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    oauth_account = result.scalar_one_or_none()

    if oauth_account:
        # Update tokens
        oauth_account.access_token = access_token
        oauth_account.refresh_token = refresh_token
        oauth_account.expires_at = expires_at
        await db.commit()
        result2 = await db.execute(select(User).where(User.id == oauth_account.user_id))
        return result2.scalar_one()

    # New user
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        display_name=display_name,
    )
    db.add(user)
    await db.flush()

    db.add(OAuthAccount(
        id=str(uuid.uuid4()),
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    ))
    await db.commit()
    return user
