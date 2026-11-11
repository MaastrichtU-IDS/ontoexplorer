#!/usr/bin/env python
"""One-shot backfill: materialize versions.owl_profile for existing versions.

The OWL 2 profile payload (EL/QL/RL/DL verdicts + language tier) is computed at
index time and stored on the version row (see
modules/owl_profile/compute.py::compute_owl_profile_payload). It previously lived
only in a 30-day-TTL Redis cache, so versions indexed > 30 days ago dropped out
of the /owl-profile/public rollup and the profile/language catalogue filters.

For each ready version whose owl_profile IS NULL this copies the still-live Redis
payload when present (cheap), and otherwise recomputes from the stored file
(downloads + horned-profile parse). Versions whose file no longer parses stay
NULL — the endpoints already degrade to 404 for those.

Idempotent and resumable: only versions whose owl_profile IS NULL are touched.

    kubectl -n ontoexplorer-dev exec -i deploy/api -- \
        python - < scripts/backfill_owl_profile.py

Options:
    --version-id ID   backfill a single version (recompute even if present)
    --limit N         stop after N versions (smoke test)
    --force           recompute versions that already have owl_profile
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
from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
from ontoexplorer.modules.owl_profile.compute import compute_owl_profile_payload
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
                stmt = stmt.where(OntologyVersion.owl_profile.is_(None))
            if limit:
                stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()

    if not rows:
        log.info("nothing to backfill (all versions already have owl_profile)")
        return {"copied": 0, "recomputed": 0, "failed": 0, "skipped": 0, "total": 0}

    log.info("backfilling owl_profile for %d version(s)", len(rows))
    r = _get_redis()
    copied = recomputed = failed = skipped = 0
    for row in rows:
        vid, oid, sn = str(row.id), str(row.ontology_id), row.shortname
        t0 = time.monotonic()
        source = "redis"
        try:
            raw = await asyncio.to_thread(r.get, owl_profile_cache_key(vid))
            payload = json.loads(raw) if raw is not None else None
            if payload is None:
                source = "recompute"
                async with Session() as session:
                    payload = await compute_owl_profile_payload(session, vid, oid)
            if payload is None:
                skipped += 1
                log.info("  %s (%s) skipped — no stored file", vid, sn)
                continue
            async with Session() as session:
                await session.execute(
                    update(OntologyVersion).where(OntologyVersion.id == vid).values(
                        owl_profile=payload))
                await session.commit()
        except Exception as exc:
            failed += 1
            log.error("  %s (%s) FAILED: %s", vid, sn, exc)
            continue
        if source == "redis":
            copied += 1
        else:
            recomputed += 1
        tier = (payload.get("language") or {}).get("tier")
        log.info("  %s (%s) ← %s tier=%s (%.1fs)", vid, sn, source, tier,
                 time.monotonic() - t0)
    return {"copied": copied, "recomputed": recomputed, "failed": failed,
            "skipped": skipped, "total": len(rows)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version-id", help="backfill a single version (recompute even if present)")
    ap.add_argument("--limit", type=int, help="stop after N versions")
    ap.add_argument("--force", action="store_true", help="recompute versions that already have owl_profile")
    args = ap.parse_args()

    res = asyncio.run(
        _backfill(args.version_id, args.limit, force=args.force or bool(args.version_id)))
    log.info("done: %d copied, %d recomputed, %d skipped, %d failed (of %d)",
             res["copied"], res["recomputed"], res["skipped"], res["failed"], res["total"])
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
