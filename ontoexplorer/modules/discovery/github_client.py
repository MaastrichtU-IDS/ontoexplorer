"""Async GitHub API client for ontology discovery.

Talks only to ``api.github.com`` (code search, repo metadata, git trees) with a
bearer PAT. Read-only. Blob **downloads** are not done here — they go through the
ingestion pipeline's SSRF-guarded resolver at ingest time.

Secret hygiene (this repo is public): the PAT rides in the ``Authorization``
header (never a query string, so httpx's request-line logging cannot leak it),
and it is never logged, never placed in an exception message, and never in a
logged URL. Only typed reasons / counts are logged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ontoexplorer.modules.discovery.throttle import PeerRateLimiter

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"
_MAX_RETRIES = 2
_BACKOFF_CAP_S = 30.0


class GithubDiscoveryError(Exception):
    """A GitHub discovery call failed.

    ``reason`` is a short typed label (e.g. ``"rate_limited"``, ``"no_token"``,
    ``"not_found:repo"``); neither it nor ``str(exc)`` ever contains the PAT or a
    full request URL.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _is_rate_limited(resp: httpx.Response) -> bool:
    if resp.headers.get("retry-after"):
        return True
    return resp.headers.get("x-ratelimit-remaining") == "0"


def _retry_after_s(resp: httpx.Response) -> float:
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            return min(float(ra), _BACKOFF_CAP_S)
        except ValueError:
            pass
    return 1.0


class GithubClient:
    """Minimal async GitHub REST client scoped to what discovery needs.

    ``transport`` and ``sleep`` are injectable so tests are deterministic and make
    no real network calls.
    """

    def __init__(
        self,
        token: str,
        *,
        rate_limiter: PeerRateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        api_base: str = _API_BASE,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._token = token or ""
        self._rate_limiter = rate_limiter
        self._transport = transport
        self._api_base = api_base.rstrip("/")
        self._sleep = sleep
        self._repo_cache: dict[str, dict[str, Any]] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
        }

    async def _wait(self) -> None:
        if self._rate_limiter is not None:
            await self._rate_limiter.wait()

    async def _get(self, path: str, *, where: str, params: dict | None = None) -> Any:
        """GET ``api_base + path``. ``where`` is a token-free label for logs/errors."""
        if not self._token:
            raise GithubDiscoveryError("no_token")
        url = self._api_base + path
        for attempt in range(_MAX_RETRIES + 1):
            await self._wait()
            try:
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=30.0
                ) as client:
                    resp = await client.get(url, params=params, headers=self._headers())
            except httpx.HTTPError:
                # Scrub: an httpx error's str can embed the request URL. The URL
                # carries no secret here (token is a header), but we keep the
                # message typed and URL-free regardless.
                raise GithubDiscoveryError(f"request_failed:{where}") from None
            if resp.status_code == 403 and _is_rate_limited(resp):
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "github_rate_limited where=%s attempt=%d", where, attempt
                    )
                    await self._sleep(_retry_after_s(resp))
                    continue
                raise GithubDiscoveryError("rate_limited")
            if resp.status_code == 404:
                raise GithubDiscoveryError(f"not_found:{where}")
            if resp.status_code >= 400:
                raise GithubDiscoveryError(f"http_{resp.status_code}:{where}")
            try:
                return resp.json()
            except Exception:
                raise GithubDiscoveryError(f"bad_json:{where}") from None
        raise GithubDiscoveryError("rate_limited")  # unreachable: loop returns/raises

    async def search_code(self, query: str, *, per_page: int = 100) -> list[dict]:
        """Return the raw ``items`` of a code-search query (auth-mandatory, ~10/min)."""
        doc = await self._get(
            "/search/code", where="search", params={"q": query, "per_page": str(per_page)}
        )
        items = doc.get("items", []) if isinstance(doc, dict) else []
        return [it for it in items if isinstance(it, dict)]

    async def get_repo(self, full_name: str) -> dict:
        """Return (and cache) a repo object: ``.license.spdx_id``, ``.default_branch``, ``.fork``."""
        if full_name in self._repo_cache:
            return self._repo_cache[full_name]
        doc = await self._get(f"/repos/{full_name}", where="repo")
        if not isinstance(doc, dict):
            raise GithubDiscoveryError("bad_json:repo")
        self._repo_cache[full_name] = doc
        return doc

    async def list_tree(self, full_name: str, *, default_branch: str) -> list[dict]:
        """Return the recursive git-tree entries (``path``/``sha``/``size``/``type``)."""
        doc = await self._get(
            f"/repos/{full_name}/git/trees/{default_branch}",
            where="tree",
            params={"recursive": "1"},
        )
        tree = doc.get("tree", []) if isinstance(doc, dict) else []
        return [e for e in tree if isinstance(e, dict)]
