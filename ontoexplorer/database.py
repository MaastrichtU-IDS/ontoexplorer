from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from ontoexplorer.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=settings.debug, pool_pre_ping=True)


engine = _make_engine()
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def make_celery_db_session() -> async_sessionmaker:
    """Return a session factory with NullPool, safe across asyncio.run() calls in Celery tasks."""
    settings = get_settings()
    celery_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    return async_sessionmaker(celery_engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
