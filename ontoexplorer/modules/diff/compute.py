"""Compute term-level diff between two ontology versions using Oxigraph quad iteration."""
import hashlib
from typing import Literal

import pyoxigraph as ox

from ontoexplorer.clients.oxigraph import graph_iri
from ontoexplorer.modules.diff import manchester as _mos

_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


ReasoningStatus = Literal["ready", "pending", "failed", "missing"]


async def _reasoning_status_for_version(db, version_id: str) -> ReasoningStatus:
    """Return the reasoning-readiness status for an ontology version.

    Ranking: if ANY 'done' job exists → 'ready'. Else if a 'running' or
    'pending' (queued) job exists → 'pending'. Else if a 'failed' job exists →
    'failed'. Else 'missing'.
    """
    from sqlalchemy import select

    from ontoexplorer.models.db import Job

    rows = await db.execute(
        select(Job.status).where(Job.version_id == version_id, Job.type == "reason")
    )
    statuses = {r[0] for r in rows.all()}
    if "done" in statuses:
        return "ready"
    if "running" in statuses or "pending" in statuses:
        return "pending"
    if "failed" in statuses:
        return "failed"
    return "missing"

# Blank node IDs (b123) are assigned at parse time and differ between versions
# even when the underlying structure is identical, so we replace each bnode in
# a triple with a fingerprint of its outgoing-triple closure. Depth-bounded so
# pathological cycles can't blow up — most OWL bnodes (Restrictions, RDF lists,
# class expressions) are shallow.
_BNODE_FP_MAX_DEPTH = 10

_ENTITY_TYPES: dict[str, str] = {
    "class":               "http://www.w3.org/2002/07/owl#Class",
    "object_property":     "http://www.w3.org/2002/07/owl#ObjectProperty",
    "data_property":       "http://www.w3.org/2002/07/owl#DatatypeProperty",
    "annotation_property": "http://www.w3.org/2002/07/owl#AnnotationProperty",
    "individual":          "http://www.w3.org/2002/07/owl#NamedIndividual",
}


def _tokens_to_str(tokens: list) -> str:
    """Flatten a Manchester token list to a plain string for legacy display/search.

    Concatenates text tokens verbatim and IRI tokens by their label.
    """
    return "".join(
        t["v"] if t["t"] == "text" else t["label"]
        for t in tokens
    )


def _collect_iris(store: ox.Store, graph: ox.NamedNode, type_iri: str) -> set[str]:
    rdf_type = ox.NamedNode(_RDF_TYPE)
    type_node = ox.NamedNode(type_iri)
    return {
        q.subject.value
        for q in store.quads_for_pattern(None, rdf_type, type_node, graph)
        if isinstance(q.subject, ox.NamedNode)
    }


def _first_label(store: ox.Store, graph: ox.NamedNode, iri: str) -> str | None:
    label_node = ox.NamedNode(_RDFS_LABEL)
    for q in store.quads_for_pattern(ox.NamedNode(iri), label_node, None, graph):
        if isinstance(q.object, ox.Literal):
            return q.object.value
    return None


def _literal_triples(
    store: ox.Store, graph: ox.NamedNode, iri: str
) -> set[tuple[str, str | None, str]]:
    """Return (predicate_iri, lang_or_none, value) for all literal-valued triples."""
    return {
        (q.predicate.value, q.object.language, q.object.value)
        for q in store.quads_for_pattern(ox.NamedNode(iri), None, None, graph)
        if isinstance(q.object, ox.Literal)
    }


def _structural_triples(
    store: ox.Store, graph: ox.NamedNode, iri: str
) -> tuple[set[tuple[str, str]], dict[tuple[str, str], ox.NamedNode | ox.BlankNode]]:
    """Return (comparable set, term lookup) for (predicate, object) triples.

    The comparable set is what `run_diff` set-diffs across versions; bnode
    objects are represented by their content fingerprint so structurally
    identical bnodes collapse. The lookup maps each (predicate, repr) key back
    to the original ox.Term, so the Manchester renderer can walk the bnode
    subgraph for display.
    """
    triples: set[tuple[str, str]] = set()
    terms: dict[tuple[str, str], ox.NamedNode | ox.BlankNode] = {}
    for q in store.quads_for_pattern(ox.NamedNode(iri), None, None, graph):
        if isinstance(q.object, ox.NamedNode):
            key = (q.predicate.value, q.object.value)
            triples.add(key)
            terms[key] = q.object
        elif isinstance(q.object, ox.BlankNode):
            fp = _bnode_fingerprint(store, graph, q.object.value)
            key = (q.predicate.value, f"_:fp:{fp}")
            triples.add(key)
            terms[key] = q.object
    return triples, terms


def _axioms_for_entity(
    store: ox.Store, graph: ox.NamedNode, iri: str,
) -> list[tuple[str, ox.NamedNode | ox.BlankNode | ox.Literal]]:
    """Return all outgoing (predicate, object) pairs for `iri` in `graph`,
    excluding the declaring `rdf:type` triple whose object is one of the
    five OWL/RDFS entity meta-classes (owl:Class, owl:ObjectProperty,
    owl:DatatypeProperty, owl:AnnotationProperty, owl:NamedIndividual).

    Used to collect the full axiom set for an entity in the added/removed
    buckets of the diff, where the entity is fully present on one side only.
    Non-meta-class rdf:type triples (e.g. property characteristics, individual
    types) are retained so render_axiom can route them appropriately.
    """
    meta_classes = set(_ENTITY_TYPES.values())
    triples: list[tuple[str, ox.NamedNode | ox.BlankNode | ox.Literal]] = []
    for q in store.quads_for_pattern(ox.NamedNode(iri), None, None, graph):
        if (
            q.predicate.value == _RDF_TYPE
            and isinstance(q.object, ox.NamedNode)
            and q.object.value in meta_classes
        ):
            continue
        triples.append((q.predicate.value, q.object))
    return triples


def _bnode_fingerprint(
    store: ox.Store,
    graph: ox.NamedNode,
    bnode_id: str,
    visited: frozenset[str] = frozenset(),
    depth: int = 0,
) -> str:
    """Deterministic SHA-1-derived fingerprint of a bnode's outgoing triples.

    Recursively descends into bnode-valued objects; depth-bounded and
    cycle-aware. Literals are encoded with language tag + datatype so they
    round-trip; NamedNode objects use their stable URI; nested bnodes recurse.
    """
    if depth >= _BNODE_FP_MAX_DEPTH or bnode_id in visited:
        return "max"
    new_visited = visited | {bnode_id}
    parts: list[str] = []
    for q in store.quads_for_pattern(ox.BlankNode(bnode_id), None, None, graph):
        p = q.predicate.value
        if isinstance(q.object, ox.NamedNode):
            o = f"<{q.object.value}>"
        elif isinstance(q.object, ox.Literal):
            lang = q.object.language or ""
            dt = q.object.datatype.value if q.object.datatype else ""
            o = f'"{q.object.value}"@{lang}^^<{dt}>'
        elif isinstance(q.object, ox.BlankNode):
            sub_fp = _bnode_fingerprint(store, graph, q.object.value, new_visited, depth + 1)
            o = f"_:fp:{sub_fp}"
        else:
            o = "?"
        parts.append(f"{p}\t{o}")
    parts.sort()
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16]


def _run_diff_core(
    store: ox.Store,
    from_graph: ox.NamedNode,
    to_graph: ox.NamedNode,
) -> tuple[dict, dict]:
    """Diff two named graphs in `store`. Pure function over graph IRIs —
    callers build the IRIs from their own identifiers (ontology_id+version
    for intra-ontology diffs, two ontology_ids for cross-ontology compare).

    Returns (summary, diff_data). diff_data has the shape
        {"added": [...], "removed": [...], "modified": [...]}
    matching the existing OntologyDiff JSON contract.
    """
    added_list: list[dict] = []
    removed_list: list[dict] = []
    modified_list: list[dict] = []
    labels: dict[str, str] = {}

    # Discover owl:AnnotationProperty in both graphs once; union forms the
    # annotation_props set used by render_axiom/render_frame for every entity.
    annotation_props = (
        _mos._BUILTIN_ANNOTATION_PROPS
        | _mos._discover_annotation_props(store, from_graph)
        | _mos._discover_annotation_props(store, to_graph)
    )

    # Pre-compute the in-ontology IRI set for each side so render_frame can
    # decide which iri tokens become clickable links.
    known_iris_from = _mos._known_iris(store, from_graph)
    known_iris_to   = _mos._known_iris(store, to_graph)
    # For modified entities — entity is on both sides — we union the two sets:
    # an axiom-filler IRI that lives only on one side is still legitimately
    # part of the comparison context and should remain clickable.
    known_iris_union = known_iris_from | known_iris_to

    for entity_type, type_iri in _ENTITY_TYPES.items():
        from_iris = _collect_iris(store, from_graph, type_iri)
        to_iris   = _collect_iris(store, to_graph, type_iri)

        for iri in to_iris - from_iris:
            axioms = _axioms_for_entity(store, to_graph, iri)
            axiom_changes = [
                {"op": "added", "predicate": p, "object": o, "graph": to_graph}
                for p, o in axioms
            ]
            frame = _mos.render_frame(
                store, iri, entity_type, axiom_changes,
                labels=labels, annotation_props=annotation_props,
                known_iris=known_iris_to, op="added",
            )
            added_list.append({
                "iri": iri,
                "label": _first_label(store, to_graph, iri),
                "entity_type": entity_type,
                "manchester_frame": frame,
            })

        for iri in from_iris - to_iris:
            axioms = _axioms_for_entity(store, from_graph, iri)
            axiom_changes = [
                {"op": "removed", "predicate": p, "object": o, "graph": from_graph}
                for p, o in axioms
            ]
            frame = _mos.render_frame(
                store, iri, entity_type, axiom_changes,
                labels=labels, annotation_props=annotation_props,
                known_iris=known_iris_from, op="removed",
            )
            removed_list.append({
                "iri": iri,
                "label": _first_label(store, from_graph, iri),
                "entity_type": entity_type,
                "manchester_frame": frame,
            })

        for iri in from_iris & to_iris:
            from_lits   = _literal_triples(store, from_graph, iri)
            to_lits     = _literal_triples(store, to_graph, iri)
            from_struct, from_terms = _structural_triples(store, from_graph, iri)
            to_struct,   to_terms   = _structural_triples(store, to_graph, iri)

            if from_lits == to_lits and from_struct == to_struct:
                continue

            from_lits_map = {(p, lang): v for p, lang, v in from_lits - to_lits}
            to_lits_map   = {(p, lang): v for p, lang, v in to_lits   - from_lits}
            literal_changes = [
                {
                    "predicate": pred,
                    "lang": lang,
                    "removed": from_lits_map.get((pred, lang)),
                    "added":   to_lits_map.get((pred, lang)),
                }
                for pred, lang in sorted(
                    set(from_lits_map) | set(to_lits_map),
                    key=lambda t: (t[0], t[1] or ""),
                )
            ]

            change_records: list[dict] = []
            for p_iri, o_repr in sorted(from_struct - to_struct):
                change_records.append({
                    "op": "removed",
                    "predicate": p_iri,
                    "object": from_terms[(p_iri, o_repr)],
                    "graph": from_graph,
                })
            for p_iri, o_repr in sorted(to_struct - from_struct):
                change_records.append({
                    "op": "added",
                    "predicate": p_iri,
                    "object": to_terms[(p_iri, o_repr)],
                    "graph": to_graph,
                })

            axiom_changes: list[dict] = []
            for rec in change_records:
                axiom_tokens = _mos.render_axiom(
                    store, rec["graph"], iri,
                    rec["predicate"], rec["object"],
                    labels=labels, known_iris=known_iris_union,
                    entity_type=entity_type,
                )
                if axiom_tokens is None:
                    obj_val = rec["object"].value if hasattr(rec["object"], "value") else str(rec["object"])
                    axiom_str = f"<{rec['predicate']}> <{obj_val}>"
                else:
                    axiom_str = _tokens_to_str(axiom_tokens)
                axiom_changes.append({"op": rec["op"], "axiom": axiom_str})

            manchester_frame = _mos.render_frame(
                store, iri, entity_type, change_records,
                labels=labels, annotation_props=annotation_props,
                known_iris=known_iris_union,
            )

            label = _first_label(store, to_graph, iri) or _first_label(store, from_graph, iri)
            modified_list.append({
                "iri": iri,
                "label": label,
                "entity_type": entity_type,
                "literal_changes": literal_changes,
                "axiom_changes": axiom_changes,
                "manchester_frame": manchester_frame,
            })

    by_type = {
        et: {
            "added":    sum(1 for e in added_list   if e["entity_type"] == et),
            "removed":  sum(1 for e in removed_list if e["entity_type"] == et),
            "modified": sum(1 for e in modified_list if e["entity_type"] == et),
        }
        for et in _ENTITY_TYPES
    }
    summary = {
        "added":           len(added_list),
        "removed":         len(removed_list),
        "modified":        len(modified_list),
        "literal_changes": sum(1 for m in modified_list if m["literal_changes"]),
        "axiom_changes":   sum(1 for m in modified_list if m["axiom_changes"]),
        "by_entity_type":  by_type,
    }
    diff_data = {
        "added":    added_list,
        "removed":  removed_list,
        "modified": modified_list,
    }
    return summary, diff_data


def run_diff(
    store: ox.Store,
    ontology_id: str,
    from_vid: str,
    to_vid: str,
) -> tuple[dict, dict]:
    """Compute term-level diff between two named graphs of the same ontology."""
    from_graph = ox.NamedNode(graph_iri(ontology_id, from_vid))
    to_graph   = ox.NamedNode(graph_iri(ontology_id, to_vid))
    return _run_diff_core(store, from_graph, to_graph)
