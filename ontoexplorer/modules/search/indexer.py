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
# OWL 2 profile detection moved out of build_index: it now runs on the native
# horned-profile checker (fast at every size) from the index_ontology task, which
# has the async DB + object-store access needed to load the stored file. See
# ontoexplorer.modules.owl_profile.detector and #149. (The old class-count gate,
# OWL_PROFILE_MAX_CLASSES, is gone — it was a workaround for pyowl2_profiles
# hanging on large ontologies.)


@dataclass
class IndexStats:
    version_id: str
    class_count: int
    property_count: int
    individual_count: int
    concept_count: int = 0
    # #242 Workstream B: the in-memory producer output, so entity_index can be
    # populated directly (not re-read from Redis). `entities` is {iri: hash_dict}
    # in the exact Redis-hash shape; `deprecated`/`individuals` are IRI sets.
    entities: dict | None = None
    deprecated: set | None = None
    individuals: set | None = None


def normalise_label(label: str) -> str:
    """Lowercase, strip punctuation (except : for CURIEs), collapse whitespace, strip articles."""
    label = label.lower()
    label = re.sub(r"[^\w\s:<>]", " ", label)
    label = re.sub(r"\s+", " ", label).strip()
    label = re.sub(r"^(the|a|an)\s+", "", label)
    return label


_CAMEL_BOUNDARY_1 = re.compile(r"([a-z0-9])([A-Z])")       # aB   -> a B
_CAMEL_BOUNDARY_2 = re.compile(r"([A-Z]+)([A-Z][a-z])")    # XMLP -> XML P
_VERSION_SEGMENT = re.compile(r"^(v?\d+(\.\d+)*|current|latest|\d{4}(\d\d){0,2})$", re.I)


def humanize_local_name(short: str) -> str:
    """Display-friendly form of a bare IRI local name, for entities whose source
    ontology provides no label (e.g. 'AccidentInvolvingVehicle' -> 'Accident
    Involving Vehicle', 'top_data_property' -> 'top data property'). Mirrors the
    camel/snake/kebab splitting of pg_indexer.split_compound_labels but is for
    display, not search tokenisation. Returns the input unchanged when there is
    nothing to split."""
    if not short:
        return short
    s = _CAMEL_BOUNDARY_1.sub(r"\1 \2", short)
    s = _CAMEL_BOUNDARY_2.sub(r"\1 \2", s)
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or short


def short_namespace_token(namespace: str) -> str:
    """Readable short token for an external namespace bioregistry can't resolve —
    its last meaningful path segment, minus file extension and version-like
    segments (e.g. '.../ELSEWeb/elseweb-data.owl#' -> 'elseweb-data',
    '.../PR-owl-guide-20031209/wine#' -> 'wine'). Better than showing the full
    namespace URL on a source chip."""
    if not namespace:
        return ""
    parts = [p for p in re.split(r"[/#]", namespace) if p and p not in ("http:", "https:")]
    for seg in reversed(parts):
        s = re.sub(r"\.(owl|rdf|ttl|xml|jsonld|n3)$", "", seg, flags=re.I)
        if s and not _VERSION_SEGMENT.match(s):
            return s
    return parts[-1] if parts else ""


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


class _NoopPipe:
    """Drop-in for a Redis pipeline that discards every write — used when
    INDEX_WRITE_REDIS is off so the indexer's pipe.* calls become no-ops without
    touching their call sites (#242 Workstream B)."""
    def hset(self, *a, **k): return self
    def sadd(self, *a, **k): return self
    def zadd(self, *a, **k): return self
    def expire(self, *a, **k): return self
    def delete(self, *a, **k): return self
    def execute(self): return []


def build_index(version_id: str, ontology_id: str = "", profile: dict | None = None) -> IndexStats:
    """Extract all entities and labels from Oxigraph and write the Redis entity index."""
    from datetime import datetime, timezone

    if profile is None:
        from ontoexplorer.modules.profile.registry import default_profile
        profile = default_profile()
    # Floor the detected label properties with the standard baseline. The
    # auto-detector picks label_props per ontology and can return a non-empty
    # but incomplete set (missing the property an ontology actually names its
    # terms with), which the old code used as-is — leaving those entities
    # nameless. Unioning the canonical LABEL_PROPS (rdfs:label, skos:prefLabel,
    # dc(terms):title, schema:name) can't pull in dependency labels (the label
    # query is scoped to this ontology's own entities in its own graph); it only
    # recovers names that were being missed.
    from ontoexplorer.modules.profile.registry import LABEL_PROPS
    label_props = list(dict.fromkeys(list(profile.get("label_props") or []) + LABEL_PROPS))
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
            # Readable label: strip the file extension (.owl/.rdf/…) and any
            # version-like segment from the import IRI's tail, so an import of
            # '.../dogont.owl' reads 'dogont', not 'dogont.owl'. Falls back to
            # the bare last segment.
            short_name = short_namespace_token(clean) or clean.split("/")[-1].split("#")[-1]
            if short_name:
                import_source_map[clean] = short_name
    except Exception:
        pass

    # Host identity, so the reuse arm below can exclude the ontology's own terms.
    # HTO-style ontologies aren't in the bioregistry, so their own IRIs and the
    # host IRI both resolve to the generic "obo" prefix — which is exactly what
    # makes `prefix == host_prefix` a clean native/reused separator.
    from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix
    host_iri = ""
    try:
        for row in sparql_query(f"""
            SELECT ?ont WHERE {{
                GRAPH <{named_graph}> {{
                    ?ont a <http://www.w3.org/2002/07/owl#Ontology> . FILTER(isIRI(?ont))
                }}
            }} LIMIT 1
        """):
            v = row["ont"]
            host_iri = v.value if hasattr(v, "value") else str(v)
            break
    except Exception:
        host_iri = ""
    try:
        host_prefix = iri_to_prefix(host_iri)[0] if host_iri else None
    except Exception:
        host_prefix = None
    host_namespaces = [host_iri + "#", host_iri + "/"] if host_iri else []

    def _get_source(iri: str) -> str:
        # 1) Formal owl:imports — clean import names (e.g. "sulo", "pro").
        for base, name in import_source_map.items():
            if iri.startswith(base):
                return name
        # 2) Reuse — a term referenced from an external namespace without an
        #    owl:imports (e.g. HTO reusing ChEBI / FoodOn / UBERON terms). Mirror
        #    the reuse detector: skip host-native terms, then tag with the term's
        #    bioregistry prefix. Keeps term chips consistent with the Reuse report.
        if any(iri.startswith(ns) for ns in host_namespaces):
            return ""
        try:
            prefix, resolved = iri_to_prefix(iri)
        except Exception:
            prefix, resolved = None, False
        if not prefix or prefix == host_prefix:
            return ""
        if resolved:
            return prefix
        # Unresolved: `prefix` is the raw namespace URL. Show a short readable
        # token on the chip instead of the full URL. (This shortening is
        # display-only — the reuse report groups on iri_to_prefix directly.)
        return short_namespace_token(prefix)

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
        # SKOS concepts — the browsable terms of a thesaurus/controlled vocabulary.
        # Given their own entity type "concept" (a first-class tag alongside the
        # OWL/RDFS types) and placed last so any OWL/RDFS typing wins for a punned
        # term. This is the only typing a pure-SKOS vocabulary carries, so without
        # it those ontologies index to zero entities and vanish from search (e.g.
        # dpv-pd: 206 skos:Concept, 0 owl terms). Labels already union skos:prefLabel.
        ("concept",             "http://www.w3.org/2004/02/skos/core#Concept"),
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

    # Fallback for ABox-only vocabularies whose terms are declared *purely* by
    # membership in a domain class — no owl:Class/Property/skos:Concept typing and
    # no explicit owl:NamedIndividual — e.g. QUDT's units vocab, whose terms are
    # typed qudt:Prefix / qudt:DecimalPrefix / qudt:SystemOfUnits (named, labelled,
    # but invisible to every check above). Without this they index to zero entities
    # and vanish from search. Gated on the standard extraction having found NOTHING,
    # so a well-typed ontology's output never changes (zero blast radius on the
    # catalogue): it only rescues versions that would otherwise be empty. Such terms
    # are instances of a class, so they are indexed as individuals. "Domain class" =
    # an rdf:type IRI outside the OWL/RDF(S)/SKOS meta-vocabularies and the vocab-
    # description terms (voaf:Vocabulary, dcat:Dataset) — those are structural, not
    # browsable terms. Respects the same IND_INDEX_THRESHOLD to bound memory.
    if not entities:
        _META_TYPE_NS = (
            "http://www.w3.org/2002/07/owl#",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "http://www.w3.org/2000/01/rdf-schema#",
            "http://www.w3.org/2004/02/skos/core#",
        )
        _META_TYPE_IRIS = (
            "http://purl.org/vocommons/voaf#Vocabulary",
            "http://www.w3.org/ns/dcat#Dataset",
            "http://purl.org/vocab/vann/",
            # FOAF is a metadata/provenance vocab (foaf:Document for the RDF file
            # itself, foaf:Agent for maintainers) — not browsable ontology terms.
            "http://xmlns.com/foaf/0.1/",
        )
        _ns_filter = "".join(
            f'\n                    FILTER(!STRSTARTS(STR(?t), "{ns}"))'
            for ns in _META_TYPE_NS + _META_TYPE_IRIS
        )
        fb_count_q = f"""
            SELECT (COUNT(DISTINCT ?entity) AS ?n) WHERE {{
                GRAPH <{named_graph}> {{
                    ?entity a ?t .
                    FILTER(isIRI(?entity) && isIRI(?t)){_ns_filter}
                }}
            }}
        """
        fb_rows = list(sparql_query(fb_count_q))
        fb_total = int(fb_rows[0]["n"].value) if fb_rows else 0
        if 0 < fb_total <= IND_INDEX_THRESHOLD:
            fb_q = f"""
                SELECT DISTINCT ?entity WHERE {{
                    GRAPH <{named_graph}> {{
                        ?entity a ?t .
                        FILTER(isIRI(?entity) && isIRI(?t)){_ns_filter}
                    }}
                }}
            """
            for sol in sparql_query(fb_q):
                iri = sol["entity"].value
                if iri not in entities:
                    entities[iri] = "individual"
                    individual_iris.add(iri)
                    individual_count += 1

    # Collect each individual's rdf:type classes (minus owl:NamedIndividual) so the
    # OLS /types endpoint and the class→individuals filter can read them from
    # entity_index instead of a per-request SPARQL query (#242 Stage 1 PR 5).
    # Only gathered when individuals were indexed (same threshold gate).
    types_by_iri: dict[str, list[str]] = {}
    if individual_iris:
        _OWL_NAMED_INDIVIDUAL = "http://www.w3.org/2002/07/owl#NamedIndividual"
        types_q = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?ind ?cls WHERE {{
                GRAPH <{named_graph}> {{
                    ?ind a owl:NamedIndividual .
                    ?ind rdf:type ?cls .
                    FILTER(isIRI(?ind) && isIRI(?cls))
                    FILTER(?cls != <{_OWL_NAMED_INDIVIDUAL}>)
                }}
            }}
        """
        for sol in sparql_query(types_q):
            ind_iri = sol["ind"].value
            cls_iri = sol["cls"].value
            bucket = types_by_iri.setdefault(ind_iri, [])
            if cls_iri not in bucket:
                bucket.append(cls_iri)

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

    # #242 Workstream B: once all readers are off Redis (Stage 2 + B1/B2),
    # INDEX_WRITE_REDIS=false stops writing the per-entity Redis search index
    # (:iri: hashes, type-sets, prefix-zset, meta, langs, deprecated/individuals
    # sets). entity_index is still populated (directly from the in-memory output,
    # B1), and the response caches below (tree/stats/reuse) still write. Default
    # on, so this is a no-op until the flag is flipped post-validation.
    _write_redis = os.getenv("INDEX_WRITE_REDIS", "true").strip().lower() not in (
        "false", "0", "no", "off")

    # Invalidate root terms cache so API serves fresh data with the new source fields
    for key in r.scan_iter(f"terms_root:{version_id}:*", count=5000):
        r.delete(key)

    # Write to Redis via pipeline (a no-op pipe when the Redis index is disabled, so
    # the hset/sadd/zadd calls below stay unchanged).
    prefix_key = _prefix_key(version_id)
    if _write_redis:
        r.delete(prefix_key)
        # Delete meta key upfront so we can safely use hset even if a previous run
        # left a string value there (WRONGTYPE error otherwise).
        r.delete(_meta_key(version_id))

    pipe = r.pipeline(transaction=False) if _write_redis else _NoopPipe()
    class_count = property_count = concept_count = 0
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

    # Collect the exact per-entity hash dicts so entity_index can be populated
    # DIRECTLY from them (#242 Stage 2 Workstream B), instead of pg_indexer reading
    # these same hashes back out of Redis. Same dicts in → identical entity_index
    # rows (parity), and it stops the producer depending on its own Redis output.
    entity_hashes: dict[str, dict] = {}

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

        # primary_label: first English label, or first label of any lang, or —
        # when the source ontology gives no label at all — a humanized form of
        # the IRI local name (CamelCase/snake/kebab split) rather than the raw
        # identifier. The raw `short` is still indexed for search below, so this
        # only improves display, never search recall.
        primary_label = next(
            (e["value"] for e in labels_list if e["lang"] == "en"),
            labels_list[0]["value"] if labels_list else humanize_local_name(short),
        )

        _hash = {
            "label":         primary_label,   # backward compat
            "primary_label": primary_label,
            "type":          entity_type,
            "iri":           iri,
            "short":         short,
            "source":        _get_source(iri),
            "labels":        json.dumps(labels_list),
            "synonyms":      json.dumps(deduped_syns),
            "definitions":   json.dumps(defs_list),
        }
        # Only individuals carry rdf:type classes; skip the field otherwise so
        # class/property hashes (the bulk of the working set) stay unchanged.
        _types = types_by_iri.get(iri)
        if _types:
            _hash["types"] = json.dumps(_types)
        entity_hashes[iri] = _hash
        pipe.hset(_iri_key(version_id, iri), mapping=_hash)
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
        elif entity_type == "concept":
            concept_count += 1
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
        # NOTE: owl:Thing is intentionally NOT added to entity_hashes (so it does not
        # become an entity_index row). Giving it a row makes it is_root=True → a
        # "Thing" node in every class tree and +1 in class/lang counts. It stays a
        # Redis-only built-in served via the _entity_source fallback; promoting it to
        # entity_index (with the needed root/list/count filtering) is a separate change.
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
    pipe.expire(_type_key(version_id, "concept"),             _SEARCH_TTL)
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
        "concept_count":    str(concept_count),
    })
    pipe.expire(_meta_key(version_id), _SEARCH_TTL)
    # Store deprecated IRI set for use by the inferred-tree endpoint.
    dep_key = _deprecated_key(version_id)
    pipe.delete(dep_key)
    if deprecated_iris:
        pipe.sadd(dep_key, *deprecated_iris)
        pipe.expire(dep_key, _SEARCH_TTL)
    pipe.execute()

    if _write_redis:
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
    # OWL 2 profile detection is populated separately by the index_ontology task
    # (native horned-profile over the stored file — see #149), not here.
    _populate_reuse_cache(version_id, ontology_id, entities, r)

    return IndexStats(
        version_id=version_id,
        class_count=class_count,
        property_count=property_count,
        individual_count=individual_count,
        concept_count=concept_count,
        entities=entity_hashes,
        deprecated=deprecated_iris,
        individuals=individual_iris,
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
    concept_count   = sum(1 for t in entities.values() if t == "concept")

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
    # ABox-only vocabs rescued by the indexer fallback (domain-class instances with
    # no owl:NamedIndividual typing, e.g. QUDT units) are typed "individual" in the
    # entities dict but not counted by the owl:NamedIndividual query above — floor
    # the stat with them so /stats agrees with what entity_index actually holds.
    ind_from_entities = sum(1 for t in entities.values() if t == "individual")
    ind_count = max(ind_count, ind_from_entities)

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
        "concept_count":             concept_count,
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
