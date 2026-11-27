"""Tests for GithubDiscoverySource.discover() — enumeration, license filter,
fork exclusion, sha-dedup, limit, and raw-URL construction. Uses a stub client
(no network, no GithubClient internals)."""

from __future__ import annotations

import pytest

from ontoexplorer.modules.discovery.github_client import GithubDiscoveryError
from ontoexplorer.modules.discovery.github_source import GithubDiscoverySource


class StubClient:
    def __init__(self, repos=None, trees=None, search=None, repo_search=None):
        self.repos = repos or {}            # full_name -> repo dict
        self.trees = trees or {}            # full_name -> list[tree entries]
        self.search = search or {}          # code-search query -> list[items]
        self.repo_search = repo_search or {}  # repo-search query -> list[items]
        self.repo_calls: list[str] = []
        self.repo_search_calls: list[str] = []

    async def get_repo(self, full_name):
        self.repo_calls.append(full_name)
        if full_name not in self.repos:
            raise GithubDiscoveryError("not_found:repo")
        return self.repos[full_name]

    async def list_tree(self, full_name, *, default_branch):
        return self.trees.get(full_name, [])

    async def search_code(self, query, *, per_page=100):
        return self.search.get(query, [])

    async def search_repositories(self, query, *, sort=None, order=None, per_page=30):
        self.repo_search_calls.append(query)
        return self.repo_search.get(query, [])


def _repo(spdx="CC0-1.0", branch="main", fork=False):
    lic = {"spdx_id": spdx} if spdx is not None else None
    return {"default_branch": branch, "fork": fork, "license": lic}


@pytest.mark.anyio
async def test_seed_repo_yields_candidate_with_raw_download():
    client = StubClient(
        repos={"BFO-ontology/BFO": _repo(branch="master")},
        trees={"BFO-ontology/BFO": [
            {"type": "blob", "path": "src/bfo.owl", "sha": "a", "size": 100},
            {"type": "blob", "path": "README.md", "sha": "b", "size": 10},  # non-ontology
            {"type": "tree", "path": "src", "sha": "c"},                    # dir
        ]},
    )
    src = GithubDiscoverySource(client, seed_repos=["BFO-ontology/BFO"], queries=[])
    out = await src.discover(limit=10)
    assert len(out) == 1
    c = out[0]
    assert c.download_url == "https://raw.githubusercontent.com/BFO-ontology/BFO/master/src/bfo.owl"
    assert c.canonical_iri == c.download_url
    assert c.license == "CC0-1.0"
    assert c.source_catalogue_id == "github" and c.acronym is None


@pytest.mark.anyio
async def test_code_search_yields_candidate():
    client = StubClient(
        repos={"o/r": _repo(spdx="MIT")},
        search={"q": [{"repository": {"full_name": "o/r", "fork": False},
                       "path": "onto.ttl", "sha": "z", "html_url": "https://gh/o/r/onto.ttl"}]},
    )
    src = GithubDiscoverySource(client, seed_repos=[], queries=["q"])
    out = await src.discover(limit=10)
    assert len(out) == 1
    assert out[0].download_url == "https://raw.githubusercontent.com/o/r/main/onto.ttl"
    assert out[0].landing_url == "https://gh/o/r/onto.ttl"


@pytest.mark.anyio
async def test_noncompliant_license_skipped():
    client = StubClient(
        repos={"o/r": _repo(spdx="GPL-2.0")},  # not in allowlist
        search={"q": [{"repository": {"full_name": "o/r"}, "path": "x.owl", "sha": "1"}]},
    )
    src = GithubDiscoverySource(client, queries=["q"])
    assert await src.discover(limit=10) == []


@pytest.mark.anyio
async def test_absent_license_admitted_when_not_strict():
    client = StubClient(
        repos={"o/r": _repo(spdx=None)},
        search={"q": [{"repository": {"full_name": "o/r"}, "path": "x.owl", "sha": "1"}]},
    )
    src = GithubDiscoverySource(client, queries=["q"], require_compliant_license=False)
    out = await src.discover(limit=10)
    assert len(out) == 1 and out[0].license is None


@pytest.mark.anyio
async def test_noassertion_license_treated_absent_and_skipped_when_strict():
    client = StubClient(
        repos={"o/r": _repo(spdx="NOASSERTION")},
        search={"q": [{"repository": {"full_name": "o/r"}, "path": "x.owl", "sha": "1"}]},
    )
    src = GithubDiscoverySource(client, queries=["q"])  # strict by default
    assert await src.discover(limit=10) == []


@pytest.mark.anyio
async def test_forks_excluded():
    client = StubClient(
        repos={"seed/fork": _repo(fork=True)},
        trees={"seed/fork": [{"type": "blob", "path": "a.owl", "sha": "a", "size": 1}]},
        search={"q": [{"repository": {"full_name": "o/r", "fork": True},
                       "path": "x.owl", "sha": "b"}]},
    )
    src = GithubDiscoverySource(client, seed_repos=["seed/fork"], queries=["q"])
    assert await src.discover(limit=10) == []


@pytest.mark.anyio
async def test_sha_dedup_across_inputs():
    # same blob sha appears in a seed repo and a search hit -> one candidate.
    client = StubClient(
        repos={"o/r": _repo()},
        trees={"o/r": [{"type": "blob", "path": "a.owl", "sha": "dup", "size": 1}]},
        search={"q": [{"repository": {"full_name": "o/r"}, "path": "a.owl", "sha": "dup"}]},
    )
    src = GithubDiscoverySource(client, seed_repos=["o/r"], queries=["q"])
    out = await src.discover(limit=10)
    assert len(out) == 1


@pytest.mark.anyio
async def test_oversized_tree_blob_skipped():
    client = StubClient(
        repos={"o/r": _repo()},
        trees={"o/r": [{"type": "blob", "path": "big.owl", "sha": "a", "size": 99_000_000}]},
    )
    src = GithubDiscoverySource(client, seed_repos=["o/r"], queries=[], max_file_bytes=1_000)
    assert await src.discover(limit=10) == []


@pytest.mark.anyio
async def test_noise_paths_skipped_in_tree_walk():
    client = StubClient(
        repos={"o/r": _repo(branch="main")},
        trees={"o/r": [
            {"type": "blob", "path": "foo.owl", "sha": "a", "size": 10},                       # keep
            {"type": "blob", "path": "src/ontology/foo-edit.owl", "sha": "b", "size": 10},     # keep (-edit)
            {"type": "blob", "path": "src/ontology/components/x.owl", "sha": "c", "size": 10}, # skip
            {"type": "blob", "path": "imports/merged_import.owl", "sha": "d", "size": 10},     # skip
            {"type": "blob", "path": "src/patterns/pattern.owl", "sha": "e", "size": 10},      # skip
            {"type": "blob", "path": "releases/2018/dpo-module.owl", "sha": "f", "size": 10},  # skip
            {"type": "blob", "path": "test/fixture.owl", "sha": "g", "size": 10},              # skip
        ]},
    )
    src = GithubDiscoverySource(client, seed_repos=["o/r"], topics=[], queries=[])
    out = await src.discover(limit=20)
    # title is "o/r/<path>" (full_name has one slash); keep only non-noise paths.
    assert sorted(c.title.split("/", 2)[2] for c in out) == ["foo.owl", "src/ontology/foo-edit.owl"]


@pytest.mark.anyio
async def test_topic_discovery_tree_walks_found_repos():
    client = StubClient(
        repos={"obo/thing": _repo(spdx="CC0-1.0", branch="main")},
        trees={"obo/thing": [{"type": "blob", "path": "thing.owl", "sha": "t1", "size": 50}]},
        repo_search={"topic:obofoundry": [{"full_name": "obo/thing", "fork": False}]},
    )
    src = GithubDiscoverySource(client, seed_repos=[], topics=["obofoundry"], queries=[])
    out = await src.discover(limit=10)
    assert len(out) == 1
    assert out[0].download_url == "https://raw.githubusercontent.com/obo/thing/main/thing.owl"
    assert client.repo_search_calls == ["topic:obofoundry"]


@pytest.mark.anyio
async def test_topic_repo_deduped_against_seed():
    # same repo as a seed and a topic hit -> tree-walked once.
    client = StubClient(
        repos={"o/r": _repo()},
        trees={"o/r": [{"type": "blob", "path": "a.owl", "sha": "a", "size": 1}]},
        repo_search={"topic:owl": [{"full_name": "o/r", "fork": False}]},
    )
    src = GithubDiscoverySource(client, seed_repos=["o/r"], topics=["owl"], queries=[])
    assert len(await src.discover(limit=10)) == 1


@pytest.mark.anyio
async def test_topic_fork_repo_excluded():
    client = StubClient(repo_search={"topic:owl": [{"full_name": "o/forked", "fork": True}]})
    src = GithubDiscoverySource(client, seed_repos=[], topics=["owl"], queries=[])
    assert await src.discover(limit=10) == []


@pytest.mark.anyio
async def test_empty_topics_disables_topic_search():
    client = StubClient(
        repos={"o/r": _repo()},
        trees={"o/r": [{"type": "blob", "path": "a.owl", "sha": "a", "size": 1}]},
    )
    src = GithubDiscoverySource(client, seed_repos=["o/r"], topics=[], queries=[])
    out = await src.discover(limit=10)
    assert len(out) == 1
    assert client.repo_search_calls == []  # topics=[] disables; None would use defaults


@pytest.mark.anyio
async def test_limit_honored_and_zero():
    items = [{"repository": {"full_name": "o/r"}, "path": f"f{i}.owl", "sha": str(i)}
             for i in range(5)]
    client = StubClient(repos={"o/r": _repo()}, search={"q": items})
    src = GithubDiscoverySource(client, queries=["q"])
    assert len(await src.discover(limit=3)) == 3
    assert await src.discover(limit=0) == []
