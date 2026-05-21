from pathlib import Path
from unittest.mock import patch

import pytest

from ontoexplorer.modules.consistency.mireot_source_resolver import (
    MireotSourceResolveResult,
    fetch_mireot_sources,
)


def test_resolves_known_prefix_to_canonical_iri(tmp_path):
    """Given a Phase 1 reuse cache with a MIREOT'd prefix, derive the source IRI."""
    fake_reuse = {
        "mireot_terms": [
            {"iri": "http://purl.obolibrary.org/obo/IAO_0000115",
             "source_prefix": "iao", "has_imported_from": True},
            {"iri": "http://purl.obolibrary.org/obo/IAO_0000118",
             "source_prefix": "iao", "has_imported_from": False},
        ],
        "imports": [],
    }
    # Mock the actual fetch — we test the dedup + IRI-derivation logic, not the network
    fetched_path = tmp_path / "iao.nt"
    fetched_path.write_text(
        "<http://purl.obolibrary.org/obo/IAO_0000115> "
        "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
        "<http://www.w3.org/2002/07/owl#AnnotationProperty> .\n"
    )
    with patch("ontoexplorer.modules.consistency.mireot_source_resolver._fetch_and_convert_to_nt",
               return_value=fetched_path):
        result = fetch_mireot_sources(reuse_payload=fake_reuse, out_dir=tmp_path)
    assert isinstance(result, MireotSourceResolveResult)
    assert "iao" in result.fetched
    assert "iao" not in result.skipped
    # IAO appears twice in mireot_terms but is fetched once (dedup'd)
    assert len(result.fetched) == 1


def test_skips_imported_prefixes(tmp_path):
    """If a MIREOT'd term's source IS in the imports closure, don't re-fetch it."""
    fake_reuse = {
        "mireot_terms": [
            {"iri": "http://purl.obolibrary.org/obo/IAO_0000115",
             "source_prefix": "iao", "has_imported_from": True},
        ],
        "imports": [
            {"target_iri": "http://purl.obolibrary.org/obo/iao.owl",
             "target_prefix": "iao", "depth": 1, "resolved": True},
        ],
    }
    result = fetch_mireot_sources(reuse_payload=fake_reuse, out_dir=tmp_path)
    # iao is already imported, so no fetch was needed
    assert "iao" not in result.fetched
    assert "iao" not in result.skipped


def test_unreachable_source_recorded_in_skipped(tmp_path):
    """When fetch fails, prefix moves to `skipped` not `fetched`."""
    fake_reuse = {
        "mireot_terms": [
            {"iri": "http://example.org/obscure/Foo_001",
             "source_prefix": "obscure", "has_imported_from": False},
        ],
        "imports": [],
    }
    with patch("ontoexplorer.modules.consistency.mireot_source_resolver._fetch_and_convert_to_nt",
               side_effect=RuntimeError("network unreachable")):
        result = fetch_mireot_sources(reuse_payload=fake_reuse, out_dir=tmp_path)
    assert "obscure" in result.skipped
    assert "obscure" not in result.fetched
