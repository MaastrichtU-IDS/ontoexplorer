#!/usr/bin/env python
"""One-shot backfill: populate `entity_index` from Redis for every ready version.

Run inside the worker container:
    docker exec ontoexplorer-worker-1 python scripts/backfill_entity_index.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from sqlalchemy import select

from ontoexplorer.database import make_celery_db_session
from ontoexplorer.models.db import OntologyVersion
from ontoexplorer.modules.search.pg_indexer import populate_entity_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


async def _backfill() -> int:
    Session = make_celery_db_session()
    async with Session() as session:
        result = await session.execute(
            select(OntologyVersion).where(
                OntologyVersion.status.notin_(["pending", "failed", "deprecated"])
            )
        )
        versions = result.scalars().all()

    if not versions:
        log.info("no ready versions to backfill")
        return 0

    log.info("backfilling %d versions", len(versions))
    total = 0
    for v in versions:
        t0 = time.monotonic()
        async with Session() as session:
            rows = await populate_entity_index(session, str(v.id), str(v.ontology_id))
        elapsed = time.monotonic() - t0
        total += rows
        log.info("  version %s → %d rows (%.2fs)", v.id, rows, elapsed)
    return total


if __name__ == "__main__":
    total = asyncio.run(_backfill())
    log.info("done: %d total rows in entity_index", total)
    sys.exit(0)
