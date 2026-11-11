"""Recompute a version's reuse report from durable sources.

The reuse report (imports / MIREOT / term-IRI reuse / mappings) is produced at
index time and cached in Redis, but it must also be materialized on
``versions.reuse`` so the fleet rollup and catalogue filter survive the cache's
30-day TTL. This module is the single recompute path shared by the refresh task,
the backfill, and the fleet endpoint's self-heal — all of it from durable inputs
(the ``imports`` table, the ``entity_index`` mirror, and the Oxigraph store), so
it needs neither the original upload nor a live Redis payload.

Store/detector dependencies are looked up on their source modules at call time so
tests can monkeypatch them.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import EntityIndex, Ontology, OntologyImport, OntologyVersion


async def compute_reuse_payload(
    db: AsyncSession, version_id: str, ontology_id: str
) -> dict | None:
    """Return the reuse report payload for *version_id*, or None if it is gone.

    Gathers the host IRI, declared imports, and (iri, type) entity pairs from
    Postgres, then runs ``detect_reuse`` against the store in a worker thread
    (the Oxigraph client is synchronous). The shape matches the Redis payload the
    indexer writes, so callers can store it on the row or serve it verbatim.
    """
    from ontoexplorer.clients import oxigraph
    from ontoexplorer.modules.reuse import detector

    # Version must still exist; a missing ontology just means an empty host IRI.
    exists = await db.scalar(
        select(OntologyVersion.id).where(OntologyVersion.id == version_id))
    if exists is None:
        return None

    ont = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()

    imp_rows = (await db.execute(
        select(OntologyImport.import_iri).where(OntologyImport.version_id == version_id)
    )).all()
    db_imports = [{"import_iri": r.import_iri, "depth": 1} for r in imp_rows]

    ent_rows = (await db.execute(
        select(EntityIndex.iri, EntityIndex.type).where(
            EntityIndex.version_id == version_id)
    )).all()
    entities = [(iri, etype) for iri, etype in ent_rows]

    host_iri = ont.iri if ont else ""
    host_namespaces = [host_iri + sep for sep in ("#", "/")] if host_iri else []

    def _run() -> dict:
        report = detector.detect_reuse(
            oxigraph.get_store(),
            graph_iri=oxigraph.graph_iri(ontology_id, version_id),
            version_id=version_id,
            host_iri=host_iri,
            host_namespaces=host_namespaces,
            db_imports=db_imports,
            entities=entities,
        )
        return asdict(report)

    return await asyncio.to_thread(_run)
