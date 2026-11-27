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
# Repository topics that signal ontology/vocabulary content (after the Shapes of You
# index, github.com/vemonet/shapes-of-you). Primary discovery input: topic-tagged
# repos are intentional, and their files are tree-walked + raw-downloaded, so large
# ontologies that code search's ~384 KB index ceiling hides are still reached.
DEFAULT_TOPICS = ["owl", "obofoundry", "bioportal", "skos"]
_ONTOLOGY_EXTS = {"owl", "ttl", "rdf", "rdfs", "n3", "nt", "jsonld", "trig", "owx"}
_RAW_BASE = "https://raw.githubusercontent.com"


def _ext(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


# Paths that are editor sub-artifacts, imports, dosdp patterns, subsets, test
# fixtures or historical release modules in ODK/OBO-style repos — never the
# publishable ontology. (The ``-edit`` source file is deliberately NOT skipped.)
_SKIP_PATH_SEGMENTS = {
    "test", "tests", "example", "examples", "archive", "archived",
    "components", "imports", "patterns", "subsets", "modules",
    "deprecated", "obsolete", "tmp", "temp", "scratch", "node_modules",
}
_SKIP_FILENAME_SUFFIXES = ("-module", "-import", "_import", "-merged", "merged_import")


def _is_noise_path(path: str) -> bool:
    """True for tree/search paths that are sub-artifacts, not a publishable ontology."""
    lower = path.lower()
    if set(lower.split("/")) & _SKIP_PATH_SEGMENTS:
        return True
    stem = lower.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return stem.endswith(_SKIP_FILENAME_SUFFIXES)


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
        topics: list[str] | None = None,
        queries: list[str] | None = None,
        require_compliant_license: bool = True,
        max_file_bytes: int = 8 * 1024 * 1024,
        max_repos_per_topic: int = 25,
    ) -> None:
        self._client = client
        self._seed_repos = list(seed_repos or [])
        # None => built-in defaults; an explicit [] disables that mechanism.
        self._topics = DEFAULT_TOPICS if topics is None else list(topics)
        self._queries = DEFAULT_QUERIES if queries is None else list(queries)
        self._require_compliant_license = require_compliant_license
        self._max_file_bytes = max_file_bytes
        self._max_repos_per_topic = max_repos_per_topic
        self.name = "github"

    async def _enumerate_repo(self, full_name: str, seen: set[str], hits: list[_Hit]) -> None:
        """Tree-walk one repo, appending its ontology-extension blobs as hits.

        Uses the raw git tree (no code-search size ceiling), so large ontologies that
        code search cannot see are reachable here. Forks and oversized blobs are
        skipped; blobs are sha-deduped against ``seen``.
        """
        try:
            repo = await self._client.get_repo(full_name)
            if repo.get("fork"):
                return
            branch = repo.get("default_branch") or "HEAD"
            tree = await self._client.list_tree(full_name, default_branch=branch)
        except GithubDiscoveryError as exc:
            logger.debug("github_discover repo_skipped reason=%s", exc.reason)
            return
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            path = entry.get("path") or ""
            if _ext(path) not in _ONTOLOGY_EXTS or _is_noise_path(path):
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

    async def _discover_topic_repos(self, seen_repos: set[str]) -> list[str]:
        """Repos found by searching each configured topic, freshest first (sort=updated).

        ``seen_repos`` is updated in place so the same repo is never tree-walked twice
        across topics or against the seed list.
        """
        found: list[str] = []
        for topic in self._topics:
            try:
                repos = await self._client.search_repositories(
                    f"topic:{topic}", sort="updated", order="desc",
                    per_page=self._max_repos_per_topic,
                )
            except GithubDiscoveryError as exc:
                logger.debug("github_discover topic_skipped reason=%s", exc.reason)
                continue
            for item in repos[: self._max_repos_per_topic]:
                full_name = item.get("full_name") or ""
                if not full_name or item.get("fork") or full_name in seen_repos:
                    continue
                seen_repos.add(full_name)
                found.append(full_name)
        return found

    async def _enumerate(self) -> list[_Hit]:
        """Collect candidate files, sha-deduped, forks excluded:

        1. **Primary** — curated seed repos + topic-discovered repos, tree-walked
           (raw access, so large ontologies past code search's ~384 KB index ceiling
           are reached).
        2. **Complement** — code search over file content, for untagged repos the
           topic path misses (indexed, <384 KB files only).
        """
        seen: set[str] = set()
        hits: list[_Hit] = []
        seen_repos: set[str] = set()

        repo_names = [r.strip() for r in self._seed_repos if r.strip()]
        seen_repos.update(repo_names)
        repo_names += await self._discover_topic_repos(seen_repos)
        for full_name in repo_names:
            await self._enumerate_repo(full_name, seen, hits)

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
                if _ext(path) not in _ONTOLOGY_EXTS or _is_noise_path(path):
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
