"""Regression: the public catalogue listing must load the heavy version columns it
serialises.

#455 deferred the heavy per-version JSON columns (reason_repairs, graph_counts, …)
in `latest_versions_for` *unconditionally* to speed up global search. But the
catalogue listing shares that helper and DOES read some of those columns —
`_version_dict` serialises `reason_repairs` and `list_ontologies` reads
`graph_counts` — so accessing the now-deferred attribute triggered a lazy reload
under the async session and raised `MissingGreenlet`, turning GET /api/v1/ontologies
into a 500. The fix makes deferral opt-in; the catalogue path loads everything.
"""
import uuid

import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion


@pytest.mark.anyio
async def test_catalogue_listing_serialises_heavy_version_columns(client, db_session):
    tag = uuid.uuid4().hex[:8]
    oid = f"oc-{tag}"
    vid = f"vc-{tag}"
    db_session.add(Ontology(id=oid, iri=f"http://ex.org/{tag}/o", shortname=f"c{tag}", title="Onto C"))
    await db_session.flush()
    # A ready default version carrying the two heavy columns the listing reads.
    db_session.add(OntologyVersion(
        id=vid, ontology_id=oid, version_iri=f"http://ex.org/{tag}/o/1.0.0",
        minio_key=f"k/{vid}", sha256=f"sha-{vid}", format="owl", status="ready",
        reason_repairs={"injected_class_declarations": 13},
        graph_counts={"classes": 5, "object_properties": 2},
    ))
    await db_session.flush()

    # Public endpoint (no auth) — the exact request the dev catalogue 500'd on.
    resp = await client.get("/api/v1/ontologies")
    assert resp.status_code == 200, resp.text

    row = next((r for r in resp.json()["ontologies"] if r["id"] == oid), None)
    assert row is not None, "seeded ontology missing from the catalogue listing"
    # The deferred column must be present and correct (not lazily reloaded / crashed).
    assert row["latest_version"] is not None
    assert row["latest_version"]["reason_repairs"] == {"injected_class_declarations": 13}
