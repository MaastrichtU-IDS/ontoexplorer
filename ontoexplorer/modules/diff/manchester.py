"""RDF → Manchester OWL syntax rendering for the version diff.

Pure functions over a pyoxigraph.Store + named graph. No DB access, no async.
See docs/superpowers/specs/2026-05-17-manchester-diff-rendering-design.md.
"""
from __future__ import annotations

import hashlib

import pyoxigraph as ox

# Common IRI constants
_RDF_TYPE  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"
_RDF_REST  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"
_RDF_NIL   = "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"

_RDFS_LABEL    = "http://www.w3.org/2000/01/rdf-schema#label"
_RDFS_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
_RDFS_SUBPROP  = "http://www.w3.org/2000/01/rdf-schema#subPropertyOf"
_RDFS_DOMAIN   = "http://www.w3.org/2000/01/rdf-schema#domain"
_RDFS_RANGE    = "http://www.w3.org/2000/01/rdf-schema#range"

_OWL = "http://www.w3.org/2002/07/owl#"
_OWL_RESTRICTION    = _OWL + "Restriction"
_OWL_ON_PROPERTY    = _OWL + "onProperty"
_OWL_SOME_VALUES    = _OWL + "someValuesFrom"
_OWL_ALL_VALUES     = _OWL + "allValuesFrom"
_OWL_HAS_VALUE      = _OWL + "hasValue"
_OWL_HAS_SELF       = _OWL + "hasSelf"
_OWL_CARDINALITY    = _OWL + "cardinality"
_OWL_MIN_CARD       = _OWL + "minCardinality"
_OWL_MAX_CARD       = _OWL + "maxCardinality"
_OWL_QCARDINALITY   = _OWL + "qualifiedCardinality"
_OWL_MIN_QCARD      = _OWL + "minQualifiedCardinality"
_OWL_MAX_QCARD      = _OWL + "maxQualifiedCardinality"
_OWL_ON_CLASS       = _OWL + "onClass"
_OWL_ON_DATARANGE   = _OWL + "onDataRange"
_OWL_INTERSECTION   = _OWL + "intersectionOf"
_OWL_UNION          = _OWL + "unionOf"
_OWL_COMPLEMENT     = _OWL + "complementOf"
_OWL_ONE_OF         = _OWL + "oneOf"
_OWL_EQUIV_CLASS    = _OWL + "equivalentClass"
_OWL_DISJOINT_WITH  = _OWL + "disjointWith"
_OWL_DISJOINT_UNION = _OWL + "disjointUnionOf"
_OWL_EQUIV_PROP     = _OWL + "equivalentProperty"
_OWL_INVERSE_OF     = _OWL + "inverseOf"
_OWL_SAME_AS        = _OWL + "sameAs"
_OWL_DIFFERENT      = _OWL + "differentFrom"
_OWL_ON_DATATYPE    = _OWL + "onDatatype"
_OWL_WITH_RESTRICTIONS = _OWL + "withRestrictions"

_XSD = "http://www.w3.org/2001/XMLSchema#"
_XSD_STRING = _XSD + "string"
_XSD_BOOLEAN = _XSD + "boolean"
_XSD_TRUE_LITERAL = "true"

# Property characteristics: rdf:type values that map to Characteristics: keywords
_CHARACTERISTICS: dict[str, str] = {
    _OWL + "FunctionalProperty":        "Functional",
    _OWL + "InverseFunctionalProperty": "InverseFunctional",
    _OWL + "ReflexiveProperty":         "Reflexive",
    _OWL + "IrreflexiveProperty":       "Irreflexive",
    _OWL + "SymmetricProperty":         "Symmetric",
    _OWL + "AsymmetricProperty":        "Asymmetric",
    _OWL + "TransitiveProperty":        "Transitive",
}

# Datatype-restriction facet IRIs → Manchester operator strings.
_FACETS: dict[str, str] = {
    _XSD + "minInclusive":  ">=",
    _XSD + "maxInclusive":  "<=",
    _XSD + "minExclusive":  ">",
    _XSD + "maxExclusive":  "<",
    _XSD + "length":        "length",
    _XSD + "minLength":     "minLength",
    _XSD + "maxLength":     "maxLength",
    _XSD + "pattern":       "pattern",
}

# Class expression recursion depth (matches compute._BNODE_FP_MAX_DEPTH).
_MAX_DEPTH = 10


def _rdf_list_items(
    store: ox.Store, graph: ox.NamedNode, head: ox.Term
) -> list[ox.Term]:
    """Walk an RDF collection from `head` and return its items in order.

    Stops at rdf:nil, at the first cycle, or if a node has no rdf:first/rdf:rest.
    Returns an empty list for rdf:nil.
    """
    first_pred = ox.NamedNode(_RDF_FIRST)
    rest_pred  = ox.NamedNode(_RDF_REST)
    items: list[ox.Term] = []
    visited: set[str] = set()
    node: ox.Term = head
    while True:
        # Stop at rdf:nil
        if isinstance(node, ox.NamedNode) and node.value == _RDF_NIL:
            break
        if not isinstance(node, ox.BlankNode):
            break
        if node.value in visited:
            break
        visited.add(node.value)

        first_obj: ox.Term | None = None
        rest_obj: ox.Term | None = None
        for q in store.quads_for_pattern(node, first_pred, None, graph):
            first_obj = q.object
            break
        for q in store.quads_for_pattern(node, rest_pred, None, graph):
            rest_obj = q.object
            break
        if first_obj is None:
            break
        items.append(first_obj)
        if rest_obj is None:
            break
        node = rest_obj
    return items


def iri_to_label(
    store: ox.Store, graph: ox.NamedNode, iri: str, *, labels: dict[str, str]
) -> str:
    """Resolve an IRI to a display label.

    Order: cache hit → rdfs:label@en → any rdfs:label → local name after `#` or `/`
    → full IRI. The result is cached in `labels` so subsequent calls are O(1).
    """
    if iri in labels:
        return labels[iri]

    label_pred = ox.NamedNode(_RDFS_LABEL)
    en_label: str | None = None
    any_label: str | None = None
    for q in store.quads_for_pattern(ox.NamedNode(iri), label_pred, None, graph):
        if isinstance(q.object, ox.Literal):
            if q.object.language == "en" and en_label is None:
                en_label = q.object.value
            elif any_label is None:
                any_label = q.object.value
    chosen = en_label or any_label
    if chosen is None:
        # Local name fallback
        if "#" in iri:
            chosen = iri.rsplit("#", 1)[1]
        elif "/" in iri:
            chosen = iri.rsplit("/", 1)[1]
        else:
            chosen = iri
        if not chosen:
            chosen = iri
    labels[iri] = chosen
    return chosen


def render_class_expression(
    store: ox.Store,
    graph: ox.NamedNode,
    node: ox.Term,
    *,
    labels: dict[str, str],
    depth: int = 0,
) -> str:
    """Render an RDF term as a Manchester class expression.

    Dispatches by term kind:
      - NamedNode → label / local-name
      - Literal   → "value"[@lang][^^xsd:datatype]
      - BlankNode → introspect outgoing triples, match an OWL pattern, recurse

    Depth-bounded; deeper than _MAX_DEPTH renders as `…`.
    """
    if depth >= _MAX_DEPTH:
        return "…"
    if isinstance(node, ox.NamedNode):
        return iri_to_label(store, graph, node.value, labels=labels)
    if isinstance(node, ox.Literal):
        return _render_literal(node)
    if isinstance(node, ox.BlankNode):
        return _render_bnode_expression(store, graph, node, labels=labels, depth=depth)
    return f"[unknown:{node!r}]"


def _render_literal(lit: ox.Literal) -> str:
    """Manchester-style literal: "value"[@lang][^^xsd:dtype]."""
    text = f'"{lit.value}"'
    if lit.language:
        return f"{text}@{lit.language}"
    if lit.datatype is not None and lit.datatype.value != _XSD_STRING:
        dt = lit.datatype.value
        if dt.startswith(_XSD):
            return f"{text}^^xsd:{dt[len(_XSD):]}"
        return f"{text}^^<{dt}>"
    return text


def _render_bnode_expression(
    store: ox.Store,
    graph: ox.NamedNode,
    node: ox.BlankNode,
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    """Dispatch a blank-node class expression to its specific renderer.

    Order of detection matches OWL2's structural specification. Falls back to
    `[bnode:<short-fp>]` when no pattern matches.
    """
    preds = _bnode_predicates(store, graph, node)

    # Property restrictions: detected by presence of owl:onProperty.
    if _OWL_ON_PROPERTY in preds:
        return _render_restriction(store, graph, preds, labels=labels, depth=depth)

    return _bnode_fallback(store, graph, node)


def _bnode_predicates(
    store: ox.Store, graph: ox.NamedNode, node: ox.BlankNode
) -> dict[str, ox.Term]:
    """Map of predicate-IRI → first object found for this bnode.

    Sufficient for the OWL constructs we render (each has at most one object
    per predicate). RDF lists are walked separately via _rdf_list_items.
    """
    preds: dict[str, ox.Term] = {}
    for q in store.quads_for_pattern(node, None, None, graph):
        # First-wins; predicates we care about are functional in OWL2 anyway.
        preds.setdefault(q.predicate.value, q.object)
    return preds


def _render_restriction(
    store: ox.Store,
    graph: ox.NamedNode,
    preds: dict[str, ox.Term],
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    """Render an owl:Restriction.

    Required: owl:onProperty. Then exactly one of someValuesFrom / allValuesFrom /
    hasValue / hasSelf / cardinality-variants.
    """
    prop_term = preds[_OWL_ON_PROPERTY]
    prop_label = render_class_expression(
        store, graph, prop_term, labels=labels, depth=depth + 1
    )

    if _OWL_SOME_VALUES in preds:
        filler = render_class_expression(
            store, graph, preds[_OWL_SOME_VALUES], labels=labels, depth=depth + 1
        )
        return f"{prop_label} some {filler}"
    if _OWL_ALL_VALUES in preds:
        filler = render_class_expression(
            store, graph, preds[_OWL_ALL_VALUES], labels=labels, depth=depth + 1
        )
        return f"{prop_label} only {filler}"
    if _OWL_HAS_VALUE in preds:
        v = render_class_expression(
            store, graph, preds[_OWL_HAS_VALUE], labels=labels, depth=depth + 1
        )
        return f"{prop_label} value {v}"
    if _OWL_HAS_SELF in preds:
        v = preds[_OWL_HAS_SELF]
        if (
            isinstance(v, ox.Literal)
            and v.value == _XSD_TRUE_LITERAL
            and v.datatype is not None
            and v.datatype.value == _XSD_BOOLEAN
        ):
            return f"{prop_label} Self"
        # `hasSelf false` or non-boolean literals fall through.

    # Cardinality patterns are handled in a later task; until then, fallback.
    return f"[restriction:{prop_label}]"


def _bnode_fallback(
    store: ox.Store, graph: ox.NamedNode, node: ox.BlankNode
) -> str:
    """Short stable fingerprint for an unrecognized bnode (debugging aid)."""
    parts: list[str] = []
    for q in store.quads_for_pattern(node, None, None, graph):
        if isinstance(q.object, ox.NamedNode):
            o = q.object.value
        elif isinstance(q.object, ox.Literal):
            o = f'"{q.object.value}"'
        else:
            o = "_:b"
        parts.append(f"{q.predicate.value}\t{o}")
    parts.sort()
    fp = hashlib.sha1("\n".join(parts).encode()).hexdigest()[:8]
    return f"[bnode:{fp}]"
