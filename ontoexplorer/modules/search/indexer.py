"""Redis entity search index for ontology versions."""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass

import redis

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


def entity_lookup(
    version_id: str,
    prefix: str,
    entity_type: str | None,
    limit: int,
) -> list[dict]:
    """Prefix-search entities. Returns list of entity dicts with label/type/iri/short."""
    r = _get_redis()
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
