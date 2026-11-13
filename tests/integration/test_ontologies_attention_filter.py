"""GET /ontologies?attention=true — the list behind the dashboard "needs your
attention" badge: the caller's ontologies that have a version held for review
(status ``needs_review``). Clicking the badge lands here, so the set must match
what /ontologies/attention-count counts."""
import uuid

import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion, User


async def _onto(db, owner_id, *statuses, title="T"):
    """An ontology owned by `owner_id` with one version per status in `statuses`."""
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                 title=title, owner_id=owner_id)
    db.add(o)
    for st in statuses:
        db.add(OntologyVersion(
            id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k",
            sha256=uuid.uuid4().hex, format="turtle", status=st, triple_count=10,
        ))
    await db.commit()
    return o


def _hdr(raw):
    return {"Authorization": f"Bearer {raw}"}


@pytest.mark.anyio
async def test_attention_lists_only_my_held_ontologies(client, user_and_key, db_session):
    user, raw = user_and_key
    # PRO's shape: a published version AND a held one → included.
    held = await _onto(db_session, user.id, "ready", "needs_review", title="Held")
    # Published only → excluded.
    await _onto(db_session, user.id, "ready", title="ReadyOnly")
    # Someone else's held ontology → excluded (owner scope).
    other = User(id=str(uuid.uuid4()), email=f"other-{uuid.uuid4()}@ex.com")
    db_session.add(other)
    await db_session.commit()
    await _onto(db_session, other.id, "ready", "needs_review", title="Foreign")

    r = await client.get("/api/v1/ontologies?attention=true", headers=_hdr(raw))
    assert r.status_code == 200
    ids = {o["id"] for o in r.json()["ontologies"]}
    assert ids == {held.id}


@pytest.mark.anyio
async def test_attention_one_row_per_ontology_despite_multiple_held(client, user_and_key, db_session):
    user, raw = user_and_key
    o = await _onto(db_session, user.id, "ready", "needs_review", "needs_review")
    r = await client.get("/api/v1/ontologies?attention=true", headers=_hdr(raw))
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["ontologies"]]
    assert ids.count(o.id) == 1


@pytest.mark.anyio
async def test_attention_anonymous_is_empty(client):
    r = await client.get("/api/v1/ontologies?attention=true")
    assert r.status_code == 200
    assert r.json()["ontologies"] == []
