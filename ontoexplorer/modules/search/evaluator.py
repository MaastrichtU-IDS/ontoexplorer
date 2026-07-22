"""MOS expression evaluator: AST → matching class IRIs via hybrid ELK + Oxigraph SPARQL."""
from __future__ import annotations

import asyncio
import json as _json
import re
from dataclasses import dataclass

from ontoexplorer.clients.oxigraph import graph_iri as _graph_iri, sparql_query
from ontoexplorer.clients.reasoning import get_classification
from ontoexplorer.modules.search.indexer import (
    _get_redis,
    _iri_key,
    _prefix_key,
    _type_key,
    normalise_label,
)
from ontoexplorer.modules.search.mos_parser import (
    AllValuesFrom,
    And,
    ExactCardinality,
    HasSelf,
    HasValue,
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


def _resolve_label(
    r,
    version_id: str,
    node: NamedClass,
    allowed_types: frozenset[str] | None = None,
) -> str:
    """Resolve a NamedClass node to a single IRI. Raises AmbiguousLabelError if ambiguous.

    allowed_types: when set, only entries whose stored entity type is in this set are
    considered. Use _PROPERTY_TYPES for property-ref positions to exclude annotation
    properties, which are not valid in OWL class expressions.
    """
    if node.curie:
        # Disambiguated form: look up by CURIE (stored as `short` field)
        norm = normalise_label(node.curie)
        key = _prefix_key(version_id)
        members = r.zrangebylex(key, f"[{norm}", f"[{norm}\xff")
        for m in members:
            parts = m.split("|", 3)
            if len(parts) == 4:
                etype, iri = parts[2], parts[3]
            elif len(parts) == 3:
                etype, iri = parts[1], parts[2]
            else:
                continue
            if allowed_types and etype not in allowed_types:
                continue
            detail = r.hgetall(_iri_key(version_id, iri))
            if detail.get("short") == node.curie:
                return iri
        # Fallback: if CURIE is itself an IRI fragment
        return node.ref

    # Check if ref looks like a CURIE or IRI already
    if ":" in node.ref and not node.ref.startswith("'"):
        # Expand well-known OWL/RDF/RDFS/XSD CURIEs to full IRIs immediately.
        m = _CURIE_STRICT_RE.match(node.ref)
        if m and m.group(1) in _WELL_KNOWN_PREFIXES:
            return _WELL_KNOWN_PREFIXES[m.group(1)] + m.group(2)

        # Try direct lookup via short/CURIE
        norm = normalise_label(node.ref)
        key = _prefix_key(version_id)
        members = r.zrangebylex(key, f"[{norm}", f"[{norm}\xff")
        for m in members:
            parts = m.split("|", 3)
            if len(parts) == 4:
                etype, iri = parts[2], parts[3]
            elif len(parts) == 3:
                etype, iri = parts[1], parts[2]
            else:
                continue
            if allowed_types and etype not in allowed_types:
                continue
            return iri
        return node.ref  # treat as IRI directly

    # Plain label — look up in prefix index
    norm = normalise_label(node.ref)
    key = _prefix_key(version_id)
    members = r.zrangebylex(key, f"[{norm}|", f"[{norm}|\xff")
    # Exact-label match: the indexed norm-key equals norm AND the entity's
    # primary label also normalises to norm.  The second check filters out
    # word-suffix entries (e.g. "physical object" is indexed under "object"
    # as a word-suffix, but its primary label normalises to "physical object",
    # not "object", so it must not count as a match for 'object').
    matched: list[dict] = []
    seen_iris: set[str] = set()
    for m in members:
        parts = m.split("|", 3)
        if len(parts) == 4:
            norm_lbl, _lang_tag, etype, iri = parts
        elif len(parts) == 3:
            norm_lbl, etype, iri = parts
        else:
            continue
        if norm_lbl != norm:
            continue
        if allowed_types and etype not in allowed_types:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        detail = r.hgetall(_iri_key(version_id, iri))
        if not detail:
            continue
        if normalise_label(detail.get("label", "")) != norm:
            continue  # word-suffix entry — primary label doesn't match query
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
    lang: str | None = None,
    direct: bool = False,
    reasoner: str = "whelk",
) -> list[SearchResult]:
    """Evaluate a MOS AST node against the given version, returning matching classes.

    direct=True returns only immediate subclasses (one hop in the hierarchy) and
    classes that directly assert a restriction, without expanding via ELK subclasses.
    """
    r = _get_redis()

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
            iri = _resolve_label(r, version_id, n)
            if iri == _OWL_THING:
                return r.smembers(_type_key(version_id, "class"))
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

        if isinstance(n, (SomeValuesFrom, AllValuesFrom, HasValue, HasSelf,
                          MinCardinality, MaxCardinality, ExactCardinality)):
            asserters = await asyncio.to_thread(_sparql_eval, n, version_id, ontology_id, r)
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
                                                  ExactCardinality)) else "sparql"
    return _build_results(iris, version_id, lang, r, match_type)


def _build_results(
    iris, version_id: str, lang: str | None, r, match_type: str
) -> list[SearchResult]:
    """Resolve a set of class IRIs to labelled SearchResults via the Redis index."""
    results: list[SearchResult] = []
    for iri in iris:
        detail = r.hgetall(_iri_key(version_id, iri))
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
    relation: str = "subclasses",
    lang: str | None = None,
    direct: bool = False,
    reasoner: str = "whelk",
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
        return await evaluate(node, version_id, ontology_id, lang=lang, direct=direct, reasoner=reasoner)

    if relation not in ("superclasses", "equivalent"):
        raise ValueError(f"Unknown relation: {relation!r}")

    if not isinstance(node, NamedClass):
        raise RelationRequiresNamedClassError(relation)

    r = _get_redis()
    classification = await get_classification(version_id, reasoner=reasoner)
    # ELK's transitive `superclasses` index is unreliable on some ontologies
    # (entries missing, or inconsistent with direct_superclasses — e.g. SULO).
    # `direct_superclasses` is the trustworthy edge set; derive everything from it.
    direct_superclasses: dict[str, list[str]] = classification.get("direct_superclasses") or {}

    iri = _resolve_label(r, version_id, node)

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
        return _build_results(supers, version_id, lang, r, "elk")

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
    return _build_results(equivalents, version_id, lang, r, "elk")


def _sparql_eval(node, version_id: str, ontology_id: str, r) -> set[str]:
    """Translate restriction AST nodes to SPARQL and query Oxigraph."""
    OWL = "http://www.w3.org/2002/07/owl#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"
    g = _graph_iri(ontology_id, version_id)

    def resolve_prop(named_class_node) -> str:
        return _resolve_label(r, version_id, named_class_node, allowed_types=_PROPERTY_TYPES)

    def resolve(named_class_node) -> str:
        return _resolve_label(r, version_id, named_class_node)

    RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    if isinstance(node, SomeValuesFrom):
        prop_iri = resolve_prop(node.property_ref)
        # Use rdfs:subPropertyOf* so that restrictions written on sub-properties
        # of the queried property are also matched.  For example, querying
        # 'has part some X' should find classes with 'has direct part some X'
        # when 'has direct part' subPropertyOf 'has part'.
        if isinstance(node.filler, NamedClass):
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
        val_iri = resolve(node.value_ref)
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                GRAPH <{g}> {{
                    ?cls <{RDFS}subClassOf> ?restr .
                    ?restr <{OWL}onProperty> ?prop .
                    ?restr <{OWL}hasValue> <{val_iri}> .
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


