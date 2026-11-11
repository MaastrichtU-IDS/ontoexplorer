#!/usr/bin/env python
"""One-shot backfill: materialize versions.coverage for existing versions.

Coverage (per-entity-type label / definition / multilingual counts) is computed
at index time and stored on the version row (see
modules/search/coverage.py::compute_coverage_from_index). It previously lived
only in a 30-day-TTL Redis cache, so versions indexed > 30 days ago lost it and
dropped out of the /coverage rollup (2009 of 2013 → only 4 shown). This recomputes
the payload from the durable entity_index mirror and writes it to the row.

Idempotent and resumable: only versions whose coverage IS NULL are touched. All
work is Postgres (entity_index aggregate → version row) — no Oxigraph, no Redis —
so it runs from any pod:

    kubectl -n ontoexplorer-dev exec deploy/api -- \
        python scripts/backfill_coverage.py

    kubectl -n ontoexplorer-dev exec -i deploy/api -- \
        python - < scripts/backfill_coverage.py

Options:
    --version-id ID   backfill a single version (recompute even if present)
    --limit N         stop after N versions (smoke test)
    --force           recompute versions that already have coverage
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from sqlalchemy import select, update

from ontoexplorer.database import make_celery_db_session
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.coverage import compute_coverage_from_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SKIP_STATUSES = ["pending", "failed", "deprecated"]


async def _backfill(version_id: str | None, limit: int | None, force: bool) -> tuple[int, int, int]:
    Session = make_celery_db_session()

    async with Session() as session:
        stmt = select(
            OntologyVersion.id, OntologyVersion.indexed_at, Ontology.shortname,
        ).join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        if version_id:
            stmt = stmt.where(OntologyVersion.id == version_id)
        else:
            stmt = stmt.where(OntologyVersion.status.notin_(SKIP_STATUSES))
            if not force:
                stmt = stmt.where(OntologyVersion.coverage.is_(None))
        rows = (await session.execute(stmt)).all()

    if not rows:
        log.info("nothing to backfill (all versions already have coverage)")
        return 0, 0, 0

    log.info("backfilling coverage for %d version(s)", len(rows))
    done = failed = 0
    for row in rows:
        vid, sn = str(row.id), row.shortname
        t0 = time.monotonic()
        try:
            async with Session() as session:
                indexed_at = row.indexed_at.isoformat() if row.indexed_at is not None else None
                payload = await compute_coverage_from_index(session, vid, indexed_at)
                await session.execute(
                    update(OntologyVersion).where(OntologyVersion.id == vid).values(coverage=payload))
                await session.commit()
        except Exception as exc:
            failed += 1
            log.error("  %s (%s) FAILED: %s", vid, sn, exc)
            continue
        done += 1
        cls = payload["by_type"]["class"]
        log.info("  %s (%s) → class total=%d with_label=%d (%.1fs)",
                 vid, sn, cls["total"], cls["with_label"], time.monotonic() - t0)
    return done, failed, len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version-id", help="backfill a single version (recompute even if present)")
    ap.add_argument("--limit", type=int, help="stop after N versions")
    ap.add_argument("--force", action="store_true", help="recompute versions that already have coverage")
    args = ap.parse_args()

    done, failed, total = asyncio.run(
        _backfill(args.version_id, args.limit, force=args.force or bool(args.version_id)))
    log.info("done: %d/%d backfilled, %d failed", done, total, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
