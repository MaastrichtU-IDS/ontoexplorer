"""OAuth 2.0 / OIDC authentication endpoints."""

from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from jose import JWTError
from sqlalchemy import select
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.modules.auth.dependencies import require_auth
from ontoexplorer.modules.auth.oauth import (
    extract_user_info,
    fetch_userinfo,
    get_authorize_url,
    get_redirect_uri,
    get_token_url,
    make_oauth_client,
)
from ontoexplorer.modules.auth.session import (
    create_link_token,
    create_merge_token,
    create_session,
    decode_link_token,
    decode_merge_token,
    find_oauth_owner,
    get_or_create_user,
    link_oauth_account,
    merge_users,
    refresh_session,
    revoke_session,
    unlink_oauth_account,
)
from pydantic import BaseModel
from ontoexplorer.config import can_upload, get_settings, is_admin
from ontoexplorer.models.db import User

router = APIRouter(prefix="/auth", tags=["auth"])

_SUPPORTED_PROVIDERS = {"orcid", "github", "google"}


@router.get("/{provider}/login", summary="Redirect to OAuth provider")
async def oauth_login(provider: str, response: Response):
    _check_provider(provider)
    client = make_oauth_client(provider)
    redirect_uri = get_redirect_uri(provider)
    authorize_url = get_authorize_url(provider)
    uri, state = client.create_authorization_url(authorize_url, redirect_uri=redirect_uri)
    resp = RedirectResponse(url=uri)
    resp.set_cookie("oauth_state", state, httponly=True, samesite="lax", max_age=600)
    return resp


@router.get("/{provider}/link", summary="Start linking a provider to the current account")
async def oauth_link_start(
    provider: str,
    response: Response,
    user: User = Depends(require_auth),
):
    """
    Begin the OAuth dance to LINK `provider` to the logged-in user. Returns the
    authorize URL (the caller redirects the browser to it) and sets a short-lived,
    signed `oauth_link` cookie so /callback knows to link rather than log in.
    Requires auth — this is a top-level nav initiated from an authenticated fetch.
    """
    _check_provider(provider)
    client = make_oauth_client(provider)
    redirect_uri = get_redirect_uri(provider)
    authorize_url = get_authorize_url(provider)
    uri, state = client.create_authorization_url(authorize_url, redirect_uri=redirect_uri)
    response.set_cookie("oauth_state", state, httponly=True, samesite="lax", max_age=600)
    response.set_cookie("oauth_link", create_link_token(user.id), httponly=True, samesite="lax", max_age=600)
    return {"authorize_url": uri}


@router.post("/{provider}/unlink", summary="Unlink a provider from the current account")
async def oauth_unlink(
    provider: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    _check_provider(provider)
    try:
        remaining = await unlink_oauth_account(db, user.id, provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"connected_providers": remaining}


class _MergeRequest(BaseModel):
    token: str


@router.post("/merge", summary="Merge another account into the current one")
async def oauth_merge(
    body: _MergeRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm a merge previously offered by /callback (when linking hit an identity
    owned by another account). The signed merge token proves control of both
    accounts was established during the OAuth round-trip; here we additionally
    require the caller to be authenticated as the token's target. Destructive:
    moves the source's resources here and deletes it.
    """
    try:
        target_id, source_id = decode_merge_token(body.token)
    except JWTError:
        raise HTTPException(status_code=400, detail="Merge request expired or invalid — start again.")
    if target_id != user.id:
        raise HTTPException(status_code=403, detail="This merge request is for a different account.")
    try:
        result = await merge_users(db, target_id=user.id, source_id=source_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get("/{provider}/callback", summary="Handle OAuth callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None),
    oauth_link: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    _check_provider(provider)

    if not oauth_state or oauth_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    client = make_oauth_client(provider)
    redirect_uri = get_redirect_uri(provider)
    token_url = get_token_url(provider)

    token = await client.fetch_token(
        token_url,
        code=code,
        redirect_uri=redirect_uri,
        grant_type="authorization_code",
    )

    access_token = token.get("access_token")
    orcid_id = token.get("orcid") if provider == "orcid" else None

    userinfo = await fetch_userinfo(provider, access_token, orcid_id=orcid_id)
    provider_user_id, email, display_name = extract_user_info(provider, userinfo)

    # ORCID's OAuth token response carries the authoritative iD; the userinfo
    # /person payload does not reliably include it. Prefer the token value.
    if provider == "orcid" and orcid_id:
        provider_user_id = str(orcid_id)

    # NEVER proceed without a real provider id. A null/"None" id would match the
    # (provider, "None") key for every such login and collapse them all onto one
    # account (a privilege-escalation bug we hit with ORCID).
    if not provider_user_id or provider_user_id == "None":
        raise HTTPException(
            status_code=400,
            detail=f"Could not determine your {provider} account identifier; login aborted.",
        )

    from datetime import UTC, datetime, timedelta
    expires_at = None
    if token.get("expires_in"):
        expires_at = datetime.now(UTC) + timedelta(seconds=int(token["expires_in"]))

    frontend = get_settings().frontend_url.rstrip('/')

    # ── LINK MODE ────────────────────────────────────────────────────────────
    # A signed oauth_link cookie means an already-logged-in user is attaching this
    # provider to their account (not logging in). Attach it, then bounce back to
    # the profile page — no new session is issued.
    if oauth_link:
        try:
            link_user_id = decode_link_token(oauth_link)
        except JWTError:
            resp = RedirectResponse(url=f"{frontend}/dashboard/profile?link_error={quote('Link request expired — try again.')}")
            resp.delete_cookie("oauth_link")
            return resp
        # If this identity already belongs to a DIFFERENT account, we can't just
        # link it — but the caller has now proven control of BOTH accounts (the
        # signed oauth_link cookie = target, this fresh OAuth = source). Offer a
        # merge: mint a signed merge token and bounce to a confirm UI. We do NOT
        # merge here — it's destructive, so it needs an explicit confirmation.
        owner = await find_oauth_owner(db, provider, provider_user_id)
        if owner is not None and owner != link_user_id:
            merge_token = create_merge_token(target_user_id=link_user_id, source_user_id=owner)
            resp = RedirectResponse(
                url=f"{frontend}/dashboard/profile?merge_available={quote(merge_token)}&merge_provider={quote(provider)}"
            )
            resp.delete_cookie("oauth_link")
            return resp

        try:
            await link_oauth_account(
                db,
                user_id=link_user_id,
                provider=provider,
                provider_user_id=provider_user_id,
                email=email,
                display_name=display_name,
                access_token=access_token,
                refresh_token=token.get("refresh_token"),
                expires_at=expires_at,
            )
        except ValueError as exc:
            resp = RedirectResponse(url=f"{frontend}/dashboard/profile?link_error={quote(str(exc))}")
            resp.delete_cookie("oauth_link")
            return resp
        resp = RedirectResponse(url=f"{frontend}/dashboard/profile?linked={provider}")
        resp.delete_cookie("oauth_link")
        return resp

    # ── LOGIN MODE ───────────────────────────────────────────────────────────
    user = await get_or_create_user(
        db,
        provider=provider,
        provider_user_id=provider_user_id,
        email=email,
        display_name=display_name,
        access_token=access_token,
        refresh_token=token.get("refresh_token"),
        expires_at=expires_at,
    )

    jwt_access, refresh_token = await create_session(db, user.id)

    resp = RedirectResponse(url=f"{frontend}/dashboard")
    resp.set_cookie("refresh_token", refresh_token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    resp.set_cookie("access_token", jwt_access, httponly=False, samesite="lax", max_age=3600)
    return resp


@router.post("/refresh", summary="Refresh access token")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("refresh_token", "")
    try:
        access_token, new_refresh = await refresh_session(db, token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    response.set_cookie("refresh_token", new_refresh, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout", summary="Invalidate session")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("refresh_token", "")
    if token:
        await revoke_session(db, token)
    response.delete_cookie("refresh_token")
    return {"detail": "Logged out"}


@router.get("/me", summary="Current user profile")
async def me(user: User = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    from ontoexplorer.models.db import OAuthAccount
    accounts = (await db.execute(
        select(OAuthAccount).where(OAuthAccount.user_id == user.id)
    )).scalars().all()
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat(),
        "is_admin": is_admin(user),
        "is_uploader": can_upload(user),
        "connected_providers": [a.provider for a in accounts],
        "preferred_lang": user.preferred_lang,
        "lang_fallback_strategy": user.lang_fallback_strategy,
    }


@router.patch("/me", summary="Update user preferences")
async def update_me(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    allowed = {"preferred_lang", "lang_fallback_strategy", "display_name"}
    updates = {k: v for k, v in body.items() if k in allowed}

    if "lang_fallback_strategy" in updates:
        valid = {"silent", "show_all", "indicate_missing"}
        if updates["lang_fallback_strategy"] not in valid:
            raise HTTPException(status_code=422, detail=f"lang_fallback_strategy must be one of {valid}")

    for k, v in updates.items():
        setattr(user, k, v)
    await db.commit()
    await db.refresh(user)
    return {
        "id": user.id,
        "preferred_lang": user.preferred_lang,
        "lang_fallback_strategy": user.lang_fallback_strategy,
    }


def _check_provider(provider: str) -> None:
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")
