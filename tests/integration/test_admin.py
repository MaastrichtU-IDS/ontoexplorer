"""Tests for the admin overview endpoint."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.anyio
async def test_admin_overview_requires_admin(client):
    """Request without admin privileges returns 403 (or 401 if auth is enforced)."""
    resp = await client.get("/api/v1/admin/overview")
    assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_admin_overview_requires_admin_email(client, user_and_key):
    """Authenticated non-admin user returns 403."""
    _, raw_key = user_and_key
    resp = await client.get(
        "/api/v1/admin/overview",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_overview_returns_shape(client, user_and_key, monkeypatch):
    """Admin user gets a response with services/ontologies/jobs keys."""
    user, raw_key = user_and_key

    # Make the user an admin by patching is_admin
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)

    # Patch all external I/O
    with (
        patch("ontoexplorer.api.admin._check_postgres", new=AsyncMock(return_value="ok")),
        patch("ontoexplorer.api.admin._check_redis", return_value="ok"),
        patch("ontoexplorer.api.admin._check_minio", new=AsyncMock(return_value="ok")),
        patch("ontoexplorer.api.admin._check_elk", new=AsyncMock(return_value="ok")),
        patch("ontoexplorer.api.admin._celery_queue_depth", return_value=0),
        patch("ontoexplorer.api.admin._search_redis", return_value=MagicMock(exists=lambda k: False)),
        patch("ontoexplorer.api.admin._elk_redis", return_value=MagicMock(exists=lambda k: False)),
        patch("ontoexplorer.api.admin._reasoning_status", new=AsyncMock(return_value="not_started")),
    ):
        resp = await client.get(
            "/api/v1/admin/overview",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "services" in body
    assert "ontologies" in body
    assert "jobs" in body
    assert "postgres" in body["services"]
    assert "celery_queue_depth" in body["services"]


@pytest.mark.anyio
async def test_is_admin_helper_empty_config():
    """is_admin returns False when ADMIN_EMAILS is empty."""
    from ontoexplorer.config import is_admin

    user = MagicMock()
    user.email = "anyone@example.com"

    with patch("ontoexplorer.config.get_settings") as mock_settings:
        mock_settings.return_value.admin_emails = ""
        assert is_admin(user) is False


@pytest.mark.anyio
async def test_is_admin_helper_matching_email():
    """is_admin returns True when user email is in ADMIN_EMAILS."""
    from ontoexplorer.config import is_admin

    user = MagicMock()
    user.email = "michel@maastrichtuniversity.nl"

    with patch("ontoexplorer.config.get_settings") as mock_settings:
        mock_settings.return_value.admin_emails = "michel@maastrichtuniversity.nl,other@example.com"
        assert is_admin(user) is True


@pytest.mark.anyio
async def test_auth_me_includes_is_admin(client, user_and_key):
    """GET /auth/me returns is_admin field."""
    _, raw_key = user_and_key
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    assert "is_admin" in resp.json()
    assert isinstance(resp.json()["is_admin"], bool)


@pytest.mark.anyio
async def test_diff_status_for_pair_missing(db_session):
    """No OntologyDiff row → status='missing'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion

    ont = Ontology(iri="http://example.org/ds-missing.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsm1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsm2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2)
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "missing"
    assert result["diff_id"] is None
    assert result["computed_at"] is None


@pytest.mark.anyio
async def test_diff_status_for_pair_ready(db_session):
    """Ready diff with inferred_status ready on both sides → 'ready'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff

    ont = Ontology(iri="http://example.org/ds-ready.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsr1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsr2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    diff = OntologyDiff(
        ontology_id=ont.id, version_from_id=v1.id, version_to_id=v2.id,
        status="ready",
        summary={"inferred_status": {"from_version": "ready", "to_version": "ready"}},
    )
    db_session.add(diff)
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "ready"
    assert result["diff_id"] == diff.id


@pytest.mark.anyio
async def test_diff_status_for_pair_pending(db_session):
    """OntologyDiff.status='pending' → 'pending'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff

    ont = Ontology(iri="http://example.org/ds-pending.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsp1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsp2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    db_session.add(OntologyDiff(
        ontology_id=ont.id, version_from_id=v1.id, version_to_id=v2.id,
        status="pending", summary=None,
    ))
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "pending"


@pytest.mark.anyio
async def test_diff_status_for_pair_failed(db_session):
    """OntologyDiff.status='failed' → 'failed'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff

    ont = Ontology(iri="http://example.org/ds-failed.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsf1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsf2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    db_session.add(OntologyDiff(
        ontology_id=ont.id, version_from_id=v1.id, version_to_id=v2.id,
        status="failed", summary=None,
    ))
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "failed"


@pytest.mark.anyio
async def test_diff_status_for_pair_stale_when_inferred_missing(db_session):
    """Ready diff with inferred_status='missing' for a side whose reason job is 'done' → 'stale'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff, Job

    ont = Ontology(iri="http://example.org/ds-stale.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsst1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsst2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    db_session.add(OntologyDiff(
        ontology_id=ont.id, version_from_id=v1.id, version_to_id=v2.id,
        status="ready",
        summary={"inferred_status": {"from_version": "missing", "to_version": "ready"}},
    ))
    # Now reasoning for v1 has actually completed but the diff hasn't been refreshed yet.
    db_session.add(Job(version_id=v1.id, type="reason", status="done"))
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "stale"
