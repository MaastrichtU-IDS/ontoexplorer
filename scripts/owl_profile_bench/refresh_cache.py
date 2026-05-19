"""Refresh the owl_profile:{vid} Redis cache for selected versions WITHOUT
re-running the search indexer (which would also re-trigger embeddings).

Uses the already-loaded Oxigraph store, runs detect_profiles() against each
version's named graph, writes the JSON payload to Redis with the standard TTL.

Usage:
    docker exec -i ontoexplorer-worker-1 python /app/scripts/owl_profile_bench/refresh_cache.py
    # reads "shortname ontology_id version_id" lines on stdin
    # OR with --all to enumerate all ready versions via DB
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

# When invoked via docker exec, /app is the bind-mounted code root.


def _main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true",
                   help="Enumerate all ready versions from the DB instead of reading stdin")
    args = p.parse_args()

    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.modules.owl_profile.detector import detect_profiles
    from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
    from ontoexplorer.modules.search.indexer import _get_redis, _SEARCH_TTL

    pairs: list[tuple[str, str, str]] = []  # (shortname, ontology_id, version_id)

    if args.all:
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.models.db import Ontology, OntologyVersion
        from sqlalchemy import select

        async def _fetch():
            async with make_celery_db_session()() as db:
                rows = (await db.execute(
                    select(OntologyVersion.id, OntologyVersion.ontology_id,
                           Ontology.shortname)
                    .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
                    .where(OntologyVersion.status == "ready")
                )).all()
                return [(r.shortname or str(r.ontology_id)[:8], str(r.ontology_id), str(r.id))
                       for r in rows]
        pairs = asyncio.run(_fetch())
    else:
        for line in sys.stdin:
            parts = line.strip().split()
            if len(parts) >= 3:
                pairs.append((parts[0], parts[1], parts[2]))

    if not pairs:
        print("no versions to process")
        return 1

    store = get_store()
    r = _get_redis()
    print(f"Refreshing OWL profile cache for {len(pairs)} version(s)")
    for sn, oid, vid in pairs:
        t0 = time.time()
        try:
            g = graph_iri(oid, vid)
            payload = detect_profiles(store, graph_iri=g, ontology_id=oid, version_id=vid)
            r.setex(owl_profile_cache_key(vid), _SEARCH_TTL, json.dumps(payload))
            verdicts = " ".join(
                f"{p}={'I' if payload[p]['in_profile'] else 'O'}"
                for p in ("el", "rl", "ql", "dl")
            )
            print(f"  {sn:14s} {time.time()-t0:6.2f}s  {verdicts}")
        except Exception as e:
            print(f"  {sn:14s} ERROR: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
