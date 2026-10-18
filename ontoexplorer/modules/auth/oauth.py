"""OAuth 2.0 / OIDC provider configuration via Authlib."""

from authlib.integrations.httpx_client import AsyncOAuth2Client

from ontoexplorer.config import get_settings

# Provider metadata
_PROVIDERS: dict[str, dict] = {
    "orcid": {
        "authorize_url": "https://orcid.org/oauth/authorize",
        "token_url": "https://orcid.org/oauth/token",
        "userinfo_url": "https://pub.orcid.org/v3.0/{orcid}/person",
        "sandbox_authorize_url": "https://sandbox.orcid.org/oauth/authorize",
        "sandbox_token_url": "https://sandbox.orcid.org/oauth/token",
        "scope": "/authenticate",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
    },
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
    },
    # Keycloak endpoints are not fixed URLs: they derive from the realm issuer
    # (keycloak_issuer), resolved at call time by _keycloak_cfg(). The static
    # entry here only carries the scope and marks the provider as known so
    # _check_provider / get_provider_config accept it.
    "keycloak": {
        "scope": "openid email profile",
        "issuer_derived": True,
    },
}


def _keycloak_cfg() -> dict:
    """Resolve the ids3-realm OIDC endpoints from the configured issuer (#368).

    Standard OIDC discovery paths off the issuer; no network discovery call so
    the config stays self-contained and testable.
    """
    s = get_settings()
    issuer = str(s.keycloak_issuer).rstrip("/")
    if not issuer:
        raise ValueError(
            "KEYCLOAK_ISSUER is not configured; cannot use the keycloak provider."
        )
    base = f"{issuer}/protocol/openid-connect"
    return {
        "authorize_url": f"{base}/auth",
        "token_url": f"{base}/token",
        "userinfo_url": f"{base}/userinfo",
        "end_session_url": f"{base}/logout",
        "scope": _PROVIDERS["keycloak"]["scope"],
    }


def get_provider_config(provider: str) -> dict:
    if provider not in _PROVIDERS:
        raise ValueError(f"Unknown OAuth provider: {provider}. Supported: {list(_PROVIDERS)}")
    if provider == "keycloak":
        return _keycloak_cfg()
    return _PROVIDERS[provider]


def make_oauth_client(provider: str) -> AsyncOAuth2Client:
    s = get_settings()
    cfg = get_provider_config(provider)

    if provider == "orcid":
        client_id = s.orcid_client_id
        client_secret = s.orcid_client_secret
    elif provider == "github":
        client_id = s.github_client_id
        client_secret = s.github_client_secret
    elif provider == "google":
        client_id = s.google_client_id
        client_secret = s.google_client_secret
    elif provider == "keycloak":
        client_id = s.keycloak_client_id
        client_secret = s.keycloak_client_secret
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return AsyncOAuth2Client(
        client_id=client_id,
        client_secret=client_secret,
        scope=cfg["scope"],
    )


def get_authorize_url(provider: str) -> str:
    s = get_settings()
    cfg = get_provider_config(provider)
    if provider == "orcid" and s.orcid_sandbox:
        return cfg["sandbox_authorize_url"]
    return cfg["authorize_url"]


def get_token_url(provider: str) -> str:
    s = get_settings()
    cfg = get_provider_config(provider)
    if provider == "orcid" and s.orcid_sandbox:
        return cfg["sandbox_token_url"]
    return cfg["token_url"]


def get_redirect_uri(provider: str) -> str:
    s = get_settings()
    return f"{str(s.app_url).rstrip('/')}/auth/{provider}/callback"


async def fetch_userinfo(provider: str, access_token: str, orcid_id: str | None = None) -> dict:
    """Fetch user profile from the provider's userinfo endpoint."""
    import httpx

    cfg = get_provider_config(provider)
    headers = {"Authorization": f"Bearer {access_token}"}

    if provider == "github":
        headers["Accept"] = "application/vnd.github+json"

    url = cfg["userinfo_url"]
    if provider == "orcid" and orcid_id:
        url = url.format(orcid=orcid_id)
        headers["Accept"] = "application/json"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def extract_user_info(provider: str, userinfo: dict) -> tuple[str, str | None, str | None]:
    """
    Extract (provider_user_id, email, display_name) from provider userinfo response.
    """
    if provider == "orcid":
        orcid_id = userinfo.get("orcid-identifier", {}).get("path") or userinfo.get("orcid")
        name_data = userinfo.get("name", {})
        given = name_data.get("given-names", {}).get("value", "") if isinstance(name_data.get("given-names"), dict) else ""
        family = name_data.get("family-name", {}).get("value", "") if isinstance(name_data.get("family-name"), dict) else ""
        display_name = f"{given} {family}".strip() or orcid_id
        # Return None (not str(None)=="None") when the iD can't be extracted, so
        # callers reject it instead of collapsing every such login onto one
        # bogus (orcid,"None") account. The authoritative iD comes from the token
        # response; see the callback, which prefers it.
        return (str(orcid_id) if orcid_id else None), None, display_name

    if provider == "github":
        return str(userinfo["id"]), userinfo.get("email"), userinfo.get("name") or userinfo.get("login")

    if provider == "google":
        return userinfo["sub"], userinfo.get("email"), userinfo.get("name")

    if provider == "keycloak":
        # OIDC userinfo / id-token claims from the ids3 realm (#368). A brokered
        # ORCID login surfaces the iD as a mapped claim (see claim_orcid).
        sub = userinfo.get("sub")
        name = userinfo.get("name") or userinfo.get("preferred_username")
        return (str(sub) if sub else None), userinfo.get("email"), name

    raise ValueError(f"Unknown provider: {provider}")


def claim_email_verified(provider: str, userinfo: dict) -> bool:
    """Whether the provider asserts the email is verified. Keycloak and Google set
    the OIDC ``email_verified`` claim; the others don't assert it here (→ False)."""
    if provider in ("keycloak", "google"):
        return bool(userinfo.get("email_verified"))
    return False


def claim_orcid(userinfo: dict) -> str | None:
    """A brokered ORCID iD from a Keycloak claim, if the realm maps one."""
    return userinfo.get("orcid") or userinfo.get("orcid_id") or None
