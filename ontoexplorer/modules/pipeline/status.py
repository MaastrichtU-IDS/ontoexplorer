"""Pipeline-stage status (done + when) for an ontology version.

Five stages: ingested, indexed, profiled, reasoned, embedded. Only `indexed_at`
is a column on `versions`; the rest derive from existing tables:
  - ingested: the version exists; at = versions.created_at
  - indexed:  entity_index has rows; at = versions.indexed_at (NULL for versions
              indexed before the column existed — "done, time not recorded")
  - profiled: ontology_profiles row exists; at = ontology_profiles.created_at
  - reasoned: a done `reason` job exists; at = its finished_at
  - embedded: term_embeddings has rows; at = the done `embedding` job's finished_at

Used by the ontology-page repository metadata (one version) and the admin
coverage cards/filter (latest version per ontology).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

STAGES = ("ingested", "indexed", "profiled", "reasoned", "embedded")

# Per-version done-flags + timestamps. `done` is independent of the timestamp so
# an older indexed version (indexed_at NULL) still counts as indexed. Portable
# SQL (EXISTS + scalar subqueries) so the SQLite test DB runs it too.
_VERSION_SQL = """
SELECT
  v.created_at AS ingested_at,
  (EXISTS (SELECT 1 FROM entity_index e WHERE e.version_id = v.id))    AS indexed,
  v.indexed_at AS indexed_at,
  (EXISTS (SELECT 1 FROM ontology_profiles p WHERE p.version_id = v.id)) AS profiled,
  (SELECT p.created_at FROM ontology_profiles p WHERE p.version_id = v.id LIMIT 1) AS profiled_at,
  (EXISTS (SELECT 1 FROM jobs j WHERE j.version_id = v.id AND j.type = 'reason' AND j.status = 'done')) AS reasoned,
  (SELECT max(j.finished_at) FROM jobs j WHERE j.version_id = v.id AND j.type = 'reason' AND j.status = 'done') AS reasoned_at,
  (EXISTS (SELECT 1 FROM term_embeddings t WHERE t.version_id = v.id)) AS embedded,
  (SELECT max(j.finished_at) FROM jobs j WHERE j.version_id = v.id AND j.type = 'embedding' AND j.status = 'done') AS embedded_at
FROM versions v
WHERE v.id = :vid
"""


def _iso(dt) -> str | None:
    # Postgres returns datetimes; SQLite (tests) returns the stored string.
    if dt is None:
        return None
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


async def version_pipeline(db: AsyncSession, version_id: str) -> dict:
    """{stage: {done: bool, at: iso|None}} for one version. Empty dict if unknown."""
    row = (await db.execute(text(_VERSION_SQL), {"vid": version_id})).mappings().first()
    if row is None:
        return {}
    return {
        "ingested": {"done": True, "at": _iso(row["ingested_at"])},
        "indexed": {"done": bool(row["indexed"]), "at": _iso(row["indexed_at"])},
        "profiled": {"done": bool(row["profiled"]), "at": _iso(row["profiled_at"])},
        "reasoned": {"done": bool(row["reasoned"]), "at": _iso(row["reasoned_at"])},
        "embedded": {"done": bool(row["embedded"]), "at": _iso(row["embedded_at"])},
    }


# Latest (non-deprecated) version per ontology, with the five done-flags. One row
# per ontology; counts and filtering are derived from this on the client.
_COVERAGE_SQL = """
WITH ranked AS (
  SELECT id, ontology_id,
         row_number() OVER (PARTITION BY ontology_id ORDER BY created_at DESC) AS rn
  FROM versions WHERE status <> 'deprecated'
),
latest AS (SELECT id, ontology_id FROM ranked WHERE rn = 1)
SELECT
  o.id        AS ontology_id,
  o.shortname AS shortname,
  l.id        AS version_id,
  1                                                                    AS ingested,
  (EXISTS (SELECT 1 FROM entity_index e WHERE e.version_id = l.id))      AS indexed,
  (EXISTS (SELECT 1 FROM ontology_profiles p WHERE p.version_id = l.id)) AS profiled,
  (EXISTS (SELECT 1 FROM jobs j WHERE j.version_id = l.id AND j.type = 'reason' AND j.status = 'done'))      AS reasoned,
  (EXISTS (SELECT 1 FROM term_embeddings t WHERE t.version_id = l.id))   AS embedded
FROM latest l
JOIN ontologies o ON o.id = l.ontology_id
ORDER BY o.shortname, o.id
"""


async def coverage(db: AsyncSession) -> dict:
    """Admin coverage over the latest version per ontology.

    Returns per-stage {done, missing} counts (for the cards) and a per-ontology
    stage map (for the client-side filter), so the admin can narrow to the
    "missing X" set and re-trigger from the existing per-ontology actions.
    """
    rows = (await db.execute(text(_COVERAGE_SQL))).mappings().all()
    counts = {s: {"done": 0, "missing": 0} for s in STAGES}
    ontologies = []
    for r in rows:
        stages = {s: bool(r[s]) for s in STAGES}
        for s in STAGES:
            counts[s]["done" if stages[s] else "missing"] += 1
        ontologies.append({
            "ontology_id": r["ontology_id"],
            "shortname": r["shortname"],
            "version_id": r["version_id"],
            "stages": stages,
        })
    return {"stages": list(STAGES), "counts": counts, "ontologies": ontologies}
