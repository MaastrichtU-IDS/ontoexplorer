import pytest
import fakeredis
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from ontoexplorer.modules.mod.ratelimit import mod_rate_limit


def _fake_request(ip: str = "1.2.3.4") -> MagicMock:
    req = MagicMock()
    req.client.host = ip
    return req


def _fake_settings(anon_limit: int = 1000, auth_limit: int = 10000) -> MagicMock:
    s = MagicMock()
    s.mod_rate_limit_anon = anon_limit
    s.mod_rate_limit_auth = auth_limit
    return s


@pytest.mark.anyio
async def test_anon_request_allowed():
    fr = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=fr), \
         patch("ontoexplorer.modules.mod.ratelimit.get_settings", return_value=_fake_settings()):
        await mod_rate_limit(request=_fake_request(), user=None)  # no exception


@pytest.mark.anyio
async def test_anon_rate_limit_exceeded():
    fr = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=fr), \
         patch("ontoexplorer.modules.mod.ratelimit.get_settings", return_value=_fake_settings(anon_limit=2)):
        req = _fake_request()
        await mod_rate_limit(request=req, user=None)
        await mod_rate_limit(request=req, user=None)
        with pytest.raises(HTTPException) as exc_info:
            await mod_rate_limit(request=req, user=None)
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers


@pytest.mark.anyio
async def test_authenticated_uses_higher_limit():
    fr = fakeredis.FakeRedis(decode_responses=True)
    fake_user = MagicMock()
    fake_user.id = "user-123"
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=fr), \
         patch("ontoexplorer.modules.mod.ratelimit.get_settings", return_value=_fake_settings(anon_limit=1, auth_limit=5)):
        req = _fake_request()
        # 3 requests — would exceed anon limit of 1, but auth limit is 5
        await mod_rate_limit(request=req, user=fake_user)
        await mod_rate_limit(request=req, user=fake_user)
        await mod_rate_limit(request=req, user=fake_user)  # no exception


@pytest.mark.anyio
async def test_different_ips_have_separate_counters():
    fr = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=fr), \
         patch("ontoexplorer.modules.mod.ratelimit.get_settings", return_value=_fake_settings(anon_limit=1)):
        await mod_rate_limit(request=_fake_request("1.1.1.1"), user=None)
        # Different IP — should not be rate limited
        await mod_rate_limit(request=_fake_request("2.2.2.2"), user=None)  # no exception
