"""Tests for the gated harvest runner and the harvest_peer Celery task."""

from __future__ import annotations

import pytest

from ontoexplorer.modules.discovery import gate
from ontoexplorer.modules.discovery.models import Candidate
from ontoexplorer.modules.discovery.runner import HarvestReport, run_harvest
from ontoexplorer.modules.discovery.throttle import RunBudget
from ontoexplorer.modules.federation.client import FederationFetchError
from ontoexplorer.modules.jobs import tasks

_PEER = "agroportal"
_GROUPS = ["mod-harvest", _PEER]
_ALLOWLIST = {"CC-BY-4.0", "CC0-1.0"}


def _cand(iri: str, **extra) -> Candidate:
    base = {
        "canonical_iri": iri,
        "title": f"Title {iri}",
        "source_catalogue_id": _PEER,
        "source_catalogue_label": "AgroPortal",
    }
    base.update(extra)
    return Candidate(**base)


class _FakeSource:
    name = "fake"

    def __init__(self, candidates):
        self._candidates = candidates
        self.limits: list[int] = []

    async def discover(self, *, limit: int):
        self.limits.append(limit)
        return list(self._candidates)


class _FailingSource:
    name = "failing"

    async def discover(self, *, limit: int):
        raise FederationFetchError("timeout")


@pytest.fixture
def delay_calls(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(tasks.ingest_ontology, "delay", lambda **kw: calls.append(kw))
    return calls


@pytest.fixture(autouse=True)
def _gate_env(monkeypatch):
    """No known IRIs by default; fixed allowlist (the real gate runs, no DB)."""
    known: set[str] = set()

    async def _find(db, iri, *, exclude_id=None):
        return object() if iri in known else None

    monkeypatch.setattr(gate, "find_ontology_by_canonical_iri", _find)
    monkeypatch.setattr(gate, "compliant_license_set", lambda: set(_ALLOWLIST))
    return known


async def _run(source, *, budget=5, dry_run=True) -> HarvestReport:
    return await run_harvest(
        None, source, budget=RunBudget(budget), dry_run=dry_run,
        source_catalogue=_PEER, groups=_GROUPS,
    )


async def test_dry_run_enqueues_nothing(delay_calls):
    src = _FakeSource([
        _cand("http://ex.org/a", download_url="http://ex.org/a.owl"),
        _cand("http://ex.org/b"),
        _cand("urn:bad"),
    ])
    report = await _run(src, dry_run=True)
    assert report.dry_run is True
    assert report.enqueued == 0
    assert delay_calls == []
    assert (report.seen, report.admitted) == (3, 2)
    assert report.rejected == {"bad_iri": 1}


async def test_live_run_enqueues_admitted_with_provenance(delay_calls):
    src = _FakeSource([
        _cand("http://ex.org/a", download_url="http://ex.org/a.owl", acronym="CO_320"),
        _cand("http://ex.org/b"),
    ])
    report = await _run(src, dry_run=False)
    assert (report.seen, report.admitted, report.enqueued) == (2, 2, 2)
    # The catalogue acronym is threaded into the ingest enqueue (None when absent).
    assert delay_calls == [
        {"url": "http://ex.org/a.owl", "groups": _GROUPS,
         "source_catalogue": _PEER, "source_acronym": "CO_320"},
        {"iri": "http://ex.org/b", "groups": _GROUPS,
         "source_catalogue": _PEER, "source_acronym": None},
    ]
    assert report.as_dict() == {
        "source": "fake", "seen": 2, "admitted": 2, "enqueued": 2,
        "rejected": {}, "errors": [], "dry_run": False,
    }


async def test_rejected_tallied_by_reason(delay_calls, _gate_env):
    _gate_env.add("http://ex.org/dupe")
    src = _FakeSource([
        _cand("http://ex.org/dupe"),
        _cand("http://ex.org/nc", license="http://creativecommons.org/licenses/by-nc/4.0/"),
    ])
    report = await _run(src, dry_run=False)
    assert report.rejected == {"duplicate": 1, "license_noncompliant": 1}
    assert (report.seen, report.admitted, report.enqueued) == (2, 0, 0)
    assert delay_calls == []


async def test_budget_caps_enqueue(delay_calls):
    src = _FakeSource([_cand("http://ex.org/a"), _cand("http://ex.org/b")])
    report = await _run(src, budget=1, dry_run=False)
    assert report.enqueued == 1
    assert len(delay_calls) == 1
    assert src.limits == [1]


async def test_discover_error_recorded(delay_calls):
    report = await _run(_FailingSource(), dry_run=False)
    assert report.errors == ["discover_failed: timeout"]
    assert (report.seen, report.admitted, report.enqueued) == (0, 0, 0)
    assert delay_calls == []


# --- harvest_peer short-circuits -------------------------------------------------


class _Settings:
    def __init__(self, enabled: bool, peer_id: str = ""):
        self.harvest_enabled = enabled
        self.harvest_peer_id = peer_id
        self.harvest_max_candidates = 50
        self.harvest_min_interval_ms = 0


def test_harvest_peer_disabled(monkeypatch, delay_calls):
    monkeypatch.setattr(tasks, "get_settings", lambda: _Settings(False))
    assert tasks.harvest_peer() == {"status": "disabled"}
    assert delay_calls == []


def test_harvest_peer_unknown_peer(monkeypatch, delay_calls):
    monkeypatch.setattr(tasks, "get_settings", lambda: _Settings(True, "nope"))
    monkeypatch.setattr(
        "ontoexplorer.modules.federation.config.get_federation_peers", lambda: []
    )
    assert tasks.harvest_peer() == {"status": "unknown_peer", "peer_id": "nope"}
    assert tasks.harvest_peer(peer_id="other") == {"status": "unknown_peer", "peer_id": "other"}
    assert delay_calls == []
