"""Merging accounts must move everything, not destroy it.

The source User is deleted at the end of a merge. Every table with a user FK is
therefore either CASCADE (the row is destroyed) or SET NULL (orphaned) unless it
is reassigned first. Anything missing from _MERGE_REASSIGN is silent data loss.
"""

import uuid

import pytest
from sqlalchemy import select

from ontoexplorer.models.db import (
    Job,
    MaintainerRequest,
    Ontology,
    OntologyMaintainer,
    User,
)
from ontoexplorer.modules.auth.session import merge_users


async def _user(db) -> User:
    u = User(id=str(uuid.uuid4()), email=f"m-{uuid.uuid4()}@example.com", display_name="M")
    db.add(u)
    await db.commit()
    return u


async def _ontology(db) -> Ontology:
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                 shortname=f"o{uuid.uuid4().hex[:8]}")
    db.add(o)
    await db.commit()
    return o


@pytest.mark.anyio
async def test_maintainer_grants_survive_a_merge(db_session):
    """CASCADE meant merging silently revoked the source's maintainer roles."""
    target, source = await _user(db_session), await _user(db_session)
    onto = await _ontology(db_session)
    db_session.add(OntologyMaintainer(id=str(uuid.uuid4()), user_id=source.id, ontology_id=onto.id))
    await db_session.commit()

    await merge_users(db_session, target_id=target.id, source_id=source.id)

    rows = (await db_session.execute(
        select(OntologyMaintainer).where(OntologyMaintainer.ontology_id == onto.id)
    )).scalars().all()
    assert [r.user_id for r in rows] == [target.id]


@pytest.mark.anyio
async def test_a_shared_grant_does_not_break_the_merge(db_session):
    """(user_id, ontology_id) is UNIQUE, so a straight UPDATE would collide when
    both accounts already maintain the same ontology."""
    target, source = await _user(db_session), await _user(db_session)
    onto = await _ontology(db_session)
    db_session.add(OntologyMaintainer(id=str(uuid.uuid4()), user_id=target.id, ontology_id=onto.id))
    db_session.add(OntologyMaintainer(id=str(uuid.uuid4()), user_id=source.id, ontology_id=onto.id))
    await db_session.commit()

    await merge_users(db_session, target_id=target.id, source_id=source.id)

    rows = (await db_session.execute(
        select(OntologyMaintainer).where(OntologyMaintainer.ontology_id == onto.id)
    )).scalars().all()
    assert len(rows) == 1 and rows[0].user_id == target.id


@pytest.mark.anyio
async def test_jobs_follow_their_submitter(db_session):
    """SET NULL would orphan them, and a NULL submitter is admin-only."""
    target, source = await _user(db_session), await _user(db_session)
    jid = str(uuid.uuid4())
    db_session.add(Job(id=jid, version_id=None, type="ingestion", status="done", user_id=source.id))
    await db_session.commit()

    await merge_users(db_session, target_id=target.id, source_id=source.id)

    job = (await db_session.execute(select(Job).where(Job.id == jid))).scalar_one()
    assert job.user_id == target.id


@pytest.mark.anyio
async def test_maintainer_requests_survive_a_merge(db_session):
    target, source = await _user(db_session), await _user(db_session)
    rid = str(uuid.uuid4())
    db_session.add(MaintainerRequest(id=rid, user_id=source.id, request_type="uploader",
                                     status="pending"))
    await db_session.commit()

    await merge_users(db_session, target_id=target.id, source_id=source.id)

    req = (await db_session.execute(
        select(MaintainerRequest).where(MaintainerRequest.id == rid)
    )).scalar_one()
    assert req.user_id == target.id


def test_every_user_fk_is_either_reassigned_or_deliberately_excluded():
    """A new table with a user FK is silent data loss on merge unless listed.
    This fails when one is added without a decision being made about it."""
    from ontoexplorer.models import db as models
    from ontoexplorer.modules.auth.session import _MERGE_REASSIGN

    reassigned = {m.__tablename__ for m, _ in _MERGE_REASSIGN}
    # Sessions are dropped on purpose; a hashed token cannot be moved meaningfully.
    # The audit columns record who acted, and that person still existed at the time.
    excluded = {"sessions", "users"}
    audit_only = {"granted_by", "reviewed_by", "created_by"}

    missing = []
    for mapper in models.Base.registry.mappers:
        cls = mapper.class_
        for col in mapper.columns:
            if not col.foreign_keys:
                continue
            if not any(fk.target_fullname == "users.id" for fk in col.foreign_keys):
                continue
            if col.key in audit_only:
                continue
            if cls.__tablename__ in reassigned | excluded:
                continue
            missing.append(f"{cls.__tablename__}.{col.key}")

    assert not missing, (
        "these carry a user FK and are neither reassigned on merge nor excluded: "
        + ", ".join(sorted(set(missing)))
    )
