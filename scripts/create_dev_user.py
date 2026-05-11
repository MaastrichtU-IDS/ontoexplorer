"""Create a dev user and API key for local testing."""
import asyncio
import hashlib
import secrets
import sys
import uuid

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, ".")
from ontoexplorer.config import get_settings
from ontoexplorer.models.db import User, ApiKey


async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        user = User(
            id=str(uuid.uuid4()),
            email="dev@ontoexplorer.local",
            display_name="Dev User",
        )
        db.add(user)
        await db.flush()

        raw_key = f"oe_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key = ApiKey(
            id=str(uuid.uuid4()),
            user_id=user.id,
            key_hash=key_hash,
            name="dev",
            scopes=["read", "write"],
        )
        db.add(api_key)
        await db.commit()

        print(f"User ID:  {user.id}")
        print(f"API Key:  {raw_key}")


asyncio.run(main())
