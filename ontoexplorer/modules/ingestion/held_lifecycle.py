"""Held-draft lifecycle (#364 Phase 3).

A version held by the quality gate (``needs_review``) that the contributor never
comes back to fix would otherwise sit in their attention queue forever. This sweep
— run daily by a beat task — does two things, both tunable (and each disabled when
its window is 0):

* **Nudge** once, when a version has been held at least ``nudge_days``: a single
  reminder email (``held_nudged_at`` records it so the reminder never re-fires).
* **Retire**, when held at least ``retire_days``: auto-deprecate it (status
  ``deprecated``) — reversibly. ``held_nudged_at`` is retained so the owner can
  *reactivate* the set-aside draft back to ``needs_review`` (distinguishing it from
  an ordinary deprecate).

The sweep mutates the versions and returns the email payloads to send; the caller
(the beat task) commits and sends them, so this stays unit-testable without SMTP.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Ontology, OntologyVersion, User


def _label(o: Ontology) -> str:
    return o.title or o.shortname or o.iri or "your ontology"


async def sweep_held_drafts(
    db: AsyncSession, *, nudge_days: int, retire_days: int, now: datetime | None = None,
) -> dict:
    """Nudge and/or retire stale held versions. Mutates the matching versions and
    returns ``{"nudged": [...], "retired": [...], "scanned": n}`` where each list
    holds the email payloads for the caller to send after commit."""
    now = now or datetime.now(timezone.utc)
    rows = (await db.execute(
        select(OntologyVersion, Ontology, User)
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        .outerjoin(User, User.id == Ontology.owner_id)
        .where(OntologyVersion.status == "needs_review")
    )).all()

    nudged: list[dict] = []
    retired: list[dict] = []
    for v, o, owner in rows:
        created = v.created_at
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days
        base = {
            "owner_email": owner.email if owner else None,
            "owner_name": owner.display_name if owner else None,
            "ontology_label": _label(o),
            "days_held": age_days,
        }
        if retire_days and age_days >= retire_days:
            v.status = "deprecated"
            if v.held_nudged_at is None:   # keep held-provenance for reactivate
                v.held_nudged_at = now
            retired.append(base)
        elif nudge_days and age_days >= nudge_days and v.held_nudged_at is None:
            v.held_nudged_at = now
            nudged.append({**base, "retire_days": retire_days})

    if nudged or retired:
        await db.commit()
    return {"nudged": nudged, "retired": retired, "scanned": len(rows)}
