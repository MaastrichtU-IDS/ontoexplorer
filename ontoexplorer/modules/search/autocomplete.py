"""Cursor-aware MOS autocomplete engine."""
from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class Completion:
    text: str           # display text
    type: str           # "class" | "property" | "keyword" | "cardinality"
    iri: str | None
    short: str | None
    insert: str         # text to splice at cursor (includes closing ' for labels)
    lang: str | None = None
    cross_language: bool = False


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
