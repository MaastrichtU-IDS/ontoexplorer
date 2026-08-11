"""run_meta_detection must not clobber a user_confirmed meta profile on auto
re-detection (ingestion / admin reindex), but must when force=True (explicit
Re-detect). Regression for: unmapping a predicate silently reverted after a
reindex re-ran auto-detection.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ontoexplorer.modules.meta_profile import detector

_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"


def _patch_sparql(monkeypatch):
    # No triples in the (fake) header → auto-detection would derive empty props.
    monkeypatch.setattr(detector, "_fetch_onto_triples", lambda *a, **k: {})
    monkeypatch.setattr(detector, "_get_prop_labels", lambda *a, **k: {})
    monkeypatch.setattr(detector, "graph_iri", lambda *a, **k: "urn:g")


def _db_with_existing(existing):
    iri_res = MagicMock(); iri_res.scalar_one.return_value = "http://ex.org/onto"
    prof_res = MagicMock(); prof_res.scalar_one_or_none.return_value = existing
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[iri_res, prof_res])
    db.commit = AsyncMock()
    return db


def _confirmed_profile():
    return SimpleNamespace(
        version_id="v1", status="user_confirmed",
        description_props=[_COMMENT], resolved={"description": ["x"]}, candidates_data={},
    )


@pytest.mark.anyio
async def test_auto_redetect_preserves_user_confirmed(monkeypatch):
    _patch_sparql(monkeypatch)
    existing = _confirmed_profile()
    await detector.run_meta_detection(_db_with_existing(existing), "v1", ontology_id="o1")
    # Guard kept the user's mapping + confirmed status.
    assert existing.status == "user_confirmed"
    assert existing.description_props == [_COMMENT]


@pytest.mark.anyio
async def test_forced_redetect_overrides_user_confirmed(monkeypatch):
    _patch_sparql(monkeypatch)
    existing = _confirmed_profile()
    await detector.run_meta_detection(_db_with_existing(existing), "v1", ontology_id="o1", force=True)
    # Explicit Re-detect re-derives (empty header → comment dropped, back to auto).
    assert existing.status == "auto_detected"
    assert existing.description_props == []
