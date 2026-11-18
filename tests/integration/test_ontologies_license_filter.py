"""GET /ontologies?license= and /ontologies/license-facets — filter the catalogue
by the latest ready version's SPDX license (or ``none`` for no detected license),
and the facet counts that drive the browse license chips.

The integration DB is shared across tests, so each case uses a unique synthetic
license id and asserts membership (never a global exact set / global count).
"""
import uuid

import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion


async def _onto(db, *, license, title="T"):
    """A ready ontology whose latest version carries ``license`` (None = no license)."""
    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}", title=title)
    db.add(o)
    db.add(OntologyVersion(
        id=str(uuid.uuid4()), ontology_id=o.id, minio_key="k", sha256=uuid.uuid4().hex,
        format="turtle", status="ready", triple_count=10, license=license,
    ))
    await db.commit()
    return o


@pytest.mark.anyio
async def test_license_filter_exact_match(client, db_session):
    lic = f"TEST-{uuid.uuid4().hex[:8]}"
    match = await _onto(db_session, license=lic)
    other = await _onto(db_session, license=f"TEST-{uuid.uuid4().hex[:8]}")
    r = await client.get(f"/api/v1/ontologies?license={lic}")
    assert r.status_code == 200
    ids = {o["id"] for o in r.json()["ontologies"]}
    assert ids == {match.id}       # unique license → exactly the one row
    assert other.id not in ids


@pytest.mark.anyio
async def test_license_filter_none_selects_unlicensed(client, db_session):
    lic = f"TEST-{uuid.uuid4().hex[:8]}"
    nolic = await _onto(db_session, license=None)
    licensed = await _onto(db_session, license=lic)
    r = await client.get("/api/v1/ontologies?license=none")
    assert r.status_code == 200
    ids = {o["id"] for o in r.json()["ontologies"]}
    assert nolic.id in ids and licensed.id not in ids


@pytest.mark.anyio
async def test_license_facets_counts(client, db_session):
    lic = f"TEST-{uuid.uuid4().hex[:8]}"
    await _onto(db_session, license=lic)
    await _onto(db_session, license=lic)
    r = await client.get("/api/v1/ontologies/license-facets")
    assert r.status_code == 200
    facets = {f["license"]: f for f in r.json()["facets"]}
    assert facets[lic]["count"] == 2           # unique license → exactly our two rows
    # the "No license" bucket is present and labelled (its count is global)
    assert facets["none"]["label"] == "No license"
