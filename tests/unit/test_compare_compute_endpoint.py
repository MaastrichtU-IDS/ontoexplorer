"""Regression tests for POST /api/v1/compare/compute.

The endpoint inserts a pending `ontology_comparisons` row BEFORE dispatching the
Celery task. That table's `from_ontology_id` / `to_ontology_id` columns are NOT
NULL with no default, so the row MUST set them. A previous version omitted them:
the insert raised IntegrityError, a bare `except` swallowed it and returned early
— so no row was created AND the task was never dispatched, leaving the comparison
stuck at 404 forever (the UI showed "no results"). These tests lock that down.
"""
import hashlib
import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import Ontology, OntologyComparison, OntologyVersion
from ontoexplorer.modules.jobs import tasks

pytestmark = pytest.mark.anyio


async def _seed_version(db_session) -> tuple[str, str]:
    """Insert an ontology + one ready version; return (ontology_id, version_id)."""
    oid = str(uuid.uuid4())
    vid = str(uuid.uuid4())
    db_session.add(Ontology(id=oid, iri=f"http://ex/{uuid.uuid4()}",
                            shortname=f"o{uuid.uuid4().hex[:8]}"))
    await db_session.commit()
    db_session.add(OntologyVersion(id=vid, ontology_id=oid,
                                   minio_key=f"{oid}/v/x.ttl",
                                   sha256=hashlib.sha256(vid.encode()).hexdigest(),
                                   format="ttl", status="ready"))
    await db_session.commit()
    return oid, vid


async def test_compute_creates_row_and_dispatches(client, db_session, monkeypatch):
    """A fresh pair inserts a pending row WITH both ontology ids and dispatches."""
    from_oid, from_vid = await _seed_version(db_session)
    to_oid, to_vid = await _seed_version(db_session)

    dispatched: list[tuple] = []
    monkeypatch.setattr(tasks.compute_ontology_comparison, "delay",
                        lambda *a: dispatched.append(a), raising=False)

    r = await client.post(
        f"/api/v1/compare/compute?from_version_id={from_vid}&to_version_id={to_vid}"
    )
    assert r.status_code == 202
    assert r.json()["status"] == "pending"

    # The regression: the row must exist (insert didn't silently fail) …
    row = await db_session.scalar(
        select(OntologyComparison).where(
            OntologyComparison.version_from_id == from_vid,
            OntologyComparison.version_to_id == to_vid,
        )
    )
    assert row is not None, "pending comparison row was not inserted"
    assert row.from_ontology_id == from_oid
    assert row.to_ontology_id == to_oid
    assert row.status == "pending"
    # … and the task must have been dispatched (not skipped by an early return).
    assert dispatched == [(from_vid, to_vid)]


async def test_compute_then_get_is_not_404(client, db_session, monkeypatch):
    """After compute, GET returns the pending row rather than 404."""
    _, from_vid = await _seed_version(db_session)
    _, to_vid = await _seed_version(db_session)
    monkeypatch.setattr(tasks.compute_ontology_comparison, "delay",
                        lambda *a: None, raising=False)

    await client.post(
        f"/api/v1/compare/compute?from_version_id={from_vid}&to_version_id={to_vid}"
    )
    r = await client.get(
        f"/api/v1/compare?from_version_id={from_vid}&to_version_id={to_vid}"
    )
    # Pending row → 202 (not the 404 the old bug produced).
    assert r.status_code == 202
    assert r.json()["status"] == "pending"
