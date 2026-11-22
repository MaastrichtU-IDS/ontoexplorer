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


async def test_reasoned_version_ids(db_session):
    """reasoned_version_ids returns exactly the versions with a done reason job —
    the durable 'classified for MOS' signal (inferred closure persisted in Oxigraph),
    independent of the reasoner cache TTL."""
    import datetime as _dt
    from ontoexplorer.models.db import Job, Ontology, OntologyVersion
    from ontoexplorer.modules.pipeline.status import reasoned_version_ids

    o = Ontology(iri="http://x/reasoned.owl", shortname="reasoned-x")
    db_session.add(o)
    await db_session.flush()
    v_reasoned = OntologyVersion(ontology_id=o.id, minio_key="r", sha256="rid-r",
                                 format="turtle", status="ready")
    v_unreasoned = OntologyVersion(ontology_id=o.id, minio_key="u", sha256="rid-u",
                                   format="turtle", status="ready")
    db_session.add_all([v_reasoned, v_unreasoned])
    await db_session.flush()
    db_session.add(Job(version_id=v_reasoned.id, type="reason", status="done",
                       finished_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)))
    # A reason job that is NOT done must not count.
    db_session.add(Job(version_id=v_unreasoned.id, type="reason", status="running"))
    await db_session.flush()

    got = await reasoned_version_ids(db_session, [str(v_reasoned.id), str(v_unreasoned.id)])
    assert str(v_reasoned.id) in got
    assert str(v_unreasoned.id) not in got
    assert await reasoned_version_ids(db_session, []) == set()
