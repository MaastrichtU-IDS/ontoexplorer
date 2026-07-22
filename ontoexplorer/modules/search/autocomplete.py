"""Cursor-aware MOS autocomplete engine."""
from __future__ import annotations

from dataclasses import dataclass

from ontoexplorer.modules.search.indexer import _get_redis, _prefix_key, _iri_key, normalise_label
from ontoexplorer.modules.search.mos_parser import PartialParseResult, partial_parse

def _parse_lang_from_member(member: str) -> tuple[str, str, str, str]:
    """Split a v2 sorted-set key into (norm, lang, entity_type, iri)."""
    parts = member.split("|", 3)
    if len(parts) == 4:
        return parts[0], parts[1], parts[2], parts[3]
    # Graceful fallback for v1 keys: norm|type|iri
    p = member.split("|", 2)
    return (p[0], "", p[1], p[2]) if len(p) == 3 else ("", "", "", "")


_RESTRICTION_KEYWORDS = ["some", "only", "value", "min", "max", "exactly", "Self"]
_BOOLEAN_KEYWORDS = ["and", "or", "not", "(", ")"]

# Restriction keywords apply to object/data properties (not annotation properties).
_PROPERTY_TYPES = frozenset({"object_property", "data_property", "property"})


def _is_property(r, version_id: str, ident: str) -> bool:
    """Is the entity identified by `ident` (IRI, or exact label) an object/data
    property? Used to decide restriction-keyword vs boolean-keyword completion."""
    if ident.startswith("http://") or ident.startswith("https://"):
        detail = r.hgetall(_iri_key(version_id, ident))
        return bool(detail) and detail.get("type") in _PROPERTY_TYPES
    norm = normalise_label(ident)
    if not norm:
        return False
    # Exact-label scan of the prefix index (handles v1 `norm|type|iri` and
    # v2 `norm|lang|type|iri` member formats via _parse_lang_from_member).
    members = r.zrangebylex(_prefix_key(version_id), f"[{norm}|", f"[{norm}|\xff", start=0, num=25)
    for m in members:
        m_norm, _lang, m_type, _iri = _parse_lang_from_member(m)
        if m_norm == norm and m_type in _PROPERTY_TYPES:
            return True
    return False


@dataclass
class Completion:
    text: str           # display text
    type: str           # "class" | "property" | "keyword" | "cardinality"
    iri: str | None
    short: str | None
    insert: str         # text to splice at cursor (includes closing ' for labels)
    lang: str | None = None
    cross_language: bool = False


# Built-in OWL classes injected into autocomplete when they match the partial.
# Not declared as owl:Class in ontology files so absent from the index until re-indexed.
_BUILTIN_CLASSES = [
    Completion(
        text="owl:Thing",
        type="class",
        iri="http://www.w3.org/2002/07/owl#Thing",
        short="owl:Thing",
        insert="owl:Thing ",
    ),
]


def get_completions(
    q: str,
    cursor: int,
    version_id: str,
    limit: int = 10,
    lang: str | None = None,
) -> list[Completion]:
    result = partial_parse(q, cursor)
    r = _get_redis()

    if result.token_type == "OPEN_QUOTE":
        return _entity_completions(r, version_id, result.partial, entity_type=None, limit=limit,
                                   excluded_types=frozenset({"annotation_property"}), lang=lang)

    if result.token_type == "EXPECT_ENTITY":
        if result.partial:
            # User is typing a bare word (no opening quote) — show entity completions directly.
            raw = _entity_completions(r, version_id, result.partial, entity_type=None, limit=limit,
                                      excluded_types=frozenset({"annotation_property"}), lang=lang)
            # Single-word labels don't need quotes; multi-word must be quoted.
            return [
                Completion(
                    text=c.text,
                    type=c.type,
                    iri=c.iri,
                    short=c.short,
                    insert=c.text + " " if " " not in c.text else f"'{c.text}' ",
                    lang=c.lang,
                    cross_language=c.cross_language,
                )
                for c in raw
            ]
        kws = _keyword_completions(["not", "'"])  # not is valid before any entity
        return kws

    if result.token_type == "EXPECT_KEYWORD":
        # After an object/data property MOS expects a restriction keyword
        # (some/only/value/min/max/exactly/Self); after a class (or a closed
        # group) it expects a boolean (and/or). Resolve the preceding entity.
        if result.prev_entity and _is_property(r, version_id, result.prev_entity):
            return _keyword_completions(_RESTRICTION_KEYWORDS)
        return _keyword_completions(_BOOLEAN_KEYWORDS)

    if result.token_type == "EXPECT_INT":
        return [Completion(text="1", type="cardinality", iri=None, short=None, insert="1 "),
                Completion(text="2", type="cardinality", iri=None, short=None, insert="2 "),
                Completion(text="3", type="cardinality", iri=None, short=None, insert="3 ")]

    return []


def pg_rows_to_completions(rows: list[dict], close_quote: bool) -> list[Completion]:
    """Wrap pg_autocomplete_entities rows (relevance-ranked, multi-token) into MOS
    Completions for the DL-query autocomplete.

    close_quote=True:  the user already typed an opening quote — insert closes it.
    close_quote=False: bare token — single-word inserts as-is, multi-word is quoted.
    Same-label collisions get a ' (short)' suffix so they're distinguishable.
    """
    from collections import Counter
    label_counts = Counter((row.get("label") or "") for row in rows)
    out: list[Completion] = []
    for row in rows:
        label = row.get("label") or row.get("iri") or ""
        short = row.get("short")
        text = f"{label} ({short})" if label and label_counts[label] > 1 and short else label
        if close_quote:
            insert = f"{text}'"
        else:
            insert = f"{text} " if " " not in text else f"'{text}' "
        out.append(Completion(
            text=text,
            type=row.get("type") or "class",
            iri=row.get("iri"),
            short=short,
            insert=insert,
        ))
    return out


# ── Unified MOS autocomplete (Postgres) ──────────────────────────────────────
# One implementation used by every MOS-expression autocomplete endpoint
# (per-ontology and cross-ontology). Entities come from the Postgres
# entity_index (ranked, multi-token); keywords/cardinalities are context-driven.

_ENTITY_OPEN_KEYWORDS = ["not", "inverse", "'"]
_CARDINALITIES = ["1", "2", "3"]


def keyword_set_for(token_type: str, prev_is_property: bool,
                    after_inverse: bool = False) -> list[str]:
    """The keyword/cardinality tokens valid at a non-entity MOS context. Pure and
    unit-tested — the single source of truth for which keywords to offer."""
    if token_type == "EXPECT_KEYWORD":
        # After an object/data property → restriction; after a class → boolean.
        return _RESTRICTION_KEYWORDS if prev_is_property else _BOOLEAN_KEYWORDS
    if token_type == "EXPECT_INT":
        return _CARDINALITIES
    # EXPECT_ENTITY with no partial. Right after `inverse` a property is expected,
    # so offer an opening paren (Protégé-style `inverse (P)`) or quote — no
    # `not`/nested `inverse`. Otherwise an entity, a negation, or an
    # inverse-property restriction can start here.
    if after_inverse:
        return ["(", "'"]
    return _ENTITY_OPEN_KEYWORDS


def _kw_dict(kw: str) -> dict:
    # "(" and "'" open a token so take no trailing space; everything else does.
    ktype = "cardinality" if kw in _CARDINALITIES else "keyword"
    insert = kw if kw in ("(", "'") else kw + " "
    return {"text": kw, "type": ktype, "iri": None, "short": None,
            "insert": insert, "lang": None, "cross_language": False, "ontology_shortname": ""}


def _entity_dicts(rows: list[dict], close_quote: bool) -> list[dict]:
    """Wrap pg_autocomplete_entities rows into completion dicts with MOS insert
    semantics (close the open quote, or quote multi-word bare labels) and
    same-label disambiguation."""
    from collections import Counter
    label_counts = Counter((r.get("label") or "") for r in rows)
    out: list[dict] = []
    for r in rows:
        label = r.get("label") or r.get("iri") or ""
        short = r.get("short")
        text = f"{label} ({short})" if label and label_counts[label] > 1 and short else label
        insert = f"{text}'" if close_quote else (f"{text} " if " " not in text else f"'{text}' ")
        out.append({
            "text": text, "type": r.get("type") or "class", "iri": r.get("iri"),
            "short": short, "insert": insert, "lang": None, "cross_language": False,
            "ontology_shortname": r.get("ontology_shortname", ""),
        })
    return out


def _observed_filler_iris(prop_iri: str, graph_iris: list[str], limit: int,
                          keyword: str | None = None) -> list[str]:
    """IRIs used as fillers of `prop_iri` (or its sub-properties) across the given
    graphs, ordered by frequency of use (most-used first; IRI tiebreaker for a
    deterministic order).

    For a `value` restriction the fillers are INDIVIDUALS drawn from owl:hasValue;
    for every other keyword (some/only/min/max/exactly) they are CLASSES drawn
    from someValuesFrom / allValuesFrom / onClass."""
    from ontoexplorer.clients.oxigraph import get_store
    OWL = "http://www.w3.org/2002/07/owl#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"
    values = " ".join(f"<{g}>" for g in graph_iris)
    if keyword == "value":
        filler_clause = f"?r <{OWL}hasValue> ?f ."
    else:
        filler_clause = (
            f"{{ ?r <{OWL}someValuesFrom> ?f }} UNION "
            f"{{ ?r <{OWL}allValuesFrom> ?f }} UNION "
            f"{{ ?r <{OWL}onClass> ?f }}"
        )
    query = f"""
        SELECT ?f (COUNT(DISTINCT ?r) AS ?n) WHERE {{
            VALUES ?g {{ {values} }}
            GRAPH ?g {{
                ?r <{OWL}onProperty> ?p .
                ?p <{RDFS}subPropertyOf>* <{prop_iri}> .
                {filler_clause}
                FILTER(isIRI(?f))
            }}
        }} GROUP BY ?f ORDER BY DESC(?n) ?f LIMIT {int(limit)}
    """
    try:
        return [row["f"].value for row in get_store().query(query)]
    except Exception:
        return []


async def mos_autocomplete(
    db, q: str, cursor: int, limit: int, *,
    version_id: str | None = None,
    ontology_ids: list[str] | None = None,
    filler_scope: list[tuple[str, str]] | None = None,
    excluded_types: frozenset[str] = frozenset({"annotation_property"}),
) -> tuple[list[dict], PartialParseResult]:
    """Cursor-aware MOS autocomplete for either a single version (`version_id`)
    or a set of ontologies (`ontology_ids`). Returns (completion dicts, parse
    context). The single shared implementation behind all MOS endpoints.

    `filler_scope` is a list of (version_id, graph_iri) pairs. When supplied, a
    filler position right after a restriction keyword suggests classes actually
    used as fillers of the property across those graphs; otherwise it falls back
    to `not` / opening-quote.
    """
    import asyncio
    from ontoexplorer.modules.search.pg_search import (
        pg_autocomplete_entities, pg_entities_by_iri, pg_is_property, pg_property_iri,
    )
    ctx = partial_parse(q, cursor)
    tt = ctx.token_type

    # Entity contexts (quoted, or a bare word still being typed).
    if tt == "OPEN_QUOTE" or (tt == "EXPECT_ENTITY" and bool(ctx.partial)):
        rows = await pg_autocomplete_entities(
            db, partial=ctx.partial, limit=limit, excluded_types=excluded_types,
            ontology_ids=ontology_ids, version_id=version_id,
        )
        return _entity_dicts(rows, close_quote=(tt == "OPEN_QUOTE")), ctx

    # Filler position (empty partial right after a restriction keyword): suggest
    # the entities actually used as fillers of that property across the scoped
    # ontology graphs — individuals for `value`, classes otherwise.
    if (tt == "EXPECT_ENTITY" and not ctx.partial and ctx.restriction_property
            and filler_scope):
        vids = [v for v, _ in filler_scope]
        graphs = [g for _, g in filler_scope]
        prop_iri = await pg_property_iri(db, ctx.restriction_property, vids)
        if prop_iri:
            iris = await asyncio.to_thread(
                _observed_filler_iris, prop_iri, graphs, limit * 4, ctx.restriction_keyword)
            rows = await pg_entities_by_iri(db, iris, vids, limit)
            if rows:
                # `value` takes a bare individual — `not` (a class-expression
                # operator) is not valid there, so offer only an opening quote.
                extra = [_kw_dict("'")] if ctx.restriction_keyword == "value" \
                    else [_kw_dict("not"), _kw_dict("'")]
                return _entity_dicts(rows, close_quote=False) + extra, ctx

    # Keyword contexts. Restriction-vs-boolean depends on the preceding entity.
    prev_is_property = bool(ctx.prev_entity) and await pg_is_property(
        db, ctx.prev_entity, ontology_ids=ontology_ids, version_id=version_id)
    return [_kw_dict(k) for k in keyword_set_for(tt, prev_is_property, ctx.after_inverse)], ctx


# ── Legacy Redis autocomplete (OLS entity lookup) ─────────────────────────────

def _entity_completions(
    r,
    version_id: str,
    partial: str,
    entity_type: str | None,
    limit: int,
    excluded_types: frozenset[str] | None = None,
    lang: str | None = None,
) -> list[Completion]:
    norm = normalise_label(partial) if partial else ""
    key = _prefix_key(version_id)

    if norm:
        if lang:
            # Preferred-lang exact scan first, then broad prefix fallback (same as no-lang path).
            # The broad scan uses "[{norm}" (no pipe) so multi-word entries like
            # "at time|en|..." are captured when searching "at".
            pref_members = r.zrangebylex(key, f"[{norm}|{lang}|", f"[{norm}|{lang}|\xff",
                                          start=0, num=max(limit, 20))
            all_members = r.zrangebylex(key, f"[{norm}", f"[{norm}\xff",
                                         start=0, num=limit * 8)
            pref_set = set(pref_members)
            members = list(pref_members) + [m for m in all_members if m not in pref_set]
        else:
            # Original two-scan for no-lang case
            # Space (0x20) < pipe (0x7C) in Redis lex order, so "cell adhesion|..."
            # sorts BEFORE "cell|..." (exact) in a single prefix scan.
            exact_members = r.zrangebylex(key, f"[{norm}|", f"[{norm}|\xff", start=0, num=max(limit, 20))
            all_members   = r.zrangebylex(key, f"[{norm}",  f"[{norm}\xff",  start=0, num=limit * 8)
            exact_set = set(exact_members)
            members = list(exact_members) + [m for m in all_members if m not in exact_set]
    else:
        members = r.zrange(key, 0, limit * 4 - 1)

    # Separate into two tiers based on whether the PRIMARY label starts with the
    # query.  Word-suffix index entries (e.g. "cell" indexing "T cell receptor")
    # are tier-B; labels that genuinely start with the query are tier-A.
    # First pass: filter candidates and collect unique IRIs
    seen_iris: set[str] = set()
    candidates: list[tuple[str, str, str, str]] = []  # (norm_lbl, lang_tag, etype, iri)
    for member in members:
        norm_lbl, lang_tag, etype, iri = _parse_lang_from_member(member)
        if not iri:
            continue
        if entity_type and etype != entity_type:
            continue
        if excluded_types and etype in excluded_types:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        candidates.append((norm_lbl, lang_tag, etype, iri))

    # Fetch all detail hashes in one pipeline round-trip
    pipe = r.pipeline(transaction=False)
    for _, _, _, iri in candidates:
        pipe.hgetall(_iri_key(version_id, iri))
    details = pipe.execute()

    # Second pass: bucket into tiers
    tier_a: dict[str, list[dict]] = {}
    tier_b: dict[str, list[dict]] = {}
    for (norm_lbl, lang_tag, etype, iri), detail in zip(candidates, details):
        if not detail:
            continue
        is_cross = bool(lang) and lang_tag != lang
        primary_norm = normalise_label(detail.get("label", ""))
        detail["_lang_tag"] = lang_tag
        detail["_cross_language"] = is_cross
        if not norm or primary_norm.startswith(norm):
            tier_a.setdefault(primary_norm, []).append(detail)
        else:
            tier_b.setdefault(norm_lbl, []).append(detail)

    def _build(bucket: dict[str, list[dict]], out: list[Completion]) -> None:
        for _key, entities in bucket.items():
            if len(entities) == 1:
                e = entities[0]
                out.append(Completion(
                    text=e["label"],
                    type=e["type"],
                    iri=e["iri"],
                    short=e["short"],
                    insert=f"{e['label']}'",
                    lang=e.get("_lang_tag") or None,
                    cross_language=bool(e.get("_cross_language")),
                ))
            else:
                for e in entities:
                    out.append(Completion(
                        text=f"{e['label']} ({e['short']})",
                        type=e["type"],
                        iri=e["iri"],
                        short=e["short"],
                        insert=f"{e['label']} ({e['short']})'",
                        lang=e.get("_lang_tag") or None,
                        cross_language=bool(e.get("_cross_language")),
                    ))
            if len(out) >= limit:
                return

    completions: list[Completion] = []
    _build(tier_a, completions)
    if len(completions) < limit:
        _build(tier_b, completions)

    # Inject built-in classes (e.g. owl:Thing) when the partial matches and they're
    # not already present from the index (added by re-indexing, absent in old indexes).
    if len(completions) < limit:
        already = {c.iri for c in completions}
        for builtin in _BUILTIN_CLASSES:
            if builtin.iri in already:
                continue
            if entity_type and builtin.type != entity_type:
                continue
            if excluded_types and builtin.type in excluded_types:
                continue
            norm_text = normalise_label(builtin.text)
            norm_short = normalise_label(builtin.short or "")
            if not norm or norm_text.startswith(norm) or norm_short.startswith(norm):
                completions.append(builtin)
            if len(completions) >= limit:
                break

    return completions[:limit]


def _keyword_completions(keywords: list[str]) -> list[Completion]:
    return [
        Completion(
            text=kw,
            type="keyword",
            iri=None,
            short=None,
            insert=f" {kw} " if kw not in ("(", ")", "'") else kw,
        )
        for kw in keywords
    ]
