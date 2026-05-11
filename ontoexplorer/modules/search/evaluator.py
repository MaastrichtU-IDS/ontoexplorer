"""MOS expression evaluator: AST → matching class IRIs via hybrid ELK + Oxigraph SPARQL."""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
from ontoexplorer.clients.reasoning import ReasoningNotReadyError, get_classification
from ontoexplorer.modules.search.indexer import (
    _get_redis,
    _iri_key,
    _prefix_key,
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


@dataclass
class SearchResult:
    iri: str
    label: str
    short: str
    match_type: str   # "elk" | "sparql" | "entity"


class AmbiguousLabelError(ValueError):
    def __init__(self, label: str, candidates: list[dict]):
        super().__init__(f"Ambiguous label: {label!r} matches {len(candidates)} entities")
        self.label = label
        self.candidates = candidates


def _resolve_label(r, version_id: str, node: NamedClass) -> str:
    """Resolve a NamedClass node to a single IRI. Raises AmbiguousLabelError if ambiguous."""
    if node.curie:
        # Disambiguated form: look up by CURIE (stored as `short` field)
        norm = normalise_label(node.curie)
        key = _prefix_key(version_id)
        members = r.zrangebylex(key, f"[{norm}", f"[{norm}\xff")
        for m in members:
            parts = m.split("|", 2)
            if len(parts) == 3:
                _, _, iri = parts
                detail = r.hgetall(_iri_key(version_id, iri))
                if detail.get("short") == node.curie:
                    return iri
        # Fallback: if CURIE is itself an IRI fragment
        return node.ref

    # Check if ref looks like a CURIE or IRI already
    if ":" in node.ref and not node.ref.startswith("'"):
        # Try direct lookup via short/CURIE
        norm = normalise_label(node.ref)
        key = _prefix_key(version_id)
        members = r.zrangebylex(key, f"[{norm}", f"[{norm}\xff")
        for m in members:
            parts = m.split("|", 2)
            if len(parts) == 3:
                _, _, iri = parts
                return iri
        return node.ref  # treat as IRI directly

    # Plain label — look up in prefix index
    norm = normalise_label(node.ref)
    key = _prefix_key(version_id)
    members = r.zrangebylex(key, f"[{norm}|", f"[{norm}|\xff")
    # Exact-label match: members where the norm_label part exactly equals norm
    matched: list[dict] = []
    seen_iris: set[str] = set()
    for m in members:
        parts = m.split("|", 2)
        if len(parts) != 3:
            continue
        norm_lbl, _, iri = parts
        if norm_lbl != norm:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        detail = r.hgetall(_iri_key(version_id, iri))
        if detail:
            matched.append(detail)

    if len(matched) == 0:
        return node.ref  # unknown — pass through, SPARQL may handle it
    if len(matched) == 1:
        return matched[0]["iri"]
    raise AmbiguousLabelError(node.ref, matched)


async def evaluate(node, version_id: str) -> list[SearchResult]:
    """Evaluate a MOS AST node against the given version, returning matching classes."""
    r = _get_redis()
    classification = await get_classification(version_id)
    subclasses_index: dict[str, list[str]] = classification.get("subclasses", {})
    all_class_iris: set[str] = set(subclasses_index.keys()) | {
        iri for subs in subclasses_index.values() for iri in subs
    }

    async def _eval(n) -> set[str]:
        if isinstance(n, NamedClass):
            iri = _resolve_label(r, version_id, n)
            subs = set(subclasses_index.get(iri, []))
            subs.add(iri)
            return subs

        if isinstance(n, And):
            return await _eval(n.left) & await _eval(n.right)

        if isinstance(n, Or):
            return await _eval(n.left) | await _eval(n.right)

        if isinstance(n, Not):
            return all_class_iris - await _eval(n.operand)

        if isinstance(n, (SomeValuesFrom, AllValuesFrom, HasValue, HasSelf,
                          MinCardinality, MaxCardinality, ExactCardinality)):
            return _sparql_eval(n, version_id, r)

        return set()

    iris = await _eval(node)

    # Build results with labels
    results: list[SearchResult] = []
    for iri in iris:
        detail = r.hgetall(_iri_key(version_id, iri))
        label = detail.get("label", iri.split("/")[-1]) if detail else iri.split("/")[-1]
        short = detail.get("short", "") if detail else ""
        match_type = "elk" if not isinstance(node, (SomeValuesFrom, AllValuesFrom, HasValue,
                                                      HasSelf, MinCardinality, MaxCardinality,
                                                      ExactCardinality)) else "sparql"
        results.append(SearchResult(iri=iri, label=label, short=short, match_type=match_type))

    return results


def _sparql_eval(node, version_id: str, r) -> set[str]:
    """Translate restriction AST nodes to SPARQL and query Oxigraph."""
    OWL = "http://www.w3.org/2002/07/owl#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"

    if isinstance(node, SomeValuesFrom):
        prop_iri = node.property_ref.ref if node.property_ref.curie is None else node.property_ref.ref
        fill_iri = node.filler.ref if isinstance(node.filler, NamedClass) and node.filler.curie is None else getattr(node.filler, "ref", "")
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}someValuesFrom> <{fill_iri}> .
            }}
        """
    elif isinstance(node, AllValuesFrom):
        prop_iri = node.property_ref.ref
        fill_iri = node.filler.ref if isinstance(node.filler, NamedClass) else ""
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}allValuesFrom> <{fill_iri}> .
            }}
        """
    elif isinstance(node, MinCardinality):
        prop_iri = node.property_ref.ref
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}minCardinality> ?n .
                FILTER(?n >= {node.cardinality})
            }}
        """
    elif isinstance(node, MaxCardinality):
        prop_iri = node.property_ref.ref
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}maxCardinality> ?n .
                FILTER(?n <= {node.cardinality})
            }}
        """
    elif isinstance(node, ExactCardinality):
        prop_iri = node.property_ref.ref
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}cardinality> {node.cardinality} .
            }}
        """
    else:
        return set()

    results: set[str] = set()
    for sol in sparql_query(q):
        try:
            results.add(sol["cls"].value)
        except Exception:
            pass
    return results
