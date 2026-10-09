"""Version-injection guard: an upload may only attach to an existing ontology the
uploader can edit (owner / admin / approved maintainer). See pipeline._ensure_ontology
and _assert_can_attach — the fix for the ingest impersonation/hijack vector."""
import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import (
    MaintainerRequest,
    Ontology,
    OntologyMaintainer,
    User,
)
from ontoexplorer.modules.ingestion.pipeline import (
    IngestionRequest,
    OntologyAccessDenied,
    _ensure_ontology,
)
from ontoexplorer.modules.jobs.tasks import _file_ontology_maintainer_request

async def _user(db, email):
    # Session-scoped sqlite accumulates across tests, and users.email is UNIQUE —
    # so make every seeded user distinct.
    u = User(id=uuid.uuid4().hex, email=f"{uuid.uuid4().hex[:8]}-{email}", display_name=email)
    db.add(u)
    await db.commit()
    return u


async def _victim_onto(db, owner_id):
    # ontologies.iri + shortname are UNIQUE and the test DB accumulates, so each
    # victim ontology gets a fresh IRI; the caller reuses the returned IRI.
    iri = f"https://w3id.org/victim-{uuid.uuid4().hex[:10]}/"
    o = Ontology(id=uuid.uuid4().hex, iri=iri, shortname=f"victim{uuid.uuid4().hex[:8]}",
                 title="Victim", owner_id=owner_id)
    db.add(o)
    await db.commit()
    return o, iri


@pytest.mark.anyio
async def test_owner_may_reattach(db_session):
    owner = await _user(db_session, "owner@example.org")
    o, iri = await _victim_onto(db_session, owner.id)
    oid, created = await _ensure_ontology(db_session, iri, IngestionRequest(iri=iri, owner_id=owner.id))
    assert (oid, created) == (o.id, False)


@pytest.mark.anyio
async def test_stranger_is_rejected(db_session):
    owner = await _user(db_session, "owner@example.org")
    stranger = await _user(db_session, "stranger@example.org")
    _o, iri = await _victim_onto(db_session, owner.id)
    with pytest.raises(OntologyAccessDenied) as ei:
        await _ensure_ontology(db_session, iri, IngestionRequest(iri=iri, owner_id=stranger.id))
    assert ei.value.iri == iri


@pytest.mark.anyio
async def test_approved_maintainer_may_attach(db_session):
    owner = await _user(db_session, "owner@example.org")
    maint = await _user(db_session, "maint@example.org")
    o, iri = await _victim_onto(db_session, owner.id)
    db_session.add(OntologyMaintainer(id=uuid.uuid4().hex, user_id=maint.id, ontology_id=o.id))
    await db_session.commit()
    oid, created = await _ensure_ontology(db_session, iri, IngestionRequest(iri=iri, owner_id=maint.id))
    assert (oid, created) == (o.id, False)


@pytest.mark.anyio
async def test_system_ingest_bypasses_guard(db_session):
    owner = await _user(db_session, "owner@example.org")
    o, iri = await _victim_onto(db_session, owner.id)
    # No owner_id → trusted system/backfill ingest; must not be blocked.
    oid, created = await _ensure_ontology(db_session, iri, IngestionRequest(iri=iri, owner_id=None))
    assert (oid, created) == (o.id, False)


@pytest.mark.anyio
async def test_new_iri_creates_and_assigns_owner(db_session):
    uploader = await _user(db_session, "uploader@example.org")
    new_iri = f"https://w3id.org/brand-new-{uuid.uuid4().hex[:8]}/"
    oid, created = await _ensure_ontology(db_session, new_iri, IngestionRequest(iri=new_iri, owner_id=uploader.id))
    assert created is True
    o = (await db_session.execute(select(Ontology).where(Ontology.id == oid))).scalar_one()
    assert o.owner_id == uploader.id


@pytest.mark.anyio
async def test_maintainer_request_auto_filed_and_deduped(db_session):
    owner = await _user(db_session, "owner@example.org")
    stranger = await _user(db_session, "stranger@example.org")
    o, _iri = await _victim_onto(db_session, owner.id)
    await _file_ontology_maintainer_request(db_session, stranger.id, o.id)
    await _file_ontology_maintainer_request(db_session, stranger.id, o.id)  # dedup
    reqs = (await db_session.execute(select(MaintainerRequest).where(
        MaintainerRequest.user_id == stranger.id, MaintainerRequest.ontology_id == o.id,
    ))).scalars().all()
    assert len(reqs) == 1
    assert reqs[0].request_type == "ontology"
    assert reqs[0].status == "pending"


@pytest.mark.anyio
async def test_no_request_filed_for_existing_maintainer(db_session):
    owner = await _user(db_session, "owner@example.org")
    maint = await _user(db_session, "maint@example.org")
    o, _iri = await _victim_onto(db_session, owner.id)
    db_session.add(OntologyMaintainer(id=uuid.uuid4().hex, user_id=maint.id, ontology_id=o.id))
    await db_session.commit()
    await _file_ontology_maintainer_request(db_session, maint.id, o.id)
    reqs = (await db_session.execute(select(MaintainerRequest).where(
        MaintainerRequest.user_id == maint.id, MaintainerRequest.ontology_id == o.id,
    ))).scalars().all()
    assert reqs == []
