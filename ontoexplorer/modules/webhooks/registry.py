"""Webhook CRUD operations."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Webhook, WebhookDelivery

VALID_EVENTS = frozenset({
    "ontology.ingested",
    "version.deprecated",
    "reasoning.completed",
    "reasoning.failed",
    "indexing.completed",
})


async def create_webhook(
    db: AsyncSession,
    user_id: str,
    url: str,
    events: list[str],
    secret: str | None,
) -> Webhook:
    invalid = set(events) - VALID_EVENTS
    if invalid:
        raise ValueError(f"Unknown event types: {invalid}. Valid: {sorted(VALID_EVENTS)}")

    webhook = Webhook(
        id=str(uuid.uuid4()),
        user_id=user_id,
        url=url,
        events=events,
        secret=secret,
        active=True,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return webhook


async def get_webhook(db: AsyncSession, webhook_id: str, user_id: str) -> Webhook | None:
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_webhooks(db: AsyncSession, user_id: str) -> list[Webhook]:
    result = await db.execute(
        select(Webhook).where(Webhook.user_id == user_id).order_by(Webhook.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_webhook(db: AsyncSession, webhook_id: str, user_id: str) -> bool:
    webhook = await get_webhook(db, webhook_id, user_id)
    if not webhook:
        return False
    await db.delete(webhook)
    await db.commit()
    return True


async def list_deliveries(db: AsyncSession, webhook_id: str, limit: int = 50) -> list[WebhookDelivery]:
    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
