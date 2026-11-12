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

# Force a CUSTOM plan for the partitioned entity_index enrichment lookups.
#
# With a bound `version_id = ANY($1)` array, PostgreSQL switches the prepared
# statement to a GENERIC plan after ~5 executions. A generic plan prunes partitions
# only at execution time but still takes an AccessShareLock on ALL 64 entity_index
# partitions (and their 12 indexes each) at setup — 832 partition locks per request,
# regardless of how few versions the candidates span. Under concurrency that overflows
# the shared lock table: the #402 failure (`out of shared memory / increase
# max_locks_per_transaction`, ~54% of requests at 150 VU). The earlier split (#403)
# did not help: EXPLAIN with inlined literals showed pruning (a one-shot custom plan),
# but asyncpg sends a bound array → generic plan → all 64 locked.
#
# A custom plan prunes at PLAN time to just the candidates' partitions (measured on
# dev via pg_locks: 832 → 234 partition locks for a fleet-wide top-20). SET LOCAL
# scopes this to the current request transaction only; both query 1 (vector) and this
# enrichment already run in that one transaction.
_FORCE_CUSTOM_PLAN = text("SET LOCAL plan_cache_mode = force_custom_plan")


async def semantic_search(
    query: str,
    db: AsyncSession,
    version_ids: list[str],
    limit: int = 10,
) -> list[dict]:
    """Return entities semantically similar to query across the given versions.

    Two queries, not one (#402). Query 1 is the vector top-N over `term_embeddings`
    alone (+ `versions` for ontology_id) — it keeps the HNSW index and touches NONE
    of the 64 `entity_index` partitions. Query 2 enriches only those ≤`limit`
    candidates from `entity_index`, keyed to the concrete versions they came from, so
    partition pruning limits it to that handful of partitions. The old single query
    `LEFT JOIN`ed `entity_index` with a runtime version_id, which the planner can't
    prune → it locked all 64 partitions per request and, under concurrency, exhausted
    the Postgres shared lock table (`out of shared memory`).

    A candidate with no `entity_index` row (no label) is skipped — same as the old
    LEFT-JOIN-then-skip (#242 Stage 3: the Redis `:iri:` hash fallback is gone now the
    index is Postgres-only).
    """
    if not version_ids or not query.strip():
        return []

    try:
        qvec = await asyncio.to_thread(embed_query, query)
    except Exception as e:
        log.warning("semantic_search_embed_failed", error=str(e))
        return []

    vec_str = "[" + ",".join(f"{x:.8f}" for x in qvec) + "]"

    # Query 1 — vector top-N, term_embeddings only (0 entity_index partition locks).
    try:
        vsql = text("""
            SELECT te.entity_iri AS iri, te.entity_type AS type,
                   te.version_id, v.ontology_id,
                   1 - (te.embedding <=> CAST(:vec AS vector)) AS score
            FROM term_embeddings te
            JOIN versions v ON v.id = te.version_id
            WHERE te.version_id = ANY(:ids)
            ORDER BY te.embedding <=> CAST(:vec AS vector)
            LIMIT :lim
        """)
        cand = (await db.execute(
            vsql, {"vec": vec_str, "ids": version_ids, "lim": limit})).all()
    except Exception as e:
        log.warning("semantic_search_query_failed", error=str(e))
        return []

    if not cand:
        return []

    # Query 2 — enrich the candidates from entity_index, keyed to their concrete
    # (version_id, iri). force_custom_plan makes version_id = ANY(<few>) prune to just
    # those partitions instead of locking all 64 (see _FORCE_CUSTOM_PLAN, #402).
    try:
        vids = list({c.version_id for c in cand})
        iris = list({c.iri for c in cand})
        await db.execute(_FORCE_CUSTOM_PLAN)
        esql = text("""
            SELECT version_id, iri, primary_label, short, source
            FROM entity_index
            WHERE version_id = ANY(:vids) AND iri = ANY(:iris)
        """)
        meta = {(m.version_id, m.iri): m
                for m in (await db.execute(esql, {"vids": vids, "iris": iris})).all()}
    except Exception as e:
        log.warning("semantic_search_enrich_failed", error=str(e))
        return []

    seen_iris: set[str] = set()
    out: list[dict] = []

    for row in cand:
        iri = row.iri
        if iri in seen_iris:
            continue
        # entity_index is the sole metadata source; a candidate with no row (or NULL
        # primary_label) has no label to render — skip it.
        m = meta.get((row.version_id, iri))
        if m is None or m.primary_label is None:
            continue
        seen_iris.add(iri)

        out.append({
            "iri": iri,
            "label": m.primary_label,
            "short": m.short or "",
            "type": row.type,
            "source": m.source or "",
            "match_type": "semantic",
            "score": round(float(row.score), 4),
            "version_id": row.version_id,
            "ontology_id": row.ontology_id,
        })
        if len(out) >= limit:
            break

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
        # Query 1 — vector top-k over term_embeddings (+ versions for the optional
        # ontology filter). No entity_index join → 0 of the 64 partition locks (#402).
        onto_clause = "AND v.ontology_id = ANY(:onts)" if ontology_ids else ""
        vsql = text(f"""
            SELECT te.entity_iri AS iri, te.version_id,
                   1 - (te.embedding <=> CAST(:vec AS vector)) AS score
            FROM term_embeddings te
            JOIN versions v ON v.id = te.version_id
            WHERE te.entity_type = :type
              AND te.version_id = ANY(:ids)
              {onto_clause}
            ORDER BY te.embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        params = {"vec": vec_str, "type": type, "ids": version_ids, "k": k}
        if ontology_ids:
            params["onts"] = ontology_ids
        cand = (await db.execute(vsql, params)).all()
        if not cand:
            return []
        # Query 2 — enrich the k candidates from entity_index, keyed to their concrete
        # (version_id, iri) so partition pruning limits it to those few partitions.
        # force_custom_plan is required for the bound version_id array to prune rather
        # than lock all 64 partitions (see _FORCE_CUSTOM_PLAN, #402).
        # INNER semantics preserved: a candidate with no entity_index row is dropped.
        vids = list({c.version_id for c in cand})
        iris = list({c.iri for c in cand})
        await db.execute(_FORCE_CUSTOM_PLAN)
        esql = text("""
            SELECT ei.version_id, ei.iri, ei.primary_label, ei.labels, ei.short,
                   ei.type, ei.ontology_id, ei.source, ei.definitions,
                   o.title AS ontology_title, o.shortname AS ontology_shortname
            FROM entity_index ei
            JOIN ontologies o ON o.id = ei.ontology_id
            WHERE ei.version_id = ANY(:vids) AND ei.iri = ANY(:iris)
        """)
        meta = {(m["version_id"], m["iri"]): m for m in
                (await db.execute(esql, {"vids": vids, "iris": iris})).mappings().all()}
        out = []
        for c in cand:
            m = meta.get((c.version_id, c.iri))
            if m is None:
                continue
            out.append({**m, "score": round(float(c.score), 4)})
        return out

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
