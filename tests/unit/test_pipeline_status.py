"""Pipeline-stage status: done-flags + timestamps derive correctly, on SQLite.

Uses flush() (not commit()) so nothing persists into the shared session-scoped
test DB, and asserts relative to its own ontologies (other tests may have left
committed rows), so it is order-independent in the full suite.
"""
import datetime as dt


async def test_version_pipeline_and_coverage(db_session):
    from ontoexplorer.models.db import Job, Ontology, OntologyVersion
    from ontoexplorer.modules.pipeline.status import coverage, version_pipeline

    # Ontology A: a ready version with a done reason job (reasoned, not the rest).
    oa = Ontology(iri="http://x/pipe-a.owl", shortname="pipe-aaa")
    db_session.add(oa)
    await db_session.flush()
    va = OntologyVersion(ontology_id=oa.id, minio_key="a", sha256="pipe-sa",
                         format="turtle", status="ready")
    db_session.add(va)
    await db_session.flush()
    db_session.add(Job(version_id=va.id, type="reason", status="done",
                       finished_at=dt.datetime(2026, 1, 2, 3, 4, tzinfo=dt.timezone.utc)))

    # Ontology B: a bare ingested version (only ingested).
    ob = Ontology(iri="http://x/pipe-b.owl", shortname="pipe-bbb")
    db_session.add(ob)
    await db_session.flush()
    vb = OntologyVersion(ontology_id=ob.id, minio_key="b", sha256="pipe-sb",
                         format="turtle", status="ingested")
    db_session.add(vb)
    await db_session.flush()

    pa = await version_pipeline(db_session, va.id)
    assert pa["ingested"]["done"] is True and pa["ingested"]["at"]
    assert pa["reasoned"]["done"] is True and pa["reasoned"]["at"].startswith("2026-01-02")
    assert pa["indexed"]["done"] is False and pa["indexed"]["at"] is None
    assert pa["profiled"]["done"] is False and pa["embedded"]["done"] is False

    cov = await coverage(db_session)
    by_id = {r["ontology_id"]: r for r in cov["ontologies"]}
    assert by_id[oa.id]["stages"] == {"ingested": True, "indexed": False,
                                      "profiled": False, "reasoned": True, "embedded": False}
    assert by_id[ob.id]["stages"]["reasoned"] is False
    # Counts aggregate every ontology in the DB; assert our contributions are present.
    assert cov["counts"]["reasoned"]["done"] >= 1
    assert cov["counts"]["indexed"]["missing"] >= 2
