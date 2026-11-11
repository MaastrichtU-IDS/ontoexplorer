"""Recompute a version's OWL 2 profile payload from durable sources.

The profile classification (EL/QL/RL/DL verdicts + language tier) is produced at
index time and cached in Redis, but it must also be materialized on
``versions.owl_profile`` so the fleet rollup and catalogue filters survive the
cache's 30-day TTL. This is the single recompute path shared by the refresh task,
the backfill, and endpoint self-heal.

Unlike reuse/coverage (recomputable from the Postgres mirror), the profile check
is content-based: it parses the stored ontology FILE with horned-profile, so it
needs the object store and may legitimately fail for the ~14% of files
horned-owl's strict reader rejects. Callers treat None as "leave the row NULL".

Dependencies are looked up on their source modules at call time (not bound at
import) so tests can monkeypatch ``download_bytes`` / ``detect_language`` /
``get_store``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import OntologyVersion


async def compute_owl_profile_payload(
    db: AsyncSession, version_id: str, ontology_id: str
) -> dict | None:
    """Return the OWL profile payload for *version_id*, or None if unobtainable.

    None means the version has no stored file (nothing to classify); a parse
    failure propagates as an exception for the caller to log and skip. The shape
    matches the Redis payload the indexer writes, including the ``indexed_at``
    stamp the UI's "Last computed" caption reads.
    """
    from ontoexplorer.clients import minio
    from ontoexplorer.clients import oxigraph
    from ontoexplorer.config import get_settings
    from ontoexplorer.modules.owl_profile import detector, language

    row = (await db.execute(
        select(OntologyVersion.minio_key, OntologyVersion.format).where(
            OntologyVersion.id == version_id)
    )).first()
    if not row or not row.minio_key:
        return None

    bucket = get_settings().minio_ontologies_bucket
    key, fmt = row.minio_key, row.format

    def _run() -> dict:
        content = minio.download_bytes(bucket, key)
        payload = detector.detect_profiles(content, fmt)
        payload["language"] = language.detect_language(
            oxigraph.get_store(), graph_iri=oxigraph.graph_iri(ontology_id, version_id))
        payload["indexed_at"] = datetime.now(timezone.utc).isoformat()
        return payload

    return await asyncio.to_thread(_run)
