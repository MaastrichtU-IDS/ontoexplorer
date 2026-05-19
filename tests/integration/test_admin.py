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


@pytest.mark.anyio
async def test_admin_versions_returns_all_versions_newest_first(client, user_and_key, monkeypatch, db_session):
    """GET /admin/ontologies/{id}/versions returns all versions, newest first."""
    from datetime import datetime, timezone, timedelta
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/av1.owl", shortname="av1")
    db_session.add(ont); await db_session.flush()
    now = datetime.now(timezone.utc)
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="av101", format="turtle", status="deprecated", triple_count=100, created_at=now - timedelta(seconds=10))
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="av102", format="turtle", status="ready", triple_count=200, created_at=now)
    db_session.add(v1); db_session.add(v2)
    await db_session.commit()

    with (
        patch("ontoexplorer.api.admin._search_redis", return_value=MagicMock(exists=lambda k: False)),
        patch("ontoexplorer.api.admin._reasoning_status", new=AsyncMock(return_value="not_started")),
    ):
        resp = await client.get(
            f"/api/v1/admin/ontologies/{ont.id}/versions",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ontology_id"] == ont.id
    versions = body["versions"]
    assert len(versions) == 2
    # Newest first
    assert versions[0]["version_id"] == v2.id
    assert versions[1]["version_id"] == v1.id
    # Newest is_latest
    assert versions[0]["is_latest"] is True
    assert versions[1]["is_latest"] is False
    # diff_vs_prev shape on the oldest version: previous_version_id is None
    assert versions[1]["diff_vs_prev"]["previous_version_id"] is None
    assert versions[1]["diff_vs_prev"]["status"] == "missing"
    # diff_vs_prev on the newer version: previous_version_id == v1.id
    assert versions[0]["diff_vs_prev"]["previous_version_id"] == v1.id


@pytest.mark.anyio
async def test_admin_versions_404_for_unknown_ontology(client, user_and_key, monkeypatch):
    """Unknown ontology_id → 404."""
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key
    resp = await client.get(
        "/api/v1/admin/ontologies/nonexistent-id/versions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_admin_versions_requires_admin(client, user_and_key, db_session):
    """Non-admin → 403."""
    from ontoexplorer.models.db import Ontology
    _, raw_key = user_and_key
    ont = Ontology(iri="http://example.org/av2.owl")
    db_session.add(ont); await db_session.commit()

    resp = await client.get(
        f"/api/v1/admin/ontologies/{ont.id}/versions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_version_action_index_queues_task(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/va-idx.owl")
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="vai01", format="turtle", status="ready")
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-idx-1")
    with patch("ontoexplorer.modules.jobs.tasks.index_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/index",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "task_id": "task-idx-1"}
    m.assert_called_once_with(version_id=v.id, ontology_id=ont.id)


@pytest.mark.anyio
async def test_admin_version_action_embed_queues_task(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/va-emb.owl")
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="vae01", format="turtle", status="ready")
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-emb-1")
    with patch("ontoexplorer.modules.jobs.tasks.embed_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/embed",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "task_id": "task-emb-1"}
    m.assert_called_once_with(version_id=v.id, ontology_id=ont.id)


@pytest.mark.anyio
async def test_admin_version_action_reason_queues_task(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/va-rsn.owl")
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="var01", format="turtle", status="ready")
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-rsn-1")
    with patch("ontoexplorer.modules.jobs.tasks.reason_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/reason",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "task_id": "task-rsn-1"}
    m.assert_called_once_with(version_id=v.id)


@pytest.mark.anyio
async def test_admin_version_action_404_for_unknown_version(client, user_and_key, monkeypatch):
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key
    resp = await client.post(
        "/api/v1/admin/versions/no-such-vid/index",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_admin_version_action_ingest_uses_source_url(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/va-ing.owl", owner_id=None)
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(
        ontology_id=ont.id, minio_key="k", sha256="vain01", format="turtle",
        status="ready", source_url="https://example.org/ont.ttl",
    )
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-ing-1")
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/ingest",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert resp.json()["method"] == "url"
    m.assert_called_once()
    kwargs = m.call_args.kwargs
    assert kwargs["url"] == "https://example.org/ont.ttl"
    assert kwargs["iri"] is None


@pytest.mark.anyio
async def test_admin_version_action_ingest_falls_back_to_iri(client, user_and_key, monkeypatch, db_session):
    """No source_url → falls back to ontology IRI with content negotiation."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/has-iri.owl", owner_id=None)
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="vain02", format="turtle", status="ready", source_url=None)
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-ing-2")
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/ingest",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 200
    assert resp.json()["method"] == "iri"
    kwargs = m.call_args.kwargs
    assert kwargs["iri"] == "http://example.org/has-iri.owl"
    assert kwargs["url"] is None


@pytest.mark.anyio
async def test_admin_version_action_ingest_422_when_no_source(client, user_and_key, monkeypatch, db_session):
    """No source_url and no IRI on the parent → 422."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="", owner_id=None)  # blank IRI
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="vain03", format="turtle", status="ready", source_url=None)
    db_session.add(v); await db_session.commit()

    resp = await client.post(
        f"/api/v1/admin/versions/{v.id}/ingest",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_admin_queue_diff_dispatches_compute_diff(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/dq.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dq01", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dq02", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.commit()

    mock_task = MagicMock(id="task-diff-1")
    with patch("ontoexplorer.modules.jobs.tasks.compute_diff.delay", return_value=mock_task) as m:
        resp = await client.post(
            "/api/v1/admin/diffs/queue",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"from_version_id": v1.id, "to_version_id": v2.id},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert resp.json()["task_id"] == "task-diff-1"
    m.assert_called_once_with(v1.id, v2.id, ont.id)


@pytest.mark.anyio
async def test_admin_queue_diff_422_when_versions_belong_to_different_ontologies(
    client, user_and_key, monkeypatch, db_session
):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    o1 = Ontology(iri="http://example.org/dq-a.owl")
    o2 = Ontology(iri="http://example.org/dq-b.owl")
    db_session.add(o1); db_session.add(o2); await db_session.flush()
    v1 = OntologyVersion(ontology_id=o1.id, minio_key="k", sha256="dqx1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=o2.id, minio_key="k", sha256="dqx2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.commit()

    resp = await client.post(
        "/api/v1/admin/diffs/queue",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"from_version_id": v1.id, "to_version_id": v2.id},
    )
    assert resp.status_code == 422
    assert "different ontologies" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_admin_recompute_all_diffs_queues_consecutive_pairs(
    client, user_and_key, monkeypatch, db_session
):
    """Three versions → two consecutive pairs queued."""
    from datetime import datetime, timedelta, timezone
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/rcad.owl")
    db_session.add(ont); await db_session.flush()
    now = datetime.now(timezone.utc)
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="rcad01", format="turtle", status="ready", created_at=now - timedelta(seconds=20))
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="rcad02", format="turtle", status="ready", created_at=now - timedelta(seconds=10))
    v3 = OntologyVersion(ontology_id=ont.id, minio_key="k3", sha256="rcad03", format="turtle", status="ready", created_at=now)
    db_session.add(v1); db_session.add(v2); db_session.add(v3); await db_session.commit()

    calls = []
    with patch(
        "ontoexplorer.modules.jobs.tasks.compute_diff.delay",
        side_effect=lambda *a, **kw: calls.append((a, kw)) or MagicMock(id="t"),
    ):
        resp = await client.post(
            f"/api/v1/admin/ontologies/{ont.id}/diffs/recompute-all",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    assert resp.json()["queued"] == 2
    # Pairs are (oldest→middle) and (middle→newest)
    assert calls[0][0] == (v1.id, v2.id, ont.id)
    assert calls[1][0] == (v2.id, v3.id, ont.id)


@pytest.mark.anyio
async def test_admin_recompute_all_diffs_single_version_returns_zero(
    client, user_and_key, monkeypatch, db_session
):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/rcad-one.owl")
    db_session.add(ont); await db_session.flush()
    db_session.add(OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="rcad11", format="turtle", status="ready"))
    await db_session.commit()

    with patch("ontoexplorer.modules.jobs.tasks.compute_diff.delay") as m:
        resp = await client.post(
            f"/api/v1/admin/ontologies/{ont.id}/diffs/recompute-all",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 200
    assert resp.json()["queued"] == 0
    m.assert_not_called()
