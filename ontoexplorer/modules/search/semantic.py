"""pgvector cosine-similarity search over term embeddings."""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.modules.search.embedder import embed_query
from ontoexplorer.modules.search.indexer import _get_redis, _iri_key


async def semantic_search(
    query: str,
    db: AsyncSession,
    version_ids: list[str],
    limit: int = 10,
) -> list[dict]:
    """Return entities semantically similar to query across the given versions.

    Single SQL query joining `term_embeddings` → `entity_index` for metadata, so we
    don't need to fan out to Redis for HGETALLs. Falls back to Redis for any IRIs
    that aren't in entity_index yet (e.g. very new ingests before backfill).
    """
    if not version_ids or not query.strip():
        return []

    try:
        qvec = await asyncio.to_thread(embed_query, query)
        vec_str = "[" + ",".join(f"{x:.8f}" for x in qvec) + "]"
        sql = text("""
            SELECT te.entity_iri AS iri, te.entity_type AS type,
                   te.version_id, v.ontology_id,
                   1 - (te.embedding <=> CAST(:vec AS vector)) AS score,
                   ei.primary_label, ei.short, ei.source
            FROM term_embeddings te
            JOIN versions v ON v.id = te.version_id
            LEFT JOIN entity_index ei
                   ON ei.version_id = te.version_id AND ei.iri = te.entity_iri
            WHERE te.version_id = ANY(:ids)
            ORDER BY te.embedding <=> CAST(:vec AS vector)
            LIMIT :lim
        """)
        result = await db.execute(sql, {"vec": vec_str, "ids": version_ids, "lim": limit})
        rows = result.all()
    except Exception:
        return []

    if not rows:
        return []

    seen_iris: set[str] = set()
    out: list[dict] = []
    # Cache the Redis client only for the (rare) entity_index miss fallback.
    r = _get_redis()

    for row in rows:
        iri = row.iri
        if iri in seen_iris:
            continue
        seen_iris.add(iri)

        if row.primary_label is not None:
            label = row.primary_label
            short = row.short or ""
            source = row.source or ""
        else:
            # Fallback for IRIs not yet mirrored to entity_index.
            entity = await asyncio.to_thread(r.hgetall, _iri_key(row.version_id, iri))
            if not entity:
                continue
            label = entity.get("primary_label") or entity.get("label", iri)
            short = entity.get("short", "")
            source = entity.get("source", "")

        out.append({
            "iri": iri,
            "label": label,
            "short": short,
            "type": row.type,
            "source": source,
            "match_type": "semantic",
            "score": round(float(row.score), 4),
            "version_id": row.version_id,
            "ontology_id": row.ontology_id,
        })

    return out
