"""Compute term-level diff between two ontology versions using Oxigraph quad iteration."""
import pyoxigraph as ox

from ontoexplorer.clients.oxigraph import graph_iri

_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

_ENTITY_TYPES: dict[str, str] = {
    "class":               "http://www.w3.org/2002/07/owl#Class",
    "object_property":     "http://www.w3.org/2002/07/owl#ObjectProperty",
    "data_property":       "http://www.w3.org/2002/07/owl#DatatypeProperty",
    "annotation_property": "http://www.w3.org/2002/07/owl#AnnotationProperty",
    "individual":          "http://www.w3.org/2002/07/owl#NamedIndividual",
}


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
) -> set[tuple[str, str]]:
    """Return (predicate_iri, object_value) for all URI/blank-node-valued triples."""
    return {
        (q.predicate.value, q.object.value)
        for q in store.quads_for_pattern(ox.NamedNode(iri), None, None, graph)
        if isinstance(q.object, (ox.NamedNode, ox.BlankNode))
    }


def run_diff(
    store: ox.Store,
    ontology_id: str,
    from_vid: str,
    to_vid: str,
) -> tuple[dict, dict]:
    """
    Compute term-level diff between two named graphs in `store`.

    Returns (summary, diff_data) matching the spec shapes defined in
    docs/superpowers/specs/2026-05-16-ontology-version-diff-design.md.
    Both graphs must already exist in the store.
    """
    from_graph = ox.NamedNode(graph_iri(ontology_id, from_vid))
    to_graph   = ox.NamedNode(graph_iri(ontology_id, to_vid))

    added_list: list[dict] = []
    removed_list: list[dict] = []
    modified_list: list[dict] = []

    for entity_type, type_iri in _ENTITY_TYPES.items():
        from_iris = _collect_iris(store, from_graph, type_iri)
        to_iris   = _collect_iris(store, to_graph, type_iri)

        for iri in to_iris - from_iris:
            added_list.append({
                "iri": iri,
                "label": _first_label(store, to_graph, iri),
                "entity_type": entity_type,
            })

        for iri in from_iris - to_iris:
            removed_list.append({
                "iri": iri,
                "label": _first_label(store, from_graph, iri),
                "entity_type": entity_type,
            })

        for iri in from_iris & to_iris:
            from_lits   = _literal_triples(store, from_graph, iri)
            to_lits     = _literal_triples(store, to_graph, iri)
            from_struct = _structural_triples(store, from_graph, iri)
            to_struct   = _structural_triples(store, to_graph, iri)

            if from_lits == to_lits and from_struct == to_struct:
                continue

            # Pair removed/added literals by (predicate, lang)
            from_lits_map = {(p, lang): v for p, lang, v in from_lits - to_lits}
            to_lits_map   = {(p, lang): v for p, lang, v in to_lits   - from_lits}
            literal_changes = [
                {
                    "predicate": pred,
                    "lang": lang,
                    "removed": from_lits_map.get((pred, lang)),
                    "added":   to_lits_map.get((pred, lang)),
                }
                for pred, lang in sorted(set(from_lits_map) | set(to_lits_map))
            ]

            axiom_changes = [
                {"op": "removed", "axiom": f"<{p}> <{o}>"}
                for p, o in sorted(from_struct - to_struct)
            ] + [
                {"op": "added", "axiom": f"<{p}> <{o}>"}
                for p, o in sorted(to_struct - from_struct)
            ]

            label = _first_label(store, to_graph, iri) or _first_label(store, from_graph, iri)
            modified_list.append({
                "iri": iri,
                "label": label,
                "entity_type": entity_type,
                "literal_changes": literal_changes,
                "axiom_changes": axiom_changes,
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
