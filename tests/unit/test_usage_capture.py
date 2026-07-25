"""Unit tests for usage capture: bot/DNT filtering, salted daily hash, and the
Redis dedup+count path (via fakeredis)."""
from datetime import UTC, datetime
from types import SimpleNamespace

import fakeredis.aioredis
import pytest

from ontoexplorer.modules.usage import capture


def _req(ua="Mozilla/5.0 (X11; Linux) Firefox/123", ip="1.2.3.4", headers=None):
    h = {"user-agent": ua}
    if ip:
        h["x-forwarded-for"] = ip
    if headers:
        h.update(headers)
    return SimpleNamespace(headers=h, client=SimpleNamespace(host="10.0.0.1"))


def test_is_bot():
    assert capture._is_bot("python-requests/2.31")
    assert capture._is_bot("Googlebot/2.1")
    assert capture._is_bot("curl/8.0")
    assert capture._is_bot("")  # missing UA treated as bot
    assert not capture._is_bot("Mozilla/5.0 (Macintosh) Safari/605")


def test_do_not_track():
    assert capture._do_not_track(_req(headers={"dnt": "1"}))
    assert capture._do_not_track(_req(headers={"sec-gpc": "1"}))
    assert not capture._do_not_track(_req())


def test_visitor_hash_is_daily_rotating_and_deterministic():
    h1 = capture._visitor_hash("1.2.3.4", "UA", "onto1", "20260725")
    h2 = capture._visitor_hash("1.2.3.4", "UA", "onto1", "20260725")
    h_next_day = capture._visitor_hash("1.2.3.4", "UA", "onto1", "20260726")
    h_other_ip = capture._visitor_hash("9.9.9.9", "UA", "onto1", "20260725")
    assert h1 == h2                 # deterministic within a day
    assert h1 != h_next_day         # rotates across days (no cross-day linkage)
    assert h1 != h_other_ip         # distinguishes visitors
    assert len(h1) == 64            # sha256 hex


@pytest.mark.anyio
async def test_record_usage_dedup_and_counts(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(capture, "_redis", fake)
    day = datetime.now(UTC).strftime("%Y%m%d")
    onto = "onto-xyz"
    counts = f"usage:counts:{day}"

    # First download from this visitor → total=1, unique=1.
    await capture.record_usage(_req(), onto, capture.KIND_DOWNLOAD)
    assert await fake.hget(counts, f"download:{onto}:total") == "1"
    assert await fake.hget(counts, f"download:{onto}:unique") == "1"

    # Same visitor, same day → total=2, unique stays 1 (deduped).
    await capture.record_usage(_req(), onto, capture.KIND_DOWNLOAD)
    assert await fake.hget(counts, f"download:{onto}:total") == "2"
    assert await fake.hget(counts, f"download:{onto}:unique") == "1"

    # A different visitor → unique=2.
    await capture.record_usage(_req(ip="5.6.7.8"), onto, capture.KIND_DOWNLOAD)
    assert await fake.hget(counts, f"download:{onto}:unique") == "2"


@pytest.mark.anyio
async def test_record_usage_skips_bots_and_dnt(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(capture, "_redis", fake)
    day = datetime.now(UTC).strftime("%Y%m%d")

    await capture.record_usage(_req(ua="Googlebot/2.1"), "o", capture.KIND_VIEW)
    await capture.record_usage(_req(headers={"dnt": "1"}), "o", capture.KIND_VIEW)
    assert await fake.hgetall(f"usage:counts:{day}") == {}
