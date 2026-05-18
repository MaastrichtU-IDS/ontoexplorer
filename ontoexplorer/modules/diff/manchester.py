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

# Well-known annotation properties — predicates whose value is metadata about
# the subject rather than a logical axiom. The Manchester `Annotations:`
# keyword block groups all of these.
_DC = "http://purl.org/dc/elements/1.1/"
_DCTERMS = "http://purl.org/dc/terms/"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

_RDFS_SEE_ALSO       = _RDFS + "seeAlso"
_RDFS_IS_DEFINED_BY  = _RDFS + "isDefinedBy"
_RDFS_COMMENT        = _RDFS + "comment"

_OWL_ANNOTATION_PROPERTY = _OWL + "AnnotationProperty"
_OWL_VERSION_INFO        = _OWL + "versionInfo"
_OWL_DEPRECATED          = _OWL + "deprecated"
_OWL_PRIOR_VERSION       = _OWL + "priorVersion"
_OWL_INCOMPATIBLE_WITH   = _OWL + "incompatibleWith"

# Predicates that always render as annotations regardless of graph context.
# Dynamically-discovered owl:AnnotationProperty entries are added on top of
# this set per run_diff invocation.
_BUILTIN_ANNOTATION_PROPS: frozenset[str] = frozenset({
    _RDFS_LABEL, _RDFS_COMMENT, _RDFS_SEE_ALSO, _RDFS_IS_DEFINED_BY,
    _DC + "title", _DC + "description", _DC + "creator",
    _DCTERMS + "title", _DCTERMS + "description",
    _DCTERMS + "creator", _DCTERMS + "license",
    _SKOS + "prefLabel", _SKOS + "altLabel", _SKOS + "definition",
    _SKOS + "scopeNote", _SKOS + "example",
    _OWL_VERSION_INFO, _OWL_DEPRECATED, _OWL_PRIOR_VERSION, _OWL_INCOMPATIBLE_WITH,
})

# Known namespaces for CURIE-style display of annotation predicates.
# Order matters: longest prefixes (dcterms before dc) must be tried first
# so dcterms:title doesn't shorten to dc:terms/title.
_CURIE_PREFIXES: list[tuple[str, str]] = [
    (_DCTERMS, "dcterms:"),
    (_DC,      "dc:"),
    (_SKOS,    "skos:"),
    (_RDFS,    "rdfs:"),
    (_OWL,     "owl:"),
    (_XSD,     "xsd:"),
]


def _to_curie(iri: str) -> str:
    """Return a `prefix:local` CURIE if iri starts with a known namespace,
    otherwise `<full-iri>` in angle brackets.
    """
    for ns, prefix in _CURIE_PREFIXES:
        if iri.startswith(ns):
            return f"{prefix}{iri[len(ns):]}"
    return f"<{iri}>"

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

    if _OWL_INTERSECTION in preds:
        return _render_junction(
            store, graph, preds[_OWL_INTERSECTION], "and", labels=labels, depth=depth
        )
    if _OWL_UNION in preds:
        return _render_junction(
            store, graph, preds[_OWL_UNION], "or", labels=labels, depth=depth
        )
    if _OWL_COMPLEMENT in preds:
        inner_term = preds[_OWL_COMPLEMENT]
        inner = render_class_expression(
            store, graph, inner_term, labels=labels, depth=depth + 1
        )
        # Parenthesize complex inner expressions to avoid Manchester precedence
        # ambiguity. Junctions already self-parenthesize via _render_junction;
        # restrictions, datatype expressions, and other bnode forms do not.
        if isinstance(inner_term, ox.BlankNode) and not (inner.startswith("(") or inner.startswith("{")):
            inner = f"({inner})"
        return f"not {inner}"

    if _OWL_ONE_OF in preds:
        items = _rdf_list_items(store, graph, preds[_OWL_ONE_OF])
        parts = [
            render_class_expression(store, graph, it, labels=labels, depth=depth + 1)
            for it in items
        ]
        return "{" + ", ".join(parts) + "}"

    if _OWL_ON_DATATYPE in preds and _OWL_WITH_RESTRICTIONS in preds:
        return _render_datatype_restriction(
            store, graph, preds, labels=labels, depth=depth
        )

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

    # Cardinality variants. Unqualified predicates NEVER carry a filler, per
    # the OWL2 RDF mapping. Qualified predicates require owl:onClass or
    # owl:onDataRange for a filler.
    for card_pred, kw in (
        (_OWL_CARDINALITY, "exactly"),
        (_OWL_MIN_CARD,    "min"),
        (_OWL_MAX_CARD,    "max"),
    ):
        if card_pred in preds:
            n = preds[card_pred]
            if isinstance(n, ox.Literal):
                return f"{prop_label} {kw} {n.value}"

    for card_pred, kw in (
        (_OWL_QCARDINALITY, "exactly"),
        (_OWL_MIN_QCARD,    "min"),
        (_OWL_MAX_QCARD,    "max"),
    ):
        if card_pred in preds:
            n = preds[card_pred]
            if isinstance(n, ox.Literal):
                on_class = preds.get(_OWL_ON_CLASS) or preds.get(_OWL_ON_DATARANGE)
                if on_class is not None:
                    filler = render_class_expression(
                        store, graph, on_class, labels=labels, depth=depth + 1
                    )
                    return f"{prop_label} {kw} {n.value} {filler}"
                return f"{prop_label} {kw} {n.value}"

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


def _render_junction(
    store: ox.Store,
    graph: ox.NamedNode,
    list_head: ox.Term,
    op: str,
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    """Render intersectionOf / unionOf as `(A op B op C)`."""
    items = _rdf_list_items(store, graph, list_head)
    if not items:
        return f"({op})"
    parts = [
        render_class_expression(store, graph, it, labels=labels, depth=depth + 1)
        for it in items
    ]
    return "(" + f" {op} ".join(parts) + ")"


# Predicate-keyed dispatch for axioms whose Manchester rendering is
# `<Keyword>: <class-or-property-expression>`. The frame layer groups changes
# by keyword; this function only emits a single axiom line.
_CLASS_AXIOMS: dict[str, str] = {
    _RDFS_SUBCLASS:      "SubClassOf",
    _OWL_EQUIV_CLASS:    "EquivalentTo",
    _OWL_DISJOINT_WITH:  "DisjointWith",
    _OWL_DISJOINT_UNION: "DisjointUnionOf",
}

_PROPERTY_AXIOMS: dict[str, str] = {
    _RDFS_SUBPROP:    "SubPropertyOf",
    _OWL_EQUIV_PROP:  "EquivalentTo",
    _OWL_INVERSE_OF:  "InverseOf",
    _RDFS_DOMAIN:     "Domain",
    _RDFS_RANGE:      "Range",
}

_INDIVIDUAL_AXIOMS: dict[str, str] = {
    _OWL_SAME_AS:     "SameAs",
    _OWL_DIFFERENT:   "DifferentFrom",
}


def render_axiom(
    store: ox.Store,
    graph: ox.NamedNode,
    subject_iri: str,
    predicate_iri: str,
    object_term: ox.Term,
    *,
    labels: dict[str, str],
    entity_type: str | None = None,
) -> str | None:
    """Render a single (predicate, object) pair as a Manchester axiom line.

    `entity_type` (one of 'class', 'object_property', 'data_property',
    'annotation_property', 'individual') changes the meaning of rdf:type and
    of unknown predicates:

      * On individuals: rdf:type → `Types: X`; any other predicate → `Facts: p o`.
      * On properties: rdf:type with an OWL characteristic class → `Characteristics: Functional` etc.
      * Other unrecognized predicates → None (caller falls back).
    """
    # Individuals: rdf:type → Types, anything else → Facts.
    if entity_type == "individual":
        if predicate_iri == _RDF_TYPE:
            filler = render_class_expression(store, graph, object_term, labels=labels)
            return f"Types: {filler}"
        if predicate_iri in _INDIVIDUAL_AXIOMS:
            keyword = _INDIVIDUAL_AXIOMS[predicate_iri]
            filler = render_class_expression(store, graph, object_term, labels=labels)
            return f"{keyword}: {filler}"
        # Property assertion: predicate is some property, object is the value.
        prop_label = iri_to_label(store, graph, predicate_iri, labels=labels)
        value_label = render_class_expression(store, graph, object_term, labels=labels)
        return f"Facts: {prop_label} {value_label}"

    # Property characteristics: rdf:type with an OWL characteristic class.
    if predicate_iri == _RDF_TYPE and isinstance(object_term, ox.NamedNode):
        char = _CHARACTERISTICS.get(object_term.value)
        if char is not None:
            return f"Characteristics: {char}"
        return None  # other rdf:type triples belong in the frame header

    keyword = (
        _CLASS_AXIOMS.get(predicate_iri)
        or _PROPERTY_AXIOMS.get(predicate_iri)
        or _INDIVIDUAL_AXIOMS.get(predicate_iri)
    )
    if keyword is None:
        return None
    filler = render_class_expression(store, graph, object_term, labels=labels)
    return f"{keyword}: {filler}"


def _render_datatype_restriction(
    store: ox.Store,
    graph: ox.NamedNode,
    preds: dict[str, ox.Term],
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    """Render rdfs:Datatype + owl:onDatatype + owl:withRestrictions as
    `<datatype>[facet1 v1, facet2 v2]`. Falls back to bare datatype label when
    the facet list is empty or unrecognized.
    """
    base = preds[_OWL_ON_DATATYPE]
    base_label = render_class_expression(store, graph, base, labels=labels, depth=depth + 1)
    if isinstance(base, ox.NamedNode) and base.value.startswith(_XSD):
        base_label = f"xsd:{base.value[len(_XSD):]}"

    items = _rdf_list_items(store, graph, preds[_OWL_WITH_RESTRICTIONS])
    facet_strs: list[str] = []
    for item in items:
        if not isinstance(item, ox.BlankNode):
            continue
        for q in store.quads_for_pattern(item, None, None, graph):
            facet_iri = q.predicate.value
            if facet_iri not in _FACETS:
                continue
            op = _FACETS[facet_iri]
            if op == "pattern":
                value_str = _render_literal(q.object) if isinstance(q.object, ox.Literal) else str(q.object.value)
                facet_strs.append(f"pattern {value_str}")
            else:
                # Numeric comparators (>=, <=, >, <) and length facets — emit the
                # lexical form so "0" doesn't become '"0"^^xsd:integer'.
                inner = q.object.value if isinstance(q.object, ox.Literal) else str(q.object.value)
                facet_strs.append(f"{op} {inner}")
    if not facet_strs:
        return base_label
    return f"{base_label}[" + ", ".join(facet_strs) + "]"


# Order in which keywords appear in the frame. Predicates not in the table are
# emitted at the end under "Other:" (or omitted, for unrecognized ones).
# Tuples: (predicate, manchester-keyword, applicable-entity-types).
_FRAME_KEYWORD_ORDER: list[tuple[str, str, set[str] | None]] = [
    # Class axioms
    (_RDFS_SUBCLASS,      "SubClassOf",       {"class"}),
    (_OWL_EQUIV_CLASS,    "EquivalentTo",     {"class"}),
    (_OWL_DISJOINT_WITH,  "DisjointWith",     {"class"}),
    (_OWL_DISJOINT_UNION, "DisjointUnionOf",  {"class"}),
    # Property axioms
    (_RDFS_SUBPROP,       "SubPropertyOf",
        {"object_property", "data_property", "annotation_property"}),
    (_OWL_EQUIV_PROP,     "EquivalentTo",
        {"object_property", "data_property"}),
    (_OWL_INVERSE_OF,     "InverseOf",        {"object_property"}),
    (_RDFS_DOMAIN,        "Domain",
        {"object_property", "data_property", "annotation_property"}),
    (_RDFS_RANGE,         "Range",
        {"object_property", "data_property", "annotation_property"}),
    # Property characteristics — special predicate (rdf:type) handled via its own keyword.
    (_RDF_TYPE,           "Characteristics",
        {"object_property", "data_property"}),
    # Individual axioms
    (_RDF_TYPE,           "Types",            {"individual"}),
    (_OWL_SAME_AS,        "SameAs",           {"individual"}),
    (_OWL_DIFFERENT,      "DifferentFrom",    {"individual"}),
    # Property assertions for individuals — wildcard predicate, handled below.
]

_ENTITY_KEYWORD: dict[str, str] = {
    "class":               "Class",
    "object_property":     "ObjectProperty",
    "data_property":       "DataProperty",
    "annotation_property": "AnnotationProperty",
    "individual":          "Individual",
}


def _discover_annotation_props(
    store: ox.Store, graph: ox.NamedNode,
) -> frozenset[str]:
    """Return the set of IRIs declared as owl:AnnotationProperty in `graph`.

    Augments `_BUILTIN_ANNOTATION_PROPS` for each run_diff invocation. Result
    is intended to be cached at the call site for the duration of the run.
    """
    rdf_type = ox.NamedNode(_RDF_TYPE)
    ap_class = ox.NamedNode(_OWL_ANNOTATION_PROPERTY)
    return frozenset(
        q.subject.value
        for q in store.quads_for_pattern(None, rdf_type, ap_class, graph)
        if isinstance(q.subject, ox.NamedNode)
    )


def render_frame(
    store: ox.Store,
    entity_iri: str,
    entity_type: str,
    axiom_changes: list[dict],
    *,
    labels: dict[str, str],
) -> str | None:
    """Render a Protégé-style Manchester frame for one modified entity.

    `axiom_changes` is a list of dicts with keys:
      op:        'added' | 'removed'
      predicate: str (predicate IRI)
      object:    ox.Term
      graph:     ox.NamedNode (which named graph this change came from — needed
                 because bnode IDs differ between from-graph and to-graph)

    Returns None when no axiom_changes produce a renderable line.
    """
    # Render every change to a (keyword, op, line_text). Drop lines whose predicate
    # isn't covered (render_axiom returns None) — they don't appear in the frame.
    rendered: list[tuple[str, str, str]] = []  # (keyword, op, text)
    for change in axiom_changes:
        line = render_axiom(
            store, change["graph"], entity_iri,
            change["predicate"], change["object"],
            labels=labels, entity_type=entity_type,
        )
        if line is None:
            continue
        keyword, _, body = line.partition(": ")
        rendered.append((keyword, change["op"], body))

    if not rendered:
        return None

    # Group by keyword, preserving _FRAME_KEYWORD_ORDER. Unknown keywords go
    # to the end in insertion order.
    keyword_order: list[str] = []
    seen: set[str] = set()
    for pred, kw, types in _FRAME_KEYWORD_ORDER:
        if (types is None or entity_type in types) and kw not in seen:
            keyword_order.append(kw)
            seen.add(kw)
    # Always include 'Facts' last for individuals (assertion lines).
    if entity_type == "individual" and "Facts" not in seen:
        keyword_order.append("Facts")
        seen.add("Facts")
    # Any leftover keywords we didn't anticipate.
    for kw, _, _ in rendered:
        if kw not in seen:
            keyword_order.append(kw)
            seen.add(kw)

    # Build the frame. At this point `axiom_changes` is non-empty (else we
    # returned None above), so we can safely take a graph from the first change
    # to resolve the entity's label if not yet cached.
    entity_keyword = _ENTITY_KEYWORD.get(entity_type, "Entity")
    entity_label = iri_to_label(
        store, axiom_changes[0]["graph"], entity_iri, labels=labels,
    )
    lines: list[str] = [f"{entity_keyword}: {entity_label}  ({entity_iri})"]

    for kw in keyword_order:
        kw_lines = [(op, body) for k, op, body in rendered if k == kw]
        if not kw_lines:
            continue
        lines.append(f"    {kw}:")
        # Removed first, then added, alphabetical within each.
        removed = sorted([b for op, b in kw_lines if op == "removed"])
        added   = sorted([b for op, b in kw_lines if op == "added"])
        for body in removed:
            lines.append(f"-       {body}")
        for body in added:
            lines.append(f"+       {body}")

    return "\n".join(lines)
