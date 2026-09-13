"""Admin can reassign or clear an ontology's owner (un-orphan path from #118)."""
import uuid

import pytest
from fastapi import HTTPException

from ontoexplorer.api.admin.actions import admin_set_ontology_owner
from ontoexplorer.models.db import Ontology, User


def _u():
    return User(id=str(uuid.uuid4()), email=f"u-{uuid.uuid4()}@ex.org", display_name="U")


async def _onto(db, owner_id=None):
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                 shortname=f"o{uuid.uuid4().hex[:8]}", owner_id=owner_id)
    db.add(o); await db.commit(); return o


@pytest.mark.anyio
async def test_assign_owner_to_ownerless(db_session):
    admin = _u(); new = _u()
    db_session.add_all([admin, new]); await db_session.commit()
    o = await _onto(db_session, owner_id=None)
    r = await admin_set_ontology_owner(o.id, user_id=new.id, _=admin, db=db_session)
    assert r["owner_id"] == new.id
    await db_session.refresh(o); assert o.owner_id == new.id


@pytest.mark.anyio
async def test_clear_owner(db_session):
    admin = _u(); owner = _u()
    db_session.add_all([admin, owner]); await db_session.commit()
    o = await _onto(db_session, owner_id=owner.id)
    r = await admin_set_ontology_owner(o.id, user_id=None, _=admin, db=db_session)
    assert r["owner_id"] is None
    await db_session.refresh(o); assert o.owner_id is None


@pytest.mark.anyio
async def test_unknown_user_422(db_session):
    admin = _u(); db_session.add(admin); await db_session.commit()
    o = await _onto(db_session)
    with pytest.raises(HTTPException) as ei:
        await admin_set_ontology_owner(o.id, user_id="nope", _=admin, db=db_session)
    assert ei.value.status_code == 422


@pytest.mark.anyio
async def test_unknown_ontology_404(db_session):
    admin = _u(); db_session.add(admin); await db_session.commit()
    with pytest.raises(HTTPException) as ei:
        await admin_set_ontology_owner("nope", user_id=None, _=admin, db=db_session)
    assert ei.value.status_code == 404
