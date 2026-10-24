"""Platform email — SMTP-based, best-effort.

With no ``SMTP_HOST`` configured (the dev/test default) messages are LOGGED, not
sent, so nothing leaves the cluster. Production sets the SMTP creds and mail goes
out from ``EMAIL_FROM`` (info-ids@maastrichtuniversity.nl). Every send is
best-effort: a mail failure is logged and swallowed, never raised into the caller
(a notification must not break the request/approval it accompanies).
"""
from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as _MIMEMessage

import structlog

from ontoexplorer.config import get_settings

log = structlog.get_logger(__name__)


@dataclass
class Email:
    to: list[str]
    subject: str
    body: str


def admin_recipients() -> list[str]:
    """The ADMIN_EMAILS allowlist — who receives maintainer-request notifications."""
    return [e.strip() for e in get_settings().admin_emails.split(",") if e.strip()]


def _header_safe(text: str, *, max_len: int = 150) -> str:
    """Collapse whitespace (incl. CR/LF) and cap length for use in a Subject.
    A raw newline in a user-controlled title would make EmailMessage reject the
    header, and send_email would silently swallow it — so the mail never goes out."""
    return " ".join(text.split())[:max_len]


def _send_sync(msg: Email) -> None:
    s = get_settings()
    recipients = [r for r in msg.to if r]
    if not recipients:
        return
    if not s.smtp_host:
        # Dev/test: no transport configured → log, don't send.
        log.info("email_logged_not_sent", to=recipients, subject=msg.subject)
        return
    em = _MIMEMessage()
    em["From"] = s.email_from
    em["To"] = ", ".join(recipients)
    em["Subject"] = msg.subject
    em.set_content(msg.body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        if s.smtp_use_tls:
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(em)
    log.info("email_sent", to=recipients, subject=msg.subject)


async def send_email(msg: Email) -> None:
    """Best-effort async send — runs SMTP off the event loop and never raises."""
    try:
        await asyncio.to_thread(_send_sync, msg)
    except Exception as exc:  # noqa: BLE001 — a notification must not break its caller
        log.warning("email_send_failed", to=msg.to, subject=msg.subject, error=str(exc))


# ── Maintainer-request notifications ─────────────────────────────────────────────

async def notify_admins_new_request(
    *, requester_email: str | None, requester_name: str | None,
    request_type: str, ontology: str | None, note: str | None,
) -> None:
    """Email the admin allowlist that a maintainer request was filed."""
    admins = admin_recipients()
    if not admins:
        log.info("maintainer_request_no_admins_to_notify", request_type=request_type)
        return
    target = f"ontology '{ontology}'" if ontology else "global upload access"
    who = requester_name or requester_email or "A user"
    lines = [
        f"{who} requested {target}.",
        "",
        f"Requester: {requester_email or '(unknown)'}",
        f"Type: {request_type}",
    ]
    if ontology:
        lines.append(f"Ontology: {ontology}")
    lines += [f"Note: {note or '(none)'}", "",
              f"Review: {get_settings().frontend_url.rstrip('/')}/admin"]
    await send_email(Email(to=admins, subject=f"[OntoExplorer] Maintainer request: {request_type}",
                           body="\n".join(lines)))


# ── Quality-gate hold notification (#364 Add-Ontology) ───────────────────────────

async def notify_owner_version_held(
    *, owner_email: str | None, owner_name: str | None,
    ontology_label: str, reasons: list[str],
) -> None:
    """Email a contributor that their uploaded version was held by the quality gate
    (status needs_review) and needs their attention before it publishes. Best-effort
    and never raised into the ingest task; a no-op when the owner has no email."""
    if not owner_email:
        log.info("version_held_no_owner_email", ontology=ontology_label)
        return
    who = owner_name or "there"
    # Title is contributor-controlled; sanitize before it reaches the Subject header.
    label = _header_safe(ontology_label)
    bullets = "\n".join(f"  • {r}" for r in reasons) or "  • (see the dashboard)"
    dash = get_settings().frontend_url.rstrip("/") + "/dashboard"
    lines = [
        f"Hi {who},",
        "",
        f"An ontology you own, “{label}”, was received but needs a quick fix "
        "before it can be published:",
        "",
        bullets,
        "",
        "Open your dashboard to resolve it (assert a license, add a title) and "
        "publish — no re-upload needed in most cases:",
        dash,
    ]
    await send_email(Email(
        to=[owner_email],
        subject=f"[OntoExplorer] Action needed: “{label}” is held for review",
        body="\n".join(lines),
    ))


async def notify_requester_decision(
    *, requester_email: str | None, request_type: str, ontology: str | None,
    approved: bool, note: str | None,
) -> None:
    """Email the requester the approve/deny outcome of their maintainer request."""
    if not requester_email:
        return
    decision = "approved" if approved else "declined"
    target = f"ontology '{ontology}'" if ontology else "upload access"
    lines = [f"Your request for {target} was {decision}."]
    if note:
        lines += ["", f"Note from the reviewer: {note}"]
    lines += ["", get_settings().frontend_url.rstrip("/") + "/"]
    await send_email(Email(to=[requester_email],
                           subject=f"[OntoExplorer] Your maintainer request was {decision}",
                           body="\n".join(lines)))
