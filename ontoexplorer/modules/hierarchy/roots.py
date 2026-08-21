"""Top-level (root) entity detection for the navigation tree.

A root is an entity with no named parent. Finding them means comparing the set
of entities against the set that have a parent, which is inherently a whole-graph
question — but only the survivors are ever displayed, so nothing else should be
paid for.

Measured on DRON (784,921 classes), the earlier implementation took 61.8 s to
return 5 roots: it joined `rdfs:label` onto every class and sorted 771k rows
(44.6 s), enumerated every class having a parent with redundant type guards
(13.7 s), then subtracted. Enumerating bare IRIs and labelling only the
survivors brings the same answer back in ~13 s, and the cache below means it is
normally paid once per version rather than every five minutes.
"""

from __future__ import annotations

from ontoexplorer.modules.search.indexer import _SEARCH_TTL

# Roots are a property of an ingested version's content, which does not change
# until the version is re-ingested or re-indexed — at which point the cache is
# invalidated explicitly (see invalidate_root_cache). A short TTL just means
# re-paying a very expensive query on a schedule.
ROOT_CACHE_TTL = _SEARCH_TTL

# Labels are fetched with a VALUES block. A flat ontology makes every entity a
# root, so the list is chunked rather than emitted as one unbounded clause.
LABEL_CHUNK = 5_000

_OWL_THING = "http://www.w3.org/2002/07/owl#Thing"

_PREFIXES = """
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""


def root_cache_key(
    version_id: str,
    entity_type: str,
    limit: int,
    hide_obsolete: bool,
    lang: str | None,
) -> str:
    return f"terms_root:{version_id}:{entity_type}:{limit}:{int(hide_obsolete)}:{lang or ''}"


def invalidate_root_cache(redis, version_id: str) -> int:
    """Drop every cached root variant for one version. Returns the number removed.

    Required because ROOT_CACHE_TTL is long: a re-ingest or re-index changes the
    root set, and the cache key covers several variants (entity type, page size,
    obsolete filter, language) so overwriting only the warmed one would leave
    the rest stale for a month.
    """
    removed = 0
    for key in redis.scan_iter(match=f"terms_root:{version_id}:*"):
        redis.delete(key)
        removed += 1
    return removed


def _label_score(lang_tag: str | None, preferred: str | None) -> int:
    """Prefer the requested language, then English, then untagged, then anything."""
    if preferred and lang_tag == preferred:
        return 3
    if lang_tag == "en":
        return 2
    if lang_tag is None or lang_tag == "":
        return 1
    return 0


def _all_entities_query(graph: str, deprecated_filter: str) -> str:
    """Bare IRIs only — no label join, no ORDER BY.

    Both were the dominant cost and neither affects which entities are roots:
    the result is a set difference, and ordering is applied after labelling.
    """
    return f"""{_PREFIXES}
        SELECT ?class WHERE {{
            GRAPH <{graph}> {{
                {{ ?class a owl:Class }} UNION {{ ?class a rdfs:Class }}
                FILTER(isIRI(?class))
                {deprecated_filter}
            }}
        }}"""


def _has_parent_query(graph: str) -> str:
    """Entities with a named parent other than owl:Thing.

    No `?class a owl:Class` / `?parent a owl:Class` guards: isIRI already
    excludes blank-node parents (restrictions), and the result is only ever
    subtracted from the enumerated entity set, so a non-entity subject cannot
    survive. On DRON the guards cost 8 s and changed the result by 0 IRIs.
    """
    return f"""{_PREFIXES}
        SELECT DISTINCT ?class WHERE {{
            GRAPH <{graph}> {{
                ?class rdfs:subClassOf ?parent .
                FILTER(isIRI(?class) && isIRI(?parent) && str(?parent) != "{_OWL_THING}")
            }}
        }}"""


def _labels_query(graph: str, iris: list[str]) -> str:
    values = " ".join(f"<{iri}>" for iri in iris)
    return f"""{_PREFIXES}
        SELECT ?class ?label WHERE {{
            GRAPH <{graph}> {{
                VALUES ?class {{ {values} }}
                OPTIONAL {{ ?class rdfs:label ?label }}
            }}
        }}"""


def _fetch_labels(store, graph: str, iris: list[str], lang: str | None):
    """iri -> (label, lang_tag) for the best-scoring label of each IRI."""
    best: dict[str, tuple[str | None, int, str | None]] = {}
    for start in range(0, len(iris), LABEL_CHUNK):
        chunk = iris[start:start + LABEL_CHUNK]
        for row in store.query(_labels_query(graph, chunk)):
            iri = row["class"].value
            # Unbound OPTIONAL reads back as None; matches _row_label/_row_lang.
            cell = row["label"]
            if cell is None or not hasattr(cell, "value"):
                continue
            label = cell.value
            tag = getattr(cell, "language", None)
            score = _label_score(tag, lang)
            prev = best.get(iri)
            if prev is None or score > prev[1]:
                best[iri] = (label, score, tag)
    return {iri: (lbl, tag) for iri, (lbl, _, tag) in best.items()}


def compute_roots(
    store,
    graph: str,
    *,
    lang: str | None = None,
    deprecated_filter: str = "",
) -> list[tuple[str, str | None, str | None]]:
    """Return every root as (iri, label, lang_tag), sorted for display.

    Unpaginated: the caller slices. Sorting needs each root's label, and the
    roots are few relative to the ontology, so all of them are labelled — the
    saving is in not labelling the non-roots.
    """
    entities = {row["class"].value for row in store.query(
        _all_entities_query(graph, deprecated_filter))}
    with_parent = {row["class"].value for row in store.query(_has_parent_query(graph))}

    root_iris = sorted(entities - with_parent)
    labels = _fetch_labels(store, graph, root_iris, lang)

    roots = [(iri, *labels.get(iri, (None, None))) for iri in root_iris]
    roots.sort(key=lambda r: (r[1] or r[0]).lower())
    return roots


# Default variant the navigation tree requests (see useClassTreeNodes:
# limit 200, hide_obsolete on, no explicit language).
WARM_LIMIT = 200


def warm_root_cache(
    store,
    redis,
    version_id: str,
    graph: str,
    *,
    limit: int = WARM_LIMIT,
    deprecated_filter: str = "",
) -> int:
    """Compute the class roots and cache them. Returns how many were cached.

    Called from indexing, so the first visitor after an ingest does not pay the
    enumeration. Every other cached variant for this version is dropped first —
    they describe the pre-index content and would otherwise survive for the
    whole (long) TTL.

    The payload mirrors list_terms' response exactly, so a cache hit is
    indistinguishable from a computed one; tests pin the shape.
    """
    import json

    invalidate_root_cache(redis, version_id)
    roots = compute_roots(store, graph, lang=None, deprecated_filter=deprecated_filter)
    payload = {
        "terms": [{"iri": iri, "label": lbl, "lang": lt} for iri, lbl, lt in roots[:limit]],
        "offset": 0,
        "limit": limit,
        "parent": "root",
    }
    redis.setex(
        root_cache_key(version_id, "class", limit, True, None),
        ROOT_CACHE_TTL,
        json.dumps(payload),
    )
    return len(payload["terms"])
