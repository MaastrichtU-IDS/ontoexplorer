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


def get_completions(
    q: str,
    cursor: int,
    version_id: str,
    limit: int = 10,
) -> list[Completion]:
    result = partial_parse(q, cursor)
    r = _get_redis()

    if result.token_type == "OPEN_QUOTE":
        return _entity_completions(r, version_id, result.partial, entity_type=None, limit=limit)

    if result.token_type == "EXPECT_ENTITY":
        # After some/only/not/and/or/(  — figure out if we expect class or property
        # Heuristic: after a restriction keyword (some/only/value/min N/max N/exactly N) → class
        # At start / after boolean → either
        kws = _keyword_completions(["'"])  # trigger quote
        return kws

    if result.token_type == "EXPECT_KEYWORD":
        # After a complete entity ref — offer restriction + boolean keywords
        kws = _keyword_completions(_RESTRICTION_KEYWORDS + _BOOLEAN_KEYWORDS)
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
) -> list[Completion]:
    norm = normalise_label(partial) if partial else ""
    key = _prefix_key(version_id)

    if norm:
        min_val = f"[{norm}"
        max_val = f"[{norm}\xff"
        members = r.zrangebylex(key, min_val, max_val, start=0, num=limit * 4)
    else:
        members = r.zrange(key, 0, limit * 4 - 1)

    # Group members by normalised label to detect ambiguity
    by_norm_label: dict[str, list[dict]] = {}
    for member in members:
        parts = member.split("|", 2)
        if len(parts) != 3:
            continue
        norm_lbl, etype, iri = parts
        if entity_type and etype != entity_type:
            continue
        detail = r.hgetall(_iri_key(version_id, iri))
        if not detail:
            continue
        by_norm_label.setdefault(norm_lbl, []).append(detail)

    completions: list[Completion] = []
    for norm_lbl, entities in by_norm_label.items():
        if len(entities) == 1:
            e = entities[0]
            completions.append(Completion(
                text=e["label"],
                type=e["type"],
                iri=e["iri"],
                short=e["short"],
                insert=f"{e['label']}'",
            ))
        else:
            for e in entities:
                completions.append(Completion(
                    text=f"{e['label']} ({e['short']})",
                    type=e["type"],
                    iri=e["iri"],
                    short=e["short"],
                    insert=f"{e['label']} ({e['short']})'",
                ))
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
