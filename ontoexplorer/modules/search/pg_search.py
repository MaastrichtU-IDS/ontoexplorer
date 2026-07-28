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

import base64
import json
from typing import Any

from sqlalchemy import bindparam, text
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
    version_id: str | None = None,
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

    # Scope to a single version (per-ontology DL-query autocomplete).
    version_filter_sql = ""
    if version_id:
        version_filter_sql = "AND ei.version_id = :version_id"

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
          {version_filter_sql}
        ORDER BY CASE WHEN ei.primary_label_norm = :norm THEN 0 ELSE 1 END,
                 LENGTH(ei.primary_label_norm), ei.primary_label_norm, ei.iri
        LIMIT :over
    """)
    params: dict = {"norm": norm, "prefix": norm + "%", "over": limit * _OVERSAMPLE}
    if excluded_types:
        params["excluded"] = list(excluded_types)
    if ontology_ids:
        params["ontology_ids"] = ontology_ids
    if version_id:
        params["version_id"] = version_id
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
          {version_filter_sql}
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
    if version_id:
        params2["version_id"] = version_id
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

    # Stage 3: trigram fuzzy fallback (typo tolerance). Only when the exact
    # prefix + tsvector tiers under-fill, and only for >=3 chars (trigrams are
    # noise below that). `<%` is index-accelerated by the gin_trgm_ops index on
    # primary_label_norm and matches the query against the best word/substring,
    # so `adhesn` still surfaces `cell adhesion`. Fuzzy hits rank last.
    if len(out) < limit and len(norm) >= 3:
        # Lower the word-similarity threshold for this fallback (default 0.6 is
        # too strict for short-drop typos); scoped to the transaction.
        await db.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = 0.4"))
        fuzzy_sql = text(f"""
            SELECT ei.iri, ei.primary_label, ei.short, ei.type,
                   ei.version_id, ei.ontology_id, ei.primary_label_norm,
                   COALESCE(o.shortname, '') AS ontology_shortname
            FROM entity_index ei
            JOIN versions v ON v.id = ei.version_id
            JOIN ontologies o ON o.id = ei.ontology_id
            WHERE v.status NOT IN ('pending','failed','deprecated')
              AND :norm <% ei.primary_label_norm
              AND ei.primary_label_norm NOT LIKE :prefix
              {type_filter_sql}
              {ontology_filter_sql}
              {version_filter_sql}
            ORDER BY word_similarity(:norm, ei.primary_label_norm) DESC,
                     LENGTH(ei.primary_label_norm), ei.iri
            LIMIT :over
        """)
        params3: dict = {"norm": norm, "prefix": norm + "%", "over": limit * _OVERSAMPLE}
        if excluded_types:
            params3["excluded"] = list(excluded_types)
        if ontology_ids:
            params3["ontology_ids"] = ontology_ids
        if version_id:
            params3["version_id"] = version_id
        for row in (await db.execute(fuzzy_sql, params3)).all():
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


async def pg_is_property(db: AsyncSession, ident: str, ontology_ids: list[str] | None = None,
                         version_id: str | None = None) -> bool:
    """True if `ident` (an IRI, or an exact label) is an object/data property in
    the (optionally scoped) entity_index. Used by the MOS autocomplete to offer
    restriction keywords after a property."""
    from ontoexplorer.modules.search.pg_indexer import split_compound_labels
    is_iri = ident.startswith("http://") or ident.startswith("https://")
    norm = "" if is_iri else normalise_label(split_compound_labels(ident))
    if not is_iri and not norm:
        return False
    onto_sql = "AND ei.ontology_id = ANY(:ontology_ids)" if ontology_ids else ""
    version_sql = "AND ei.version_id = :version_id" if version_id else ""
    match_sql = "ei.iri = :ident" if is_iri else "ei.primary_label_norm = :norm"
    sql = text(f"""
        SELECT 1 FROM entity_index ei
        JOIN versions v ON v.id = ei.version_id
        WHERE v.status NOT IN ('pending','failed','deprecated')
          AND ei.type IN ('object_property','data_property')
          AND {match_sql}
          {onto_sql}
          {version_sql}
        LIMIT 1
    """)
    params: dict = {"ident": ident} if is_iri else {"norm": norm}
    if ontology_ids:
        params["ontology_ids"] = ontology_ids
    if version_id:
        params["version_id"] = version_id
    return (await db.execute(sql, params)).first() is not None


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


async def pg_property_iri(db: AsyncSession, ident: str, version_ids: list[str]) -> str | None:
    """Resolve a property reference (IRI, exact label, or CURIE/short) to its IRI
    within the given versions' entity_index. Used to look up a restriction's
    property when suggesting relevant fillers."""
    if ident.startswith("http://") or ident.startswith("https://"):
        return ident
    if not version_ids:
        return None
    from ontoexplorer.modules.search.pg_indexer import split_compound_labels
    norm = normalise_label(split_compound_labels(ident))
    sql = text("""
        SELECT ei.iri FROM entity_index ei
        WHERE ei.version_id = ANY(:vids)
          AND ei.type IN ('object_property', 'data_property')
          AND (ei.primary_label_norm = :norm OR ei.short = :ident OR ei.iri = :ident)
        LIMIT 1
    """)
    row = (await db.execute(sql, {"vids": version_ids, "norm": norm, "ident": ident})).first()
    return row[0] if row else None


async def pg_entities_by_iri(db: AsyncSession, iris: list[str], version_ids: list[str],
                             limit: int) -> list[dict]:
    """Fetch display rows (label/short/type/shortname) for a set of IRIs within
    the given versions, deduped by IRI across versions. Rows come back in the
    order the IRIs were passed in — callers rank the IRIs (e.g. by filler
    frequency) and that ranking is preserved here. The shortest label is chosen
    as each IRI's representative when a version has several."""
    if not iris or not version_ids:
        return []
    sql = text("""
        SELECT DISTINCT ON (ei.iri)
               ei.iri, ei.primary_label, ei.short, ei.type,
               ei.version_id, ei.ontology_id, ei.primary_label_norm,
               COALESCE(o.shortname, '') AS ontology_shortname
        FROM entity_index ei
        JOIN ontologies o ON o.id = ei.ontology_id
        WHERE ei.version_id = ANY(:vids) AND ei.iri = ANY(:iris)
              AND ei.type <> 'annotation_property'
        ORDER BY ei.iri, LENGTH(ei.primary_label_norm)
    """)
    rows = (await db.execute(sql, {"vids": version_ids, "iris": list(iris)})).all()
    rank = {iri: i for i, iri in enumerate(iris)}
    rows = sorted(rows, key=lambda r: rank.get(r.iri, len(rank)))
    return [{
        "iri": r.iri, "label": r.primary_label, "short": r.short, "type": r.type,
        "version_id": r.version_id, "ontology_id": r.ontology_id,
        "ontology_shortname": r.ontology_shortname, "primary_label_norm": r.primary_label_norm,
    } for r in rows[:limit]]


_LISTABLE_TYPES = {
    "class", "object_property", "data_property", "annotation_property", "individual",
}


def encode_entity_cursor(label: str, iri: str, version: str | None = None) -> str:
    d: dict = {"l": label, "i": iri}
    if version is not None:
        d["v"] = version
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).decode()


def decode_entity_cursor(s: str) -> tuple[str, str, str | None] | None:
    """Decode an opaque cursor to (label_norm, iri, version_id|None); None if malformed.

    Collapsed-mode cursors carry no version (one row per IRI), so `v` is optional.
    """
    try:
        d = json.loads(base64.urlsafe_b64decode(s.encode()))
        return (d["l"], d["i"], d.get("v"))
    except Exception:
        return None


async def _latest_version_ids(db: AsyncSession) -> list[str]:
    """The default (pin-aware, version-aware) version id per ontology.

    Reuses the same selection the rest of the app uses so the listing shows one
    version per ontology (killing same-ontology multi-version duplicates) and so
    a row links to the version that actually serves that term.
    """
    from ontoexplorer.modules.search.versions import latest_ready_versions
    return [v.id for v in await latest_ready_versions(db)]


def _occ(ontology_id: str, version_id: str) -> dict:
    return {"ontology_id": ontology_id, "version_id": version_id}


async def list_entities_by_type(
    db: AsyncSession,
    entity_type: str,
    limit: int,
    after: tuple[str, str, str | None] | None,
    collapse: bool = False,
) -> tuple[list[dict], str | None]:
    """Keyset-paginated cross-repository listing of one `entity_index.type`.

    Scoped to the default version per ontology (see `_latest_version_ids`).
    Each returned entity has the shape
    `{iri, label, short, type, source, ontologies: [{ontology_id, version_id}]}`.

    - `collapse=False` (default): one entity per (ontology occurrence) of an IRI,
      ordered/keyset by (primary_label_norm, iri, version_id); `ontologies` has one
      entry.
    - `collapse=True`: one entity per IRI, ordered/keyset by (primary_label_norm,
      iri); `ontologies` aggregates every ontology whose default version has it.

    `after` is the previous page's last key (label_norm, iri, version_id|None);
    None for the first page. Fetches limit+1 rows to detect a further page.
    Returns (entities, next_cursor); next_cursor is None on the final page.
    """
    vids = await _latest_version_ids(db)
    if not vids:
        return [], None

    if not collapse:
        params: dict = {"t": entity_type, "vids": vids, "lim": limit + 1}
        keyset = ""
        if after is not None:
            al, ai, av = after
            keyset = """
              AND ( ei.primary_label_norm > :al
                    OR (ei.primary_label_norm = :al AND ei.iri > :ai)
                    OR (ei.primary_label_norm = :al AND ei.iri = :ai AND ei.version_id > :av) )
            """
            params |= {"al": al, "ai": ai, "av": av or ""}
        sql = text(f"""
            SELECT ei.iri, ei.primary_label, ei.short, ei.type,
                   ei.version_id, ei.ontology_id, ei.source, ei.primary_label_norm
            FROM entity_index ei
            WHERE ei.type = :t
              AND ei.version_id IN :vids
              {keyset}
            ORDER BY ei.primary_label_norm, ei.iri, ei.version_id
            LIMIT :lim
        """).bindparams(bindparam("vids", expanding=True))
        rows = (await db.execute(sql, params)).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        entities = [{
            "iri": r.iri, "label": r.primary_label, "short": r.short, "type": r.type,
            "source": r.source or "", "ontologies": [_occ(r.ontology_id, r.version_id)],
        } for r in page]
        next_cursor = (
            encode_entity_cursor(page[-1].primary_label_norm, page[-1].iri, page[-1].version_id)
            if has_more and page else None
        )
        return entities, next_cursor

    # collapse=True: one row per IRI. Portable two-step (GROUP BY/min + fetch
    # occurrences) instead of Postgres-only json_agg, so it also runs on SQLite.
    params = {"t": entity_type, "vids": vids, "lim": limit + 1}
    keyset = ""
    if after is not None:
        al, ai, _ = after
        keyset = """
          HAVING ( MIN(ei.primary_label_norm) > :al
                   OR (MIN(ei.primary_label_norm) = :al AND ei.iri > :ai) )
        """
        params |= {"al": al, "ai": ai}
    group_sql = text(f"""
        SELECT ei.iri,
               MIN(ei.primary_label) AS label,
               MIN(ei.short) AS short,
               MIN(ei.primary_label_norm) AS label_norm
        FROM entity_index ei
        WHERE ei.type = :t
          AND ei.version_id IN :vids
        GROUP BY ei.iri
        {keyset}
        ORDER BY MIN(ei.primary_label_norm), ei.iri
        LIMIT :lim
    """).bindparams(bindparam("vids", expanding=True))
    grouped = (await db.execute(group_sql, params)).all()
    has_more = len(grouped) > limit
    page = grouped[:limit]
    if not page:
        return [], None

    iris = [g.iri for g in page]
    occ_sql = text("""
        SELECT ei.iri, ei.ontology_id, ei.version_id
        FROM entity_index ei
        WHERE ei.type = :t
          AND ei.version_id IN :vids
          AND ei.iri IN :iris
        ORDER BY ei.ontology_id
    """).bindparams(bindparam("vids", expanding=True), bindparam("iris", expanding=True))
    occ_rows = (await db.execute(occ_sql, {"t": entity_type, "vids": vids, "iris": iris})).all()
    by_iri: dict[str, list[dict]] = {}
    for o in occ_rows:
        by_iri.setdefault(o.iri, []).append(_occ(o.ontology_id, o.version_id))

    entities = [{
        "iri": g.iri, "label": g.label, "short": g.short, "type": entity_type,
        "source": "", "ontologies": by_iri.get(g.iri, []),
    } for g in page]
    next_cursor = (
        encode_entity_cursor(page[-1].label_norm, page[-1].iri)
        if has_more else None
    )
    return entities, next_cursor


async def count_entities_by_type(db: AsyncSession, entity_type: str, collapse: bool = False) -> int:
    vids = await _latest_version_ids(db)
    if not vids:
        return 0
    col = "COUNT(DISTINCT ei.iri)" if collapse else "COUNT(*)"
    sql = text(f"""
        SELECT {col}
        FROM entity_index ei
        WHERE ei.type = :t
          AND ei.version_id IN :vids
    """).bindparams(bindparam("vids", expanding=True))
    return int((await db.execute(sql, {"t": entity_type, "vids": vids})).scalar_one())
