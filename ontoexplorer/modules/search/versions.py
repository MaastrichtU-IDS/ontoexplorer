"""Shared helpers for resolving the default ("latest") OntologyVersion.

Selection rules, in order:
  1. If the ontology pins a `current_version_id` and that version is still ready,
     use it (explicit admin/maintainer override).
  2. Otherwise pick the highest-versioned ready version by a *version-aware* key
     parsed from `version_iri` (the integer groups, so `0.2.14 > 0.2.12` and a
     dated IRI `2024-05-01 > 2024-01-01`), falling back to `created_at`.

Ordering by version rather than ingest time means loading an OLDER release after
a newer one (as with SULO's back-catalogue) does not hijack the default.
"""
import re
import time
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Ontology, OntologyVersion

# In-process cache for the latest-ready-versions list. Invalidated implicitly by TTL;
# new ingests become visible within _LATEST_TTL seconds.
_LATEST_TTL = 30.0
_latest_cache: tuple[float, list[OntologyVersion]] | None = None

_NOT_READY = ("pending", "failed", "deprecated")


def invalidate_latest_ready_versions_cache() -> None:
    """Call after a new version becomes ready (or the pin changes) so the next
    lookup sees it immediately."""
    global _latest_cache
    _latest_cache = None


def _version_key(v: OntologyVersion) -> tuple:
    """A comparable key ranking versions newest-last. The integer groups in
    version_iri (e.g. (0, 2, 14) or (2024, 5, 1)) dominate; created_at is the
    tiebreaker and the fallback when version_iri carries no numbers."""
    nums = tuple(int(n) for n in re.findall(r"\d+", v.version_iri or ""))
    return (nums, v.created_at)


def _choose(versions: list[OntologyVersion], current_version_id: str | None) -> OntologyVersion | None:
    """Pick the default among an ontology's versions: the pinned one if set and
    ready, else the highest by _version_key. None if no ready version exists."""
    ready = [v for v in versions if v.status not in _NOT_READY]
    if not ready:
        return None
    if current_version_id:
        pinned = next((v for v in ready if v.id == current_version_id), None)
        if pinned is not None:
            return pinned
    return max(ready, key=_version_key)


async def latest_versions_for(db: AsyncSession, ontology_ids: list[str]) -> dict[str, OntologyVersion]:
    """Default version per ontology id, honouring pins + version-aware ordering.
    Ontologies with no ready version are simply absent from the result."""
    if not ontology_ids:
        return {}
    ids = list(ontology_ids)
    pin_rows = (await db.execute(
        select(Ontology.id, Ontology.current_version_id).where(Ontology.id.in_(ids))
    )).all()
    pins = {oid: cvid for oid, cvid in pin_rows}
    vers = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_id.in_(ids))
    )).scalars().all()
    by_ont: dict[str, list[OntologyVersion]] = defaultdict(list)
    for v in vers:
        by_ont[v.ontology_id].append(v)
    out: dict[str, OntologyVersion] = {}
    for oid in ids:
        chosen = _choose(by_ont.get(oid, []), pins.get(oid))
        if chosen is not None:
            out[oid] = chosen
    return out


async def latest_ready_version(db: AsyncSession, ontology_id: str) -> OntologyVersion:
    """Return the default (pinned-or-version-latest) ready version for
    *ontology_id*, or raise HTTP 404 when there is none."""
    chosen = (await latest_versions_for(db, [ontology_id])).get(ontology_id)
    if chosen is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ontology '{ontology_id}' not found or has no indexed version",
        )
    return chosen


async def latest_ready_versions(db: AsyncSession) -> list[OntologyVersion]:
    """Return the default version for every ontology (pin-aware, version-aware).

    Cached in-process for _LATEST_TTL seconds — new ingests become visible after TTL
    expiry (or immediately via invalidate_latest_ready_versions_cache()).
    """
    global _latest_cache
    now = time.monotonic()
    if _latest_cache is not None and now - _latest_cache[0] < _LATEST_TTL:
        return _latest_cache[1]

    all_ids = [oid for (oid,) in (await db.execute(select(Ontology.id))).all()]
    chosen = await latest_versions_for(db, all_ids)
    latest = list(chosen.values())
    # Detach from the SQLAlchemy session so cached rows survive after the session closes.
    db.expunge_all()
    _latest_cache = (now, latest)
    return latest
