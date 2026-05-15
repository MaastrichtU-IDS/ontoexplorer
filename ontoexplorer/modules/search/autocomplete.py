"""Cursor-aware MOS autocomplete engine."""
from __future__ import annotations

from dataclasses import dataclass

from ontoexplorer.modules.search.indexer import _get_redis, _prefix_key, _iri_key, normalise_label
from ontoexplorer.modules.search.mos_parser import partial_parse

_RESTRICTION_KEYWORDS = ["some", "only", "value", "Self", "min", "max", "exactly"]
_BOOLEAN_KEYWORDS = ["and", "or", "not", "(", ")"]


@dataclass
class Completion:
    text: str           # display text
    type: str           # "class" | "property" | "keyword" | "cardinality"
    iri: str | None
    short: str | None
    insert: str         # text to splice at cursor (includes closing ' for labels)


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
) -> list[Completion]:
    result = partial_parse(q, cursor)
    r = _get_redis()

    if result.token_type == "OPEN_QUOTE":
        return _entity_completions(r, version_id, result.partial, entity_type=None, limit=limit,
                                   excluded_types=frozenset({"annotation_property"}))

    if result.token_type == "EXPECT_ENTITY":
        if result.partial:
            # User is typing a bare word (no opening quote) — show entity completions directly.
            raw = _entity_completions(r, version_id, result.partial, entity_type=None, limit=limit,
                                      excluded_types=frozenset({"annotation_property"}))
            # Single-word labels don't need quotes; multi-word must be quoted.
            return [
                Completion(
                    text=c.text,
                    type=c.type,
                    iri=c.iri,
                    short=c.short,
                    insert=c.text + " " if " " not in c.text else f"'{c.text}' ",
                )
                for c in raw
            ]
        kws = _keyword_completions(["'"])  # trigger quote
        return kws

    if result.token_type == "EXPECT_KEYWORD":
        # Boolean operators first (and/or/not more common after a class), then restrictions
        kws = _keyword_completions(_BOOLEAN_KEYWORDS + _RESTRICTION_KEYWORDS)
        return kws

    if result.token_type == "EXPECT_INT":
        return [Completion(text="1", type="cardinality", iri=None, short=None, insert="1 "),
                Completion(text="2", type="cardinality", iri=None, short=None, insert="2 "),
                Completion(text="3", type="cardinality", iri=None, short=None, insert="3 ")]

    return []


def _entity_completions(
    r,
    version_id: str,
    partial: str,
    entity_type: str | None,
    limit: int,
    excluded_types: frozenset[str] | None = None,
) -> list[Completion]:
    norm = normalise_label(partial) if partial else ""
    key = _prefix_key(version_id)

    if norm:
        # Two-scan: exact-label entries first, then all prefix entries.
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
    seen_iris: set[str] = set()
    # tier_a: primary-label starts with query  (key = primary norm label)
    # tier_b: word-suffix match               (key = indexed norm label)
    tier_a: dict[str, list[dict]] = {}
    tier_b: dict[str, list[dict]] = {}

    for member in members:
        parts = member.split("|", 2)
        if len(parts) != 3:
            continue
        norm_lbl, etype, iri = parts
        if entity_type and etype != entity_type:
            continue
        if excluded_types and etype in excluded_types:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        detail = r.hgetall(_iri_key(version_id, iri))
        if not detail:
            continue
        primary_norm = normalise_label(detail.get("label", ""))
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
                ))
            else:
                for e in entities:
                    out.append(Completion(
                        text=f"{e['label']} ({e['short']})",
                        type=e["type"],
                        iri=e["iri"],
                        short=e["short"],
                        insert=f"{e['label']} ({e['short']})'",
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
