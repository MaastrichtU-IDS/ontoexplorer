"""Redis entity search index for ontology versions."""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass

import redis

from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
from ontoexplorer.config import get_settings

_SEARCH_TTL = 30 * 24 * 3600  # 30 days, same as ELK classification TTL

_LABEL_PREDICATES = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://www.w3.org/2004/02/skos/core#altLabel",
    "http://schema.org/name",
]


@dataclass
class IndexStats:
    version_id: str
    class_count: int
    property_count: int
    individual_count: int


def normalise_label(label: str) -> str:
    """Lowercase, strip punctuation (except : for CURIEs), collapse whitespace, strip articles."""
    label = label.lower()
    label = re.sub(r"[^\w\s:<>]", " ", label)
    label = re.sub(r"\s+", " ", label).strip()
    label = re.sub(r"^(the|a|an)\s+", "", label)
    return label


def _prefix_key(version_id: str) -> str:
    return f"search:entities:{version_id}:prefix"


def _iri_key(version_id: str, iri: str) -> str:
    encoded = urllib.parse.quote(iri, safe="")
    return f"search:entities:{version_id}:iri:{encoded}"


def _type_key(version_id: str, entity_type: str) -> str:
    return f"search:entities:{version_id}:type:{entity_type}"


def _meta_key(version_id: str) -> str:
    return f"search:meta:{version_id}"


def _stats_cache_key(version_id: str) -> str:
    return f"version_stats:{version_id}"


def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _short_iri(iri: str) -> str:
    if "#" in iri:
        return iri.split("#")[-1]
    return iri.rstrip("/").split("/")[-1]


_CURIE_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*):\s*([A-Za-z0-9_\-\.]+)$")


def _rank_key(detail: dict, norm_query: str) -> tuple:
    """Return sort key: (tier, label). Tier 0=exact, 1=prefix, 2=word-suffix."""
    lbl = normalise_label(detail.get("label", ""))
    if lbl == norm_query:
        return (0, lbl)
    if lbl.startswith(norm_query):
        return (1, lbl)
    return (2, lbl)


def entity_lookup(
    version_id: str,
    prefix: str,
    entity_type: str | None,
    limit: int,
) -> list[dict]:
    """Prefix-search entities. Returns list of entity dicts with label/type/iri/short."""
    r = _get_redis()

    _PROP_SUBTYPES_SET = {"object_property", "data_property", "annotation_property"}

    def _detail_type_matches(detail: dict) -> bool:
        if entity_type is None:
            return True
        stored = detail.get("type", "")
        if entity_type == "property":
            return stored in _PROP_SUBTYPES_SET or stored == "property"
        return stored == entity_type

    # Direct full-IRI lookup
    if prefix.startswith("http://") or prefix.startswith("https://"):
        detail = r.hgetall(_iri_key(version_id, prefix.strip()))
        if detail and _detail_type_matches(detail):
            return [detail]
        return []

    # CURIE lookup — search by the local name (the short form is indexed)
    curie_match = _CURIE_PATTERN.match(prefix.strip())
    if curie_match:
        local_name = curie_match.group(2)
        norm = normalise_label(local_name)
    else:
        norm = normalise_label(prefix)

    if not norm:
        return []

    key = _prefix_key(version_id)

    # The sorted set stores entries as "{norm_label}|{type}|{iri}".
    # Because space (0x20) < pipe (0x7C), word-suffix entries like
    # "cell death b cells|..." sort BEFORE the exact entry "cell death|..."
    # in a single lexicographic scan.  We avoid that by doing two scans:
    #   1. Exact-label scan: "[{norm}|" → "[{norm}|\xff"  — only entries
    #      whose label part is exactly norm.
    #   2. Full prefix scan:  "[{norm}"  → "[{norm}\xff"  — everything.
    # Exact matches are always emitted first; the full scan fills the rest.

    # Use at least 50 for the exact scan so common query terms (e.g. "cell death")
    # don't miss the canonical entry when many synonyms share the same label.
    exact_members = r.zrangebylex(key, f"[{norm}|", f"[{norm}|\xff", start=0, num=max(limit, 50))
    all_members = r.zrangebylex(key, f"[{norm}", f"[{norm}\xff", start=0, num=limit * 5)

    _PROP_SUBTYPES = {"object_property", "data_property", "annotation_property"}

    def _type_matches(etype: str) -> bool:
        if entity_type is None:
            return True
        if entity_type == "property":
            return etype in _PROP_SUBTYPES or etype == "property"
        return etype == entity_type

    seen_iris: set[str] = set()
    candidates: list[dict] = []

    def _collect(members: list[str]) -> None:
        for member in members:
            parts = member.split("|", 2)
            if len(parts) != 3:
                continue
            _, etype, iri = parts
            if not _type_matches(etype):
                continue
            if iri in seen_iris:
                continue
            seen_iris.add(iri)
            detail = r.hgetall(_iri_key(version_id, iri))
            if not detail:
                continue
            candidates.append(detail)

    _collect(exact_members)   # tier-0 results first
    _collect(all_members)     # then prefix / word-suffix results

    # Within each tier, sort alphabetically by label for stable ordering
    candidates.sort(key=lambda d: _rank_key(d, norm))
    return candidates[:limit]


def build_index(version_id: str, ontology_id: str) -> IndexStats:
    """Extract all entities and labels from Oxigraph and write the Redis entity index."""
    from datetime import datetime, timezone

    r = _get_redis()
    named_graph = graph_iri(ontology_id, version_id)

    # Collect entity IRIs with their types
    entities: dict[str, str] = {}  # iri -> "class" | "object_property" | "data_property" | "annotation_property"
    for entity_type, owl_type in [
        ("class",               "http://www.w3.org/2002/07/owl#Class"),
        ("object_property",     "http://www.w3.org/2002/07/owl#ObjectProperty"),
        ("data_property",       "http://www.w3.org/2002/07/owl#DatatypeProperty"),
        ("annotation_property", "http://www.w3.org/2002/07/owl#AnnotationProperty"),
    ]:
        q = f"""
            SELECT DISTINCT ?entity WHERE {{
                GRAPH <{named_graph}> {{
                    ?entity a <{owl_type}> .
                    FILTER(isIRI(?entity))
                }}
            }}
        """
        for sol in sparql_query(q):
            iri = sol["entity"].value
            if iri not in entities:
                entities[iri] = entity_type

    # Collect labels per entity
    labels_by_iri: dict[str, list[str]] = {iri: [] for iri in entities}
    pred_filter = " ".join(f"<{p}>" for p in _LABEL_PREDICATES)
    q = f"""
        SELECT ?entity ?label WHERE {{
            GRAPH <{named_graph}> {{
                VALUES ?pred {{ {pred_filter} }}
                ?entity ?pred ?label .
                FILTER(isIRI(?entity) && isLiteral(?label))
            }}
        }}
    """
    for sol in sparql_query(q):
        iri = sol["entity"].value
        if iri in labels_by_iri:
            labels_by_iri[iri].append(sol["label"].value)

    # Write to Redis via pipeline
    prefix_key = _prefix_key(version_id)
    r.delete(prefix_key)

    pipe = r.pipeline(transaction=False)
    class_count = property_count = 0

    for iri, entity_type in entities.items():
        labels = labels_by_iri.get(iri, [])
        short = _short_iri(iri)
        primary_label = labels[0] if labels else short
        all_labels = labels + ([short] if short not in labels else [])

        pipe.hset(_iri_key(version_id, iri), mapping={
            "label": primary_label,
            "type":  entity_type,
            "iri":   iri,
            "short": short,
            "synonyms": "|".join(labels[1:]) if len(labels) > 1 else "",
        })
        pipe.expire(_iri_key(version_id, iri), _SEARCH_TTL)
        pipe.sadd(_type_key(version_id, entity_type), iri)

        for label_text in all_labels:
            norm = normalise_label(label_text)
            if not norm:
                continue
            # Full-label prefix entry (matches from the start)
            pipe.zadd(prefix_key, {f"{norm}|{entity_type}|{iri}": 0})
            # Word-suffix entries so mid-label words are searchable
            # e.g. "cell death" also gets "death|..." so "death" matches it
            words = norm.split()
            for i in range(1, len(words)):
                suffix = " ".join(words[i:])
                pipe.zadd(prefix_key, {f"{suffix}|{entity_type}|{iri}": 0})

        if entity_type == "class":
            class_count += 1
        else:
            property_count += 1

    pipe.expire(prefix_key, _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "class"),               _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "object_property"),     _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "data_property"),       _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "annotation_property"), _SEARCH_TTL)
    pipe.setex(_meta_key(version_id), _SEARCH_TTL, json.dumps({
        "indexed_at":      datetime.now(timezone.utc).isoformat(),
        "class_count":     class_count,
        "property_count":  property_count,
        "individual_count": 0,
    }))
    pipe.execute()

    _build_tree_cache(version_id, ontology_id, entities, labels_by_iri, r)
    _populate_stats_cache(version_id, ontology_id, entities, r)

    return IndexStats(
        version_id=version_id,
        class_count=class_count,
        property_count=property_count,
        individual_count=0,
    )


def _build_tree_cache(
    version_id: str,
    ontology_id: str,
    entities: dict[str, str],
    labels_by_iri: dict[str, list[str]],
    r: redis.Redis,
) -> None:
    """Pre-compute root class/property lists and cache in Redis.

    Uses two simple join queries instead of correlated FILTER NOT EXISTS so this
    stays fast even for ontologies with 50k+ classes (e.g. GO).
    """
    named_graph = graph_iri(ontology_id, version_id)
    _OWL_THING = "http://www.w3.org/2002/07/owl#Thing"

    # Deprecated entities — excluded from tree views
    deprecated_q = f"""
        SELECT DISTINCT ?c WHERE {{
            GRAPH <{named_graph}> {{
                ?c <http://www.w3.org/2002/07/owl#deprecated> ?d .
                FILTER(str(?d) = "true")
            }}
        }}
    """
    deprecated_iris = {sol["c"].value for sol in sparql_query(deprecated_q)}

    # Classes with a named-class parent — these are NOT roots
    non_root_class_q = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?child WHERE {{
            GRAPH <{named_graph}> {{
                ?child rdfs:subClassOf ?parent .
                ?child a owl:Class .
                ?parent a owl:Class .
                FILTER(isIRI(?child) && isIRI(?parent) && str(?parent) != "{_OWL_THING}")
            }}
        }}
    """
    non_root_classes = {sol["child"].value for sol in sparql_query(non_root_class_q)}

    # Classes that have at least one direct subclass
    has_children_class_q = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?parent WHERE {{
            GRAPH <{named_graph}> {{
                ?child rdfs:subClassOf ?parent .
                ?child a owl:Class .
                ?parent a owl:Class .
                FILTER(isIRI(?child) && isIRI(?parent))
            }}
        }}
    """
    has_children_classes = {sol["parent"].value for sol in sparql_query(has_children_class_q)}

    # Properties with a named parent — not roots
    non_root_prop_q = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?child WHERE {{
            GRAPH <{named_graph}> {{
                ?child rdfs:subPropertyOf ?parent .
                FILTER(isIRI(?child) && isIRI(?parent))
                {{ ?child a owl:ObjectProperty }} UNION
                {{ ?child a owl:DatatypeProperty }} UNION
                {{ ?child a owl:AnnotationProperty }}
            }}
        }}
    """
    non_root_props = {sol["child"].value for sol in sparql_query(non_root_prop_q)}

    # Properties with children
    has_children_prop_q = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?parent WHERE {{
            GRAPH <{named_graph}> {{
                ?child rdfs:subPropertyOf ?parent .
                FILTER(isIRI(?child) && isIRI(?parent))
                {{ ?child a owl:ObjectProperty }} UNION
                {{ ?child a owl:DatatypeProperty }} UNION
                {{ ?child a owl:AnnotationProperty }}
            }}
        }}
    """
    has_children_props = {sol["parent"].value for sol in sparql_query(has_children_prop_q)}

    def _primary_label(iri: str) -> str | None:
        labels = labels_by_iri.get(iri, [])
        return labels[0] if labels else None

    _DEFAULT_LIMIT = 100

    def _sort_key(iri: str) -> str:
        return (_primary_label(iri) or iri).lower()

    root_classes = sorted(
        (iri for iri, t in entities.items()
         if t == "class" and iri not in non_root_classes and iri not in deprecated_iris),
        key=_sort_key,
    )
    class_terms = [
        {"iri": iri, "label": _primary_label(iri), "has_children": iri in has_children_classes}
        for iri in root_classes[:_DEFAULT_LIMIT]
    ]
    r.setex(
        f"terms_root:{version_id}:class:{_DEFAULT_LIMIT}",
        _SEARCH_TTL,
        json.dumps({"terms": class_terms, "offset": 0, "limit": _DEFAULT_LIMIT, "parent": "root"}),
    )

    _PROP_SUBTYPES = ("object_property", "data_property", "annotation_property")
    for subtype in _PROP_SUBTYPES:
        root_props = sorted(
            (iri for iri, t in entities.items()
             if t == subtype and iri not in non_root_props and iri not in deprecated_iris),
            key=_sort_key,
        )
        prop_terms = [
            {"iri": iri, "label": _primary_label(iri), "has_children": iri in has_children_props}
            for iri in root_props[:_DEFAULT_LIMIT]
        ]
        r.setex(
            f"terms_root:{version_id}:{subtype}:{_DEFAULT_LIMIT}",
            _SEARCH_TTL,
            json.dumps({"terms": prop_terms, "offset": 0, "limit": _DEFAULT_LIMIT, "parent": "root"}),
        )


def _populate_stats_cache(
    version_id: str,
    ontology_id: str,
    entities: dict[str, str],
    r: redis.Redis,
) -> None:
    """Write full VoID stats to Redis so the first /stats request is instant."""
    named_graph = graph_iri(ontology_id, version_id)

    # Per-type property counts are free from the already-built entities dict
    obj_prop_count  = sum(1 for t in entities.values() if t == "object_property")
    data_prop_count = sum(1 for t in entities.values() if t == "data_property")
    ann_prop_count  = sum(1 for t in entities.values() if t == "annotation_property")
    class_count     = sum(1 for t in entities.values() if t == "class")

    # Two extra queries for counts not derivable from the entity dict
    def _count(sparql: str) -> int:
        rows = list(sparql_query(sparql))
        if rows:
            v = rows[0]["n"]
            return int(v.value) if v is not None else 0
        return 0

    triple_count = _count(
        f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{named_graph}> {{ ?s ?p ?o }} }}"
    )
    ind_count = _count(f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT (COUNT(DISTINCT ?i) AS ?n) WHERE {{
            GRAPH <{named_graph}> {{ ?i a owl:NamedIndividual . FILTER(isIRI(?i)) }}
        }}
    """)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    prop_count = obj_prop_count + data_prop_count + ann_prop_count

    stats = {
        "triple_count":              triple_count,
        "class_count":               class_count,
        "property_count":            prop_count,
        "object_property_count":     obj_prop_count,
        "datatype_property_count":   data_prop_count,
        "annotation_property_count": ann_prop_count,
        "individual_count":          ind_count,
        "index_meta": {
            "indexed_at":     now,
            "class_count":    class_count,
            "property_count": prop_count,
        },
    }
    r.setex(_stats_cache_key(version_id), _SEARCH_TTL, json.dumps(stats))


def invalidate_index(version_id: str) -> None:
    """Delete all search index keys for a version."""
    r = _get_redis()
    cursor = 0
    to_delete: list[str] = []
    while True:
        cursor, keys = r.scan(cursor, match=f"search:*:{version_id}:*", count=100)
        to_delete.extend(keys)
        if cursor == 0:
            break
    to_delete.append(_meta_key(version_id))
    to_delete.append(_stats_cache_key(version_id))
    keys_present = [k for k in to_delete if r.exists(k)]
    if keys_present:
        r.delete(*keys_present)
