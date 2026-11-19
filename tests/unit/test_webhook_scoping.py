"""An ontology-scoped webhook event must reach only the ontology's owner and its
approved maintainers — never an unrelated subscriber (issue #445).

broadcast_event previously fanned every event out to all active webhooks that
listed it, so anyone subscribing to e.g. ontology.update_available received events
about ontologies they neither own nor maintain. These tests pin the scoped delivery.
"""
import uuid

import pytest

from ontoexplorer.models.db import Ontology, OntologyMaintainer, User, Webhook
from ontoexplorer.modules.webhooks import delivery


def _add_user(db) -> User:
    u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.com", display_name="u")
    db.add(u)
    return u


def _add_webhook(db, user_id: str, events=("ontology.update_available",)) -> Webhook:
    w = Webhook(id=str(uuid.uuid4()), user_id=user_id, url="https://example.com/hook", events=list(events))
    db.add(w)
    return w


@pytest.fixture()
def delivered_to(monkeypatch):
    """Capture which webhooks broadcast_event tried to deliver to, without any HTTP."""
    seen: list[str] = []

    async def fake_deliver(db, webhook, event, payload):
        seen.append(webhook.id)

    monkeypatch.setattr(delivery, "deliver_webhook", fake_deliver)
    return seen


@pytest.mark.anyio
async def test_scoped_event_reaches_only_owner_and_maintainers(db_session, delivered_to):
    owner, maintainer, stranger = _add_user(db_session), _add_user(db_session), _add_user(db_session)
    await db_session.flush()

    onto = Ontology(iri=f"https://ex.org/{uuid.uuid4()}", shortname=str(uuid.uuid4()), owner_id=owner.id)
    db_session.add(onto)
    await db_session.flush()
    db_session.add(OntologyMaintainer(id=str(uuid.uuid4()), user_id=maintainer.id, ontology_id=onto.id))

    w_owner = _add_webhook(db_session, owner.id)
    w_maint = _add_webhook(db_session, maintainer.id)
    w_stranger = _add_webhook(db_session, stranger.id)
    await db_session.flush()

    await delivery.broadcast_event(
        db_session, "ontology.update_available", {"ontology_id": onto.id}, ontology_id=onto.id
    )

    assert set(delivered_to) == {w_owner.id, w_maint.id}
    assert w_stranger.id not in delivered_to


@pytest.mark.anyio
async def test_subscriber_without_the_event_is_skipped(db_session, delivered_to):
    owner = _add_user(db_session)
    await db_session.flush()
    onto = Ontology(iri=f"https://ex.org/{uuid.uuid4()}", shortname=str(uuid.uuid4()), owner_id=owner.id)
    db_session.add(onto)
    # Owner is subscribed to a different event only — must not receive update_available.
    _add_webhook(db_session, owner.id, events=("ontology.ingested",))
    await db_session.flush()

    await delivery.broadcast_event(
        db_session, "ontology.update_available", {"ontology_id": onto.id}, ontology_id=onto.id
    )

    assert delivered_to == []


@pytest.mark.anyio
async def test_ownerless_ontology_with_no_maintainers_delivers_to_nobody(db_session, delivered_to):
    stranger = _add_user(db_session)
    await db_session.flush()
    onto = Ontology(iri=f"https://ex.org/{uuid.uuid4()}", shortname=str(uuid.uuid4()), owner_id=None)
    db_session.add(onto)
    _add_webhook(db_session, stranger.id)
    await db_session.flush()

    await delivery.broadcast_event(
        db_session, "ontology.update_available", {"ontology_id": onto.id}, ontology_id=onto.id
    )

    assert delivered_to == []


@pytest.mark.anyio
async def test_global_event_without_ontology_id_reaches_all_subscribers(db_session, delivered_to):
    a, b = _add_user(db_session), _add_user(db_session)
    await db_session.flush()
    wa = _add_webhook(db_session, a.id)
    wb = _add_webhook(db_session, b.id)
    await db_session.flush()

    # ontology_id=None -> global broadcast (no current event uses this, but the
    # path is preserved for a genuinely catalogue-wide event).
    await delivery.broadcast_event(db_session, "ontology.update_available", {"x": 1})

    assert {wa.id, wb.id} <= set(delivered_to)
