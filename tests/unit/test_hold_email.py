"""notify_owner_version_held — the quality-gate "held for review" contributor
email (#364 Phase 2). Best-effort: a missing address is a no-op, never a raise."""
import pytest

from ontoexplorer.modules.notifications import email as email_mod


@pytest.mark.anyio
async def test_sends_with_reasons(monkeypatch):
    sent = {}
    async def _capture(msg):
        sent["msg"] = msg
    monkeypatch.setattr(email_mod, "send_email", _capture)

    await email_mod.notify_owner_version_held(
        owner_email="owner@example.com", owner_name="Ada",
        ontology_label="My Ontology",
        reasons=["license missing or not on the platform compliance allowlist", "no title"],
    )
    msg = sent["msg"]
    assert msg.to == ["owner@example.com"]
    assert "My Ontology" in msg.subject
    assert "Ada" in msg.body
    assert "no title" in msg.body
    assert "/dashboard" in msg.body


@pytest.mark.anyio
async def test_no_email_is_noop(monkeypatch):
    called = False
    async def _capture(msg):
        nonlocal called
        called = True
    monkeypatch.setattr(email_mod, "send_email", _capture)

    await email_mod.notify_owner_version_held(
        owner_email=None, owner_name=None, ontology_label="X", reasons=["no title"],
    )
    assert called is False
