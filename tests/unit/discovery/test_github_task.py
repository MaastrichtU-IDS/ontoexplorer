"""Tests for the discover_github task guards, the csv split helper, and the
admin endpoint wiring. The enabled+token happy path needs a DB + GitHub and is
exercised by the dry-run on dev, not here."""

from __future__ import annotations

from ontoexplorer.api.admin import harvest as harvest_ep
from ontoexplorer.config import get_settings
from ontoexplorer.modules.jobs.tasks import _split_csv, discover_github


def test_split_csv():
    assert _split_csv("") == []
    assert _split_csv(None) == []
    assert _split_csv("a, b ,,c ") == ["a", "b", "c"]


def test_task_disabled_is_noop(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "github_discovery_enabled", False, raising=False)
    assert discover_github.apply(kwargs={"dry_run": True}).get() == {"status": "disabled"}


def test_task_enabled_without_token_is_noop(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "github_discovery_enabled", True, raising=False)
    monkeypatch.setattr(s, "github_api_token", "", raising=False)
    assert discover_github.apply(kwargs={"dry_run": True}).get() == {"status": "no_token"}


def test_endpoint_registered_and_dry_run_default():
    paths = {r.path for r in harvest_ep.router.routes}
    assert "/harvest/github" in paths
    body = harvest_ep.GithubHarvestRequest()
    assert body.dry_run is True
    assert body.limit is None
