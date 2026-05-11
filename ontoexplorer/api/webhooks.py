"""Webhook management API."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import User, Webhook, WebhookDelivery
from ontoexplorer.modules.auth.dependencies import require_auth
from ontoexplorer.modules.webhooks import delivery as delivery_mod
from ontoexplorer.modules.webhooks import registry

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str]
    secret: str | None = None


@router.post("", summary="Register a webhook")
async def create_webhook(
    body: WebhookCreate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        webhook = await registry.create_webhook(db, user.id, str(body.url), body.events, body.secret)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _webhook_dict(webhook)


@router.get("", summary="List registered webhooks")
async def list_webhooks(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    webhooks = await registry.list_webhooks(db, user.id)
    return {"webhooks": [_webhook_dict(w) for w in webhooks]}


@router.get("/{webhook_id}", summary="Webhook detail + delivery history")
async def get_webhook(webhook_id: str, user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    webhook = await _get_or_404(db, webhook_id, user.id)
    deliveries = await registry.list_deliveries(db, webhook_id)
    return {**_webhook_dict(webhook), "deliveries": [_delivery_dict(d) for d in deliveries]}


@router.get("/{webhook_id}/deliveries", summary="Delivery history for a webhook")
async def get_deliveries(webhook_id: str, user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, webhook_id, user.id)
    deliveries = await registry.list_deliveries(db, webhook_id)
    return {"deliveries": [_delivery_dict(d) for d in deliveries]}


@router.delete("/{webhook_id}", summary="Unregister webhook")
async def delete_webhook(webhook_id: str, user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    deleted = await registry.delete_webhook(db, webhook_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"detail": "Webhook deleted"}


@router.post("/{webhook_id}/test", summary="Send test event")
async def test_webhook(webhook_id: str, user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    webhook = await _get_or_404(db, webhook_id, user.id)
    d = await delivery_mod.deliver_webhook(db, webhook, "ping", {"test": True, "webhook_id": webhook_id})
    return {"delivery_id": d.id, "status": d.status, "http_status": d.http_status}


async def _get_or_404(db: AsyncSession, webhook_id: str, user_id: str) -> Webhook:
    webhook = await registry.get_webhook(db, webhook_id, user_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook


def _webhook_dict(w: Webhook) -> dict:
    return {
        "id": w.id,
        "url": w.url,
        "events": w.events,
        "active": w.active,
        "created_at": w.created_at.isoformat(),
    }


def _delivery_dict(d: WebhookDelivery) -> dict:
    return {
        "id": d.id,
        "event": d.event,
        "status": d.status,
        "attempts": d.attempts,
        "http_status": d.http_status,
        "last_attempt_at": d.last_attempt_at.isoformat() if d.last_attempt_at else None,
    }
