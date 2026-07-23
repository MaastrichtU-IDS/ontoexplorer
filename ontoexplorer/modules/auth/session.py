"""JWT session management: issue, verify, refresh, revoke."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.models.db import (
    ApiKey,
    OAuthAccount,
    Ontology,
    SavedQuery,
    Session,
    User,
    Webhook,
)


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


# ── Account-link tokens ────────────────────────────────────────────────────────
# A short-lived signed token that carries "the currently-logged-in user wants to
# link a provider" through the OAuth redirect. It rides in an httpOnly cookie set
# by /auth/{provider}/link and is verified in /auth/{provider}/callback. Signing
# it (rather than putting a raw user_id in a cookie) prevents forging a link to an
# arbitrary account.

_LINK_TOKEN_TTL_MINUTES = 10


def create_link_token(user_id: str) -> str:
    s = _settings()
    expire = datetime.now(UTC) + timedelta(minutes=_LINK_TOKEN_TTL_MINUTES)
    payload = {"sub": user_id, "exp": expire, "type": "link"}
    return jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def decode_link_token(token: str) -> str:
    """Decode a link token. Returns user_id or raises JWTError."""
    s = _settings()
    payload = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    if payload.get("type") != "link":
        raise JWTError("Not a link token")
    user_id: str = payload["sub"]
    return user_id


# ── Account-merge tokens ───────────────────────────────────────────────────────
# Minted by /callback ONLY after the caller has proven control of BOTH accounts:
# the signed oauth_link cookie (target) + a fresh OAuth with the other provider
# (source). Carries {target, source} to the confirm step, which re-checks the
# caller is authenticated as `target`. Short-lived to limit replay.

_MERGE_TOKEN_TTL_MINUTES = 10


def create_merge_token(target_user_id: str, source_user_id: str) -> str:
    s = _settings()
    expire = datetime.now(UTC) + timedelta(minutes=_MERGE_TOKEN_TTL_MINUTES)
    payload = {"target": target_user_id, "source": source_user_id, "exp": expire, "type": "merge"}
    return jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def decode_merge_token(token: str) -> tuple[str, str]:
    """Decode a merge token → (target_user_id, source_user_id) or raise JWTError."""
    s = _settings()
    payload = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    if payload.get("type") != "merge":
        raise JWTError("Not a merge token")
    return payload["target"], payload["source"]


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


async def link_oauth_account(
    db: AsyncSession,
    user_id: str,
    provider: str,
    provider_user_id: str,
    email: str | None,
    display_name: str | None,
    access_token: str | None,
    refresh_token: str | None,
    expires_at: datetime | None,
) -> User:
    """
    Attach an OAuth identity to an EXISTING user (the one who initiated the link).

    - If the identity is already linked to this same user → refresh tokens (no-op).
    - If it belongs to a DIFFERENT user → raise ValueError (no silent takeover /
      cross-account merge; that would require reassigning owned resources).
    - Otherwise → create the OAuthAccount and, opportunistically, backfill the
      user's email/display_name if they're empty (helps e.g. admin-by-email).
    """
    existing = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_user_id == provider_user_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.user_id == user_id:
            existing.access_token = access_token
            existing.refresh_token = refresh_token
            existing.expires_at = expires_at
            await db.commit()
        else:
            raise ValueError(
                f"This {provider} identity is already linked to a different "
                f"OntoExplorer account."
            )
    else:
        db.add(OAuthAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        ))
        # Backfill empty profile fields from the newly linked provider, guarding
        # the unique email constraint.
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        if email and not user.email:
            taken = (
                await db.execute(
                    select(User).where(User.email == email, User.id != user_id)
                )
            ).scalar_one_or_none()
            if taken is None:
                user.email = email
        if display_name and not user.display_name:
            user.display_name = display_name
        await db.commit()

    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


async def unlink_oauth_account(db: AsyncSession, user_id: str, provider: str) -> list[str]:
    """
    Remove a provider from a user. Refuses to remove the user's ONLY sign-in
    method (that would lock them out). Returns the remaining provider names.
    Raises ValueError if the provider isn't linked or it's the last one.
    """
    accounts = (
        await db.execute(select(OAuthAccount).where(OAuthAccount.user_id == user_id))
    ).scalars().all()

    targets = [a for a in accounts if a.provider == provider]
    if not targets:
        raise ValueError(f"No {provider} account is linked.")
    if len(accounts) - len(targets) < 1:
        raise ValueError("Cannot unlink your only sign-in method.")

    for a in targets:
        await db.delete(a)
    await db.commit()

    return [a.provider for a in accounts if a.provider != provider]


async def find_oauth_owner(db: AsyncSession, provider: str, provider_user_id: str) -> str | None:
    """Return the user_id that owns this provider identity, or None if unlinked."""
    row = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_user_id == provider_user_id,
            )
        )
    ).scalar_one_or_none()
    return row.user_id if row else None


# All tables that reference users.id (see models/db.py). Merge reassigns each from
# the source user to the target BEFORE the source is deleted. None carry a
# per-user unique constraint, so reassignment can't collide. Sessions are dropped
# rather than reassigned (the old identity simply re-logs in).
_MERGE_REASSIGN = [
    (OAuthAccount, "user_id"),
    (Ontology, "owner_id"),
    (Webhook, "user_id"),
    (ApiKey, "user_id"),
    (SavedQuery, "user_id"),
]


async def merge_users(db: AsyncSession, target_id: str, source_id: str) -> dict:
    """
    Merge `source` into `target`: move everything source owns to target, then
    delete source. Returns a per-table count of moved rows plus the target's
    resulting providers. Idempotent-ish: safe to call once; source ceases to exist.

    Authorization is the caller's responsibility — this must only run once the
    caller has proven control of both accounts (see the /callback + /auth/merge
    flow and the signed merge token).
    """
    if target_id == source_id:
        raise ValueError("Cannot merge an account into itself.")

    target = (await db.execute(select(User).where(User.id == target_id))).scalar_one_or_none()
    source = (await db.execute(select(User).where(User.id == source_id))).scalar_one_or_none()
    if target is None or source is None:
        raise ValueError("Account not found.")

    moved: dict[str, int] = {}
    for model, col in _MERGE_REASSIGN:
        res = await db.execute(
            update(model).where(getattr(model, col) == source_id).values(**{col: target_id})
        )
        moved[model.__tablename__] = res.rowcount or 0

    # Drop the source's sessions (can't reassign a hashed token meaningfully).
    await db.execute(delete(Session).where(Session.user_id == source_id))

    # Backfill target profile from source where empty. Email is UNIQUE, and the
    # source still holds it until deleted, so free it first to avoid a collision.
    src_email = source.email
    src_name = source.display_name
    if src_email and not target.email:
        await db.execute(update(User).where(User.id == source_id).values(email=None))
        await db.execute(update(User).where(User.id == target_id).values(email=src_email))
    if src_name and not target.display_name:
        await db.execute(update(User).where(User.id == target_id).values(display_name=src_name))

    # Source now owns nothing — safe to delete.
    await db.execute(delete(User).where(User.id == source_id))
    await db.commit()

    providers = [
        a.provider
        for a in (
            await db.execute(select(OAuthAccount).where(OAuthAccount.user_id == target_id))
        ).scalars().all()
    ]
    return {"moved": moved, "connected_providers": providers}
