"""Unit coverage for the subscribable webhook event registry.

These run in CI (tests/unit); the webhook CRUD path has integration coverage in
tests/integration/test_webhooks.py.
"""

from ontoexplorer.modules.webhooks.registry import VALID_EVENTS


def test_update_available_is_subscribable():
    """`ontology.update_available` is broadcast by the poller (tasks.py), so it
    must be in VALID_EVENTS or create_webhook rejects any subscription to it and
    the broadcast reaches no one."""
    assert "ontology.update_available" in VALID_EVENTS


def test_core_events_present():
    expected = {
        "ontology.ingested",
        "ontology.update_available",
        "version.deprecated",
        "reasoning.completed",
        "reasoning.failed",
        "indexing.completed",
        "justification.completed",
        "justification.failed",
    }
    assert expected <= VALID_EVENTS
