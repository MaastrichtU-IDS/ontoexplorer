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

    Returns [] if version_ids is empty, query is blank, or no embeddings exist.
    Deduplicates by IRI, keeping the highest-scoring occurrence.
    """
    if not version_ids or not query.strip():
        return []

    try:
        qvec = await asyncio.to_thread(embed_query, query)

        vec_str = "[" + ",".join(f"{x:.8f}" for x in qvec) + "]"
        sql = text("""
            SELECT te.entity_iri, te.entity_type, te.version_id, v.ontology_id,
                   1 - (te.embedding <=> CAST(:vec AS vector)) AS score
            FROM term_embeddings te
            JOIN versions v ON v.id = te.version_id
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

    r = _get_redis()

    seen_iris: set[str] = set()
    out: list[dict] = []
    for row in rows:
        iri = row.entity_iri
        if iri in seen_iris:
            continue
        seen_iris.add(iri)

        entity = await asyncio.to_thread(r.hgetall, _iri_key(row.version_id, iri))
        if not entity:
            continue

        out.append({
            "iri": iri,
            "label": entity.get("primary_label") or entity.get("label", iri),
            "short": entity.get("short", ""),
            "type": row.entity_type,
            "source": entity.get("source", ""),
            "match_type": "semantic",
            "score": round(float(row.score), 4),
            "version_id": row.version_id,
            "ontology_id": row.ontology_id,
        })

    return out
