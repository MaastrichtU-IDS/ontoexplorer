"""Capturing a user's email so notifications can reach them.

Two gaps left users with no address on file — and every notification (held-version,
nudge, maintainer-request) silently no-ops without one:
  1. GitHub's /user endpoint returns email=null when the primary email is private
     (the default). We hold the `user:email` scope, so /user/emails has it.
  2. A user who first signed in before we captured an address kept a null email
     forever; a returning login that now carries one must fill the absence.

Email is only ever FILLED when absent, never overwritten, and the unique-email
constraint is still guarded — backfill must not become an account-takeover path.
"""

import uuid

import httpx
import pytest

from ontoexplorer.models.db import OAuthAccount, User
from ontoexplorer.modules.auth.oauth import extract_user_info, fetch_userinfo
from ontoexplorer.modules.auth.session import get_or_create_user


# ── the GitHub /user/emails fallback ──────────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, routes):
        self._routes = routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        return _Resp(self._routes[url])


@pytest.mark.anyio
async def test_github_userinfo_falls_back_to_user_emails(monkeypatch):
    routes = {
        "https://api.github.com/user": {"id": 42, "email": None, "login": "octo", "name": "Octo"},
        "https://api.github.com/user/emails": [
            {"email": "noreply@users.github.com", "primary": False, "verified": True},
            {"email": "octo@example.com", "primary": True, "verified": True},
        ],
    }
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(routes))

    info = await fetch_userinfo("github", "tok")
    assert info["email"] == "octo@example.com"
    pid, email, name = extract_user_info("github", info)
    assert (pid, email) == ("42", "octo@example.com")


@pytest.mark.anyio
async def test_github_userinfo_keeps_a_public_profile_email(monkeypatch):
    routes = {
        "https://api.github.com/user": {"id": 7, "email": "public@example.com", "login": "pub"},
        # /user/emails present but must not override the already-public address
        "https://api.github.com/user/emails": [
            {"email": "other@example.com", "primary": True, "verified": True},
        ],
    }
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(routes))

    info = await fetch_userinfo("github", "tok")
    assert info["email"] == "public@example.com"


@pytest.mark.anyio
async def test_github_userinfo_unverified_only_stays_unreachable(monkeypatch):
    routes = {
        "https://api.github.com/user": {"id": 9, "email": None, "login": "u"},
        "https://api.github.com/user/emails": [
            {"email": "unverified@example.com", "primary": True, "verified": False},
        ],
    }
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(routes))

    info = await fetch_userinfo("github", "tok")
    # Never adopt an unverified address — an unreachable row is better than a wrong one.
    assert info.get("email") is None


@pytest.mark.anyio
async def test_github_user_emails_failure_does_not_break_login(monkeypatch):
    class _Boom(_FakeClient):
        async def get(self, url, headers=None):
            if url.endswith("/emails"):
                raise httpx.HTTPError("boom")
            return _Resp(self._routes[url])

    routes = {"https://api.github.com/user": {"id": 1, "email": None, "login": "u"}}
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Boom(routes))

    info = await fetch_userinfo("github", "tok")  # must not raise
    assert info.get("email") is None


# ── opportunistic backfill on a returning login ───────────────────────────────

async def _user_with_account(db, *, email, provider, provider_user_id):
    u = User(id=str(uuid.uuid4()), email=email, display_name="U")
    db.add(u)
    await db.commit()
    db.add(OAuthAccount(id=str(uuid.uuid4()), user_id=u.id,
                        provider=provider, provider_user_id=provider_user_id))
    await db.commit()
    return u


@pytest.mark.anyio
async def test_returning_login_backfills_a_missing_email(db_session):
    pid = f"gh-{uuid.uuid4()}"
    u = await _user_with_account(db_session, email=None, provider="github", provider_user_id=pid)

    addr = f"found-{uuid.uuid4()}@example.com"
    same = await get_or_create_user(
        db_session, provider="github", provider_user_id=pid,
        email=addr, display_name="U", access_token="t", refresh_token=None, expires_at=None,
    )
    assert same.id == u.id
    assert same.email == addr


@pytest.mark.anyio
async def test_backfill_does_not_overwrite_an_existing_email(db_session):
    pid = f"gh-{uuid.uuid4()}"
    kept = f"kept-{uuid.uuid4()}@example.com"
    u = await _user_with_account(db_session, email=kept, provider="github", provider_user_id=pid)

    same = await get_or_create_user(
        db_session, provider="github", provider_user_id=pid,
        email=f"new-{uuid.uuid4()}@example.com", display_name="U",
        access_token="t", refresh_token=None, expires_at=None,
    )
    assert same.id == u.id
    assert same.email == kept  # a present address is authoritative, never replaced


@pytest.mark.anyio
async def test_backfill_will_not_steal_an_address_held_by_another_user(db_session):
    taken = f"taken-{uuid.uuid4()}@example.com"
    await _user_with_account(db_session, email=taken, provider="orcid",
                             provider_user_id=f"orc-{uuid.uuid4()}")

    pid = f"gh-{uuid.uuid4()}"
    u = await _user_with_account(db_session, email=None, provider="github", provider_user_id=pid)

    same = await get_or_create_user(
        db_session, provider="github", provider_user_id=pid,
        email=taken, display_name="U", access_token="t", refresh_token=None, expires_at=None,
    )
    assert same.id == u.id
    assert same.email is None  # the unique-email constraint is guarded; no silent steal
