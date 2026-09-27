"""Shared pytest fixtures for OntoExplorer tests."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ontoexplorer.database import Base, get_db
from ontoexplorer.main import create_app
from ontoexplorer.models.db import ApiKey, User

# SQLite in-memory for fast, isolated tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


class _FakeVec:
    """A stand-in embedding vector with the .tolist() the embedder callers expect."""

    def tolist(self) -> list[float]:
        return [0.0] * 768


class _FakeEmbedder:
    def query_embed(self, texts):
        return iter([_FakeVec() for _ in texts])

    def passage_embed(self, texts, batch_size: int = 128):
        return [_FakeVec() for _ in texts]


@pytest.fixture(autouse=True)
def _stub_embedder(request, monkeypatch):
    """Keep the real fastembed/ONNX model out of the test lane.

    Building the app under TestClient fires the startup warmup thread, and any
    semantic-search call hits embed_query — both load a ~500 MB fastembed model
    whose native ONNX runtime aborts at interpreter shutdown (a flaky SIGABRT /
    "I/O operation on closed file" that intermittently reds the backend CI job).
    Patch the single choke point, get_embedder(); embed_query/embed_texts both go
    through it, so every path (warmup thread included) gets the fake. Tests marked
    `slow` — the ones that deliberately exercise the real embedder, and which CI
    excludes — opt out.
    """
    if request.node.get_closest_marker("slow"):
        return
    import ontoexplorer.modules.search.embedder as _emb
    monkeypatch.setattr(_emb, "get_embedder", lambda: _FakeEmbedder())


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
