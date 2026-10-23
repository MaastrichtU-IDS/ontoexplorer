"""Keycloak Shared Signals (SSF) receiver (#372): verify a signed SET, then
purge / unlink / revoke the matching local account. Covers the happy paths plus
the security rejections (bad signature, wrong audience, wrong typ)."""

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt
from sqlalchemy import select

from ontoexplorer.config import get_settings
from ontoexplorer.models.db import ApiKey, OAuthAccount, Session, User
from ontoexplorer.modules.auth import ssf

ISSUER = "https://keycloak.example.org/realms/ontoexplorer"
CLIENT = "ontoexplorer"
KID = "test-kid-1"

# One RSA keypair for the whole module: the "realm" signing key.
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIV_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
_PUB_PEM = _KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
_PUB_JWK = {**jwk.construct(_PUB_PEM, "RS256").to_dict(), "kid": KID, "use": "sig", "alg": "RS256"}

# A different key, to forge a bad signature under the same kid.
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PRIV_PEM = _OTHER.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()


@pytest.fixture(autouse=True)
def _wire_ssf(monkeypatch):
    """Point the verifier at our test realm + key, bypassing the network JWKS fetch."""
    monkeypatch.setattr(get_settings(), "keycloak_issuer", ISSUER, raising=False)
    monkeypatch.setattr(get_settings(), "keycloak_client_id", CLIENT, raising=False)
    monkeypatch.setattr(get_settings(), "keycloak_ssf_shared_secret", "", raising=False)

    async def _fake_jwks(force: bool = False):
        return [_PUB_JWK]

    monkeypatch.setattr(ssf, "_fetch_jwks", _fake_jwks)


def _set(event_type: str, sub: str, *, priv=_PRIV_PEM, aud=CLIENT, typ="secevent+jwt") -> str:
    payload = {
        "iss": ISSUER,
        "aud": aud,
        "iat": int(datetime.now(UTC).timestamp()),
        "jti": uuid.uuid4().hex,
        "sub_id": {"format": "iss_sub", "iss": ISSUER, "sub": sub},
        "events": {event_type: {}},
    }
    return jwt.encode(payload, priv, algorithm="RS256", headers={"kid": KID, "typ": typ})


async def _post(client, token: str):
    return await client.post(
        "/auth/keycloak/ssf", content=token,
        headers={"content-type": "application/secevent+jwt"},
    )


async def _make_user(db, *, providers: list[str], email=None) -> tuple[User, dict[str, str]]:
    u = User(id=str(uuid.uuid4()), email=email or f"u-{uuid.uuid4().hex}@ex.org", display_name="U")
    db.add(u)
    subs = {}
    for p in providers:
        sub = f"{p}-{uuid.uuid4().hex[:8]}"
        subs[p] = sub
        db.add(OAuthAccount(id=str(uuid.uuid4()), user_id=u.id, provider=p, provider_user_id=sub))
    await db.commit()
    return u, subs


async def _add_session(db, user_id: str) -> None:
    from datetime import timedelta
    db.add(Session(id=str(uuid.uuid4()), user_id=user_id,
                   token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                   expires_at=datetime.now(UTC) + timedelta(days=30)))
    await db.commit()


# ── account-purged ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_purge_deletes_keycloak_only_user(client, db_session):
    u, subs = await _make_user(db_session, providers=["keycloak"])
    await _add_session(db_session, u.id)

    r = await _post(client, _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"]))
    assert r.status_code == 202
    assert r.json()["handled"][0]["outcome"] == "deleted_user"

    assert (await db_session.execute(select(User).where(User.id == u.id))).scalar_one_or_none() is None
    assert (await db_session.execute(
        select(OAuthAccount).where(OAuthAccount.user_id == u.id))).first() is None


@pytest.mark.anyio
async def test_purge_unlinks_when_other_login_remains(client, db_session):
    u, subs = await _make_user(db_session, providers=["keycloak", "github"])

    r = await _post(client, _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"]))
    assert r.status_code == 202
    assert r.json()["handled"][0]["outcome"] == "unlinked_keycloak"

    # User survives; only the keycloak link is gone.
    assert (await db_session.execute(select(User).where(User.id == u.id))).scalar_one_or_none() is not None
    provs = (await db_session.execute(
        select(OAuthAccount.provider).where(OAuthAccount.user_id == u.id))).scalars().all()
    assert provs == ["github"]


@pytest.mark.anyio
async def test_purge_replay_is_noop(client, db_session):
    u, subs = await _make_user(db_session, providers=["keycloak"])
    assert (await _post(client, _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"]))).json()["handled"][0]["outcome"] == "deleted_user"
    # Replaying the same subject now finds nothing.
    r2 = await _post(client, _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"]))
    assert r2.status_code == 202
    assert r2.json()["handled"][0]["outcome"] == "unmatched"


@pytest.mark.anyio
async def test_purge_unmatched_subject(client, db_session):
    r = await _post(client, _set(ssf.EVT_ACCOUNT_PURGED, "nobody-here"))
    assert r.status_code == 202
    assert r.json()["handled"][0]["outcome"] == "unmatched"


# ── account-disabled / session-revoked ──────────────────────────────────────

@pytest.mark.anyio
async def test_disabled_revokes_sessions_and_keys(client, db_session):
    u, subs = await _make_user(db_session, providers=["keycloak"])
    await _add_session(db_session, u.id)
    key = ApiKey(id=str(uuid.uuid4()), user_id=u.id,
                 key_hash=hashlib.sha256(b"k").hexdigest(), name="k")
    db_session.add(key)
    await db_session.commit()

    r = await _post(client, _set(ssf.EVT_ACCOUNT_DISABLED, subs["keycloak"]))
    assert r.json()["handled"][0]["outcome"] == "disabled_revoked"

    # Account kept, but sessions gone and key revoked.
    assert (await db_session.execute(select(User).where(User.id == u.id))).scalar_one_or_none() is not None
    assert (await db_session.execute(select(Session).where(Session.user_id == u.id))).first() is None
    await db_session.refresh(key)
    assert key.revoked_at is not None


@pytest.mark.anyio
async def test_session_revoked_drops_sessions(client, db_session):
    u, subs = await _make_user(db_session, providers=["keycloak"])
    await _add_session(db_session, u.id)
    r = await _post(client, _set(ssf.EVT_SESSION_REVOKED, subs["keycloak"]))
    assert r.json()["handled"][0]["outcome"] == "sessions_revoked"
    assert (await db_session.execute(select(Session).where(Session.user_id == u.id))).first() is None
    # User and link remain.
    assert (await db_session.execute(select(User).where(User.id == u.id))).scalar_one_or_none() is not None


# ── security rejections ─────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_bad_signature_rejected(client, db_session):
    u, subs = await _make_user(db_session, providers=["keycloak"])
    bad = _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"], priv=_OTHER_PRIV_PEM)  # wrong key, same kid
    r = await _post(client, bad)
    assert r.status_code == 400
    # User untouched.
    assert (await db_session.execute(select(User).where(User.id == u.id))).scalar_one_or_none() is not None


@pytest.mark.anyio
async def test_wrong_audience_rejected(client, db_session):
    u, subs = await _make_user(db_session, providers=["keycloak"])
    r = await _post(client, _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"], aud="someone-else"))
    assert r.status_code == 400
    assert (await db_session.execute(select(User).where(User.id == u.id))).scalar_one_or_none() is not None


@pytest.mark.anyio
async def test_keycloak_stream_audience_accepted(client, db_session):
    # Keycloak stamps aud as "<clientId>/<streamId>" per stream (observed on dev).
    u, subs = await _make_user(db_session, providers=["keycloak"])
    aud = f"{CLIENT}/ceb94fdb-6004-46a6-aad1-f56a68b26833"
    r = await _post(client, _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"], aud=aud))
    assert r.status_code == 202
    assert r.json()["handled"][0]["outcome"] == "deleted_user"


@pytest.mark.anyio
async def test_wrong_typ_rejected(client, db_session):
    u, subs = await _make_user(db_session, providers=["keycloak"])
    r = await _post(client, _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"], typ="jwt"))
    assert r.status_code == 400
    assert (await db_session.execute(select(User).where(User.id == u.id))).scalar_one_or_none() is not None


@pytest.mark.anyio
async def test_shared_secret_enforced(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "keycloak_ssf_shared_secret", "s3cret", raising=False)
    u, subs = await _make_user(db_session, providers=["keycloak"])
    tok = _set(ssf.EVT_ACCOUNT_PURGED, subs["keycloak"])
    # No/!wrong bearer -> 401, user untouched.
    r = await client.post("/auth/keycloak/ssf", content=tok,
                          headers={"content-type": "application/secevent+jwt"})
    assert r.status_code == 401
    assert (await db_session.execute(select(User).where(User.id == u.id))).scalar_one_or_none() is not None
    # Correct bearer -> processed.
    r2 = await client.post("/auth/keycloak/ssf", content=tok,
                           headers={"content-type": "application/secevent+jwt",
                                    "authorization": "Bearer s3cret"})
    assert r2.status_code == 202
    assert r2.json()["handled"][0]["outcome"] == "deleted_user"
