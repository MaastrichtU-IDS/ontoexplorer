"""Tests for the discovery Candidate model and DiscoverySource interface."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ontoexplorer.modules.discovery.models import Candidate
from ontoexplorer.modules.discovery.source import DiscoverySource


def _kwargs(**extra):
    base = {
        "canonical_iri": "http://example.org/onto",
        "title": "Example",
        "source_catalogue_id": "cat1",
        "source_catalogue_label": "Catalogue 1",
    }
    base.update(extra)
    return base


def test_candidate_ingest_target_prefers_download_url():
    c = Candidate(**_kwargs(download_url="http://example.org/onto.owl"))
    assert c.ingest_target() == ("url", "http://example.org/onto.owl")


def test_candidate_ingest_target_falls_back_to_iri():
    c = Candidate(**_kwargs())
    assert c.ingest_target() == ("iri", "http://example.org/onto")


def test_candidate_requires_iri_and_title():
    with pytest.raises(ValidationError):
        Candidate(title="x", source_catalogue_id="a", source_catalogue_label="b")
    with pytest.raises(ValidationError):
        Candidate(canonical_iri="http://x", source_catalogue_id="a", source_catalogue_label="b")


def test_candidate_optional_defaults():
    c = Candidate(**_kwargs())
    assert c.license is None
    assert c.download_url is None
    assert c.landing_url is None


def test_discovery_source_protocol_is_runtime_checkable():
    class Fake:
        name = "fake"

        async def discover(self, *, limit: int) -> list[Candidate]:
            return []

    assert isinstance(Fake(), DiscoverySource)
    assert not isinstance(object(), DiscoverySource)
