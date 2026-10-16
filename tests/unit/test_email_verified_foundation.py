"""Keycloak-auth groundwork (#368): claim extraction + email_verified plumbing.
No account-linking or gating here — just that the provider's verified-email claim
maps through to the User, upgrade-only."""
import pytest
from sqlalchemy import select

from ontoexplorer.models.db import User
from ontoexplorer.modules.auth.oauth import (
    claim_email_verified,
    claim_orcid,
    extract_user_info,
)
from ontoexplorer.modules.auth.session import get_or_create_user


def test_extract_keycloak_claims():
    sub, email, name = extract_user_info("keycloak", {
        "sub": "kc-123", "email": "a@b.org", "name": "Ada L.",
    })
    assert sub == "kc-123"
    assert email == "a@b.org"
    assert name == "Ada L."
    # preferred_username fallback for name
    _, _, name2 = extract_user_info("keycloak", {"sub": "x", "preferred_username": "ada"})
    assert name2 == "ada"


def test_claim_email_verified():
    assert claim_email_verified("keycloak", {"email_verified": True}) is True
    assert claim_email_verified("keycloak", {"email_verified": False}) is False
    assert claim_email_verified("google", {"email_verified": True}) is True
    # Providers that don't assert it here never report verified.
    assert claim_email_verified("github", {"email_verified": True}) is False
    assert claim_email_verified("orcid", {}) is False


def test_claim_orcid():
    assert claim_orcid({"orcid": "0000-0001-0002-0003"}) == "0000-0001-0002-0003"
    assert claim_orcid({"orcid_id": "x"}) == "x"
    assert claim_orcid({}) is None


@pytest.mark.anyio
async def test_get_or_create_user_sets_email_verified(db_session):
    u = await get_or_create_user(
        db_session, provider="keycloak", provider_user_id="kc-new",
        email="new@x.org", display_name="New", access_token=None,
        refresh_token=None, expires_at=None, email_verified=True,
    )
    assert u.email_verified is True
    row = (await db_session.execute(select(User).where(User.id == u.id))).scalar_one()
    assert row.email_verified is True


@pytest.mark.anyio
async def test_email_verified_is_upgrade_only(db_session):
    # First login unverified → False.
    u = await get_or_create_user(
        db_session, provider="keycloak", provider_user_id="kc-up",
        email="up@x.org", display_name="Up", access_token=None,
        refresh_token=None, expires_at=None, email_verified=False,
    )
    assert u.email_verified is False
    # Re-login now verified → upgraded to True (same account).
    u2 = await get_or_create_user(
        db_session, provider="keycloak", provider_user_id="kc-up",
        email="up@x.org", display_name="Up", access_token=None,
        refresh_token=None, expires_at=None, email_verified=True,
    )
    assert u2.id == u.id
    assert u2.email_verified is True
