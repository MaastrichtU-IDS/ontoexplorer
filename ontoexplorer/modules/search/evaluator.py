"""MOS expression evaluator: AST → matching class IRIs via hybrid ELK + Oxigraph SPARQL."""
from __future__ import annotations

import asyncio
import json as _json
import re
from dataclasses import dataclass

from ontoexplorer.clients.oxigraph import graph_iri as _graph_iri, sparql_query
from ontoexplorer.clients.reasoning import get_classification
from ontoexplorer.modules.search.indexer import normalise_label
from ontoexplorer.modules.search.mos_parser import (
    AllValuesFrom,
    And,
    DatatypeRestriction,
    ExactCardinality,
    HasSelf,
    HasValue,
    InverseRestriction,
    Literal,
    MaxCardinality,
    MinCardinality,
    NamedClass,
    Not,
    Or,
    SomeValuesFrom,
)


def _pick_label(detail: dict, lang: str | None) -> tuple[str, str | None]:
    """Return (label_string, lang_tag) for the given lang preference.

    Falls back to primary_label when the preferred lang is not available.
    """
    labels_raw = detail.get("labels")
    if labels_raw:
        try:
            labels = _json.loads(labels_raw)
        except (ValueError, TypeError):
            labels = []
        if lang and labels:
            for entry in labels:
                if entry.get("lang") == lang:
                    return entry["value"], lang
        if labels:
            first = labels[0]
            return first["value"], first.get("lang") or None
    # v1 schema fallback or empty labels
    return detail.get("primary_label") or detail.get("label", ""), None


@dataclass
class SearchResult:
    iri: str
    label: str
    short: str
    match_type: str       # "elk" | "sparql" | "entity"
    lang: str | None = None
    cross_language: bool = False


class AmbiguousLabelError(ValueError):
    def __init__(self, label: str, candidates: list[dict]):
        super().__init__(f"Ambiguous label: {label!r} matches {len(candidates)} entities")
        self.label = label
        self.candidates = candidates


_PROPERTY_TYPES = frozenset({"object_property", "data_property"})

_OWL_THING = "http://www.w3.org/2002/07/owl#Thing"

_WELL_KNOWN_PREFIXES: dict[str, str] = {
    "owl":  "http://www.w3.org/2002/07/owl#",
    "rdf":  "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd":  "http://www.w3.org/2001/XMLSchema#",
}
_CURIE_STRICT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*):([A-Za-z0-9_\-\.]+)$")


@dataclass
class _Resolver:
    """In-memory label/CURIE/IRI resolution index for one version, built once from
    entity_index (#242 Workstream B — replaces the Redis prefix-zset + `:iri:` hashes
    the evaluator read per node). Keeps the sync SPARQL evaluators sync.
    """
    by_norm: dict[str, list[tuple[str, str]]]   # normalise_label(primary_label) -> [(type, iri)]
    by_short: dict[str, tuple[str, str]]         # short -> (type, iri), first-wins
    by_iri: dict[str, dict]                      # iri -> legacy entity dict (for labels)
    class_iris: set[str]


# Synthetic owl:Thing — the indexer injects an owl:Thing LABEL entry into the Redis
# prefix-zset (indexer.py) but writes NO entity_index row for it (it is a built-in,
# not an asserted class). Seed it into every resolver so `Thing` / the `owl:Thing`
# CURIE still resolve to the universal class. It is ADDED alongside any real class
# labelled "Thing" (so a genuine collision still raises AmbiguousLabelError), and
# `class_iris` (the owl:Thing EXPANSION target) deliberately excludes owl:Thing
# itself, matching the old `smembers(type:class)` set.
_OWL_THING_DETAIL = {
    "iri": _OWL_THING, "primary_label": "Thing", "label": "Thing",
    "short": "owl:Thing", "type": "class", "source": "",
    "labels": _json.dumps([{"value": "Thing", "lang": None}]),
    "synonyms": "[]", "definitions": "[]", "types": "[]",
}


def _seed_owl_thing(resolver: _Resolver) -> None:
    resolver.by_norm.setdefault("thing", []).append(("class", _OWL_THING))
    resolver.by_short.setdefault("owl:Thing", ("class", _OWL_THING))
    resolver.by_iri.setdefault(_OWL_THING, _OWL_THING_DETAIL)


def _resolver_from_rows(rows, class_iris: set[str] | None = None) -> _Resolver:
    from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict as _adapt
    by_norm: dict[str, list[tuple[str, str]]] = {}
    by_short: dict[str, tuple[str, str]] = {}
    by_iri: dict[str, dict] = {}
    _classes: set[str] = set(class_iris) if class_iris is not None else set()
    for row in rows:
        by_iri[row.iri] = _adapt(row)
        if class_iris is None and row.type == "class":
            _classes.add(row.iri)
        # Key on the entity's own primary label normalised — matches the old
        # exact-label check `normalise_label(detail["label"]) == norm` (NOT the
        # decamelized primary_label_norm, which is more permissive).
        n = normalise_label(row.primary_label or "")
        if n:
            by_norm.setdefault(n, []).append((row.type, row.iri))
        if row.short and row.short not in by_short:
            by_short[row.short] = (row.type, row.iri)
    resolver = _Resolver(by_norm, by_short, by_iri, _classes)
    _seed_owl_thing(resolver)
    return resolver


def _collect_refs(node) -> tuple[set[str], bool]:
    """Walk a MOS AST, returning (every NamedClass ref/curie string referenced,
    whether owl:Thing is referenced). Used to SCOPE the resolver query to just the
    labels a query mentions, instead of loading a version's whole entity_index."""
    refs: set[str] = set()
    owl_thing = False

    def walk(n) -> None:
        nonlocal owl_thing
        if isinstance(n, NamedClass):
            if n.ref:
                refs.add(n.ref)
            if n.curie:
                refs.add(n.curie)
            if n.curie == "owl:Thing" or normalise_label(n.ref or "") == "thing":
                owl_thing = True
            return  # a NamedClass carries no child AST nodes
        if n is None or isinstance(n, (str, int, float, bool, Literal)):
            return
        if isinstance(n, (list, tuple, set)):
            for x in n:
                walk(x)
            return
        if hasattr(n, "__dict__"):
            for v in vars(n).values():
                walk(v)

    walk(node)
    return refs, owl_thing


def _scope_conditions(_EI, refs: set[str]):
    """SQL predicates selecting entity_index rows that COULD match one of `refs`
    under the evaluator's exact `normalise_label(primary_label)` / `short` keys.

    A superset (the exact match is re-applied in Python by `_resolver_from_rows`):
    `primary_label_norm` is the decamelized norm (catches space/punctuation-normal
    labels) and `lower(primary_label)` catches camelCase labels queried by their
    concatenated form; `short` catches CURIE/short refs."""
    from sqlalchemy import func, or_
    normed = {normalise_label(r) for r in refs if r}
    normed.discard("")
    lowered = {r.lower() for r in refs if r}
    conds = []
    if normed:
        conds.append(_EI.primary_label_norm.in_(normed))
    if lowered:
        conds.append(func.lower(_EI.primary_label).in_(lowered))
    if refs:
        conds.append(_EI.short.in_(refs))
    return or_(*conds) if conds else None


async def build_resolver(
    db, version_id: str, refs: set[str], *, need_classes: bool = False
) -> _Resolver:
    """Load the entity_index rows for one version that `refs` could resolve to.

    Scoped to the query's referenced labels so a single expression search never
    materialises the whole version (#242 Workstream B). When `need_classes` (the
    query mentions owl:Thing), also load every class IRI for owl:Thing expansion."""
    from sqlalchemy import select as _select
    from ontoexplorer.models.db import EntityIndex as _EI
    cond = _scope_conditions(_EI, refs)
    rows = []
    if cond is not None:
        rows = (await db.execute(
            _select(_EI).where(_EI.version_id == version_id, cond))).scalars().all()
    class_iris: set[str] | None = None
    if need_classes:
        class_iris = set((await db.execute(
            _select(_EI.iri).where(_EI.version_id == version_id, _EI.type == "class")
        )).scalars().all())
    return _resolver_from_rows(rows, class_iris)


async def build_resolvers(
    db, version_ids: list[str], refs: set[str], *, need_classes: bool = False
) -> dict[str, _Resolver]:
    """Batch-build scoped resolvers for several versions in ONE query, so the
    cross-version expression fan-out doesn't run a per-version query on a shared
    session (asyncio.gather over one AsyncSession is unsafe). Scoped to `refs`."""
    if not version_ids:
        return {}
    from sqlalchemy import select as _select
    from ontoexplorer.models.db import EntityIndex as _EI
    vids = list(version_ids)
    cond = _scope_conditions(_EI, refs)
    by_v: dict[str, list] = {}
    if cond is not None:
        rows = (await db.execute(
            _select(_EI).where(_EI.version_id.in_(vids), cond))).scalars().all()
        for row in rows:
            by_v.setdefault(row.version_id, []).append(row)
    classes_by_v: dict[str, set[str]] = {}
    if need_classes:
        crows = (await db.execute(
            _select(_EI.version_id, _EI.iri).where(
                _EI.version_id.in_(vids), _EI.type == "class"))).all()
        for vid, iri in crows:
            classes_by_v.setdefault(vid, set()).add(iri)
    return {
        vid: _resolver_from_rows(
            by_v.get(vid, []), classes_by_v.get(vid) if need_classes else None)
        for vid in vids
    }


async def enrich_labels(db, items: list[dict], lang: str | None) -> None:
    """Fill proper labels on a (small, ≤limit) list of result dicts in place.

    Each item needs `version_id` and `iri`; `label`/`short`/`lang`/`cross_language`
    are overwritten from entity_index. The resolver renders labels only for the
    query's referenced IRIs, so expression RESULTS (subclasses/fillers, unknown
    until evaluation) arrive with a shortname fallback — this batched lookup
    (one query, bounded by the capped result set) restores their real labels.
    IRIs with no entity_index row (e.g. owl:Thing-expanded externals) keep the
    fallback."""
    from sqlalchemy import select as _select
    from ontoexplorer.models.db import EntityIndex as _EI
    from ontoexplorer.api.ols._shapes import entity_index_to_legacy_dict as _adapt
    pairs = {(it["version_id"], it["iri"]) for it in items if it.get("version_id")}
    if not pairs:
        return
    vids = {v for v, _ in pairs}
    iris = {i for _, i in pairs}
    rows = (await db.execute(
        _select(_EI).where(_EI.version_id.in_(vids), _EI.iri.in_(iris)))).scalars().all()
    by_key = {(r.version_id, r.iri): _adapt(r) for r in rows}
    for it in items:
        detail = by_key.get((it.get("version_id"), it["iri"]))
        if detail:
            label, result_lang = _pick_label(detail, lang)
            it["label"] = label
            it["short"] = detail.get("short", "")
            it["lang"] = result_lang
            it["cross_language"] = bool(lang) and result_lang != lang


def _resolve_label(
    resolver: _Resolver,
    version_id: str,
    node: NamedClass,
    allowed_types: frozenset[str] | None = None,
) -> str:
    """Resolve a NamedClass node to a single IRI via the entity_index resolver.
    Raises AmbiguousLabelError if ambiguous.

    allowed_types: when set, only entries whose stored entity type is in this set are
    considered. Use _PROPERTY_TYPES for property-ref positions to exclude annotation
    properties, which are not valid in OWL class expressions.
    """
    if node.curie:
        # Disambiguated form: look up by CURIE (stored as the `short` field).
        hit = resolver.by_short.get(node.curie)
        if hit and (not allowed_types or hit[0] in allowed_types):
            return hit[1]
        return node.ref  # Fallback: treat the CURIE as an IRI fragment.

    # Check if ref looks like a CURIE or IRI already
    if ":" in node.ref and not node.ref.startswith("'"):
        # Expand well-known OWL/RDF/RDFS/XSD CURIEs to full IRIs immediately.
        m = _CURIE_STRICT_RE.match(node.ref)
        if m and m.group(1) in _WELL_KNOWN_PREFIXES:
            return _WELL_KNOWN_PREFIXES[m.group(1)] + m.group(2)

        # A CURIE-shaped ref may be stored verbatim as an entity's `short`
        # (e.g. ontologies that keep CURIE short-forms) — try that first, then a
        # normalised-label match, mirroring the old prefix-zset recall for this
        # branch. Last resort: treat the ref as an IRI directly.
        hit = resolver.by_short.get(node.ref)
        if hit and (not allowed_types or hit[0] in allowed_types):
            return hit[1]
        for etype, iri in resolver.by_norm.get(normalise_label(node.ref), []):
            if not allowed_types or etype in allowed_types:
                return iri
        return node.ref  # treat as IRI directly

    # Plain label — exact-label match from the resolver (by_norm is keyed on the
    # entity's own normalised primary label, so there are no word-suffix entries).
    norm = normalise_label(node.ref)
    matched: list[dict] = []
    seen_iris: set[str] = set()
    for etype, iri in resolver.by_norm.get(norm, []):
        if allowed_types and etype not in allowed_types:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        detail = resolver.by_iri.get(iri)
        if detail:
            matched.append(detail)

    if len(matched) == 0:
        raise ValueError(f"'{node.ref}' not found in this ontology's index")
    if len(matched) == 1:
        return matched[0]["iri"]
    raise AmbiguousLabelError(node.ref, matched)


def _needs_elk(node) -> bool:
    """True if the top-level node uses the ELK subclass index (NamedClass, And, Or, Not).
    Restrictions go through SPARQL and never need ELK, even when their filler is a NamedClass."""
    if isinstance(node, NamedClass):
        return True
    if isinstance(node, And):
        return _needs_elk(node.left) or _needs_elk(node.right)
    if isinstance(node, Or):
        return _needs_elk(node.left) or _needs_elk(node.right)
    if isinstance(node, Not):
        return True
    # Restrictions (SomeValuesFrom, AllValuesFrom, etc.) are SPARQL-only
    return False


async def evaluate(
    node,
    version_id: str,
    ontology_id: str,
    resolver: _Resolver,
    lang: str | None = None,
    direct: bool = False,
    reasoner: str = "rustdl",
) -> list[SearchResult]:
    """Evaluate a MOS AST node against the given version, returning matching classes.

    `resolver` is the entity_index-backed label index for this version (build it with
    `build_resolver`); callers build it so a cross-version fan-out can batch one query.

    direct=True returns only immediate subclasses (one hop in the hierarchy) and
    classes that directly assert a restriction, without expanding via ELK subclasses.
    """

    # Always load ELK: needed for NamedClass/And/Or/Not, and (when direct=False) to
    # expand SPARQL restriction results with inherited subclasses.
    classification = await get_classification(version_id, reasoner=reasoner)
    subclasses_index: dict[str, list[str]] = classification.get("subclasses", {})
    # The whelk backend keeps ASSERTED subclass edges only in `direct_subclasses`
    # — `subclasses` holds inferred-not-asserted transitive edges. Neither map
    # alone is the complete closure: their union is (every edge missing from
    # `subclasses` is an asserted one, and asserted edges are exactly what
    # `direct_subclasses` carries). So a class whose subsumption under the query
    # is asserted (e.g. GO_0016218 subClassOf 'catalytic activity') lives only in
    # `direct_subclasses` and must be folded back in for a complete answer.
    _asserted_direct_sub: dict[str, list[str]] = classification.get("direct_subclasses") or {}
    # direct_subclasses_index falls back to subclasses_index if the key is absent
    # (older ELK service versions may not include it).
    _ds = classification.get("direct_subclasses")
    direct_subclasses_index: dict[str, list[str]] = (
        _ds if _ds is not None else subclasses_index
    ) if direct else subclasses_index
    all_class_iris: set[str] = (
        set(subclasses_index.keys())
        | {iri for subs in subclasses_index.values() for iri in subs}
        | set(_asserted_direct_sub.keys())
        | {iri for subs in _asserted_direct_sub.values() for iri in subs}
    )

    async def _eval_with_index(n, idx: dict) -> set[str]:
        if isinstance(n, NamedClass):
            iri = _resolve_label(resolver, version_id, n)
            if iri == _OWL_THING:
                return set(resolver.class_iris)
            # Union the asserted direct edges so asserted genus links (present
            # only in direct_subclasses) are never dropped. Idempotent in direct
            # mode, where `idx` already is the asserted-direct map.
            subs = set(idx.get(iri, [])) | set(_asserted_direct_sub.get(iri, []))
            subs.add(iri)
            return subs

        if isinstance(n, And):
            left, right = await asyncio.gather(
                _eval_with_index(n.left, idx), _eval_with_index(n.right, idx)
            )
            return left & right

        if isinstance(n, Or):
            left, right = await asyncio.gather(
                _eval_with_index(n.left, idx), _eval_with_index(n.right, idx)
            )
            return left | right

        if isinstance(n, Not):
            # Always subtract using the full subclass index — "not A" means
            # all classes that are not A or any of its subclasses, regardless
            # of the direct flag on the outer query.
            return all_class_iris - await _eval_with_index(n.operand, subclasses_index)

        # Restriction nodes (SomeValuesFrom, HasValue, etc.) are not ELK-based;
        # delegate to _eval which handles SPARQL evaluation for them.
        return await _eval(n)

    async def _eval(n) -> set[str]:
        if isinstance(n, (NamedClass, And, Or, Not)):
            return await _eval_with_index(n, direct_subclasses_index)

        if isinstance(n, InverseRestriction):
            # Reverse lookup: resolve the holder-constraint class, expand it with
            # its subclasses (unless direct), then return the fillers of the
            # forward restriction carried by those holders.
            holder_iri = _resolve_label(resolver, version_id, n.holder_ref)
            holders = {holder_iri}
            if not direct:
                holders |= set(subclasses_index.get(holder_iri, []))
                holders |= set(_asserted_direct_sub.get(holder_iri, []))
            return await asyncio.to_thread(
                _sparql_eval_inverse, n, holders, version_id, ontology_id, resolver)

        if isinstance(n, (SomeValuesFrom, AllValuesFrom, HasValue, HasSelf,
                          MinCardinality, MaxCardinality, ExactCardinality)):
            asserters = await asyncio.to_thread(_sparql_eval, n, version_id, ontology_id, resolver)
            if direct:
                # Direct mode: only classes that explicitly assert the restriction,
                # no ELK subclass expansion.
                return asserters
            # Non-direct: expand with ELK subclasses so classes that inherit the
            # restriction from a superclass are also included.
            expanded = set(asserters)
            for iri in asserters:
                expanded.update(subclasses_index.get(iri, []))
                expanded.update(_asserted_direct_sub.get(iri, []))
            return expanded

        return set()

    iris = await _eval(node)

    match_type = "elk" if not isinstance(node, (SomeValuesFrom, AllValuesFrom, HasValue,
                                                  HasSelf, MinCardinality, MaxCardinality,
                                                  ExactCardinality, InverseRestriction)) else "sparql"
    return _build_results(iris, version_id, lang, resolver, match_type)


def _build_results(
    iris, version_id: str, lang: str | None, resolver: _Resolver, match_type: str
) -> list[SearchResult]:
    """Resolve a set of class IRIs to labelled SearchResults via the entity_index resolver."""
    results: list[SearchResult] = []
    for iri in iris:
        detail = resolver.by_iri.get(iri)
        if detail:
            label, result_lang = _pick_label(detail, lang)
            cross_language = bool(lang) and result_lang != lang
            short = detail.get("short", "")
        else:
            label, result_lang, cross_language = iri.split("/")[-1], None, False
            short = ""
        results.append(SearchResult(
            iri=iri,
            label=label,
            short=short,
            match_type=match_type,
            lang=result_lang,
            cross_language=cross_language,
        ))
    return results


class RelationRequiresNamedClassError(ValueError):
    """Raised when superclasses/equivalent is requested for a complex expression."""


async def evaluate_relation(
    node,
    version_id: str,
    ontology_id: str,
    resolver: _Resolver,
    relation: str = "subclasses",
    lang: str | None = None,
    direct: bool = False,
    reasoner: str = "rustdl",
) -> list[SearchResult]:
    """Evaluate a MOS AST node for a given relationship to the expression.

    relation:
      - "subclasses"   — subclass closure (delegates to evaluate(); any expression)
      - "superclasses" — ancestors of a single named class (direct vs all)
      - "equivalent"   — classes equivalent to a single named class

    Superclasses and equivalent are only defined for a single NamedClass; a
    complex expression raises RelationRequiresNamedClassError.
    """
    if relation == "subclasses":
        return await evaluate(node, version_id, ontology_id, resolver, lang=lang, direct=direct, reasoner=reasoner)

    if relation not in ("superclasses", "equivalent"):
        raise ValueError(f"Unknown relation: {relation!r}")

    if not isinstance(node, NamedClass):
        raise RelationRequiresNamedClassError(relation)

    classification = await get_classification(version_id, reasoner=reasoner)
    # ELK's transitive `superclasses` index is unreliable on some ontologies
    # (entries missing, or inconsistent with direct_superclasses — e.g. SULO).
    # `direct_superclasses` is the trustworthy edge set; derive everything from it.
    direct_superclasses: dict[str, list[str]] = classification.get("direct_superclasses") or {}

    iri = _resolve_label(resolver, version_id, node)

    def _direct_parents(c: str) -> list[str]:
        return [p for p in direct_superclasses.get(c, []) if p != _OWL_THING]

    if relation == "superclasses":
        if direct:
            supers = {p for p in _direct_parents(iri) if p != iri}
        else:
            # Walk the direct-superclass DAG upward to collect all ancestors.
            supers = set()
            stack = list(_direct_parents(iri))
            while stack:
                cur = stack.pop()
                if cur in supers or cur == iri:
                    continue
                supers.add(cur)
                stack.extend(_direct_parents(cur))
        return _build_results(supers, version_id, lang, resolver, "elk")

    # relation == "equivalent": A ≡ B iff each is an ancestor of the other.
    # An equivalence shows up as a cycle in the direct-superclass graph, so a
    # class B is equivalent to A when B is reachable upward from A *and* A is
    # reachable upward from B.
    _ancestor_memo: dict[str, set[str]] = {}

    def _ancestors(start: str) -> set[str]:
        if start in _ancestor_memo:
            return _ancestor_memo[start]
        seen: set[str] = set()
        stack = list(_direct_parents(start))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(_direct_parents(cur))
        _ancestor_memo[start] = seen
        return seen

    a_ancestors = _ancestors(iri)
    equivalents = {b for b in a_ancestors if b != iri and iri in _ancestors(b)}
    return _build_results(equivalents, version_id, lang, resolver, "elk")


def _literal_sparql(lit: Literal) -> str:
    """A typed-literal SPARQL term, e.g. `"42"^^<…#integer>`, with the lexical
    form escaped for a double-quoted SPARQL string."""
    esc = (lit.lexical.replace("\\", "\\\\").replace('"', '\\"')
           .replace("\n", "\\n").replace("\r", "\\r"))
    return f'"{esc}"^^<{lit.datatype}>'


def _sparql_eval(node, version_id: str, ontology_id: str, resolver: _Resolver) -> set[str]:
    """Translate restriction AST nodes to SPARQL and query Oxigraph."""
    OWL = "http://www.w3.org/2002/07/owl#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"
    g = _graph_iri(ontology_id, version_id)

    def resolve_prop(named_class_node) -> str:
        return _resolve_label(resolver, version_id, named_class_node, allowed_types=_PROPERTY_TYPES)

    def resolve(named_class_node) -> str:
        return _resolve_label(resolver, version_id, named_class_node)

    RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

    def _dtype_restr_query(prop_iri: str, dr: DatatypeRestriction, pred: str) -> str:
        """Match classes whose `pred` (someValuesFrom/allValuesFrom) filler is a
        faceted datatype restriction: onDatatype <base> with the exact facets."""
        base_dt = resolve(dr.datatype)
        facet_lines = "\n                ".join(
            f"?wr <{RDF}rest>*/<{RDF}first> [ <{fi}> {_literal_sparql(lit)} ] ."
            for fi, lit in dr.facets
        )
        return f"""
            SELECT DISTINCT ?cls WHERE {{ GRAPH <{g}> {{
                {{ ?cls <{RDFS}subClassOf> ?restr }} UNION
                {{ ?cls <{OWL}equivalentClass>/<{OWL}intersectionOf>/<{RDF}rest>*/<{RDF}first> ?restr }}
                ?restr <{OWL}onProperty> ?prop ; <{OWL}{pred}> ?dt .
                ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                ?dt <{OWL}onDatatype> <{base_dt}> ; <{OWL}withRestrictions> ?wr .
                {facet_lines}
            }} }}
        """

    if isinstance(node, SomeValuesFrom):
        prop_iri = resolve_prop(node.property_ref)
        # Use rdfs:subPropertyOf* so that restrictions written on sub-properties
        # of the queried property are also matched.  For example, querying
        # 'has part some X' should find classes with 'has direct part some X'
        # when 'has direct part' subPropertyOf 'has part'.
        if isinstance(node.filler, DatatypeRestriction):
            q = _dtype_restr_query(prop_iri, node.filler, "someValuesFrom")
        elif isinstance(node.filler, NamedClass):
            fill_iri = resolve(node.filler)
            q = f"""
                SELECT DISTINCT ?cls WHERE {{
                    GRAPH <{g}> {{
                        {{
                            ?cls <{RDFS}subClassOf> ?restr .
                            ?restr <{OWL}onProperty> ?prop .
                            ?restr <{OWL}someValuesFrom> <{fill_iri}> .
                            ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                        }} UNION {{
                            ?cls <{OWL}equivalentClass> ?inter .
                            ?inter <{OWL}intersectionOf>/<{RDF}rest>*/<{RDF}first> ?restr .
                            ?restr <{OWL}onProperty> ?prop .
                            ?restr <{OWL}someValuesFrom> <{fill_iri}> .
                            ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                        }}
                    }}
                }}
            """
        else:
            q = f"""
                SELECT DISTINCT ?cls WHERE {{
                    GRAPH <{g}> {{
                        {{
                            ?cls <{RDFS}subClassOf> ?restr .
                            ?restr <{OWL}onProperty> ?prop .
                            ?restr <{OWL}someValuesFrom> ?fill .
                            ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                        }} UNION {{
                            ?cls <{OWL}equivalentClass> ?inter .
                            ?inter <{OWL}intersectionOf>/<{RDF}rest>*/<{RDF}first> ?restr .
                            ?restr <{OWL}onProperty> ?prop .
                            ?restr <{OWL}someValuesFrom> ?fill .
                            ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                        }}
                    }}
                }}
            """
    elif isinstance(node, AllValuesFrom):
        prop_iri = resolve_prop(node.property_ref)
        if isinstance(node.filler, DatatypeRestriction):
            q = _dtype_restr_query(prop_iri, node.filler, "allValuesFrom")
        else:
            fill_iri = resolve(node.filler) if isinstance(node.filler, NamedClass) else node.filler.ref
            q = f"""
                SELECT DISTINCT ?cls WHERE {{
                    GRAPH <{g}> {{
                        ?cls <{RDFS}subClassOf> ?restr .
                        ?restr <{OWL}onProperty> ?prop .
                        ?restr <{OWL}allValuesFrom> <{fill_iri}> .
                        ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                    }}
                }}
            """
    elif isinstance(node, HasValue):
        prop_iri = resolve_prop(node.property_ref)
        val_term = (_literal_sparql(node.value_ref)
                    if isinstance(node.value_ref, Literal)
                    else f"<{resolve(node.value_ref)}>")
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                GRAPH <{g}> {{
                    ?cls <{RDFS}subClassOf> ?restr .
                    ?restr <{OWL}onProperty> ?prop .
                    ?restr <{OWL}hasValue> {val_term} .
                    ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                }}
            }}
        """
    elif isinstance(node, HasSelf):
        prop_iri = resolve_prop(node.property_ref)
        XSD = "http://www.w3.org/2001/XMLSchema#"
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                GRAPH <{g}> {{
                    ?cls <{RDFS}subClassOf> ?restr .
                    ?restr <{OWL}onProperty> ?prop .
                    ?restr <{OWL}hasSelf> "true"^^<{XSD}boolean> .
                    ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                }}
            }}
        """
    elif isinstance(node, MinCardinality):
        prop_iri = resolve_prop(node.property_ref)
        fill_iri = resolve(node.filler) if isinstance(node.filler, NamedClass) else node.filler.ref
        n = node.cardinality
        OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        # `min n R C` = at least n R-successors in C. Match, on subClassOf and on
        # equivalentClass intersections (mirroring the `some` path):
        #   - qualified min-cardinality on C with count >= n, and
        #   - since (some R C) ≡ (min 1 R C), for n <= 1 also `someValuesFrom C`.
        # Unqualified min-cardinality only constrains C when C is owl:Thing.
        blocks = [
            f"""{{ ?cls <{RDFS}subClassOf> ?restr .
                   ?restr <{OWL}onProperty> ?prop ;
                          <{OWL}minQualifiedCardinality> ?n ;
                          <{OWL}onClass> <{fill_iri}> .
                   FILTER(?n >= {n})
                   ?prop <{RDFS}subPropertyOf>* <{prop_iri}> . }}""",
            f"""{{ ?cls <{OWL}equivalentClass>/<{OWL}intersectionOf>/<{RDF}rest>*/<{RDF}first> ?restr .
                   ?restr <{OWL}onProperty> ?prop ;
                          <{OWL}minQualifiedCardinality> ?n ;
                          <{OWL}onClass> <{fill_iri}> .
                   FILTER(?n >= {n})
                   ?prop <{RDFS}subPropertyOf>* <{prop_iri}> . }}""",
        ]
        if n <= 1:
            blocks += [
                f"""{{ ?cls <{RDFS}subClassOf> ?restr .
                       ?restr <{OWL}onProperty> ?prop ;
                              <{OWL}someValuesFrom> <{fill_iri}> .
                       ?prop <{RDFS}subPropertyOf>* <{prop_iri}> . }}""",
                f"""{{ ?cls <{OWL}equivalentClass>/<{OWL}intersectionOf>/<{RDF}rest>*/<{RDF}first> ?restr .
                       ?restr <{OWL}onProperty> ?prop ;
                              <{OWL}someValuesFrom> <{fill_iri}> .
                       ?prop <{RDFS}subPropertyOf>* <{prop_iri}> . }}""",
            ]
        if fill_iri == OWL_THING:
            blocks.append(
                f"""{{ ?cls <{RDFS}subClassOf> ?restr .
                       ?restr <{OWL}onProperty> ?prop ;
                              <{OWL}minCardinality> ?n .
                       FILTER(?n >= {n})
                       ?prop <{RDFS}subPropertyOf>* <{prop_iri}> . }}""")
        q = f"SELECT DISTINCT ?cls WHERE {{ GRAPH <{g}> {{ {' UNION '.join(blocks)} }} }}"
    elif isinstance(node, (MaxCardinality, ExactCardinality)):
        # max n R C / exactly n R C: qualified cardinality on the filler with the
        # right comparator, on subClassOf and equivalentClass-intersection forms
        # (mirrors min); unqualified cardinality only when the filler is owl:Thing.
        # Neither is equivalent to `some`, so no someValuesFrom fallback.
        prop_iri = resolve_prop(node.property_ref)
        fill_iri = resolve(node.filler) if isinstance(node.filler, NamedClass) else node.filler.ref
        n = node.cardinality
        OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        if isinstance(node, MaxCardinality):
            qual_pred, unqual_pred, cmp = "maxQualifiedCardinality", "maxCardinality", "<="
        else:
            qual_pred, unqual_pred, cmp = "qualifiedCardinality", "cardinality", "="
        blocks = [
            f"""{{ ?cls <{RDFS}subClassOf> ?restr .
                   ?restr <{OWL}onProperty> ?prop ;
                          <{OWL}{qual_pred}> ?n ;
                          <{OWL}onClass> <{fill_iri}> .
                   FILTER(?n {cmp} {n})
                   ?prop <{RDFS}subPropertyOf>* <{prop_iri}> . }}""",
            f"""{{ ?cls <{OWL}equivalentClass>/<{OWL}intersectionOf>/<{RDF}rest>*/<{RDF}first> ?restr .
                   ?restr <{OWL}onProperty> ?prop ;
                          <{OWL}{qual_pred}> ?n ;
                          <{OWL}onClass> <{fill_iri}> .
                   FILTER(?n {cmp} {n})
                   ?prop <{RDFS}subPropertyOf>* <{prop_iri}> . }}""",
        ]
        if fill_iri == OWL_THING:
            blocks.append(
                f"""{{ ?cls <{RDFS}subClassOf> ?restr .
                       ?restr <{OWL}onProperty> ?prop ;
                              <{OWL}{unqual_pred}> ?n .
                       FILTER(?n {cmp} {n})
                       ?prop <{RDFS}subPropertyOf>* <{prop_iri}> . }}""")
        q = f"SELECT DISTINCT ?cls WHERE {{ GRAPH <{g}> {{ {' UNION '.join(blocks)} }} }}"
    else:
        return set()

    results: set[str] = set()
    for sol in sparql_query(q):
        try:
            cls_val = sol["cls"]
            if cls_val is not None:
                results.add(cls_val.value)
        except Exception:
            pass
    return results


def _sparql_eval_inverse(node, holders: set[str], version_id: str, ontology_id: str, resolver: _Resolver) -> set[str]:
    """Reverse-lookup evaluation of `inverse P <kind> C`: given the holder set
    (C plus its subclasses, already resolved), return the fillers of the forward
    restriction carried by those holders. Fillers are classes for some/only and
    individuals for value."""
    OWL = "http://www.w3.org/2002/07/owl#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"
    RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    g = _graph_iri(ontology_id, version_id)
    if not holders:
        return set()
    prop_iri = _resolve_label(resolver, version_id, node.property_ref, allowed_types=_PROPERTY_TYPES)
    values = " ".join(f"<{h}>" for h in holders)
    # The pattern that binds ?fill from a restriction node ?restr, by kind.
    if node.kind in ("some", "only", "value"):
        pred = {"some": f"{OWL}someValuesFrom", "only": f"{OWL}allValuesFrom",
                "value": f"{OWL}hasValue"}[node.kind]
        fill_match = f"?restr <{pred}> ?fill ."
    else:
        # min/max/exactly: qualified cardinality on onClass. `min 1` ≡ `some`, so
        # also match someValuesFrom for min with n <= 1 (parity with the forward path).
        qual = {"min": "minQualifiedCardinality", "max": "maxQualifiedCardinality",
                "exactly": "qualifiedCardinality"}[node.kind]
        cmp = {"min": ">=", "max": "<=", "exactly": "="}[node.kind]
        n = node.cardinality
        fill_match = (
            f"{{ ?restr <{OWL}{qual}> ?nn ; <{OWL}onClass> ?fill . FILTER(?nn {cmp} {n}) }}"
        )
        if node.kind == "min" and n is not None and n <= 1:
            fill_match += f" UNION {{ ?restr <{OWL}someValuesFrom> ?fill }}"
    # Match the forward restriction on subClassOf and on equivalentClass
    # intersections (mirroring the forward `some` path), constrained to holders.
    q = f"""
        SELECT DISTINCT ?fill WHERE {{
            GRAPH <{g}> {{
                VALUES ?cls {{ {values} }}
                {{ ?cls <{RDFS}subClassOf> ?restr }} UNION
                {{ ?cls <{OWL}equivalentClass>/<{OWL}intersectionOf>/<{RDF}rest>*/<{RDF}first> ?restr }}
                ?restr <{OWL}onProperty> ?prop .
                ?prop <{RDFS}subPropertyOf>* <{prop_iri}> .
                {fill_match}
                FILTER(isIRI(?fill))
            }}
        }}
    """
    results: set[str] = set()
    for sol in sparql_query(q):
        try:
            fill_val = sol["fill"]
            if fill_val is not None:
                results.add(fill_val.value)
        except Exception:
            pass
    return results


