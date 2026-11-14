"""Recompute a version's OWL 2 profile payload from durable sources.

The profile classification (EL/QL/RL/DL verdicts + language tier) is produced at
index time and cached in Redis, but it must also be materialized on
``versions.owl_profile`` so the fleet rollup and catalogue filters survive the
cache's 30-day TTL. This is the single recompute path shared by the refresh task,
the backfill, and endpoint self-heal.

Unlike reuse/coverage (recomputable from the Postgres mirror), the profile check
is content-based: it parses the stored ontology FILE with horned-profile, which legitimately fails
for the ~14% of files horned-owl's strict reader rejects. On that parse failure the
EL/QL/RL/DL block is omitted but the store-based language tier is still returned (a
tier-only payload with ``profiles_unavailable``), so the ~14% keep a tier instead of
a NULL row. None still means "no stored file -- leave the row NULL".

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

    None means the version has no stored file (nothing to classify). A parse
    failure does NOT raise: the EL/QL/RL/DL block is dropped and a tier-only
    payload (``{language, indexed_at, profiles_unavailable: True}``) is returned,
    so the ~14% of parser-rejected files keep a language tier. The success shape
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
        stamp = datetime.now(timezone.utc).isoformat()
        # Store-based language tier FIRST, independent of the strict file parse.
        # The ~14% of files horned-owl's strict reader rejects are still loaded in
        # the triple store, so their tier is computable; computing it before (and
        # outside) the profile parse means a parse failure no longer discards the
        # tier -- the version gets a tier-only payload instead of a NULL row.
        lang = language.detect_language(
            oxigraph.get_store(), graph_iri=oxigraph.graph_iri(ontology_id, version_id))
        # Download is infra: a transient MinIO/object error must stay NULL and be
        # retried, so it is OUTSIDE the catch. Only the strict in-memory parse
        # legitimately fails for the ~14% horned-owl's reader rejects.
        content = minio.download_bytes(bucket, key)
        try:
            payload = detector.detect_profiles(content, fmt)
        except Exception:
            # EL/QL/RL/DL unavailable (strict reader rejected the file); keep the
            # tier and flag the gap. Downstream readers access el/ql/rl/dl via
            # .get(), so a profile-less payload is safe.
            return {"language": lang, "indexed_at": stamp, "profiles_unavailable": True}
        payload["language"] = lang
        payload["indexed_at"] = stamp
        return payload

    return await asyncio.to_thread(_run)
