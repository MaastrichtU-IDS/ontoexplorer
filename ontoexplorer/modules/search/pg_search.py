"""Postgres-backed cross-ontology entity search.

Replaces the Redis fan-out path with a single SQL query over `entity_index`.
Two-stage strategy:
  1. Fast prefix lookup via btree(`primary_label_norm` text_pattern_ops) — handles the
     90% case where users type the start of a term (`"cell"`, `"apoptosis"`).
  2. Word-suffix fallback via tsvector(`search_tsv` GIN) — only invoked when the
     prefix stage returned fewer than `limit` unique IRIs.

This mirrors the Redis index's behaviour (exact > prefix > word-suffix tier ordering)
while keeping the common path fast.
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.modules.search.indexer import normalise_label

# Fetch up to this many rows per stage so the global Python-side dedup has enough
# variety even after collapsing duplicates across ontologies.
_OVERSAMPLE = 5


def _row_to_dict(row: Any) -> dict:
    return {
        "iri": row.iri,
        "label": row.primary_label,
        "short": row.short,
        "type": row.type,
        "version_id": row.version_id,
        "ontology_id": row.ontology_id,
        "source": row.source or "",
    }


async def pg_entity_search(
    db: AsyncSession,
    q: str,
    limit: int,
) -> list[dict]:
    """Cross-ontology entity search via Postgres `entity_index`.

    Deduplicates by IRI (first-seen-wins across ontologies). Result list is already
    globally tier-ranked: exact label match first, then prefix, then word-suffix.
    """
    norm = normalise_label(q)
    if not norm:
        return []

    # Stage 1: prefix-on-primary-label. Uses the text_pattern_ops btree.
    # Filter to ready non-deprecated versions via the JOIN.
    prefix_sql = text("""
        SELECT ei.iri, ei.primary_label, ei.short, ei.type,
               ei.version_id, ei.ontology_id, ei.source,
               ei.primary_label_norm,
               CASE WHEN ei.primary_label_norm = :norm THEN 0 ELSE 1 END AS tier
        FROM entity_index ei
        JOIN versions v ON v.id = ei.version_id
        WHERE v.status NOT IN ('pending','failed','deprecated')
          AND ei.primary_label_norm LIKE :prefix
        ORDER BY tier, ei.primary_label_norm, ei.iri
        LIMIT :over
    """)
    over = limit * _OVERSAMPLE
    result = await db.execute(prefix_sql, {"norm": norm, "prefix": norm + "%", "over": over})
    prefix_rows = result.all()

    seen_iris: set[str] = set()
    merged: list[dict] = []
    for row in prefix_rows:
        if row.iri in seen_iris:
            continue
        seen_iris.add(row.iri)
        merged.append(_row_to_dict(row))
        if len(merged) >= limit:
            return merged[:limit]

    # Stage 2: word-suffix fallback via tsvector. Only runs if prefix tier didn't fill.
    # The :* postfix on the lexeme matches any token starting with the query.
    if len(merged) < limit:
        tsv_sql = text("""
            SELECT ei.iri, ei.primary_label, ei.short, ei.type,
                   ei.version_id, ei.ontology_id, ei.source,
                   ei.primary_label_norm
            FROM entity_index ei
            JOIN versions v ON v.id = ei.version_id
            WHERE v.status NOT IN ('pending','failed','deprecated')
              AND ei.search_tsv @@ to_tsquery('simple', :tsq)
              AND ei.primary_label_norm NOT LIKE :prefix
            ORDER BY ei.primary_label_norm, ei.iri
            LIMIT :over
        """)
        result = await db.execute(
            tsv_sql,
            {"tsq": _tsquery_lexeme(norm) + ":*", "prefix": norm + "%", "over": over},
        )
        for row in result.all():
            if row.iri in seen_iris:
                continue
            seen_iris.add(row.iri)
            merged.append(_row_to_dict(row))
            if len(merged) >= limit:
                break

    return merged[:limit]


def _tsquery_lexeme(norm: str) -> str:
    """Strip whitespace/operators so a multi-word query doesn't break to_tsquery.

    For multi-word inputs ("cell death"), use the FIRST token plus :* — the simple
    dictionary tokenizer already handles individual word matching, and the prefix
    semantics are about completing the user's current keystroke.
    """
    first = norm.split()[0] if norm.split() else norm
    # Strip anything that would confuse to_tsquery's grammar.
    return "".join(c for c in first if c.isalnum() or c in "_-")


def rrf_merge(
    keyword: list[dict],
    semantic: list[dict],
    limit: int,
    k: int = 60,
) -> list[dict]:
    """Reciprocal-rank fusion of two ranked lists.

    RRF score for item d = sum_{l in lists} 1/(k + rank_l(d)). Items appearing only
    in one list still get a contribution. k=60 is the literature default and avoids
    over-rewarding rank-1 (1/61 vs 1/62 is a tiny gap, so ties stay close).

    Returns deduplicated list capped at `limit`.
    """
    scores: dict[str, float] = {}
    rep: dict[str, dict] = {}

    for rank, item in enumerate(keyword, start=1):
        iri = item["iri"]
        scores[iri] = scores.get(iri, 0.0) + 1.0 / (k + rank)
        rep.setdefault(iri, item)

    for rank, item in enumerate(semantic, start=1):
        iri = item["iri"]
        scores[iri] = scores.get(iri, 0.0) + 1.0 / (k + rank)
        rep.setdefault(iri, item)

    fused = sorted(rep.values(), key=lambda d: -scores[d["iri"]])
    for d in fused:
        d["rrf_score"] = round(scores[d["iri"]], 5)
    return fused[:limit]
