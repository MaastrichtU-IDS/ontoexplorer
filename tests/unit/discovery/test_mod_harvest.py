"""Unit tests for the paginating MOD-API harvest source (no network)."""

from __future__ import annotations

import httpx
import pytest

from ontoexplorer.config import get_settings
from ontoexplorer.modules.discovery import mod_harvest
from ontoexplorer.modules.discovery.mod_harvest import ModApiHarvestSource
from ontoexplorer.modules.discovery.source import DiscoverySource
from ontoexplorer.modules.federation.config import Peer

PEER = Peer(id="testpeer", label="Test", base_url="https://peer.example", mod_path="/mod")
_CTX = {
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "mod": "https://w3id.org/mod#",
    "hydra": "http://www.w3.org/ns/hydra/core#",
}


def _iri(n: int) -> str:
    return f"https://peer.example/ontology/ONT{n}"


def _member(n: int) -> dict:
    return {
        "@id": _iri(n),
        "@type": "mod:SemanticArtefact",
        "dcterms:title": f"Ontology {n}",
        "mod:acronym": f"ONT{n}",
        "dcterms:license": "https://creativecommons.org/licenses/by/4.0/",
    }


def _page(members: list[int]) -> dict:
    return {
        "@context": _CTX,
        "@type": "hydra:Collection",
        "hydra:member": [_member(n) for n in members],
    }


def _dist(n: int) -> dict:
    return {
        "@context": _CTX,
        "@id": f"https://peer.example/dist/{n}",
        "dcat:downloadURL": {"@id": f"https://files.example/ONT{n}.owl"},
    }


def _transport(pages: dict[int, list[int]], *, dists: str = "ok", seen: list | None = None):
    """pages: page number -> artefact numbers. dists: ok | 404 | 500."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if seen is not None:
            seen.append(str(request.url))
        if path == "/mod/artefacts":
            n = int(request.url.params["page"])
            return httpx.Response(200, json=_page(pages.get(n, [])))
        if path.startswith("/mod/artefacts/") and path.endswith("/distributions/latest"):
            acr = path.split("/")[3]
            if dists == "404":
                return httpx.Response(404)
            if dists == "500":
                return httpx.Response(500)
            if dists == "mixed" and acr == "ONT2":
                return httpx.Response(500)
            return httpx.Response(200, json=_dist(int(acr.removeprefix("ONT"))))
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _clean_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def small_pages(monkeypatch):
    """Shrink the page-size ceiling to 3 so multi-page walks need only a few rows."""
    monkeypatch.setattr(mod_harvest, "_MAX_PAGE_SIZE", 3)


def test_name_and_protocol():
    src = ModApiHarvestSource(PEER, transport=_transport({}))
    assert src.name == "mod-harvest:testpeer"
    assert isinstance(src, DiscoverySource)


async def test_enumerates_two_pages(small_pages):
    # page_size=3: page1 full, page2 short -> all five returned, page 3 never fetched
    seen: list[str] = []
    t = _transport({1: [1, 2, 3], 2: [4, 5], 3: [99]}, seen=seen)
    got = await ModApiHarvestSource(PEER, transport=t).discover(limit=50)
    assert [c.canonical_iri for c in got] == [_iri(n) for n in (1, 2, 3, 4, 5)]
    assert not any("page=3" in u for u in seen)
    assert any("page_size=3" in u for u in seen)


async def test_full_page_then_empty_page_stops(small_pages):
    t = _transport({1: [1, 2, 3], 2: [4, 5, 6], 3: []})
    got = await ModApiHarvestSource(PEER, transport=t).discover(limit=50)
    assert len(got) == 6


async def test_resolves_distribution_download_url():
    got = await ModApiHarvestSource(PEER, transport=_transport({1: [1]})).discover(limit=5)
    assert len(got) == 1
    c = got[0]
    assert c.download_url == "https://files.example/ONT1.owl"
    assert c.ingest_target() == ("url", "https://files.example/ONT1.owl")
    assert c.source_catalogue_id == "testpeer"
    assert c.source_catalogue_label == "Test"
    assert c.title == "Ontology 1"
    assert c.license == "https://creativecommons.org/licenses/by/4.0/"
    assert c.landing_url


async def test_falls_back_to_iri_when_no_distribution():
    got = await ModApiHarvestSource(PEER, transport=_transport({1: [1]}, dists="404")).discover(
        limit=5
    )
    assert got[0].download_url is None
    assert got[0].ingest_target() == ("iri", _iri(1))


async def test_stops_at_limit():
    t = _transport({1: [1, 2, 3], 2: [4, 5, 6], 3: [7, 8, 9]})
    got = await ModApiHarvestSource(PEER, transport=t).discover(limit=3)
    assert [c.canonical_iri for c in got] == [_iri(1), _iri(2), _iri(3)]


async def test_dedups_repeated_iris_across_pages(small_pages):
    t = _transport({1: [1, 2, 3], 2: [3, 2, 4], 3: []})
    got = await ModApiHarvestSource(PEER, transport=t).discover(limit=50)
    assert [c.canonical_iri for c in got] == [_iri(n) for n in (1, 2, 3, 4)]


async def test_page_with_no_new_rows_stops(small_pages):
    # A peer that ignores `page` and always serves the same full page must not loop.
    t = _transport({n: [1, 2, 3] for n in range(1, 50)})
    got = await ModApiHarvestSource(PEER, transport=t).discover(limit=50)
    assert len(got) == 3


async def test_distribution_fetch_error_skips_download_not_candidate():
    t = _transport({1: [1, 2, 3]}, dists="mixed")
    got = await ModApiHarvestSource(PEER, transport=t).discover(limit=10)
    by_iri = {c.canonical_iri: c for c in got}
    assert set(by_iri) == {_iri(1), _iri(2), _iri(3)}
    assert by_iri[_iri(2)].download_url is None
    assert by_iri[_iri(2)].ingest_target() == ("iri", _iri(2))
    assert by_iri[_iri(1)].download_url == "https://files.example/ONT1.owl"
    assert by_iri[_iri(3)].download_url == "https://files.example/ONT3.owl"


async def test_rate_limiter_awaited_before_every_fetch():
    class Counter:
        n = 0

        async def wait(self) -> None:
            Counter.n += 1

    got = await ModApiHarvestSource(
        PEER, rate_limiter=Counter(), transport=_transport({1: [1, 2]})
    ).discover(limit=5)
    assert len(got) == 2
    assert Counter.n == 1 + 2  # one page fetch + two distribution fetches
