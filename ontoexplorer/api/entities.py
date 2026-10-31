"""Cross-repository entity listing — GET /api/v1/entities."""
import asyncio
import hashlib
from types import SimpleNamespace

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import EntityIndex, Ontology
from ontoexplorer.modules.auth.dependencies import get_current_user
from ontoexplorer.modules.search import browse
from ontoexplorer.modules.search.pg_search import pg_entity_search
from ontoexplorer.modules.search.semantic import EmbedUnavailable, semantic_related
from ontoexplorer.modules.search.versions import latest_ready_versions
from ontoexplorer.modules.stats.public_stats import read_public_stats

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["entities"])

_COUNT_TTL = 300  # seconds

_TOTAL_KEY = {
    "class": "total_classes",
    "object_property": "total_object_properties",
    "data_property": "total_data_properties",
    "annotation_property": "total_annotation_properties",
    "individual": "total_individuals",
}


def _definition(definitions) -> str:
    if definitions and isinstance(definitions, list) and isinstance(definitions[0], dict):
        return str(definitions[0].get("value") or "").strip()
    return ""


def _label(row, lang: str | None) -> str:
    if lang and isinstance(row.labels, dict) and row.labels.get(lang):
        return row.labels[lang]
    return row.primary_label


async def _scoped_count(db: AsyncSession, entity_type: str, vids: list[str],
                        ontology: list[str] | None) -> int:
    sql, params = browse.predicate_for(entity_type)
    stmt = select(func.count()).select_from(EntityIndex).where(
        text(sql).bindparams(**params), EntityIndex.version_id.in_(vids))
    if ontology:
        stmt = stmt.where(EntityIndex.ontology_id.in_(ontology))

    digest = hashlib.blake2b(
        "\x1f".join([entity_type, ",".join(sorted(ontology or [])), ",".join(sorted(vids))]).encode(),
        digest_size=16).hexdigest()
    key = f"entities:count:{digest}"
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        cached = await asyncio.to_thread(_get_redis().get, key)
        if cached is not None:
            return int(cached)
    except Exception:
        pass
    n = int(await db.scalar(stmt) or 0)
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        await asyncio.to_thread(_get_redis().set, key, n, ex=_COUNT_TTL)
    except Exception:
        pass
    return n


@router.get("/entities")
async def list_entities(
    type: str = Query(...),
    q: str | None = Query(None),
    ontology: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    if type not in browse.ENTITY_TYPES:
        raise HTTPException(422, f"type must be one of {', '.join(browse.ENTITY_TYPES)}")
    cur = None
    if cursor:
        try:
            cur = browse.decode_cursor(cursor)
        except ValueError:
            raise HTTPException(422, "malformed cursor")

    vids = [v.id for v in await latest_ready_versions(db)]
    q = (q or "").strip()

    if not vids:
        entities, nxt = [], None
    elif q:
        hits = await pg_entity_search(
            db, q, limit, types=[type], ontology_ids=ontology or None,
            version_ids=vids)
        rows = (await db.execute(
            select(EntityIndex.version_id, EntityIndex.iri, EntityIndex.definitions,
                   Ontology.title, Ontology.shortname)
            .join(Ontology, Ontology.id == EntityIndex.ontology_id)
            .where(EntityIndex.version_id.in_({h["version_id"] for h in hits}),
                   EntityIndex.iri.in_({h["iri"] for h in hits}))
        )).all() if hits else []
        extra = {(r.version_id, r.iri): r for r in rows}
        entities = []
        for h in hits:
            r = extra.get((h["version_id"], h["iri"]))
            entities.append({
                "iri": h["iri"], "primary_label": h["label"], "short": h["short"],
                "type": h["type"], "ontology_id": h["ontology_id"],
                "ontology_title": (r.title if r else None) or h.get("ontology_shortname", ""),
                "ontology_shortname": h.get("ontology_shortname") or (r.shortname if r else None) or "",
                "version_id": h["version_id"], "source": h["source"],
                "definition": _definition(r.definitions) if r else "",
            })
        nxt = None
    else:
        sql, params = browse.predicate_for(type)
        stmt = (
            select(EntityIndex, Ontology.title, Ontology.shortname)
            .join(Ontology, Ontology.id == EntityIndex.ontology_id)
            .where(text(sql).bindparams(**params), EntityIndex.version_id.in_(vids))
        )
        if ontology:
            stmt = stmt.where(EntityIndex.ontology_id.in_(ontology))
        if cur:
            stmt = stmt.where(browse.keyset_after(cur))
        stmt = stmt.order_by(
            EntityIndex.primary_label_norm, EntityIndex.iri, EntityIndex.version_id
        ).limit(limit + 1)
        rows = (await db.execute(stmt)).all()
        page = rows[:limit]
        nxt = browse.encode_cursor(page[-1][0]) if len(rows) > limit else None
        entities = [{
            "iri": e.iri, "primary_label": _label(e, lang), "short": e.short,
            "type": e.type, "ontology_id": e.ontology_id,
            "ontology_title": title or "", "ontology_shortname": shortname or "",
            "version_id": e.version_id,
            "source": e.source or "", "definition": _definition(e.definitions),
        } for e, title, shortname in page]

    # Modes: q -> number of returned hits (top-N, no deep paging); unfiltered ->
    # public_stats total; ontology-only -> Redis-cached scoped COUNT(*).
    if q:
        approx_total = len(entities)
    elif not ontology:
        stats = await read_public_stats(db)
        approx_total = int(stats.get(_TOTAL_KEY[type], 0))
    else:
        approx_total = await _scoped_count(db, type, vids, ontology) if vids else 0

    return {"entities": entities, "next": nxt, "approx_total": approx_total, "limit": limit}


@router.get("/entities/related")
async def related_entities(
    type: str = Query(...),
    q: str = Query(..., min_length=1),
    ontology: list[str] | None = Query(None),
    k: int = Query(8, ge=1, le=50),
    lang: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Semantic neighbours of `q` among entities of `type` (pgvector over term_embeddings).

    An embedding-backend failure degrades to `{entities: [], unavailable: true}` (HTTP 200).
    """
    if type not in browse.ENTITY_TYPES:
        raise HTTPException(422, f"type must be one of {', '.join(browse.ENTITY_TYPES)}")
    vids = [v.id for v in await latest_ready_versions(db)]
    try:
        rows = await semantic_related(db, q, type, vids, ontology or None, k)
    except EmbedUnavailable as exc:
        log.warning("entities_related_unavailable", error=str(exc))
        return {"entities": [], "unavailable": True}
    return {"entities": [{
        "iri": r["iri"], "primary_label": _label(SimpleNamespace(**r), lang),
        "short": r["short"], "type": r["type"], "ontology_id": r["ontology_id"],
        "ontology_title": r["ontology_title"] or "",
        "ontology_shortname": r.get("ontology_shortname") or "", "version_id": r["version_id"],
        "source": r["source"] or "", "definition": _definition(r["definitions"]),
        "score": r["score"],
    } for r in rows], "unavailable": False}


@router.get("/entities/facets")
async def entity_facets(
    type: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Ontologies having entities of `type`, with counts (latest-ready versions only)."""
    if type not in browse.ENTITY_TYPES:
        raise HTTPException(422, f"type must be one of {', '.join(browse.ENTITY_TYPES)}")
    return {"ontologies": await browse.facet_counts(db, type)}
