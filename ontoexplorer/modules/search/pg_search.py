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
    types: list[str] | None = None,
) -> list[dict]:
    """Cross-ontology entity search via Postgres `entity_index`.

    Deduplicates by IRI (first-seen-wins across ontologies). Result list is already
    globally tier-ranked: exact label match first, then prefix, then word-suffix.

    `types`, if given, restricts to those entity_index.type values
    (e.g. ['class', 'object_property']). None or empty = no type filter.
    """
    from ontoexplorer.modules.search.pg_indexer import split_compound_labels
    # Decamelize the query so `PizzaSauce` and `pizza sauce` normalize alike.
    norm = normalise_label(split_compound_labels(q))
    if not norm:
        return []

    type_filter_sql = "AND ei.type = ANY(:types)" if types else ""

    # Stage 1: prefix-on-primary-label. Uses the text_pattern_ops btree.
    # Filter to ready non-deprecated versions via the JOIN.
    # Within tier-1 (prefix match), sort by label LENGTH then alphabetically so
    # the label closest in length to the query wins. Without this, an unrelated
    # short label that happens to be lex-earlier sorts above the obvious target:
    # e.g. `membran` → "membrana tympaniformis" outranking "membrane".
    prefix_sql = text(f"""
        SELECT ei.iri, ei.primary_label, ei.short, ei.type,
               ei.version_id, ei.ontology_id, ei.source,
               ei.primary_label_norm,
               CASE WHEN ei.primary_label_norm = :norm THEN 0 ELSE 1 END AS tier
        FROM entity_index ei
        JOIN versions v ON v.id = ei.version_id
        WHERE v.status NOT IN ('pending','failed','deprecated')
          AND ei.primary_label_norm LIKE :prefix
          {type_filter_sql}
        ORDER BY tier, LENGTH(ei.primary_label_norm), ei.primary_label_norm, ei.iri
        LIMIT :over
    """)
    over = limit * _OVERSAMPLE
    params: dict = {"norm": norm, "prefix": norm + "%", "over": over}
    if types:
        params["types"] = list(types)
    result = await db.execute(prefix_sql, params)
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
    # Multi-word queries are AND'd; the last token is prefix-matched (user may
    # still be typing it).
    if len(merged) < limit:
        tsv_sql = text(f"""
            SELECT ei.iri, ei.primary_label, ei.short, ei.type,
                   ei.version_id, ei.ontology_id, ei.source,
                   ei.primary_label_norm
            FROM entity_index ei
            JOIN versions v ON v.id = ei.version_id
            WHERE v.status NOT IN ('pending','failed','deprecated')
              AND ei.search_tsv @@ to_tsquery('simple', :tsq)
              AND ei.primary_label_norm NOT LIKE :prefix
              {type_filter_sql}
            ORDER BY LENGTH(ei.primary_label_norm), ei.primary_label_norm, ei.iri
            LIMIT :over
        """)
        params2: dict = {"tsq": _build_tsquery(norm), "prefix": norm + "%", "over": over}
        if types:
            params2["types"] = list(types)
        result = await db.execute(tsv_sql, params2)
        for row in result.all():
            if row.iri in seen_iris:
                continue
            seen_iris.add(row.iri)
            merged.append(_row_to_dict(row))
            if len(merged) >= limit:
                break

    return merged[:limit]


async def pg_autocomplete_entities(
    db: AsyncSession,
    partial: str,
    limit: int,
    excluded_types: frozenset[str] | None = None,
    ontology_ids: list[str] | None = None,
) -> list[dict]:
    """Cross-ontology entity autocomplete via Postgres entity_index.

    Mirrors the pg_entity_search two-stage strategy (fast prefix → tsv fallback),
    but also JOINs the `ontologies` table so the API can emit ontology_shortname
    next to each completion. Deduplicates by IRI across ontologies; the surviving
    row keeps the first-seen ontology's shortname.

    Returns list of dicts: {iri, label, short, type, version_id, ontology_id,
    ontology_shortname, primary_label_norm}. Caller is responsible for wrapping
    each dict into a Completion with the correct `insert` text.
    """
    from ontoexplorer.modules.search.pg_indexer import split_compound_labels
    norm = normalise_label(split_compound_labels(partial)) if partial else ""
    # Single-letter prefixes match tens of thousands of rows (e.g. 'c' → ~22k);
    # autocomplete on a single letter isn't useful and triggers a full table sort.
    # Bail early — the frontend should debounce to ≥2 chars anyway.
    if len(norm) < 2:
        return []

    type_filter_sql = ""
    if excluded_types:
        type_filter_sql = "AND ei.type <> ALL(:excluded)"

    ontology_filter_sql = ""
    if ontology_ids:
        ontology_filter_sql = "AND ei.ontology_id = ANY(:ontology_ids)"

    # Stage 1: btree text_pattern_ops prefix scan.
    # Within tier-1, sort by label LENGTH so the label closest in size to the
    # query wins over coincidentally-alphabetically-earlier but longer labels
    # (e.g. `membran` → "membrane" beats "membrana tympaniformis").
    prefix_sql = text(f"""
        SELECT ei.iri, ei.primary_label, ei.short, ei.type,
               ei.version_id, ei.ontology_id, ei.primary_label_norm,
               COALESCE(o.shortname, '') AS ontology_shortname
        FROM entity_index ei
        JOIN versions v ON v.id = ei.version_id
        JOIN ontologies o ON o.id = ei.ontology_id
        WHERE v.status NOT IN ('pending','failed','deprecated')
          AND ei.primary_label_norm LIKE :prefix
          {type_filter_sql}
          {ontology_filter_sql}
        ORDER BY CASE WHEN ei.primary_label_norm = :norm THEN 0 ELSE 1 END,
                 LENGTH(ei.primary_label_norm), ei.primary_label_norm, ei.iri
        LIMIT :over
    """)
    params: dict = {"norm": norm, "prefix": norm + "%", "over": limit * _OVERSAMPLE}
    if excluded_types:
        params["excluded"] = list(excluded_types)
    if ontology_ids:
        params["ontology_ids"] = ontology_ids
    result = await db.execute(prefix_sql, params)

    seen_iris: set[str] = set()
    out: list[dict] = []
    for row in result.all():
        if row.iri in seen_iris:
            continue
        seen_iris.add(row.iri)
        out.append({
            "iri": row.iri,
            "label": row.primary_label,
            "short": row.short,
            "type": row.type,
            "version_id": row.version_id,
            "ontology_id": row.ontology_id,
            "ontology_shortname": row.ontology_shortname,
            "primary_label_norm": row.primary_label_norm,
        })
        if len(out) >= limit:
            return out[:limit]

    # Stage 2: tsv fallback for word-suffix matches (label or synonym contains
    # `<norm>` as a non-leading token). Only invoked when prefix tier under-fills.
    tsv_sql = text(f"""
        SELECT ei.iri, ei.primary_label, ei.short, ei.type,
               ei.version_id, ei.ontology_id, ei.primary_label_norm,
               COALESCE(o.shortname, '') AS ontology_shortname
        FROM entity_index ei
        JOIN versions v ON v.id = ei.version_id
        JOIN ontologies o ON o.id = ei.ontology_id
        WHERE v.status NOT IN ('pending','failed','deprecated')
          AND ei.search_tsv @@ to_tsquery('simple', :tsq)
          AND ei.primary_label_norm NOT LIKE :prefix
          {type_filter_sql}
          {ontology_filter_sql}
        ORDER BY LENGTH(ei.primary_label_norm), ei.primary_label_norm, ei.iri
        LIMIT :over
    """)
    params2: dict = {
        "tsq": _build_tsquery(norm),  # multi-word AND, last token prefix
        "prefix": norm + "%",
        "over": limit * _OVERSAMPLE,
    }
    if excluded_types:
        params2["excluded"] = list(excluded_types)
    if ontology_ids:
        params2["ontology_ids"] = ontology_ids
    result = await db.execute(tsv_sql, params2)

    for row in result.all():
        if row.iri in seen_iris:
            continue
        seen_iris.add(row.iri)
        out.append({
            "iri": row.iri,
            "label": row.primary_label,
            "short": row.short,
            "type": row.type,
            "version_id": row.version_id,
            "ontology_id": row.ontology_id,
            "ontology_shortname": row.ontology_shortname,
            "primary_label_norm": row.primary_label_norm,
        })
        if len(out) >= limit:
            break

    return out[:limit]


def _sanitize_tsquery_token(t: str) -> str:
    """Strip anything that would confuse to_tsquery's grammar (operators, quotes)."""
    return "".join(c for c in t if c.isalnum() or c in "_-")


def _build_tsquery(norm: str) -> str:
    """Build a tsquery from a normalized multi-word query.

    Single-word "pizza"          → "pizza:*"
    Two-word    "pizza sauce"    → "pizza & sauce:*"   (AND, last is prefix)
    Three-word  "cell death pathway" → "cell & death & pathway:*"

    The last token gets the :* prefix-match because the user may still be
    typing it. Earlier tokens are exact-lexeme requirements.
    """
    tokens = [_sanitize_tsquery_token(t) for t in norm.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0] + ":*"
    return " & ".join(tokens[:-1]) + " & " + tokens[-1] + ":*"


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
