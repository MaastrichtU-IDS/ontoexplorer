"""POST /ontologies ``declared_license`` overlay for automated ingests (#364 Phase 3).

The API counterpart of the dashboard fix panel: an automated/backfill submitter may
assert a license at submit time instead of fixing a held version afterwards. The
value is canonicalized to SPDX, validated against the accepted allowlist (**422** if
it is not accepted, so automation fails fast instead of silently landing in review),
and forwarded to the ingest task, which stores it on the version. The gate then uses
it only to fill a content-license ABSENCE — it never launders a license the content
itself declares; that anti-laundering invariant is covered by ``effective_license``'s
own unit tests (``test_license_compliance.py``), so these tests cover the API edge:
canonicalization, validation, and faithful hand-off to the task.
"""
from unittest.mock import MagicMock, patch

import pytest


def _auth(raw):
    return {"Authorization": f"Bearer {raw}"}


async def _as_uploader(db, user):
    """Submit is gated by require_uploader; grant the fixture user the global
    upload right so these tests exercise the endpoint, not the gate."""
    user.is_uploader = True
    db.add(user)
    await db.commit()


def _mock_task():
    """A stand-in for the ingest Celery task whose .delay returns a job-id holder,
    so the endpoint never runs the real pipeline."""
    task = MagicMock()
    task.delay = MagicMock(return_value=MagicMock(id="task-xyz"))
    return task


@pytest.mark.anyio
async def test_free_text_license_is_canonicalized_before_handoff(client, user_and_key, db_session):
    user, raw = user_and_key
    await _as_uploader(db_session, user)
    task = _mock_task()
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", task):
        resp = await client.post(
            "/api/v1/ontologies",
            json={"iri": "http://example.org/o", "declared_license": "CC BY 4.0"},
            headers=_auth(raw),
        )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "task-xyz"
    # The free-text label reaches the task as a canonical SPDX id, not verbatim.
    assert task.delay.call_args.kwargs["declared_license"] == "CC-BY-4.0"


@pytest.mark.anyio
async def test_spdx_license_passes_through(client, user_and_key, db_session):
    user, raw = user_and_key
    await _as_uploader(db_session, user)
    task = _mock_task()
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", task):
        resp = await client.post(
            "/api/v1/ontologies",
            json={"url": "http://example.org/o.ttl", "declared_license": "MIT"},
            headers=_auth(raw),
        )
    assert resp.status_code == 200
    assert task.delay.call_args.kwargs["declared_license"] == "MIT"


@pytest.mark.anyio
async def test_noncompliant_license_is_rejected_before_enqueue(client, user_and_key, db_session):
    # A NonCommercial license is not on the default allowlist. Automation gets an
    # immediate 422 instead of a submission that silently lands in needs_review.
    user, raw = user_and_key
    await _as_uploader(db_session, user)
    task = _mock_task()
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", task):
        resp = await client.post(
            "/api/v1/ontologies",
            json={"iri": "http://example.org/o", "declared_license": "CC-BY-NC-4.0"},
            headers=_auth(raw),
        )
    assert resp.status_code == 422
    task.delay.assert_not_called()


@pytest.mark.anyio
async def test_unrecognized_license_is_rejected(client, user_and_key, db_session):
    user, raw = user_and_key
    await _as_uploader(db_session, user)
    task = _mock_task()
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", task):
        resp = await client.post(
            "/api/v1/ontologies",
            json={"iri": "http://example.org/o", "declared_license": "All rights reserved"},
            headers=_auth(raw),
        )
    assert resp.status_code == 422
    task.delay.assert_not_called()


@pytest.mark.anyio
async def test_absent_license_forwards_none_unchanged(client, user_and_key, db_session):
    # Back-compat: a submission that asserts nothing enqueues declared_license=None,
    # leaving the version's overlay empty (the gate judges the content as before).
    user, raw = user_and_key
    await _as_uploader(db_session, user)
    task = _mock_task()
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", task):
        resp = await client.post(
            "/api/v1/ontologies",
            json={"iri": "http://example.org/o"},
            headers=_auth(raw),
        )
    assert resp.status_code == 200
    assert task.delay.call_args.kwargs["declared_license"] is None


@pytest.mark.anyio
async def test_blank_license_is_treated_as_absent(client, user_and_key, db_session):
    # A whitespace-only value is an absence, not a rejection (parity with the overlay
    # treating "   " as no assertion).
    user, raw = user_and_key
    await _as_uploader(db_session, user)
    task = _mock_task()
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", task):
        resp = await client.post(
            "/api/v1/ontologies",
            json={"iri": "http://example.org/o", "declared_license": "   "},
            headers=_auth(raw),
        )
    assert resp.status_code == 200
    assert task.delay.call_args.kwargs["declared_license"] is None
