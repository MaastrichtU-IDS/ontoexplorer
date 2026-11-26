"""Tests for the GitHub discovery API client.

Focus: deterministic MockTransport (no network), the retry/backoff path, typed
errors, and — load-bearing because the repo is public — that the PAT never
reaches logs or an exception message.
"""

from __future__ import annotations

import httpx
import pytest

from ontoexplorer.modules.discovery.github_client import GithubClient, GithubDiscoveryError

TOKEN = "ghp_SECRETtokenVALUE_do_not_log_123"


def _client(handler, **kw) -> GithubClient:
    return GithubClient(TOKEN, transport=httpx.MockTransport(handler), **kw)


@pytest.mark.anyio
async def test_search_code_parses_items():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/code"
        assert request.url.params["q"] == "owl:Ontology extension:owl"
        return httpx.Response(200, json={"items": [{"path": "a.owl", "sha": "1"}, "junk"]})

    items = await _client(handler).search_code("owl:Ontology extension:owl")
    assert items == [{"path": "a.owl", "sha": "1"}]  # non-dict dropped


@pytest.mark.anyio
async def test_get_repo_extracts_and_caches():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"default_branch": "main", "fork": False,
                  "license": {"spdx_id": "CC0-1.0"}},
        )

    c = _client(handler)
    repo = await c.get_repo("owner/repo")
    assert repo["default_branch"] == "main"
    assert repo["license"]["spdx_id"] == "CC0-1.0"
    await c.get_repo("owner/repo")  # cached
    assert calls["n"] == 1


@pytest.mark.anyio
async def test_list_tree_filters_non_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/owner/repo/git/trees/main"
        assert request.url.params["recursive"] == "1"
        return httpx.Response(200, json={"tree": [{"path": "x.owl", "type": "blob", "size": 9}, 3]})

    tree = await _client(handler).list_tree("owner/repo", default_branch="main")
    assert tree == [{"path": "x.owl", "type": "blob", "size": 9}]


@pytest.mark.anyio
async def test_rate_limit_backoff_then_success():
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(403, headers={"retry-after": "2"}, json={"message": "slow"})
        return httpx.Response(200, json={"items": []})

    c = _client(handler, sleep=fake_sleep)
    out = await c.search_code("q")
    assert out == []
    assert slept == [2.0]  # one bounded backoff


@pytest.mark.anyio
async def test_rate_limit_exhausted_raises_typed():
    async def fake_sleep(s: float) -> None:
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={})

    with pytest.raises(GithubDiscoveryError) as ei:
        await _client(handler, sleep=fake_sleep).search_code("q")
    assert ei.value.reason == "rate_limited"
    assert TOKEN not in str(ei.value)


@pytest.mark.anyio
async def test_missing_token_raises_before_request():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={})

    c = GithubClient("", transport=httpx.MockTransport(handler))
    with pytest.raises(GithubDiscoveryError) as ei:
        await c.get_repo("o/r")
    assert ei.value.reason == "no_token"
    assert called["n"] == 0  # no network touched


@pytest.mark.anyio
async def test_token_never_logged(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        # token must be present on the wire (header), proving auth is attached...
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(403, headers={"retry-after": "0"}, json={})

    async def fake_sleep(s: float) -> None:
        return None

    with caplog.at_level("DEBUG"):
        with pytest.raises(GithubDiscoveryError):
            await _client(handler, sleep=fake_sleep).search_code("q")
    # ...but never in any log record.
    assert all(TOKEN not in r.getMessage() for r in caplog.records)
