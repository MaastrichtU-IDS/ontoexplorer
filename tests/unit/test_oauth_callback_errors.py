"""The OAuth callback must report what the provider said.

Both the token exchange and the userinfo fetch used to raise straight out of the
handler as a bare 500. GitHub answers `bad_verification_code` for a stale code
and `incorrect_client_credentials` for a wrong client_id/secret pair — the two
faults need completely different fixes and were indistinguishable once collapsed
into "Internal Server Error".
"""

import pytest
from fastapi import HTTPException

from ontoexplorer.api import auth as auth_api


class _Client:
    def __init__(self, exc=None, token=None):
        self._exc, self._token = exc, token

    async def fetch_token(self, *a, **k):
        if self._exc:
            raise self._exc
        return self._token


@pytest.fixture
def _stub(monkeypatch):
    monkeypatch.setattr(auth_api, "get_redirect_uri", lambda p: "https://app/auth/github/callback")
    monkeypatch.setattr(auth_api, "get_token_url", lambda p: "https://github.com/token")


@pytest.mark.anyio
async def test_token_exchange_failure_reports_the_provider_message(monkeypatch, _stub):
    monkeypatch.setattr(auth_api, "make_oauth_client",
                        lambda p: _Client(exc=RuntimeError("incorrect_client_credentials")))

    with pytest.raises(HTTPException) as e:
        await auth_api.oauth_callback(provider="github", code="c", state="s",
                                      oauth_state="s", oauth_link=None, db=None)
    assert e.value.status_code == 502
    assert "incorrect_client_credentials" in e.value.detail


@pytest.mark.anyio
async def test_missing_access_token_reports_the_error_body(monkeypatch, _stub):
    """A 200 response carrying an error body, which GitHub does return."""
    monkeypatch.setattr(auth_api, "make_oauth_client",
                        lambda p: _Client(token={"error": "bad_verification_code",
                                                 "error_description": "The code passed is incorrect or expired."}))

    with pytest.raises(HTTPException) as e:
        await auth_api.oauth_callback(provider="github", code="c", state="s",
                                      oauth_state="s", oauth_link=None, db=None)
    assert e.value.status_code == 502
    assert "incorrect or expired" in e.value.detail


@pytest.mark.anyio
async def test_userinfo_failure_is_distinguishable_from_token_failure(monkeypatch, _stub):
    monkeypatch.setattr(auth_api, "make_oauth_client",
                        lambda p: _Client(token={"access_token": "t"}))

    async def _boom(*a, **k):
        raise RuntimeError("401 Bad credentials")
    monkeypatch.setattr(auth_api, "fetch_userinfo", _boom)

    with pytest.raises(HTTPException) as e:
        await auth_api.oauth_callback(provider="github", code="c", state="s",
                                      oauth_state="s", oauth_link=None, db=None)
    assert e.value.status_code == 502
    assert "profile" in e.value.detail.lower()
    assert "Bad credentials" in e.value.detail


@pytest.mark.anyio
async def test_state_mismatch_still_refused_before_anything_is_exchanged(_stub):
    with pytest.raises(HTTPException) as e:
        await auth_api.oauth_callback(provider="github", code="c", state="s",
                                      oauth_state="different", oauth_link=None, db=None)
    assert e.value.status_code == 400
