"""Integration tests for the Subsystem 2 reasoning API proxy endpoints."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All version-specific endpoints call _get_version_or_404 first; patch it to avoid 404.
_VERSION_MOCK = MagicMock()
_MOCK_VERSION = AsyncMock(return_value=_VERSION_MOCK)


@pytest.mark.anyio
async def test_superclasses_not_ready(client, user_and_key):
    """Returns 409 when reasoning not yet completed."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    from ontoexplorer.clients.reasoning import ReasoningNotReadyError

    with patch("ontoexplorer.api.ontologies._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.api.ontologies.elk_superclasses",
               new=AsyncMock(side_effect=ReasoningNotReadyError("v1"))):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/superclasses",
            params={"cls": "http://example.org/A"},
            headers=auth,
        )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_superclasses_class_not_found(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    from ontoexplorer.clients.reasoning import ClassNotFoundError

    with patch("ontoexplorer.api.ontologies._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.api.ontologies.elk_superclasses",
               new=AsyncMock(side_effect=ClassNotFoundError("http://example.org/Unknown"))):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/superclasses",
            params={"cls": "http://example.org/Unknown"},
            headers=auth,
        )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_superclasses_success(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    mock_result = {"class": "http://example.org/A",
                   "superclasses": ["http://example.org/B", "http://www.w3.org/2002/07/owl#Thing"],
                   "direct": False}

    with patch("ontoexplorer.api.ontologies._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.api.ontologies.elk_superclasses",
               new=AsyncMock(return_value=mock_result)):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/superclasses",
            params={"cls": "http://example.org/A"},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "http://example.org/B" in body["superclasses"]


@pytest.mark.anyio
async def test_justification_queues_job(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    mock_task = type("Task", (), {"id": "mock-task-id"})()

    with patch("ontoexplorer.api.ontologies._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.jobs.tasks.compute_justification") as mock_celery:
        mock_celery.delay.return_value = mock_task
        resp = await client.post(
            "/api/v1/ontologies/fake-oid/fake-vid/justification",
            json={"sub": "http://example.org/A", "sup": "http://example.org/C",
                  "max_justifications": 2},
            headers=auth,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "mock-task-id"
    assert body["status"] == "queued"


@pytest.mark.anyio
async def test_webhook_justification_events_valid(client, user_and_key):
    """justification.completed and justification.failed are valid webhook events."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    for event in ("justification.completed", "justification.failed"):
        resp = await client.post(
            "/api/v1/webhooks",
            json={"url": "http://example.com/hook", "events": [event]},
            headers=auth,
        )
        assert resp.status_code == 200, f"Event {event} rejected: {resp.json()}"
