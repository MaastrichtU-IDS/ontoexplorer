import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import Ontology


@pytest.mark.anyio
async def test_ontology_stores_resolvability(db_session):
    uid = uuid.uuid4().hex[:8]
    o = Ontology(iri=f"https://w3id.org/x-{uid}/", shortname=f"xtest{uid}", title="X",
                 resolvable=True, resolve_detail={"content_type": "text/turtle"})
    db_session.add(o)
    await db_session.commit()
    got = (await db_session.execute(select(Ontology).where(Ontology.id == o.id))).scalar_one()
    assert got.resolvable is True
    assert got.resolve_detail["content_type"] == "text/turtle"
    assert got.resolve_checked_at is None  # defaults NULL until a check runs
