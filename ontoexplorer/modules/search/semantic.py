"""pgvector cosine-similarity search over term embeddings."""
from __future__ import annotations

import asyncio
import math

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import EntityIndex, Ontology, TermEmbedding
from ontoexplorer.modules.search.embedder import embed_query

log = structlog.get_logger()


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
    except Exception as e:
        log.warning("semantic_search_embed_failed", error=str(e))
        return []

    try:
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
    except Exception as e:
        log.warning("semantic_search_query_failed", error=str(e))
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


class EmbedUnavailable(Exception):
    """The embedding backend failed; distinct from DB errors so callers can degrade."""


async def semantic_related(
    db: AsyncSession,
    query: str,
    type: str,
    version_ids: list[str],
    ontology_ids: list[str] | None,
    k: int,
) -> list[dict]:
    """Nearest entities of one `type` to `query`, by cosine similarity.

    Unlike `semantic_search`, an embed-backend failure PROPAGATES (as `EmbedUnavailable`) so the caller can
    report the backend as unavailable (vs. "no embeddings" = empty list). Rows are
    returned as dicts carrying the raw `labels`/`definitions` of `entity_index` plus
    `score`; display shaping is the caller's job.
    """
    if not version_ids or not query.strip() or k < 1:
        return []

    try:
        qvec = await asyncio.to_thread(embed_query, query)
    except Exception as exc:
        raise EmbedUnavailable(str(exc)) from exc

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        vec_str = "[" + ",".join(f"{x:.8f}" for x in qvec) + "]"
        onto_clause = "AND ei.ontology_id = ANY(:onts)" if ontology_ids else ""
        sql = text(f"""
            SELECT ei.iri, ei.primary_label, ei.labels, ei.short, ei.type,
                   ei.ontology_id, o.title AS ontology_title, o.shortname AS ontology_shortname,
                   ei.version_id,
                   ei.source, ei.definitions,
                   1 - (te.embedding <=> CAST(:vec AS vector)) AS score
            FROM term_embeddings te
            JOIN entity_index ei
                 ON ei.version_id = te.version_id AND ei.iri = te.entity_iri
            JOIN ontologies o ON o.id = ei.ontology_id
            WHERE te.entity_type = :type
              AND te.version_id = ANY(:ids)
              {onto_clause}
            ORDER BY te.embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        params = {"vec": vec_str, "type": type, "ids": version_ids, "k": k}
        if ontology_ids:
            params["onts"] = ontology_ids
        rows = (await db.execute(sql, params)).mappings().all()
        return [{**r, "score": round(float(r["score"]), 4)} for r in rows]

    # Non-Postgres (sqlite test lane): no pgvector operators, rank in Python.
    stmt = (
        select(TermEmbedding.embedding, EntityIndex, Ontology.title, Ontology.shortname)
        .join(EntityIndex, (EntityIndex.version_id == TermEmbedding.version_id)
              & (EntityIndex.iri == TermEmbedding.entity_iri))
        .join(Ontology, Ontology.id == EntityIndex.ontology_id)
        .where(TermEmbedding.entity_type == type,
               TermEmbedding.version_id.in_(version_ids))
    )
    if ontology_ids:
        stmt = stmt.where(EntityIndex.ontology_id.in_(ontology_ids))
    qn = math.sqrt(sum(x * x for x in qvec)) or 1.0
    scored = []
    for emb, e, title, shortname in (await db.execute(stmt)).all():
        emb = [float(x) for x in emb]
        en = math.sqrt(sum(x * x for x in emb)) or 1.0
        score = sum(a * b for a, b in zip(qvec, emb)) / (qn * en)
        scored.append({
            "iri": e.iri, "primary_label": e.primary_label, "labels": e.labels,
            "short": e.short, "type": e.type, "ontology_id": e.ontology_id,
            "ontology_title": title, "ontology_shortname": shortname,
            "version_id": e.version_id, "source": e.source,
            "definitions": e.definitions, "score": round(score, 4),
        })
    scored.sort(key=lambda r: -r["score"])
    return scored[:k]
