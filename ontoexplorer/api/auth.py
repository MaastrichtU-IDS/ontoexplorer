"""OAuth 2.0 / OIDC authentication endpoints."""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
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
    create_session,
    get_or_create_user,
    refresh_session,
    revoke_session,
)
from ontoexplorer.config import get_settings, is_admin
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


@router.get("/{provider}/callback", summary="Handle OAuth callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None),
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

    from datetime import UTC, datetime, timedelta
    expires_at = None
    if token.get("expires_in"):
        expires_at = datetime.now(UTC) + timedelta(seconds=int(token["expires_in"]))

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

    frontend = get_settings().frontend_url.rstrip('/')
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
