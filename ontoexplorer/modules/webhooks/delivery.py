"""HMAC-SHA256 signed webhook delivery with Celery retry."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Ontology, OntologyMaintainer, Webhook, WebhookDelivery
from ontoexplorer.logging_config import get_logger
from ontoexplorer import metrics

log = get_logger(__name__)

_TIMEOUT = httpx.Timeout(10.0)
_MAX_ATTEMPTS = 5
_RETRY_DELAYS = [60, 300, 900, 3600, 7200]  # seconds between retries


def _sign_payload(secret: str, payload_bytes: bytes) -> str:
    """Return HMAC-SHA256 hex digest of payload, prefixed sha256=."""
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


async def deliver_webhook(
    db: AsyncSession,
    webhook: Webhook,
    event: str,
    payload: dict,
) -> WebhookDelivery:
    """
    Deliver a webhook synchronously and persist the delivery record.
    Returns the WebhookDelivery record regardless of success/failure.
    """
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        "Content-Type": "application/json",
        "X-OntoExplorer-Event": event,
        "X-OntoExplorer-Delivery": str(uuid.uuid4()),
    }
    if webhook.secret:
        headers["X-OntoExplorer-Signature"] = _sign_payload(webhook.secret, payload_bytes)

    delivery = WebhookDelivery(
        id=str(uuid.uuid4()),
        webhook_id=webhook.id,
        event=event,
        payload=json.dumps(payload),
        status="pending",
        attempts=0,
    )
    db.add(delivery)
    await db.flush()

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(webhook.url, content=payload_bytes, headers=headers)
        delivery.http_status = resp.status_code
        delivery.status = "delivered" if resp.is_success else "failed"
    except Exception as exc:
        log.warning("webhook_delivery_failed", url=webhook.url, error=str(exc))
        delivery.status = "failed"
        delivery.http_status = None

    delivery.attempts = 1
    delivery.last_attempt_at = datetime.now(UTC)
    metrics.webhook_deliveries_total.labels(status=delivery.status).inc()
    await db.commit()
    return delivery


async def _authorized_user_ids(db: AsyncSession, ontology_id: str) -> set[str]:
    """The users entitled to events about one ontology: its owner plus every
    approved maintainer (a row in ontology_maintainers is itself the grant)."""
    owner_id = (
        await db.execute(select(Ontology.owner_id).where(Ontology.id == ontology_id))
    ).scalar_one_or_none()
    maintainers = (
        await db.execute(
            select(OntologyMaintainer.user_id).where(OntologyMaintainer.ontology_id == ontology_id)
        )
    ).scalars().all()
    return {uid for uid in (owner_id, *maintainers) if uid}


async def broadcast_event(
    db: AsyncSession, event: str, payload: dict, *, ontology_id: str | None = None
) -> None:
    """Deliver an event to active webhooks subscribed to it.

    When ``ontology_id`` is given the event is **ontology-scoped**: it reaches only
    the webhooks of that ontology's owner and approved maintainers, so a webhook
    never fires for an ontology its owner doesn't own or maintain. With
    ``ontology_id=None`` the event is global and reaches every subscribed webhook;
    no current event uses that path.
    """
    stmt = select(Webhook).where(Webhook.active.is_(True))
    if ontology_id is not None:
        authorized = await _authorized_user_ids(db, ontology_id)
        if not authorized:
            return
        stmt = stmt.where(Webhook.user_id.in_(authorized))
    webhooks = (await db.execute(stmt)).scalars().all()
    for webhook in webhooks:
        if event in webhook.events:
            try:
                await deliver_webhook(db, webhook, event, payload)
            except Exception as exc:
                log.warning("broadcast_delivery_failed", event=event, webhook_id=webhook.id, error=str(exc))
