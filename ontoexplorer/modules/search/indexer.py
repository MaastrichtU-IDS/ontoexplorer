"""Redis entity search index for ontology versions."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
from dataclasses import dataclass

import redis

from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
from ontoexplorer.config import get_settings

_SEARCH_TTL = 30 * 24 * 3600  # 30 days, same as ELK classification TTL
# Bounds how many individuals are indexed, to bound memory. It was 50_000,
# which meant an ABox-heavy ontology had *no* individuals indexed at all — and
# that is exactly the case where reading them from Oxigraph is slow (2.3-4.8 s
# per page on 200k, degrading with offset). Classes have never had a cap and
# DRON indexes 771k of them, so the old figure was far below what the pipeline
# actually handles. Override with INDEX_INDIVIDUAL_LIMIT.
IND_INDEX_THRESHOLD = int(os.getenv("INDEX_INDIVIDUAL_LIMIT", str(1_000_000)))
# pyowl2_profiles.detect_profiles builds a whole-graph render context (scans the
# store via quads_for_pattern); on very large ontologies (e.g. uberon ~26k
# classes) it does not complete in reasonable time and, run synchronously inside
# build_index, blocks the version from ever reaching "ready". Skip profile
# detection above this class-count threshold. Empirical: cl (19,167 classes)
# completes; uberon (26k) and mondo-simple (36k) do not. The /owl-profile
# endpoint already returns a graceful "not computed" when the entry is absent.
# (A wall-clock-bounded detection would be a more robust follow-up than a
# class-count proxy.)
OWL_PROFILE_MAX_CLASSES = int(os.getenv("OWL_PROFILE_MAX_CLASSES", "20000"))


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


def _individuals_key(version_id: str) -> str:
    """Every owl:NamedIndividual, regardless of its primary `type`.

    Distinct from _type_key(v, "individual"), which only holds entities whose
    single primary type came out as 'individual' — a punned Class/Individual
    lands in the class set and would otherwise be lost.
    """
    return f"search:entities:{version_id}:individuals"


def _meta_key(version_id: str) -> str:
    return f"search:meta:{version_id}"


def _deprecated_key(version_id: str) -> str:
    return f"search:entities:{version_id}:deprecated"


def label_dedupe_key(value: str, lang_tag: str | None) -> tuple[str, str]:
    """What makes two labels the same label.

    Value *and* language. Deduping on value alone silently dropped a label
    whenever two languages spelled a term identically — "chocolate"@es lost to
    "chocolate"@en, "alimento"@pt-BR lost to "alimento"@es — while the language
    counter still counted the dropped one. /languages therefore offered
    languages that no entity could be displayed in, and choosing them appeared
    to do nothing.

    The tag is collapsed to its primary subtag because that is how labels are
    stored downstream: keeping "colour"@en-GB and "colour"@en-US separately
    would only produce a duplicate under `en`.
    """
    from ontoexplorer.modules.search.lang import canonical_lang
    return value, canonical_lang(lang_tag or "")


def _langs_key(version_id: str) -> str:
    return f"search:entities:{version_id}:langs"


def _stats_cache_key(version_id: str) -> str:
    return f"version_stats:{version_id}"


_REDIS_CLIENT: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    """Singleton Redis client. Reuses a connection pool across threads (redis-py is thread-safe).

    No max_connections cap so per-version fan-out (25 threads/request × N concurrent
    requests) doesn't block waiting for free connections.
    """
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        _REDIS_CLIENT = redis.Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
        )
    return _REDIS_CLIENT


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
    ordered_iris: list[str] = []

    def _filter(members: list[str]) -> None:
        for member in members:
            parts = member.split("|", 3)
            if len(parts) == 4:
                _, _lang, etype, iri = parts
            elif len(parts) == 3:
                _, etype, iri = parts  # v1 backward compat
            else:
                continue
            if not _type_matches(etype):
                continue
            if iri in seen_iris:
                continue
            seen_iris.add(iri)
            ordered_iris.append(iri)

    _filter(exact_members)   # tier-0 results first
    _filter(all_members)     # then prefix / word-suffix results

    if not ordered_iris:
        return []

    # Pipeline the per-IRI HGETALL lookups into a single round-trip.
    pipe = r.pipeline(transaction=False)
    for iri in ordered_iris:
        pipe.hgetall(_iri_key(version_id, iri))
    details = pipe.execute()
    candidates: list[dict] = [d for d in details if d]

    # Within each tier, sort alphabetically by label for stable ordering
    candidates.sort(key=lambda d: _rank_key(d, norm))
    return candidates[:limit]


def entity_lookup_multi(
    version_ids: list[str],
    prefix: str,
    entity_type: str | None,
    per_version_limit: int,
) -> dict[str, list[dict]]:
    """Run entity_lookup across many versions using one shared pipeline (2 round-trips total).

    Returns {version_id: [entity_dict, …]} preserving the same tier ordering as entity_lookup.
    """
    if not version_ids:
        return {}

    r = _get_redis()

    _PROP_SUBTYPES = {"object_property", "data_property", "annotation_property"}

    def _type_matches(etype: str) -> bool:
        if entity_type is None:
            return True
        if entity_type == "property":
            return etype in _PROP_SUBTYPES or etype == "property"
        return etype == entity_type

    def _detail_type_matches(detail: dict) -> bool:
        if entity_type is None:
            return True
        stored = detail.get("type", "")
        if entity_type == "property":
            return stored in _PROP_SUBTYPES or stored == "property"
        return stored == entity_type

    stripped = prefix.strip()
    is_iri = stripped.startswith("http://") or stripped.startswith("https://")

    if is_iri:
        pipe = r.pipeline(transaction=False)
        for vid in version_ids:
            pipe.hgetall(_iri_key(vid, stripped))
        details = pipe.execute()
        return {
            vid: ([d] if d and _detail_type_matches(d) else [])
            for vid, d in zip(version_ids, details)
        }

    curie_match = _CURIE_PATTERN.match(stripped)
    if curie_match:
        norm = normalise_label(curie_match.group(2))
    else:
        norm = normalise_label(prefix)

    if not norm:
        return {vid: [] for vid in version_ids}

    # Phase 1: ZRANGEBYLEX (exact + prefix) for every version in one pipeline.
    pipe = r.pipeline(transaction=False)
    for vid in version_ids:
        key = _prefix_key(vid)
        pipe.zrangebylex(key, f"[{norm}|", f"[{norm}|\xff", start=0, num=max(per_version_limit, 50))
        pipe.zrangebylex(key, f"[{norm}", f"[{norm}\xff", start=0, num=per_version_limit * 5)
    zres = pipe.execute()

    # Filter members per version and build the list of HGETALL targets.
    per_version_iris: dict[str, list[str]] = {}
    hgetall_keys: list[tuple[str, str]] = []  # (version_id, iri)

    for idx, vid in enumerate(version_ids):
        exact_members = zres[2 * idx]
        all_members = zres[2 * idx + 1]
        seen_iris: set[str] = set()
        ordered: list[str] = []

        def _filter(members: list[str]) -> None:
            for member in members:
                parts = member.split("|", 3)
                if len(parts) == 4:
                    _, _lang, etype, iri = parts
                elif len(parts) == 3:
                    _, etype, iri = parts
                else:
                    continue
                if not _type_matches(etype):
                    continue
                if iri in seen_iris:
                    continue
                seen_iris.add(iri)
                ordered.append(iri)

        _filter(exact_members)
        _filter(all_members)
        per_version_iris[vid] = ordered
        for iri in ordered:
            hgetall_keys.append((vid, iri))

    if not hgetall_keys:
        return {vid: [] for vid in version_ids}

    # Phase 2: HGETALL all entity details in one pipeline.
    pipe = r.pipeline(transaction=False)
    for vid, iri in hgetall_keys:
        pipe.hgetall(_iri_key(vid, iri))
    details = pipe.execute()

    # Reassemble per-version result lists, preserving order.
    by_vid: dict[str, list[dict]] = {vid: [] for vid in version_ids}
    for (vid, _iri), detail in zip(hgetall_keys, details):
        if detail:
            by_vid[vid].append(detail)
    return by_vid


def build_index(version_id: str, ontology_id: str = "", profile: dict | None = None) -> IndexStats:
    """Extract all entities and labels from Oxigraph and write the Redis entity index."""
    from datetime import datetime, timezone

    if profile is None:
        from ontoexplorer.modules.profile.registry import default_profile
        profile = default_profile()
    label_props = profile["label_props"]
    synonym_props = profile["synonym_props"]
    definition_props = profile["definition_props"]
    deprecated_props = profile["deprecated_props"]

    r = _get_redis()
    named_graph = graph_iri(ontology_id, version_id)

    # Build source prefix map from owl:imports declarations
    # Maps normalized base IRI → short name (e.g. "https://w3id.org/sulo" → "sulo")
    import_source_map: dict[str, str] = {}
    try:
        for row in sparql_query(f"""
            SELECT DISTINCT ?imp WHERE {{
                GRAPH <{named_graph}> {{
                    ?ont <http://www.w3.org/2002/07/owl#imports> ?imp .
                }}
            }}
        """):
            v = row["imp"]
            imp_iri = v.value if hasattr(v, "value") else str(v)
            clean = imp_iri.rstrip("/")
            short_name = clean.split("/")[-1].split("#")[-1]
            if short_name:
                import_source_map[clean] = short_name
    except Exception:
        pass

    def _get_source(iri: str) -> str:
        for base, name in import_source_map.items():
            if iri.startswith(base):
                return name
        return ""

    # Collect entity IRIs with their types.
    # OWL types are checked first; RDFS fallbacks only fill gaps for non-OWL
    # vocabularies (e.g. Schema.org uses rdfs:Class / rdf:Property).
    entities: dict[str, str] = {}  # iri -> "class" | "object_property" | "data_property" | "annotation_property"
    for entity_type, rdf_type in [
        ("class",               "http://www.w3.org/2002/07/owl#Class"),
        ("object_property",     "http://www.w3.org/2002/07/owl#ObjectProperty"),
        ("data_property",       "http://www.w3.org/2002/07/owl#DatatypeProperty"),
        ("annotation_property", "http://www.w3.org/2002/07/owl#AnnotationProperty"),
        # RDFS fallbacks — only fire when no OWL typing is present
        ("class",               "http://www.w3.org/2000/01/rdf-schema#Class"),
        ("object_property",     "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property"),
    ]:
        q = f"""
            SELECT DISTINCT ?entity WHERE {{
                GRAPH <{named_graph}> {{
                    ?entity a <{rdf_type}> .
                    FILTER(isIRI(?entity))
                }}
            }}
        """
        for sol in sparql_query(q):
            iri = sol["entity"].value
            if iri not in entities:
                entities[iri] = entity_type

    # Collect individuals — gated by threshold to prevent OOM on large ontologies
    individual_count = 0
    ind_total_q = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT (COUNT(DISTINCT ?entity) AS ?n) WHERE {{
            GRAPH <{named_graph}> {{ ?entity a owl:NamedIndividual . FILTER(isIRI(?entity)) }}
        }}
    """
    ind_total_rows = list(sparql_query(ind_total_q))
    ind_total = int(ind_total_rows[0]["n"].value) if ind_total_rows else 0
    individual_iris: set[str] = set()
    if ind_total <= IND_INDEX_THRESHOLD:
        ind_iri_q = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            SELECT DISTINCT ?entity WHERE {{
                GRAPH <{named_graph}> {{ ?entity a owl:NamedIndividual . FILTER(isIRI(?entity)) }}
            }}
        """
        for sol in sparql_query(ind_iri_q):
            iri = sol["entity"].value
            # Recorded whatever else it is. `entities` is first-wins and
            # single-valued, so an OWL 2 punned entity (Class *and*
            # NamedIndividual — DRON's UO_* unit terms) stays typed 'class';
            # without this set it would vanish from the individuals listing.
            individual_iris.add(iri)
            if iri not in entities:
                entities[iri] = "individual"
                individual_count += 1

    # Collect deprecated entities
    deprecated_iris: set[str] = set()
    for dep_prop in deprecated_props:
        dep_q = f"""
            SELECT ?entity WHERE {{
                GRAPH <{named_graph}> {{
                    ?entity <{dep_prop}> "true"^^<http://www.w3.org/2001/XMLSchema#boolean> .
                    FILTER(isIRI(?entity))
                }}
            }}
        """
        for sol in sparql_query(dep_q):
            deprecated_iris.add(sol["entity"].value)

    # Collect labels per entity
    labels_by_iri: dict[str, list[dict]] = {iri: [] for iri in entities}
    label_seen: dict[str, set[str]] = {iri: set() for iri in entities}
    lang_counts: dict[str, int] = {}
    if label_props:
        label_pred_filter = " ".join(f"<{p}>" for p in label_props)
        label_q = f"""
            SELECT ?entity ?label (lang(?label) AS ?lang) WHERE {{
                GRAPH <{named_graph}> {{
                    VALUES ?pred {{ {label_pred_filter} }}
                    ?entity ?pred ?label .
                    FILTER(isIRI(?entity) && isLiteral(?label))
                }}
            }}
        """
        for sol in sparql_query(label_q):
            iri = sol["entity"].value
            if iri in labels_by_iri:
                val = sol["label"].value
                lang_tag = sol["lang"].value if sol["lang"] is not None else ""
                entry = {"value": val, "lang": lang_tag}
                # O(1) dedup on (value, language) — see label_dedupe_key.
                key = label_dedupe_key(val, lang_tag)
                if key not in label_seen[iri]:
                    label_seen[iri].add(key)
                    labels_by_iri[iri].append(entry)
                lang_counts[lang_tag] = lang_counts.get(lang_tag, 0) + 1

    # Collect synonyms per entity
    synonyms_by_iri: dict[str, list[dict]] = {iri: [] for iri in entities}
    syn_seen: dict[str, set[str]] = {iri: set() for iri in entities}
    if synonym_props:
        syn_pred_filter = " ".join(f"<{p}>" for p in synonym_props)
        syn_q = f"""
            SELECT ?entity ?syn (lang(?syn) AS ?lang) WHERE {{
                GRAPH <{named_graph}> {{
                    VALUES ?pred {{ {syn_pred_filter} }}
                    ?entity ?pred ?syn .
                    FILTER(isIRI(?entity) && isLiteral(?syn))
                }}
            }}
        """
        for sol in sparql_query(syn_q):
            iri = sol["entity"].value
            if iri in synonyms_by_iri:
                val = sol["syn"].value
                lang_tag = sol["lang"].value if sol["lang"] is not None else ""
                entry = {"value": val, "lang": lang_tag}
                # O(1) dedup by value using tracking set
                if val not in syn_seen[iri]:
                    syn_seen[iri].add(val)
                    synonyms_by_iri[iri].append(entry)
                lang_counts[lang_tag] = lang_counts.get(lang_tag, 0) + 1

    # Collect definitions per entity (first-match across definition_props)
    defs_by_iri: dict[str, list[dict]] = {}
    for def_prop in definition_props:
        def_q = f"""
            SELECT ?entity ?def (lang(?def) AS ?lang) WHERE {{
                GRAPH <{named_graph}> {{
                    ?entity <{def_prop}> ?def .
                    FILTER(isIRI(?entity) && isLiteral(?def))
                }}
            }}
        """
        for sol in sparql_query(def_q):
            iri = sol["entity"].value
            if iri in entities and iri not in defs_by_iri:
                val = sol["def"].value
                lang_tag = sol["lang"].value if sol["lang"] is not None else ""
                defs_by_iri[iri] = [{"value": val, "lang": lang_tag}]
                lang_counts[lang_tag] = lang_counts.get(lang_tag, 0) + 1

    # Invalidate root terms cache so API serves fresh data with the new source fields
    for key in r.scan_iter(f"terms_root:{version_id}:*"):
        r.delete(key)

    # Write to Redis via pipeline
    prefix_key = _prefix_key(version_id)
    r.delete(prefix_key)
    # Delete meta key upfront so we can safely use hset even if a previous run
    # left a string value there (WRONGTYPE error otherwise).
    r.delete(_meta_key(version_id))

    pipe = r.pipeline(transaction=False)
    class_count = property_count = 0
    # individual_count was set above during threshold-gated collection
    # Flush the write pipeline every _FLUSH_ENTITIES entities so its in-memory
    # command buffer stays bounded. A single non-transactional pipeline over a
    # 26k+ class ontology otherwise queues millions of ZADD suffix entries in
    # worker memory before one execute(), which drove ~15 GiB RSS and OOM-killed
    # the indexing worker on large OBO ontologies (uberon/cl/mondo). The writes
    # are independent (distinct keys, additive ZADD/SADD), so periodic flushing
    # is semantically identical to one final execute(); the pipeline is reusable
    # after execute(), and the trailing meta/expire commands run in the final one.
    _FLUSH_ENTITIES = 2000
    _since_flush = 0

    for iri, entity_type in entities.items():
        if iri in deprecated_iris:
            continue

        labels_list = labels_by_iri.get(iri, [])
        syns_list = synonyms_by_iri.get(iri, [])
        defs_list = defs_by_iri.get(iri, [])

        # Dedup synonyms: remove entries whose value appears in labels
        label_values = {e["value"] for e in labels_list}
        deduped_syns = [e for e in syns_list if e["value"] not in label_values]

        short = _short_iri(iri)

        # primary_label: first English label, or first label of any lang, or short IRI
        primary_label = next(
            (e["value"] for e in labels_list if e["lang"] == "en"),
            labels_list[0]["value"] if labels_list else short,
        )

        pipe.hset(_iri_key(version_id, iri), mapping={
            "label":         primary_label,   # backward compat
            "primary_label": primary_label,
            "type":          entity_type,
            "iri":           iri,
            "short":         short,
            "source":        _get_source(iri),
            "labels":        json.dumps(labels_list),
            "synonyms":      json.dumps(deduped_syns),
            "definitions":   json.dumps(defs_list),
        })
        pipe.expire(_iri_key(version_id, iri), _SEARCH_TTL)
        pipe.sadd(_type_key(version_id, entity_type), iri)

        # All search texts: all labels + all synonyms + short IRI if not already covered
        all_search_texts = list(labels_list) + list(deduped_syns)
        short_entry = {"value": short, "lang": ""}
        if short not in label_values and not any(e["value"] == short for e in deduped_syns):
            all_search_texts.append(short_entry)

        for entry in all_search_texts:
            val = entry["value"]
            lang_tag = entry["lang"]
            norm = normalise_label(val)
            if not norm:
                continue
            pipe.zadd(prefix_key, {f"{norm}|{lang_tag}|{entity_type}|{iri}": 0})
            words = norm.split()
            for i in range(1, len(words)):
                suffix = " ".join(words[i:])
                pipe.zadd(prefix_key, {f"{suffix}|{lang_tag}|{entity_type}|{iri}": 0})

        if entity_type == "class":
            class_count += 1
        elif entity_type != "individual":
            property_count += 1

        _since_flush += 1
        if _since_flush >= _FLUSH_ENTITIES:
            pipe.execute()
            _since_flush = 0

    # Inject owl:Thing as a queryable built-in class for any ontology that has classes.
    # It is not declared as a owl:Class in ontology files so it would otherwise be absent.
    if class_count > 0:
        _OWL_THING_IRI = "http://www.w3.org/2002/07/owl#Thing"
        _owl_thing_key = _iri_key(version_id, _OWL_THING_IRI)
        pipe.hset(_owl_thing_key, mapping={
            "label":         "Thing",
            "primary_label": "Thing",
            "type":          "class",
            "iri":           _OWL_THING_IRI,
            "short":         "owl:Thing",
            "source":        "",
            "labels":        json.dumps([{"value": "Thing", "lang": "en"}]),
            "synonyms":      json.dumps([]),
            "definitions":   json.dumps([]),
        })
        pipe.expire(_owl_thing_key, _SEARCH_TTL)
        # Index under both "thing" (label) and "owl:thing" (short CURIE)
        pipe.zadd(prefix_key, {f"thing||class|{_OWL_THING_IRI}": 0})
        pipe.zadd(prefix_key, {f"owl:thing||class|{_OWL_THING_IRI}": 0})

    pipe.expire(prefix_key, _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "class"),               _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "object_property"),     _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "data_property"),       _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "annotation_property"), _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "individual"),          _SEARCH_TTL)
    # Rewritten wholesale: a re-index must not leave individuals behind that
    # the ontology no longer declares.
    pipe.delete(_individuals_key(version_id))
    if individual_iris:
        pipe.sadd(_individuals_key(version_id), *individual_iris)
        pipe.expire(_individuals_key(version_id), _SEARCH_TTL)
    pipe.hset(_meta_key(version_id), mapping={
        "indexed_at":       datetime.now(timezone.utc).isoformat(),
        "class_count":      str(class_count),
        "property_count":   str(property_count),
        "individual_count": str(individual_count),
    })
    pipe.expire(_meta_key(version_id), _SEARCH_TTL)
    # Store deprecated IRI set for use by the inferred-tree endpoint.
    dep_key = _deprecated_key(version_id)
    pipe.delete(dep_key)
    if deprecated_iris:
        pipe.sadd(dep_key, *deprecated_iris)
        pipe.expire(dep_key, _SEARCH_TTL)
    pipe.execute()

    # Write per-language label counts
    langs_key = _langs_key(version_id)
    r.delete(langs_key)
    if lang_counts:
        r.hset(langs_key, mapping={k: str(v) for k, v in lang_counts.items()})
        r.expire(langs_key, _SEARCH_TTL)

    # Mark index as schema v2
    r.hset(_meta_key(version_id), "schema_version", "v2")
    r.expire(_meta_key(version_id), _SEARCH_TTL)

    _build_tree_cache(version_id, ontology_id, entities, labels_by_iri, r)
    _populate_stats_cache(version_id, ontology_id, entities, r)
    _populate_coverage_cache(
        version_id, entities, deprecated_iris, labels_by_iri, defs_by_iri, r
    )
    _populate_owl_profile_cache(version_id, ontology_id, r, class_count)
    _populate_reuse_cache(version_id, ontology_id, entities, r)

    return IndexStats(
        version_id=version_id,
        class_count=class_count,
        property_count=property_count,
        individual_count=individual_count,
    )


def _build_tree_cache(
    version_id: str,
    ontology_id: str,
    entities: dict[str, str],
    labels_by_iri: dict[str, list[dict]],
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
    # Includes rdfs:Class for RDFS-only vocabularies (e.g. Schema.org)
    non_root_class_q = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?child WHERE {{
            GRAPH <{named_graph}> {{
                ?child rdfs:subClassOf ?parent .
                {{ ?child a owl:Class }} UNION {{ ?child a rdfs:Class }}
                {{ ?parent a owl:Class }} UNION {{ ?parent a rdfs:Class }}
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
                {{ ?child a owl:Class }} UNION {{ ?child a rdfs:Class }}
                {{ ?parent a owl:Class }} UNION {{ ?parent a rdfs:Class }}
                FILTER(isIRI(?child) && isIRI(?parent))
            }}
        }}
    """
    has_children_classes = {sol["parent"].value for sol in sparql_query(has_children_class_q)}

    _RDF_PROPERTY_IRI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property"
    # Properties with a named parent — not roots
    # Includes rdf:Property for RDFS-only vocabularies (e.g. Schema.org)
    non_root_prop_q = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?child WHERE {{
            GRAPH <{named_graph}> {{
                ?child rdfs:subPropertyOf ?parent .
                FILTER(isIRI(?child) && isIRI(?parent))
                {{ ?child a owl:ObjectProperty }} UNION
                {{ ?child a owl:DatatypeProperty }} UNION
                {{ ?child a owl:AnnotationProperty }} UNION
                {{ ?child a <{_RDF_PROPERTY_IRI}> }}
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
                {{ ?child a owl:AnnotationProperty }} UNION
                {{ ?child a <{_RDF_PROPERTY_IRI}> }}
            }}
        }}
    """
    has_children_props = {sol["parent"].value for sol in sparql_query(has_children_prop_q)}

    def _primary_label(iri: str) -> str | None:
        labels = labels_by_iri.get(iri, [])
        if not labels:
            return None
        # prefer English, fall back to first
        en = next((e["value"] for e in labels if e["lang"] == "en"), None)
        return en or labels[0]["value"]

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


_DESC_PREDS = [
    "http://purl.org/dc/terms/description",
    "http://purl.org/dc/elements/1.1/description",
    "http://www.w3.org/2000/01/rdf-schema#comment",
]
_TITLE_PREDS = [
    "http://purl.org/dc/terms/title",
    "http://purl.org/dc/elements/1.1/title",
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
]


_OWL_ONTOLOGY_IRI = "http://www.w3.org/2002/07/owl#Ontology"
_OWL_IMPORTS_IRI = "http://www.w3.org/2002/07/owl#imports"


def _onto_meta_from_graph(named_graph: str) -> tuple[str, str]:
    """Return (label, description) for the primary owl:Ontology node in the graph.

    Handles both named-IRI and blank-node ontology declarations.  When imports are
    loaded into the same named graph, only the non-imported node is considered so
    we don't accidentally pick up a dependency's title.

    Returns ('', '') if the ontology declaration is absent or has no matching predicates.
    """
    all_preds = _TITLE_PREDS + _DESC_PREDS
    pred_filter = " ".join(f"<{p}>" for p in all_preds)
    # Single query: find any owl:Ontology subject (named or blank) that is not an
    # owl:imports target, then fetch its title/description literals in one pass.
    rows = list(sparql_query(f"""
        SELECT ?pred ?val WHERE {{
            GRAPH <{named_graph}> {{
                ?onto a <{_OWL_ONTOLOGY_IRI}> .
                FILTER NOT EXISTS {{
                    GRAPH <{named_graph}> {{ ?other <{_OWL_IMPORTS_IRI}> ?onto . }}
                }}
                VALUES ?pred {{ {pred_filter} }}
                ?onto ?pred ?val .
                FILTER(isLiteral(?val))
                FILTER(lang(?val) = "" || langMatches(lang(?val), "en"))
            }}
        }}
    """))

    # Collect per-predicate values; prefer longest non-empty for each role
    by_pred: dict[str, list[str]] = {}
    for row in rows:
        pred = row["pred"].value
        val = row["val"].value.strip()
        if val:
            by_pred.setdefault(pred, []).append(val)

    def _pick(preds: list[str]) -> str:
        for p in preds:
            vals = by_pred.get(p, [])
            if vals:
                return max(vals, key=len)
        return ""

    return _pick(_TITLE_PREDS), _pick(_DESC_PREDS)


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

    onto_label, onto_description = _onto_meta_from_graph(named_graph)

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
        "label":                     onto_label,
        "description":               onto_description,
        "index_meta": {
            "indexed_at":     now,
            "class_count":    class_count,
            "property_count": prop_count,
        },
    }
    r.setex(_stats_cache_key(version_id), _SEARCH_TTL, json.dumps(stats))


def _populate_coverage_cache(
    version_id: str,
    entities: dict[str, str],
    deprecated_iris: set[str],
    labels_by_iri: dict[str, list[dict]],
    defs_by_iri: dict[str, list[dict]],
    r: redis.Redis,
) -> None:
    """Compute per-version coverage and write to Redis with the same TTL as stats."""
    from datetime import datetime, timezone
    from ontoexplorer.modules.search.coverage import compute_coverage, coverage_cache_key

    payload = compute_coverage(entities, deprecated_iris, labels_by_iri, defs_by_iri)
    payload["version_id"] = version_id
    payload["indexed_at"] = datetime.now(timezone.utc).isoformat()
    r.setex(coverage_cache_key(version_id), _SEARCH_TTL, json.dumps(payload))


def _populate_owl_profile_cache(
    version_id: str, ontology_id: str, r: "redis.Redis", class_count: int = 0
) -> None:
    """Run OWL 2 profile detection and write result to Redis with the same TTL as stats.

    Skipped for ontologies above OWL_PROFILE_MAX_CLASSES: detect_profiles scans the
    whole graph and, run inline here, would otherwise hang build_index (and so
    block the version reaching "ready") on very large ontologies. When skipped no
    cache entry is written, so the /owl-profile endpoint reports "not computed".
    """
    if class_count > OWL_PROFILE_MAX_CLASSES:
        # Skipped: detection is infeasible at this scale and would hang indexing.
        return
    from ontoexplorer.modules.owl_profile.detector import detect_profiles
    from ontoexplorer.modules.owl_profile.language import detect_language
    from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
    from ontoexplorer.clients.oxigraph import get_store
    from ontoexplorer.clients.oxigraph import graph_iri as _graph_iri
    store = get_store()
    g = _graph_iri(ontology_id, version_id)
    payload = detect_profiles(store, graph_iri=g, ontology_id=ontology_id, version_id=version_id)
    # Coarser language/expressivity tier (RDF/RDFS/RDFS-Plus/OWL) — a few cheap
    # ASKs, so an RDFS vocabulary is identified as such instead of surfacing only
    # as "OWL 2 DL"/"OWL Full".
    payload["language"] = detect_language(store, graph_iri=g)
    r.setex(owl_profile_cache_key(version_id), _SEARCH_TTL, json.dumps(payload))


def _populate_reuse_cache(
    version_id: str,
    ontology_id: str,
    entities: dict[str, str],
    r: "redis.Redis",
) -> None:
    """Compute the reuse report for this version and cache it in Redis.

    Mirrors `_populate_owl_profile_cache` — runs at the end of indexing so
    the data is ready before any API call.
    """
    import asyncio as _asyncio
    import json as _json

    from sqlalchemy import select

    from ontoexplorer.clients.oxigraph import get_store, graph_iri as _graph_iri
    from ontoexplorer.database import make_celery_db_session
    from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
    from ontoexplorer.modules.reuse.cache import reuse_cache_key
    from ontoexplorer.modules.reuse.detector import detect_reuse

    async def _gather():
        async with make_celery_db_session()() as db:
            ver = (await db.execute(
                select(OntologyVersion).where(OntologyVersion.id == version_id)
            )).scalar_one_or_none()
            if ver is None:
                return None, [], []
            ont = (await db.execute(
                select(Ontology).where(Ontology.id == ver.ontology_id)
            )).scalar_one_or_none()
            imp_rows = (await db.execute(
                select(OntologyImport).where(OntologyImport.version_id == version_id)
            )).scalars().all()
            db_imports = [
                {"import_iri": row.import_iri, "depth": 1} for row in imp_rows
            ]
            host_iri = ont.iri if ont else ""
            host_namespaces = [host_iri + sep for sep in ("#", "/") if host_iri]
            return host_iri, host_namespaces, db_imports

    host_iri, host_namespaces, db_imports = _asyncio.run(_gather())
    if host_iri is None:
        return  # version disappeared mid-index — skip silently

    g = _graph_iri(ontology_id, version_id)
    entity_pairs = list(entities.items())
    report = detect_reuse(
        get_store(),
        graph_iri=g,
        version_id=version_id,
        host_iri=host_iri,
        host_namespaces=host_namespaces,
        db_imports=db_imports,
        entities=entity_pairs,
    )
    # Convert dataclasses to dicts via asdict — preserves the nested structure.
    from dataclasses import asdict as _asdict
    payload = _asdict(report)
    r.setex(reuse_cache_key(version_id), _SEARCH_TTL, _json.dumps(payload))


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
    from ontoexplorer.modules.search.coverage import coverage_cache_key
    to_delete.append(coverage_cache_key(version_id))
    from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
    to_delete.append(owl_profile_cache_key(version_id))
    from ontoexplorer.modules.reuse.cache import reuse_cache_key
    to_delete.append(reuse_cache_key(version_id))
    keys_present = [k for k in to_delete if r.exists(k)]
    if keys_present:
        r.delete(*keys_present)
