"""Deletion must reach every store, and anonymous callers must not read raw errors."""

import pytest

from ontoexplorer.models.db import Job


def test_purge_task_is_routed_to_the_single_read_write_worker():
    """The API opens Oxigraph read-only. If this task ran on the light queue it
    could not remove a graph, and the failure would be silent."""
    from ontoexplorer.modules.jobs.tasks import celery_app
    routes = celery_app.conf.task_routes
    assert routes["ontoexplorer.purge_version_artifacts"] == {"queue": "write"}


def test_deletion_clears_the_shared_graphs_not_just_the_version_graph():
    """An earlier delete_version_metadata cleared only the per-version graph, so a
    deleted ontology stayed listed in cross-ontology queries."""
    from ontoexplorer.modules.metadata.dcat import dcat_subject_iris
    from ontoexplorer.modules.metadata.prov import prov_subject_iris

    dcat = dcat_subject_iris("o1", "v1", "http://app")
    assert "http://app/api/v1/ontologies/o1/v1" in dcat
    assert "http://app/api/v1/ontologies/o1/v1/download" in dcat

    prov = prov_subject_iris("v1", "http://app")
    assert "http://app/api/v1/versions/v1/provenance" in prov


def test_prov_subjects_exclude_the_shared_source_url():
    """The submitted URL is a PROV subject but is shared across every version
    ingested from it — deleting by it would remove another version's triples."""
    from ontoexplorer.modules.metadata.prov import prov_subject_iris
    subjects = prov_subject_iris("v1", "http://app")
    assert all(s.startswith("http://app/") for s in subjects)


def test_subject_helpers_match_what_the_builders_emit():
    """Deletion derives subjects independently, so drift would silently orphan
    triples. Assert the two agree."""
    import rdflib

    from ontoexplorer.modules.metadata.dcat import build_dcat_record, dcat_subject_iris
    from ontoexplorer.modules.metadata.void import VoidStats

    graph = build_dcat_record(
        ontology_id="o1", version_id="v1", ontology_iri="http://ex/o",
        version_iri=None, minio_download_url="http://app/dl", format_ext="ttl",
        void_stats=VoidStats(1, 1, 1, 0, 1, 1), app_base_url="http://app",
    )
    emitted = {str(s) for s in set(graph.subjects()) if isinstance(s, rdflib.URIRef)}
    assert emitted == set(dcat_subject_iris("o1", "v1", "http://app"))


@pytest.mark.parametrize("authenticated,expected", [(False, "hidden"), (True, "boom: 10.42.0.5 refused")])
def test_job_error_is_withheld_from_anonymous_callers(authenticated, expected):
    """`error` is str(exc)[:1000] from the ingest pipeline — for a failed fetch
    that names the target host, making this an SSRF oracle."""
    from ontoexplorer.api.jobs import _job_to_dict
    from datetime import UTC, datetime

    job = Job(id="j1", version_id="v1", type="ingest", status="failed",
              error="boom: 10.42.0.5 refused", created_at=datetime.now(UTC))
    assert _job_to_dict(job, include_error=authenticated)["error"] == expected


def test_job_without_an_error_stays_null_for_everyone():
    from ontoexplorer.api.jobs import _job_to_dict
    from datetime import UTC, datetime

    job = Job(id="j2", version_id="v1", type="ingest", status="done",
              error=None, created_at=datetime.now(UTC))
    assert _job_to_dict(job, include_error=False)["error"] is None


@pytest.mark.anyio
async def test_delete_refuses_when_the_cleanup_queue_is_unavailable(
    client, db_session, user_and_key, monkeypatch,
):
    """Deleting the rows without queueing the purge would orphan the triples and
    the stored object with nothing left to identify them."""
    import hashlib
    import uuid

    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.jobs import tasks

    owner, key = user_and_key
    from ontoexplorer.config import get_settings
    monkeypatch.setattr(get_settings(), "auth_bypass", False, raising=False)

    o = Ontology(id=str(uuid.uuid4()), iri=f"http://ex/{uuid.uuid4()}",
                 shortname=f"o{uuid.uuid4().hex[:8]}", owner_id=owner.id)
    db_session.add(o)
    await db_session.commit()
    db_session.add(OntologyVersion(id=str(uuid.uuid4()), ontology_id=o.id,
                                   minio_key=f"{o.id}/v/x.ttl", sha256=hashlib.sha256(b"x").hexdigest(),
                                   format="ttl", status="ready"))
    await db_session.commit()

    def _broker_down(*a, **k):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(tasks.purge_version_artifacts, "delay", _broker_down, raising=False)

    r = await client.delete(f"/api/v1/ontologies/{o.id}",
                            headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 503

    from sqlalchemy import select
    still_there = await db_session.scalar(select(Ontology).where(Ontology.id == o.id))
    assert still_there is not None, "rows were deleted despite the purge not being queued"
