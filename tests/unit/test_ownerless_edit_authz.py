"""An ownerless ontology is admin/maintainer-only, not editable by anyone.

owner_id is ON DELETE SET NULL, so deleting an account orphans every ontology it
registered. can_edit_ontology gates deleting an ontology and deprecating its
versions, so the old "unowned => any authenticated user" rule meant a deleted
owner's ontologies could be rewritten or destroyed by any logged-in user. These
pin the closed behaviour: ownerless => admin or approved maintainer only.
"""
import uuid

import pytest

from ontoexplorer.models.db import Ontology, OntologyMaintainer, User
from ontoexplorer.modules.auth import permissions
from ontoexplorer.modules.auth.permissions import can_edit_ontology


def _user(admin_email=None):
    return User(id=str(uuid.uuid4()),
                email=admin_email or f"u-{uuid.uuid4()}@example.com",
                display_name="U")


def _ontology(owner_id):
    return Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                    shortname=f"o{uuid.uuid4().hex[:8]}", owner_id=owner_id)


@pytest.mark.anyio
async def test_stranger_cannot_edit_ownerless(db_session):
    onto = _ontology(owner_id=None)
    stranger = _user()
    db_session.add_all([onto, stranger])
    await db_session.commit()
    assert await can_edit_ontology(db_session, stranger, onto) is False


@pytest.mark.anyio
async def test_anonymous_cannot_edit_ownerless(db_session):
    onto = _ontology(owner_id=None)
    assert await can_edit_ontology(db_session, None, onto) is False


@pytest.mark.anyio
async def test_admin_can_edit_ownerless(db_session, monkeypatch):
    onto = _ontology(owner_id=None)
    admin = _user(admin_email="admin@example.org")
    monkeypatch.setattr(permissions, "is_admin", lambda u: u is admin)
    assert await can_edit_ontology(db_session, admin, onto) is True


@pytest.mark.anyio
async def test_approved_maintainer_can_edit_ownerless(db_session):
    onto = _ontology(owner_id=None)
    maintainer = _user()
    db_session.add_all([onto, maintainer])
    await db_session.commit()
    db_session.add(OntologyMaintainer(id=str(uuid.uuid4()),
                                      ontology_id=onto.id, user_id=maintainer.id))
    await db_session.commit()
    assert await can_edit_ontology(db_session, maintainer, onto) is True


@pytest.mark.anyio
async def test_owner_still_edits_their_own(db_session):
    owner = _user()
    onto = _ontology(owner_id=owner.id)
    db_session.add_all([owner, onto])
    await db_session.commit()
    assert await can_edit_ontology(db_session, owner, onto) is True
