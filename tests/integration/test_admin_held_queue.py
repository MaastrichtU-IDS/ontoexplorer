"""Admin stale-review queue + bulk honest re-check (#364 Phase 3).

``GET /admin/versions/held`` is the global list of quality-gate-held (needs_review)
versions, oldest first, filterable by age. ``POST /admin/versions/bulk-reevaluate``
re-runs the gate from each version's stored signals — the same honest re-check the
owner `reevaluate` uses, NOT the admin publish override — publishing the ones that
now pass and leaving the rest held with reasons.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion


async def _held(db, *, title="A title", status="needs_review", triples=10,
                license_raw=None, declared_license=None, license_compliant=False,
                age_days=0):
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}", title=title,
                 shortname=f"o{uuid.uuid4().hex[:8]}")
    db.add(o)
    v = OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k",
        sha256=uuid.uuid4().hex, format="turtle", status=status,
        triple_count=triples, license_compliant=license_compliant,
        license_raw=license_raw, declared_license=declared_license,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )
    db.add(v)
    await db.commit()
    return o, v


@pytest.mark.anyio
async def test_queue_lists_only_held_oldest_first(admin_client, db_session):
    _, old = await _held(db_session, age_days=30, title="Old")
    _, recent = await _held(db_session, age_days=1, title="Recent")
    _, ready = await _held(db_session, status="ready", title="Published")  # excluded

    r = await admin_client.get("/api/v1/admin/versions/held")
    assert r.status_code == 200
    ids = [v["version_id"] for v in r.json()["versions"]]
    # The ready version is never in the held queue; the held two are, oldest first.
    assert ready.id not in ids
    assert old.id in ids and recent.id in ids
    assert ids.index(old.id) < ids.index(recent.id)


@pytest.mark.anyio
async def test_min_age_days_filters_the_backlog(admin_client, db_session):
    _, old = await _held(db_session, age_days=20)
    _, fresh = await _held(db_session, age_days=2)

    r = await admin_client.get("/api/v1/admin/versions/held?min_age_days=14")
    assert r.status_code == 200
    ids = [v["version_id"] for v in r.json()["versions"]]
    assert old.id in ids and fresh.id not in ids


@pytest.mark.anyio
async def test_row_carries_recomputed_reasons(admin_client, db_session):
    # Held with no title and non-compliant license → both reasons recomputed.
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}", title=None,
                 shortname=f"o{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    v = OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k", sha256=uuid.uuid4().hex,
        format="turtle", status="needs_review", triple_count=5, license_compliant=False,
    )
    db_session.add(v)
    await db_session.commit()

    r = await admin_client.get("/api/v1/admin/versions/held")
    row = next(x for x in r.json()["versions"] if x["version_id"] == v.id)
    assert any("license" in reason for reason in row["review_reasons"])
    assert any("title" in reason for reason in row["review_reasons"])


@pytest.mark.anyio
async def test_bulk_reevaluate_publishes_now_passing(admin_client, db_session):
    # Held only because the gate last ran before the overlay was asserted; with a
    # compliant declared_license, a title, and triples, the honest re-check passes.
    o, v = await _held(db_session, title="Good Ontology", triples=50,
                       declared_license="CC0-1.0", license_compliant=False)

    r = await admin_client.post("/api/v1/admin/versions/bulk-reevaluate",
                                json={"version_ids": [v.id]})
    assert r.status_code == 200
    body = r.json()
    assert body["published"] == 1
    assert body["results"][0]["outcome"] == "published"
    assert body["results"][0]["status"] == "ready"

    await db_session.refresh(v)
    assert v.status == "ready"
    assert v.license_compliant is True


@pytest.mark.anyio
async def test_bulk_reevaluate_leaves_still_failing_held(admin_client, db_session):
    # No title → still held after the re-check, reported with its reasons.
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}", title=None,
                 shortname=f"o{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    v = OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k", sha256=uuid.uuid4().hex,
        format="turtle", status="needs_review", triple_count=50,
        declared_license="CC0-1.0", license_compliant=False,
    )
    db_session.add(v)
    await db_session.commit()

    r = await admin_client.post("/api/v1/admin/versions/bulk-reevaluate",
                                json={"version_ids": [v.id]})
    assert r.status_code == 200
    body = r.json()
    assert body["published"] == 0
    assert body["results"][0]["outcome"] == "still_held"
    assert any("title" in reason for reason in body["results"][0]["review_reasons"])
    await db_session.refresh(v)
    assert v.status == "needs_review"


@pytest.mark.anyio
async def test_bulk_reevaluate_skips_non_held_and_unknown(admin_client, db_session):
    _, ready = await _held(db_session, status="ready")
    unknown = str(uuid.uuid4())

    r = await admin_client.post("/api/v1/admin/versions/bulk-reevaluate",
                                json={"version_ids": [ready.id, unknown]})
    assert r.status_code == 200
    outcomes = {x["version_id"]: x["outcome"] for x in r.json()["results"]}
    assert outcomes[ready.id] == "skipped"
    assert outcomes[unknown] == "not_found"


@pytest.mark.anyio
async def test_bulk_reevaluate_empty_is_422(admin_client):
    r = await admin_client.post("/api/v1/admin/versions/bulk-reevaluate",
                                json={"version_ids": []})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_held_queue_requires_admin(client):
    # No admin override here → the _require_admin dependency rejects.
    r = await client.get("/api/v1/admin/versions/held")
    assert r.status_code in (401, 403)
