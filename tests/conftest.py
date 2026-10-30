"""Shared pytest fixtures for OntoExplorer tests."""

import os

# Pin AUTH_BYPASS off for the whole test lane, BEFORE any ontoexplorer import reads
# Settings(). The dev `.env` ships AUTH_BYPASS=true (so local requests are silently
# dev@localhost), which makes the auth tests get 200 where they assert 401 — a
# divergence from CI, which has no `.env`. Environment variables win over `.env` in
# pydantic-settings, so this forces every `get_settings()` to see auth_bypass=False.
os.environ["AUTH_BYPASS"] = "false"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from ontoexplorer.database import Base, get_db  # noqa: E402
from ontoexplorer.main import create_app  # noqa: E402
from ontoexplorer.models.db import ApiKey, User  # noqa: E402

# SQLite in-memory for fast, isolated tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


def _fake_embed_batch(texts, *, prefix):
    """Deterministic fake 768-dim vector per text (stand-in for the HTTP embed client)."""
    import hashlib

    out = []
    for t in texts:
        seed = hashlib.sha256((prefix + t).encode()).digest()
        out.append([seed[i % len(seed)] / 255.0 for i in range(768)])
    return out


@pytest.fixture(autouse=True)
def _stub_embedder(request, monkeypatch):
    """Keep the real embeddings HTTP backend out of the test lane.

    Building the app under TestClient fires the startup warmup thread, and any
    semantic-search call hits embed_query. Patch the single choke point,
    embed_client.embed_batch; embed_query/embed_texts both go through it (as a
    module attribute), so every path (warmup thread included) gets the fake.
    Tests marked `slow` opt out.
    """
    if request.node.get_closest_marker("slow"):
        return
    # The client's own unit tests exercise the real embed_batch against a mocked transport.
    if request.module.__name__.rsplit(".", 1)[-1] == "test_embed_client":
        return
    import ontoexplorer.modules.search.embed_client as _ec
    monkeypatch.setattr(_ec, "embed_batch", _fake_embed_batch)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_session(engine):
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest.fixture()
async def app(db_session):
    """FastAPI app with DB overridden to use in-memory SQLite."""
    application = create_app()

    async def _override_db():
        yield db_session

    application.dependency_overrides[get_db] = _override_db
    return application


@pytest.fixture()
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture()
async def user_and_key(db_session) -> tuple[User, str]:
    """Create a test user and an API key that grants full access."""
    import hashlib
    import uuid

    raw_key = f"oe_test_key_{uuid.uuid4().hex}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    user = User(id=str(uuid.uuid4()), email=f"test-{uuid.uuid4()}@example.com", display_name="Test User")
    api_key = ApiKey(
        id=str(uuid.uuid4()),
        user_id=user.id,
        key_hash=key_hash,
        name="test-key",
        scopes=["read", "write", "admin"],
    )
    db_session.add(user)
    db_session.add(api_key)
    await db_session.commit()
    return user, raw_key
