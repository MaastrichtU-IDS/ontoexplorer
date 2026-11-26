"""GitHub discovery source: enumerate GitHub-hosted ontology files as Candidates.

Discovery is deliberately **metadata-only**. It enumerates files two ways —
curated ``owner/repo`` seeds (git tree) and code search — and filters by the
repo's SPDX license (the decisive, download-free filter: feasibility measured
only ~33% eligible). It emits a :class:`Candidate` whose ``download_url`` is the
raw blob; the ingestion pipeline then downloads, parses, derives the real
identity/shortname, dedups and runs the quality gate. Nothing is parsed here.

``canonical_iri`` carries the raw blob URL only as a provisional identity for the
admission gate's checks; the real ontology IRI is determined at ingest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from ontoexplorer.modules.discovery.github_client import GithubClient, GithubDiscoveryError
from ontoexplorer.modules.discovery.models import Candidate
from ontoexplorer.modules.ingestion.license import canonicalize_license, compliant_license_set

logger = logging.getLogger(__name__)

DEFAULT_QUERIES = [
    "owl:Ontology extension:owl",
    "owl:Ontology extension:ttl",
    "a owl:Ontology extension:rdf",
]
_ONTOLOGY_EXTS = {"owl", "ttl", "rdf", "rdfs", "n3", "nt", "jsonld", "trig", "owx"}
_RAW_BASE = "https://raw.githubusercontent.com"


def _ext(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


@dataclass(frozen=True)
class _Hit:
    """One enumerated file before license + identity resolution."""

    full_name: str
    path: str
    sha: str
    html_url: str


class GithubDiscoverySource:
    """Enumerate GitHub ontology files as ingestion :class:`Candidate` s."""

    def __init__(
        self,
        client: GithubClient,
        *,
        seed_repos: list[str] | None = None,
        queries: list[str] | None = None,
        require_compliant_license: bool = True,
        max_file_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self._client = client
        self._seed_repos = list(seed_repos or [])
        self._queries = list(queries or DEFAULT_QUERIES)
        self._require_compliant_license = require_compliant_license
        self._max_file_bytes = max_file_bytes
        self.name = "github"

    async def _enumerate(self) -> list[_Hit]:
        """Collect candidate files from curated repos and code search, sha-deduped.

        Forks are excluded (code search excludes them by default; seed repos and
        search items are re-checked). Curated files over ``max_file_bytes`` (known
        from the tree) are dropped; search hits carry no size, so the pipeline's
        source-size cap holds those.
        """
        seen: set[str] = set()
        hits: list[_Hit] = []

        for full_name in self._seed_repos:
            try:
                repo = await self._client.get_repo(full_name)
                if repo.get("fork"):
                    continue
                branch = repo.get("default_branch") or "HEAD"
                tree = await self._client.list_tree(full_name, default_branch=branch)
            except GithubDiscoveryError as exc:
                logger.debug("github_discover seed_skipped reason=%s", exc.reason)
                continue
            for entry in tree:
                if entry.get("type") != "blob":
                    continue
                path = entry.get("path") or ""
                if _ext(path) not in _ONTOLOGY_EXTS:
                    continue
                size = entry.get("size")
                if isinstance(size, int) and size > self._max_file_bytes:
                    continue
                sha = entry.get("sha") or ""
                if not sha or sha in seen:
                    continue
                seen.add(sha)
                html = f"https://github.com/{full_name}/blob/{quote(branch)}/{quote(path)}"
                hits.append(_Hit(full_name, path, sha, html))

        for query in self._queries:
            try:
                items = await self._client.search_code(query)
            except GithubDiscoveryError as exc:
                logger.debug("github_discover query_skipped reason=%s", exc.reason)
                continue
            for item in items:
                repo = item.get("repository") or {}
                if repo.get("fork"):
                    continue
                full_name = repo.get("full_name") or ""
                path = item.get("path") or ""
                sha = item.get("sha") or ""
                if not (full_name and path and sha):
                    continue
                if _ext(path) not in _ONTOLOGY_EXTS:
                    continue
                if sha in seen:
                    continue
                seen.add(sha)
                hits.append(_Hit(full_name, path, sha, item.get("html_url") or ""))

        return hits

    async def discover(self, *, limit: int) -> list[Candidate]:
        """Return up to ``limit`` license-eligible candidates from GitHub."""
        if limit <= 0:
            return []
        allowlist = compliant_license_set()
        out: list[Candidate] = []
        for hit in await self._enumerate():
            try:
                repo = await self._client.get_repo(hit.full_name)  # cached
            except GithubDiscoveryError as exc:
                logger.debug("github_discover repo_skipped reason=%s", exc.reason)
                continue
            spdx = (repo.get("license") or {}).get("spdx_id") or None
            if spdx == "NOASSERTION":
                spdx = None
            if self._require_compliant_license and allowlist:
                canon = canonicalize_license(spdx) if spdx else None
                if canon is None or canon not in allowlist:
                    continue
            branch = repo.get("default_branch") or "HEAD"
            raw_url = f"{_RAW_BASE}/{hit.full_name}/{quote(branch)}/{quote(hit.path)}"
            out.append(
                Candidate(
                    canonical_iri=raw_url,
                    title=f"{hit.full_name}/{hit.path}",
                    acronym=None,
                    license=spdx,
                    download_url=raw_url,
                    landing_url=hit.html_url or None,
                    source_catalogue_id="github",
                    source_catalogue_label="GitHub",
                )
            )
            if len(out) >= limit:
                break

        logger.info("github_discover complete candidates=%d", len(out))
        return out
