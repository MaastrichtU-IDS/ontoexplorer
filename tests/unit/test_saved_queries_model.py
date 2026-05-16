import uuid
import pytest
from sqlalchemy import select
from ontoexplorer.models.db import SavedQuery, User


@pytest.mark.anyio
async def test_saved_query_crud(db_session):
    user = User(
        id=str(uuid.uuid4()),
        email=f"sq-{uuid.uuid4()}@example.com",
        display_name="SQ User",
    )
    db_session.add(user)
    await db_session.commit()

    sq = SavedQuery(
        user_id=user.id,
        name="My query",
        description="A test query",
        query_text="SELECT * WHERE { ?s ?p ?o } LIMIT 10",
        tags=["hp", "mondo"],
        is_public=False,
    )
    db_session.add(sq)
    await db_session.commit()
    await db_session.refresh(sq)

    assert sq.id is not None
    assert sq.name == "My query"
    assert sq.tags == ["hp", "mondo"]
    assert sq.is_public is False
    assert sq.created_at is not None

    result = await db_session.execute(
        select(SavedQuery).where(SavedQuery.user_id == user.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].id == sq.id
