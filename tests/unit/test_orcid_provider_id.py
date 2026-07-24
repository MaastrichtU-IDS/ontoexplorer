"""Regression: ORCID logins must not collapse onto one account via a null id.

Root cause was extract_user_info returning str(None)=="None" for ORCID, so every
login with an unextractable iD matched the same (orcid,"None") oauth_account —
privilege escalation onto whichever account first held that row.
"""
import uuid

import pytest

from ontoexplorer.modules.auth.oauth import extract_user_info
from ontoexplorer.modules.auth.session import (
    find_oauth_owner,
    get_or_create_user,
    link_oauth_account,
)


def test_extract_orcid_missing_id_returns_none_not_string():
    pid, email, name = extract_user_info("orcid", {})
    assert pid is None            # NOT the string "None"
    assert email is None


def test_extract_orcid_real_id():
    pid, _, _ = extract_user_info("orcid", {"orcid-identifier": {"path": "0000-0002-1825-0097"}})
    assert pid == "0000-0002-1825-0097"


@pytest.mark.anyio
async def test_get_or_create_user_rejects_empty_provider_id(db_session):
    for bad in ("", None, "None"):
        with pytest.raises(ValueError):
            await get_or_create_user(
                db_session, provider="orcid", provider_user_id=bad,
                email=None, display_name=None,
                access_token=None, refresh_token=None, expires_at=None,
            )


@pytest.mark.anyio
async def test_link_rejects_empty_provider_id(db_session):
    from ontoexplorer.models.db import User
    u = User(id=str(uuid.uuid4()))
    db_session.add(u)
    await db_session.commit()
    with pytest.raises(ValueError):
        await link_oauth_account(
            db_session, user_id=u.id, provider="orcid", provider_user_id="None",
            email=None, display_name=None,
            access_token=None, refresh_token=None, expires_at=None,
        )


@pytest.mark.anyio
async def test_find_oauth_owner_ignores_empty_id(db_session):
    assert await find_oauth_owner(db_session, "orcid", "None") is None
    assert await find_oauth_owner(db_session, "orcid", "") is None
