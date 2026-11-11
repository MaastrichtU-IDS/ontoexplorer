#!/usr/bin/env python
"""One-shot backfill: materialize versions.graph_counts for existing versions.

The ontology-page statistics (triples, classes, the three OWL property kinds,
named individuals) are computed once at index time and stored on the version row
(see modules/search/graph_stats.py). Versions indexed before that column existed
have graph_counts = NULL; the /stats endpoint self-heals each on first view, but
that first view pays the old 13-30s live cost on large ontologies. This fills
them all so no reader ever waits.

Idempotent and resumable: only versions whose graph_counts IS NULL are touched,
so re-running after an interruption continues where it stopped. Counts are read
from Oxigraph over the HTTP proxy (reads only) and written to Postgres — no
Oxigraph write, no RocksDB lock, so it runs from any pod:

    kubectl -n ontoexplorer-dev exec deploy/api -- \
        python scripts/backfill_graph_counts.py

    # pipe in without a release build:
    kubectl -n ontoexplorer-dev exec -i deploy/api -- \
        python - < scripts/backfill_graph_counts.py

Options:
    --version-id ID   backfill a single version (recompute even if present)
    --limit N         stop after N versions (smoke test)
    --force           recompute versions that already have graph_counts
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ontoexplorer.clients.oxigraph import get_store, graph_iri
from ontoexplorer.database import make_celery_db_session
from ontoexplorer.models.db import OntologyVersion
from ontoexplorer.modules.search.graph_stats import compute_graph_counts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# A version with no indexed graph has nothing to count; skip the same statuses
# the fuseki backfill does.
SKIP_STATUSES = ["pending", "failed", "deprecated"]


async def _backfill(version_id: str | None, limit: int | None, force: bool) -> tuple[int, int, int]:
    Session = make_celery_db_session()
    store = get_store()

    async with Session() as session:
        stmt = select(OntologyVersion).options(selectinload(OntologyVersion.ontology))
        if version_id:
            stmt = stmt.where(OntologyVersion.id == version_id)
        else:
            stmt = stmt.where(OntologyVersion.status.notin_(SKIP_STATUSES))
            if not force:
                stmt = stmt.where(OntologyVersion.graph_counts.is_(None))
        stmt = stmt.order_by(OntologyVersion.triple_count.asc().nulls_last())
        if limit:
            stmt = stmt.limit(limit)
        versions = (await session.execute(stmt)).scalars().all()

    if not versions:
        log.info("nothing to backfill (all versions already have graph_counts)")
        return 0, 0, 0

    log.info("backfilling graph_counts for %d version(s)", len(versions))
    done = failed = 0
    for v in versions:
        oid, vid = str(v.ontology_id), str(v.id)
        sn = v.ontology.shortname if v.ontology else oid
        t0 = time.monotonic()
        try:
            # One blocking set of SPARQL counts; keep the event loop free.
            counts = await asyncio.to_thread(compute_graph_counts, store, graph_iri(oid, vid))
        except Exception as exc:
            failed += 1
            log.error("  %s (%s) FAILED: %s", vid, sn, exc)
            continue
        async with Session() as session:
            await session.execute(
                update(OntologyVersion)
                .where(OntologyVersion.id == vid)
                .values(graph_counts=counts))
            await session.commit()
        done += 1
        log.info("  %s (%s) → %s (%.1fs)", vid, sn,
                 {k: counts[k] for k in ("triple_count", "class_count")}, time.monotonic() - t0)
    return done, failed, len(versions)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version-id", help="backfill a single version (recompute even if present)")
    ap.add_argument("--limit", type=int, help="stop after N versions")
    ap.add_argument("--force", action="store_true", help="recompute versions that already have graph_counts")
    args = ap.parse_args()

    done, failed, total = asyncio.run(
        _backfill(args.version_id, args.limit, force=args.force or bool(args.version_id)))
    log.info("done: %d/%d backfilled, %d failed", done, total, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
