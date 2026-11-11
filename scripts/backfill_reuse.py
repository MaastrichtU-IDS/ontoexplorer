#!/usr/bin/env python
"""One-shot backfill: materialize versions.reuse for existing versions.

The reuse report (imports / MIREOT / term-IRI reuse / mappings) is computed at
index time and stored on the version row (see
modules/reuse/compute.py::compute_reuse_payload). It previously lived only in a
30-day-TTL Redis cache, so versions indexed > 30 days ago dropped out of the
/reuse/fleet rollup and the reuse catalogue filter (only 4 of 2013 keys survived).

For each ready version whose reuse IS NULL this copies the still-live Redis
payload when present (cheap), and otherwise recomputes via detect_reuse over the
entity_index mirror + the store. All recompute inputs are durable, so this runs
from any pod.

    kubectl -n ontoexplorer-dev exec -i deploy/api -- \
        python - < scripts/backfill_reuse.py

Options:
    --version-id ID   backfill a single version (recompute even if present)
    --limit N         stop after N versions (smoke test)
    --force           recompute versions that already have reuse
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

from sqlalchemy import select, update

from ontoexplorer.database import make_celery_db_session
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.reuse.cache import reuse_cache_key
from ontoexplorer.modules.reuse.compute import compute_reuse_payload
from ontoexplorer.modules.search.indexer import _get_redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SKIP_STATUSES = ["pending", "failed", "deprecated"]


async def _backfill(version_id: str | None, limit: int | None, force: bool) -> dict:
    Session = make_celery_db_session()

    async with Session() as session:
        stmt = select(
            OntologyVersion.id, OntologyVersion.ontology_id, Ontology.shortname,
        ).join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        if version_id:
            stmt = stmt.where(OntologyVersion.id == version_id)
        else:
            stmt = stmt.where(OntologyVersion.status.notin_(SKIP_STATUSES))
            if not force:
                stmt = stmt.where(OntologyVersion.reuse.is_(None))
            if limit:
                stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()

    if not rows:
        log.info("nothing to backfill (all versions already have reuse)")
        return {"copied": 0, "recomputed": 0, "failed": 0, "skipped": 0, "total": 0}

    log.info("backfilling reuse for %d version(s)", len(rows))
    r = _get_redis()
    copied = recomputed = failed = skipped = 0
    for row in rows:
        vid, oid, sn = str(row.id), str(row.ontology_id), row.shortname
        t0 = time.monotonic()
        source = "redis"
        try:
            raw = await asyncio.to_thread(r.get, reuse_cache_key(vid))
            payload = json.loads(raw) if raw is not None else None
            if payload is None:
                source = "recompute"
                async with Session() as session:
                    payload = await compute_reuse_payload(session, vid, oid)
            if payload is None:
                skipped += 1
                log.info("  %s (%s) skipped — version gone", vid, sn)
                continue
            async with Session() as session:
                await session.execute(
                    update(OntologyVersion).where(OntologyVersion.id == vid).values(
                        reuse=payload))
                await session.commit()
        except Exception as exc:
            failed += 1
            log.error("  %s (%s) FAILED: %s", vid, sn, exc)
            continue
        if source == "redis":
            copied += 1
        else:
            recomputed += 1
        log.info("  %s (%s) ← %s imports=%d sources=%d (%.1fs)", vid, sn, source,
                 len(payload.get("imports", [])), len(payload.get("term_iri_reuse", {})),
                 time.monotonic() - t0)
    return {"copied": copied, "recomputed": recomputed, "failed": failed,
            "skipped": skipped, "total": len(rows)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version-id", help="backfill a single version (recompute even if present)")
    ap.add_argument("--limit", type=int, help="stop after N versions")
    ap.add_argument("--force", action="store_true", help="recompute versions that already have reuse")
    args = ap.parse_args()

    res = asyncio.run(
        _backfill(args.version_id, args.limit, force=args.force or bool(args.version_id)))
    log.info("done: %d copied, %d recomputed, %d skipped, %d failed (of %d)",
             res["copied"], res["recomputed"], res["skipped"], res["failed"], res["total"])
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
