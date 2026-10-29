"""Maintainer-role requests: users ask for maintainer rights over an existing
ontology or the global ability to add new ontologies (with a rationale note);
admins approve/deny (with an optional decision note). Approved grants land in
ontology_maintainers (per-ontology) or users.is_uploader (global upload)."""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import can_upload, get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import (
    MaintainerRequest,
    OAuthAccount,
    Ontology,
    OntologyMaintainer,
    User,
)
from ontoexplorer.modules.auth.dependencies import require_admin, require_auth
from ontoexplorer.modules.notifications.email import (
    notify_admins_new_request,
    notify_requester_decision,
)

router = APIRouter(prefix="/api/v1/maintainer-requests", tags=["maintainers"])
admin_router = APIRouter(prefix="/api/v1/admin/maintainer-requests", tags=["maintainers-admin"])

_TYPES = {"ontology", "uploader"}


class MaintainerRequestCreate(BaseModel):
    request_type: str            # "ontology" | "uploader"
    ontology_id: str | None = None
    note: str | None = None      # user rationale


class DecisionBody(BaseModel):
    note: str | None = None      # admin rationale (optional)


def _req_dict(r: MaintainerRequest, user: User | None = None, onto: Ontology | None = None) -> dict:
    d = {
        "id": r.id,
        "user_id": r.user_id,
        "request_type": r.request_type,
        "ontology_id": r.ontology_id,
        "note": r.note,
        "status": r.status,
        "decision_note": r.decision_note,
        "reviewed_by": r.reviewed_by,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "created_at": r.created_at.isoformat(),
    }
    if user is not None:
        d["user_email"] = user.email
        d["user_display_name"] = user.display_name
        # Trust signals for the admin review screen (#365 Part 3): vet on a
        # verified email + prior grants rather than on affiliation.
        d["user_email_verified"] = user.email_verified
        d["user_is_uploader"] = user.is_uploader
    if onto is not None:
        d["ontology_shortname"] = onto.shortname
        d["ontology_iri"] = onto.iri
    return d


async def _decorate(db: AsyncSession, rows: list[MaintainerRequest]) -> list[dict]:
    """Attach requester + ontology display info in two batch queries."""
    user_ids = {r.user_id for r in rows} | {r.reviewed_by for r in rows if r.reviewed_by}
    onto_ids = {r.ontology_id for r in rows if r.ontology_id}
    users = {}
    if user_ids:
        users = {
            u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        }
    ontos = {}
    if onto_ids:
        ontos = {
            o.id: o for o in (await db.execute(select(Ontology).where(Ontology.id.in_(onto_ids)))).scalars().all()
        }
    # Linked identity providers per requester (orcid / github / google / keycloak)
    # — context the admin uses to vet an industry user on identity (#365 Part 3).
    providers: dict[str, list[str]] = {}
    if user_ids:
        for acct in (await db.execute(
            select(OAuthAccount).where(OAuthAccount.user_id.in_(user_ids))
        )).scalars().all():
            providers.setdefault(acct.user_id, []).append(acct.provider)
    out = []
    for r in rows:
        d = _req_dict(r, users.get(r.user_id), ontos.get(r.ontology_id) if r.ontology_id else None)
        if r.user_id in providers:
            d["user_providers"] = sorted(set(providers[r.user_id]))
        rb = users.get(r.reviewed_by) if r.reviewed_by else None
        if rb is not None:
            d["reviewed_by_email"] = rb.email
        out.append(d)
    return out


# ── User-facing ────────────────────────────────────────────────────────────────

@router.post("", summary="Request a maintainer role")
async def create_request(
    body: MaintainerRequestCreate,
    background: BackgroundTasks,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    if body.request_type not in _TYPES:
        raise HTTPException(422, f"request_type must be one of {sorted(_TYPES)}")

    onto_label: str | None = None
    if body.request_type == "ontology":
        if not body.ontology_id:
            raise HTTPException(422, "ontology_id is required for an 'ontology' request")
        onto = (await db.execute(select(Ontology).where(Ontology.id == body.ontology_id))).scalar_one_or_none()
        if onto is None:
            raise HTTPException(404, "Ontology not found")
        onto_label = onto.shortname or onto.iri
        already = (await db.execute(
            select(OntologyMaintainer).where(
                OntologyMaintainer.user_id == user.id,
                OntologyMaintainer.ontology_id == body.ontology_id,
            )
        )).scalar_one_or_none()
        if already is not None:
            raise HTTPException(409, "You already maintain this ontology")
    else:  # uploader
        body.ontology_id = None
        if can_upload(user):
            raise HTTPException(409, "You can already add ontologies")

    # One pending request per (user, type, ontology)
    dup_stmt = select(MaintainerRequest).where(
        MaintainerRequest.user_id == user.id,
        MaintainerRequest.request_type == body.request_type,
        MaintainerRequest.status == "pending",
    )
    if body.request_type == "ontology":
        dup_stmt = dup_stmt.where(MaintainerRequest.ontology_id == body.ontology_id)
    if (await db.execute(dup_stmt)).scalar_one_or_none() is not None:
        raise HTTPException(409, "You already have a pending request for this")

    r = MaintainerRequest(
        user_id=user.id,
        request_type=body.request_type,
        ontology_id=body.ontology_id,
        note=(body.note or None),
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)

    # Notify the admin allowlist that a request is waiting (best-effort, after the
    # response — a mail failure never affects the request).
    background.add_task(
        notify_admins_new_request,
        requester_email=user.email, requester_name=user.display_name,
        request_type=body.request_type, ontology=onto_label, note=body.note,
    )
    return _req_dict(r)


@router.get("", summary="List my maintainer requests")
async def my_requests(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(MaintainerRequest)
        .where(MaintainerRequest.user_id == user.id)
        .order_by(MaintainerRequest.created_at.desc())
    )).scalars().all()
    return {"requests": await _decorate(db, list(rows))}


# ── Admin review ─────────────────────────────────────────────────────────────

@admin_router.get("", summary="List maintainer requests (admin)")
async def admin_list(
    status: str | None = Query(None, description="Filter: pending | approved | denied"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MaintainerRequest).order_by(MaintainerRequest.created_at.desc())
    if status:
        stmt = stmt.where(MaintainerRequest.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return {"requests": await _decorate(db, list(rows))}


async def _load_pending(db: AsyncSession, request_id: str) -> MaintainerRequest:
    r = (await db.execute(select(MaintainerRequest).where(MaintainerRequest.id == request_id))).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "Request not found")
    if r.status != "pending":
        raise HTTPException(409, f"Request already {r.status}")
    return r


def _finalize(r: MaintainerRequest, status: str, admin_id: str, note: str | None) -> None:
    r.status = status
    r.decision_note = note or None
    r.reviewed_by = admin_id
    r.reviewed_at = datetime.now(UTC)


async def _notify_decision(
    db: AsyncSession, background: BackgroundTasks, r: MaintainerRequest,
    approved: bool, note: str | None,
) -> None:
    """Queue a best-effort email to the requester with the decision outcome."""
    req_user = (await db.execute(select(User).where(User.id == r.user_id))).scalar_one_or_none()
    onto_label = None
    if r.ontology_id:
        o = (await db.execute(select(Ontology).where(Ontology.id == r.ontology_id))).scalar_one_or_none()
        onto_label = (o.shortname or o.iri) if o else None
    background.add_task(
        notify_requester_decision,
        requester_email=req_user.email if req_user else None,
        request_type=r.request_type, ontology=onto_label, approved=approved, note=note,
    )


@admin_router.post("/{request_id}/approve", summary="Approve a maintainer request")
async def approve(
    request_id: str,
    body: DecisionBody,
    background: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await _load_pending(db, request_id)

    if r.request_type == "uploader":
        u = (await db.execute(select(User).where(User.id == r.user_id))).scalar_one_or_none()
        if u is None:
            raise HTTPException(404, "Requesting user no longer exists")
        # Upload rights anchor on a verified email (#365). Refuse the grant for an
        # unverified requester without finalizing the request, so it stays pending
        # and the admin can approve once the user verifies (via Keycloak). The
        # escape hatch is REQUIRE_VERIFIED_EMAIL_FOR_UPLOADER=false.
        if get_settings().require_verified_email_for_uploader and not u.email_verified:
            raise HTTPException(
                409,
                "Cannot grant upload access: this user's email is not verified. "
                "Ask them to sign in and complete email verification first, then "
                "approve again.",
            )
        u.is_uploader = True
    else:  # ontology
        exists = (await db.execute(
            select(OntologyMaintainer).where(
                OntologyMaintainer.user_id == r.user_id,
                OntologyMaintainer.ontology_id == r.ontology_id,
            )
        )).scalar_one_or_none()
        if exists is None:
            db.add(OntologyMaintainer(
                user_id=r.user_id, ontology_id=r.ontology_id, granted_by=admin.id,
            ))

    _finalize(r, "approved", admin.id, body.note)
    await db.commit()
    await db.refresh(r)
    await _notify_decision(db, background, r, approved=True, note=body.note)
    return _req_dict(r)


@admin_router.post("/{request_id}/deny", summary="Deny a maintainer request")
async def deny(
    request_id: str,
    body: DecisionBody,
    background: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await _load_pending(db, request_id)
    _finalize(r, "denied", admin.id, body.note)
    await db.commit()
    await db.refresh(r)
    await _notify_decision(db, background, r, approved=False, note=body.note)
    return _req_dict(r)
