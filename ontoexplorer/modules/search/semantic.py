"""pgvector cosine-similarity search over term embeddings."""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.modules.search.embedder import embed_query


async def semantic_search(
    query: str,
    db: AsyncSession,
    version_ids: list[str],
    limit: int = 10,
) -> list[dict]:
    """Return entities semantically similar to query across the given versions.

    Single SQL query joining `term_embeddings` → `entity_index` for metadata, so we
    don't need to fan out to Redis for HGETALLs. A row with no entity_index join
    (primary_label NULL) has no label to show and is skipped (#242 Stage 3 — the
    Redis `:iri:` hash fallback is gone now the index is Postgres-only).
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

    for row in rows:
        iri = row.iri
        if iri in seen_iris:
            continue
        seen_iris.add(iri)

        # entity_index is the sole metadata source (#242 Stage 3). A row that didn't
        # join (primary_label NULL) has no label to render — skip it.
        if row.primary_label is None:
            continue
        label = row.primary_label
        short = row.short or ""
        source = row.source or ""

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
