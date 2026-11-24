"""Paginating MOD-API harvest source.

Enumerates a federation peer's ``{mod_root}/artefacts`` collection page by page and,
for each artefact, resolves a download URL from its ``distributions/latest`` document.
All network access goes through the Project-1 federation client's SSRF-guarded fetch
(``fetch_mod_json``); this module never opens its own HTTP client.

Logging discipline: only peer ids / counts / typed reasons are logged, never URLs
(an ``apikey_param`` peer carries its key in the query string).
"""

from __future__ import annotations

import logging
import math
from typing import Any
from urllib.parse import quote

import httpx

from ontoexplorer.modules.discovery.models import Candidate
from ontoexplorer.modules.discovery.throttle import PeerRateLimiter
from ontoexplorer.modules.federation.adapters import (
    _DCAT,
    _as_list,
    _context_map,
    _expand,
    _http_url,
    adapter_for,
)
from ontoexplorer.modules.federation.client import FederationFetchError, fetch_mod_json
from ontoexplorer.modules.federation.config import Peer

logger = logging.getLogger(__name__)

# Largest page_size we ask a peer for.
_MAX_PAGE_SIZE = 200

_DOWNLOAD_URL = _DCAT + "downloadURL"
_ACCESS_URL = _DCAT + "accessURL"


def _mod_root(peer: Peer) -> str:
    # Mirrors federation.client._mod_root (private there).
    return (peer.base_url.rstrip("/") + (peer.mod_path or "")).rstrip("/")


def _nodes(doc: Any, ctx: dict[str, str]) -> list[dict[str, Any]]:
    """The distribution node(s) in a response: the doc itself plus any @graph/member nodes."""
    if isinstance(doc, list):
        raw: list[Any] = list(doc)
    elif isinstance(doc, dict):
        raw = [doc]
        for key in ("@graph", "member", "hydra:member", _expand("hydra:member", ctx)):
            raw.extend(_as_list(doc.get(key)))
    else:
        return []
    out: list[dict[str, Any]] = []
    for n in raw:
        if isinstance(n, dict):
            out.append({_expand(k, ctx): v for k, v in n.items() if isinstance(k, str)})
    return out


def _download_url(doc: Any) -> str | None:
    """An http(s) ``dcat:downloadURL`` (fallback ``dcat:accessURL``) from a distribution doc."""
    try:
        nodes = _nodes(doc, _context_map(doc))
    except Exception:
        return None
    for key in (_DOWNLOAD_URL, _ACCESS_URL):
        for node in nodes:
            for v in _as_list(node.get(key)):
                url = _http_url(v)
                if url:
                    return url
    return None


class ModApiHarvestSource:
    """Enumerate a MOD-API peer's artefacts as ingestion :class:`Candidate` s."""

    def __init__(
        self,
        peer: Peer,
        *,
        rate_limiter: PeerRateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._peer = peer
        self._rate_limiter = rate_limiter
        self._transport = transport
        self.name = f"mod-harvest:{peer.id}"

    async def _wait(self) -> None:
        if self._rate_limiter is not None:
            await self._rate_limiter.wait()

    async def _resolve_download_url(self, acronym: str) -> str | None:
        url = httpx.URL(
            f"{_mod_root(self._peer)}/artefacts/{quote(acronym, safe='')}/distributions/latest"
        )
        await self._wait()
        try:
            doc = await fetch_mod_json(self._peer, url, transport=self._transport)
        except FederationFetchError as exc:
            logger.debug("mod-harvest %s: no distribution (%s)", self._peer.id, exc.reason)
            return None
        return _download_url(doc)

    async def discover(self, *, limit: int) -> list[Candidate]:
        """Return up to ``limit`` candidates, paging the peer's ``/artefacts`` collection.

        Stops when a page yields no new rows, a page is short (fewer than
        ``page_size`` rows = last page), ``limit`` candidates are collected, or a
        hard page cap (``ceil(limit / page_size) + 2``) is hit.
        """
        if limit <= 0:
            return []
        peer = self._peer
        page_size = min(limit, _MAX_PAGE_SIZE)
        max_pages = math.ceil(limit / page_size) + 2
        parse = adapter_for(peer.adapter)
        root = _mod_root(peer)

        out: list[Candidate] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            url = httpx.URL(
                f"{root}/artefacts", params={"page": str(page), "page_size": str(page_size)}
            )
            await self._wait()
            doc = await fetch_mod_json(peer, url, transport=self._transport)
            rows = parse(doc, peer)

            new = 0
            for row in rows:
                if row.iri in seen:
                    continue
                seen.add(row.iri)
                new += 1
                download_url = await self._resolve_download_url(row.acronym)
                out.append(
                    Candidate(
                        canonical_iri=row.iri,
                        title=row.title,
                        license=row.license,
                        download_url=download_url,
                        landing_url=row.source_landing_url or row.homepage,
                        source_catalogue_id=peer.id,
                        source_catalogue_label=peer.label,
                    )
                )
                if len(out) >= limit:
                    break

            if len(out) >= limit or new == 0 or len(rows) < page_size:
                break

        logger.info("mod-harvest %s: %d candidate(s) discovered", peer.id, len(out))
        return out
