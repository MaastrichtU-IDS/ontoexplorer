"""Signing in with an unlinked provider must not 500.

users.email is unique. Unlink a provider, sign in with it again, and the
(provider, provider_user_id) lookup misses while the User still holds the
address — so the insert violated the constraint and the login page said
"Internal Server Error" to someone whose account was intact the whole time.
"""

import uuid

import pytest

from ontoexplorer.models.db import OAuthAccount, User
from ontoexplorer.modules.auth.session import EmailAlreadyRegistered, get_or_create_user


async def _existing_user(db, email: str, *, provider: str | None = None,
                         provider_user_id: str | None = None) -> User:
    u = User(id=str(uuid.uuid4()), email=email, display_name="Existing")
    db.add(u)
    await db.commit()
    if provider:
        # Unique per call: rows persist across tests in this session, and a
        # fixed id collides on OAuthAccount's (provider, provider_user_id).
        db.add(OAuthAccount(id=str(uuid.uuid4()), user_id=u.id,
                            provider=provider,
                            provider_user_id=provider_user_id or f"{provider}-{uuid.uuid4()}"))
        await db.commit()
    return u


@pytest.mark.anyio
async def test_unlinked_provider_relogin_raises_a_typed_error_not_an_integrity_error(db_session):
    email = f"clash-{uuid.uuid4()}@example.com"
    await _existing_user(db_session, email, provider="orcid")

    with pytest.raises(EmailAlreadyRegistered) as e:
        await get_or_create_user(
            db_session, provider="github", provider_user_id="gh-999",
            email=email, display_name="Same Person",
            access_token="t", refresh_token=None, expires_at=None,
        )
    assert "re-link" in str(e.value)
    assert email in str(e.value)


@pytest.mark.anyio
async def test_the_identity_is_not_silently_attached_to_the_existing_account(db_session):
    """Resolving this by linking on email would be an account-takeover vector:
    anyone who can register the address at another provider walks in."""
    email = f"takeover-{uuid.uuid4()}@example.com"
    victim = await _existing_user(db_session, email, provider="orcid")

    with pytest.raises(EmailAlreadyRegistered):
        await get_or_create_user(
            db_session, provider="github", provider_user_id="attacker-1",
            email=email, display_name="Attacker",
            access_token="t", refresh_token=None, expires_at=None,
        )

    from sqlalchemy import select
    linked = (await db_session.execute(
        select(OAuthAccount).where(OAuthAccount.user_id == victim.id)
    )).scalars().all()
    assert [a.provider for a in linked] == ["orcid"], "the attacker's identity was attached"


@pytest.mark.anyio
async def test_a_genuinely_new_email_still_creates_an_account(db_session):
    email = f"new-{uuid.uuid4()}@example.com"
    user = await get_or_create_user(
        db_session, provider="github", provider_user_id=f"gh-{uuid.uuid4()}",
        email=email, display_name="Newcomer",
        access_token="t", refresh_token=None, expires_at=None,
    )
    assert user.email == email


@pytest.mark.anyio
async def test_an_already_linked_identity_returns_its_own_user(db_session):
    """The normal path: same provider account signing in again."""
    email = f"repeat-{uuid.uuid4()}@example.com"
    pid = f"github-{uuid.uuid4()}"
    existing = await _existing_user(db_session, email, provider="github", provider_user_id=pid)

    same = await get_or_create_user(
        db_session, provider="github", provider_user_id=pid,
        email=email, display_name="Existing",
        access_token="t2", refresh_token=None, expires_at=None,
    )
    assert same.id == existing.id
