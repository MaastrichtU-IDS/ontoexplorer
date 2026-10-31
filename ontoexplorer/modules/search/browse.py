"""Query helpers for the cross-repository entity browser (`GET /api/v1/entities`).

Keyset pagination over `entity_index` in `(primary_label_norm, iri, version_id)`
order — the column order of `ix_entity_index_browse` — with an opaque cursor.
"""
import asyncio
import base64
import binascii
import hashlib
import json

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import EntityIndex, Ontology
from ontoexplorer.modules.search.versions import latest_ready_versions

_FACET_TTL = 300  # seconds

ENTITY_TYPES = (
    "class", "object_property", "data_property", "annotation_property", "individual",
)


def predicate_for(entity_type: str) -> tuple[str, dict]:
    """SQL predicate + bind params restricting to one entity type.

    Individuals are `type = 'individual'` (not the `is_individual` flag), so a
    punned Class+NamedIndividual is listed under `class` only.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity type: {entity_type!r}")
    return "type = :t", {"t": entity_type}


def encode_cursor(row) -> str:
    payload = {"al": row.primary_label_norm, "ai": row.iri, "av": row.version_id}
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise ValueError("malformed cursor") from exc
    if (not isinstance(data, dict)
            or not all(isinstance(data.get(k), str) for k in ("al", "ai", "av"))):
        raise ValueError("malformed cursor")
    return {k: data[k] for k in ("al", "ai", "av")}


def keyset_after(cur: dict):
    """`(label, iri, version_id) > (al, ai, av)` in expanded OR-form (SQLite-safe)."""
    return or_(
        EntityIndex.primary_label_norm > cur["al"],
        and_(EntityIndex.primary_label_norm == cur["al"], EntityIndex.iri > cur["ai"]),
        and_(EntityIndex.primary_label_norm == cur["al"],
             EntityIndex.iri == cur["ai"],
             EntityIndex.version_id > cur["av"]),
    )


async def facet_counts(db: AsyncSession, entity_type: str) -> list[dict]:
    """Ontologies having entities of `entity_type`, with counts, count-desc.

    Scoped to each ontology's latest-ready version (no double-counting across
    versions). Redis-cached, best-effort: any Redis failure falls back to SQL.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity type: {entity_type!r}")
    vids = [v.id for v in await latest_ready_versions(db)]
    if not vids:
        return []
    digest = hashlib.blake2b(
        "\x1f".join([entity_type, ",".join(sorted(vids))]).encode(),
        digest_size=16).hexdigest()
    key = f"entities:facets:{digest}"
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        cached = await asyncio.to_thread(_get_redis().get, key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass

    n = func.count().label("n")
    rows = (await db.execute(
        select(EntityIndex.ontology_id, Ontology.shortname, Ontology.title, n)
        .join(Ontology, Ontology.id == EntityIndex.ontology_id)
        .where(EntityIndex.type == entity_type, EntityIndex.version_id.in_(vids))
        .group_by(EntityIndex.ontology_id, Ontology.shortname, Ontology.title)
        .order_by(n.desc(), Ontology.shortname)
    )).all()
    out = [{"ontology_id": r.ontology_id, "short": r.shortname,
            "title": r.title or "", "count": int(r.n)} for r in rows]
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        await asyncio.to_thread(_get_redis().set, key, json.dumps(out), ex=_FACET_TTL)
    except Exception:
        pass
    return out
