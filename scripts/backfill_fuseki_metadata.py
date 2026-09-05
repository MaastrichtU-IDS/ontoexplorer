#!/usr/bin/env python
"""One-shot backfill: rebuild the Fuseki FAIR metadata store from Postgres + Oxigraph.

Fuseki metadata (DCAT + VoID + PROV-O) is normally written exactly once, at
step 7 of `run_ingestion`. There is no other producer, so anything lost -- to
the old non-durable `--mem` dataset, or to a silently swallowed write -- stays
lost until a version is re-ingested. This re-derives it for every ready version.

Run it in a pod that opens Oxigraph READ-ONLY. worker-heavy holds the RocksDB
write lock for its process lifetime, so a second read-write opener in the same
container will fail:

    kubectl -n ontoexplorer-dev exec deploy/worker-light -- \
        python scripts/backfill_fuseki_metadata.py

    # or locally
    docker exec -e OXIGRAPH_READ_ONLY=true ontoexplorer-worker-light-1 \
        python scripts/backfill_fuseki_metadata.py

This script deliberately depends only on code that exists in older images, so
it can be piped into a running pod (`kubectl exec -i ... -- python - < file`)
without waiting for a release build.

By default the catalog (`urn:meta`) and provenance (`urn:prov`) graphs are
dropped and rebuilt, which makes a full run idempotent -- those two graphs are
append-only in `write_version_metadata`, so rebuilding without a reset would
accumulate stale distribution triples. Use --no-reset with --version-id to
repair a single version without touching the rest.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import timedelta

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ontoexplorer.clients.fuseki import sparql_update
from ontoexplorer.config import get_settings
from ontoexplorer.database import make_celery_db_session
from ontoexplorer.models.db import OntologyVersion
from ontoexplorer.modules.metadata.dcat import build_dcat_record
from ontoexplorer.modules.metadata.fuseki_writer import (
    META_GRAPH,
    PROV_GRAPH,
    write_version_metadata,
)
from ontoexplorer.modules.metadata.prov import build_ingestion_activity
from ontoexplorer.modules.metadata.void import compute_void_stats_sparql

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SKIP_STATUSES = ["pending", "failed", "deprecated"]

# Presign locally rather than via ontology_download_url(), so this script works
# against images built before minio_region was introduced.
#
# The public MinIO ingress is reachable from the internet but NOT from inside
# the cluster (no hairpin back through the ingress IP), so minio-py's region
# probe -- GET /{bucket}?location= -- hangs through five urllib3 retries and
# then fails. Pinning the region skips that probe entirely: signing becomes pure
# local computation and the resulting URL is still valid for browsers.
_presign_client: "Minio | None" = None
_presign_broken = False


def _presign(minio_key: str) -> str | None:
    """Presigned GET URL, or None if signing is unavailable."""
    global _presign_client, _presign_broken
    if _presign_broken:
        return None
    s = get_settings()
    if _presign_client is None:
        _presign_client = Minio(
            s.minio_public_endpoint or s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_public_secure if s.minio_public_endpoint else s.minio_secure,
            region=getattr(s, "minio_region", None) or "us-east-1",
        )
    try:
        return _presign_client.presigned_get_object(
            s.minio_ontologies_bucket, minio_key, expires=timedelta(hours=1)
        )
    except Exception as exc:
        # Disable for the rest of the run: whatever broke is per-endpoint, not
        # per-object, and retrying it once per version is pure latency.
        _presign_broken = True
        log.warning("presigning unavailable (%s); using stable download route", exc)
        return None


async def _rebuild_one(version: OntologyVersion, app_base_url: str) -> int:
    """Re-derive and write metadata for one version. Returns triples written."""
    ontology_id = str(version.ontology_id)
    version_id = str(version.id)
    ontology_iri = version.ontology.iri

    void_stats = compute_void_stats_sparql(ontology_id, version_id)

    # Fall back to the app's own stable download route rather than to None: it
    # never expires, it is already what the REST API advertises, and keeping the
    # value non-None lets this script run against an image whose build predates
    # the optional-downloadURL change in dcat.py.
    download_url = _presign(version.minio_key) or (
        f"{app_base_url.rstrip('/')}/api/v1/ontologies/{ontology_id}/{version_id}/download"
    )

    dcat_graph = build_dcat_record(
        ontology_id=ontology_id,
        version_id=version_id,
        ontology_iri=ontology_iri,
        version_iri=version.version_iri,
        minio_download_url=download_url,
        format_ext=version.format,
        void_stats=void_stats,
        app_base_url=app_base_url,
    )

    prov_graph = build_ingestion_activity(
        version_id=version_id,
        ontology_iri=ontology_iri,
        source_url=version.source_url,
        # The original ResolvedSource is not persisted; source_url is the only
        # surviving discriminator between a fetched and an uploaded ontology.
        mode="url" if version.source_url else "bytes",
        sha256=version.sha256,
        triple_count=version.triple_count or void_stats.triple_count,
        app_base_url=app_base_url,
    )

    await write_version_metadata(ontology_id, version_id, dcat_graph, prov_graph)
    return len(dcat_graph) + len(prov_graph)


async def _backfill(version_id: str | None, reset: bool) -> tuple[int, int]:
    settings = get_settings()
    app_base_url = str(settings.app_url)
    Session = make_celery_db_session()

    async with Session() as session:
        stmt = select(OntologyVersion).options(selectinload(OntologyVersion.ontology))
        if version_id:
            stmt = stmt.where(OntologyVersion.id == version_id)
        else:
            stmt = stmt.where(OntologyVersion.status.notin_(SKIP_STATUSES))
        versions = (await session.execute(stmt)).scalars().all()

    if not versions:
        log.info("no versions to backfill")
        return 0, 0

    if reset:
        log.info("dropping <%s> and <%s>", META_GRAPH, PROV_GRAPH)
        await sparql_update(f"DROP SILENT GRAPH <{META_GRAPH}>")
        await sparql_update(f"DROP SILENT GRAPH <{PROV_GRAPH}>")

    log.info("rebuilding metadata for %d version(s) → %s", len(versions), settings.fuseki_endpoint)
    written = failed = 0
    for v in versions:
        t0 = time.monotonic()
        try:
            triples = await _rebuild_one(v, app_base_url)
        except Exception as exc:
            failed += 1
            log.error("  %s (%s) FAILED: %s", v.id, v.ontology.shortname, exc)
            continue
        written += triples
        log.info("  %s (%s) → %d triples (%.2fs)",
                 v.id, v.ontology.shortname, triples, time.monotonic() - t0)
    return written, failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version-id", help="rebuild a single version instead of all ready ones")
    ap.add_argument("--no-reset", action="store_true",
                    help="do not drop urn:meta / urn:prov first (use with --version-id)")
    args = ap.parse_args()

    written, failed = asyncio.run(_backfill(args.version_id, reset=not args.no_reset))
    log.info("done: %d triples written, %d version(s) failed", written, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
