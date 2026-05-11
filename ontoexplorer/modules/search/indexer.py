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


def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _short_iri(iri: str) -> str:
    if "#" in iri:
        return iri.split("#")[-1]
    return iri.rstrip("/").split("/")[-1]


_CURIE_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*):\s*([A-Za-z0-9_\-\.]+)$")


def entity_lookup(
    version_id: str,
    prefix: str,
    entity_type: str | None,
    limit: int,
) -> list[dict]:
    """Prefix-search entities. Returns list of entity dicts with label/type/iri/short."""
    r = _get_redis()

    # Direct full-IRI lookup
    if prefix.startswith("http://") or prefix.startswith("https://"):
        detail = r.hgetall(_iri_key(version_id, prefix.strip()))
        if detail and (entity_type is None or detail.get("type") == entity_type):
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
    min_val = f"[{norm}"
    max_val = f"[{norm}\xff"
    members = r.zrangebylex(key, min_val, max_val, start=0, num=limit * 3)

    results: list[dict] = []
    seen_iris: set[str] = set()

    for member in members:
        parts = member.split("|", 2)
        if len(parts) != 3:
            continue
        _, etype, iri = parts
        if entity_type and etype != entity_type:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        detail = r.hgetall(_iri_key(version_id, iri))
        if not detail:
            continue
        results.append(detail)
        if len(results) >= limit:
            break

    return results


def build_index(version_id: str, ontology_id: str) -> IndexStats:
    """Extract all entities and labels from Oxigraph and write the Redis entity index."""
    from datetime import datetime, timezone

    r = _get_redis()
    named_graph = graph_iri(ontology_id, version_id)

    # Collect entity IRIs with their types
    entities: dict[str, str] = {}  # iri -> "class" | "property"
    for entity_type, owl_type in [
        ("class",    "http://www.w3.org/2002/07/owl#Class"),
        ("property", "http://www.w3.org/2002/07/owl#ObjectProperty"),
        ("property", "http://www.w3.org/2002/07/owl#DatatypeProperty"),
        ("property", "http://www.w3.org/2002/07/owl#AnnotationProperty"),
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
    pipe.expire(_type_key(version_id, "class"),    _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "property"), _SEARCH_TTL)
    pipe.setex(_meta_key(version_id), _SEARCH_TTL, json.dumps({
        "indexed_at":      datetime.now(timezone.utc).isoformat(),
        "class_count":     class_count,
        "property_count":  property_count,
        "individual_count": 0,
    }))
    pipe.execute()

    return IndexStats(
        version_id=version_id,
        class_count=class_count,
        property_count=property_count,
        individual_count=0,
    )


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
    keys_present = [k for k in to_delete if r.exists(k)]
    if keys_present:
        r.delete(*keys_present)
