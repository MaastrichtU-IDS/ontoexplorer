"""SPARQL pattern catalogs for OWL 2 profile detection.

Each Pattern encodes one forbidden construct for a given OWL 2 profile.
Patterns are built with either:
  - no GRAPH clause (default graph, used in unit tests)
  - a GRAPH <iri> { ... } clause (named graph, used in production indexer)

Use make_el_patterns(graph_iri) / make_rl_patterns(graph_iri) /
make_ql_patterns(graph_iri) to obtain GRAPH-wrapped patterns.
*_PATTERNS constants use the default graph (graph_iri=None) for unit tests.
"""
from __future__ import annotations

from dataclasses import dataclass

import pyoxigraph

from ontoexplorer.modules.owl_profile.registry import ProfileName

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_XSD = "http://www.w3.org/2001/XMLSchema#"

_PREFIXES = (
    f"PREFIX owl: <{_OWL}>\n"
    f"PREFIX rdf: <{_RDF}>\n"
    f"PREFIX rdfs: <{_RDFS}>\n"
    f"PREFIX xsd: <{_XSD}>\n"
)


@dataclass(frozen=True)
class Pattern:
    """One forbidden-construct pattern for a given OWL 2 profile."""

    profile: ProfileName
    axiom_type: str
    count_sparql: str   # COUNT query returning ?n
    sample_sparql: str  # SELECT ?s LIMIT 10


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _make_basic_predicate_pattern(
    profile: ProfileName,
    axiom_type: str,
    predicate: str,
    *,
    graph_iri: str | None = None,
) -> Pattern:
    """Detect axioms of shape `?s <predicate> ?o`."""
    inner = f"?s <{predicate}> ?o ."
    if graph_iri:
        inner = f"GRAPH <{graph_iri}> {{ {inner} }}"
    return Pattern(
        profile=profile,
        axiom_type=axiom_type,
        count_sparql=f"{_PREFIXES}SELECT (COUNT(*) AS ?n) WHERE {{ {inner} }}",
        sample_sparql=f"{_PREFIXES}SELECT ?s WHERE {{ {inner} }} LIMIT 10",
    )


def _make_basic_type_pattern(
    profile: ProfileName,
    axiom_type: str,
    rdf_class: str,
    *,
    graph_iri: str | None = None,
) -> Pattern:
    """Detect axioms of shape `?s a <class>`."""
    inner = f"?s a <{rdf_class}> ."
    if graph_iri:
        inner = f"GRAPH <{graph_iri}> {{ {inner} }}"
    return Pattern(
        profile=profile,
        axiom_type=axiom_type,
        count_sparql=f"{_PREFIXES}SELECT (COUNT(*) AS ?n) WHERE {{ {inner} }}",
        sample_sparql=f"{_PREFIXES}SELECT ?s WHERE {{ {inner} }} LIMIT 10",
    )


def _make_cardinality_pattern(
    profile: ProfileName,
    *,
    graph_iri: str | None = None,
) -> Pattern:
    """Detect any cardinality restriction (owl:cardinality, owl:maxCardinality, etc.)."""
    filter_iris = ", ".join(
        f"<{_OWL}{name}>"
        for name in (
            "cardinality",
            "maxCardinality",
            "minCardinality",
            "qualifiedCardinality",
            "maxQualifiedCardinality",
            "minQualifiedCardinality",
        )
    )
    inner = f"?s ?card ?o . FILTER(?card IN ({filter_iris}))"
    if graph_iri:
        inner = f"GRAPH <{graph_iri}> {{ {inner} }}"
    return Pattern(
        profile=profile,
        axiom_type="owl:cardinality-restriction",
        count_sparql=f"{_PREFIXES}SELECT (COUNT(*) AS ?n) WHERE {{ {inner} }}",
        sample_sparql=f"{_PREFIXES}SELECT ?s WHERE {{ {inner} }} LIMIT 10",
    )


# ---------------------------------------------------------------------------
# EL pattern catalog
# ---------------------------------------------------------------------------

def _el_patterns(*, graph_iri: str | None = None) -> list[Pattern]:
    """Build the complete EL forbidden-pattern list.

    When graph_iri is given, each pattern queries inside GRAPH <graph_iri> { ... }.
    When None, queries run against the default graph.
    """
    def p(axiom_type: str, predicate: str) -> Pattern:
        return _make_basic_predicate_pattern("el", axiom_type, predicate, graph_iri=graph_iri)

    def t(axiom_type: str, rdf_class: str) -> Pattern:
        return _make_basic_type_pattern("el", axiom_type, rdf_class, graph_iri=graph_iri)

    return [
        # Disjointness constructs
        p("owl:disjointWith",           f"{_OWL}disjointWith"),
        t("owl:AllDisjointClasses",     f"{_OWL}AllDisjointClasses"),
        p("owl:disjointUnionOf",        f"{_OWL}disjointUnionOf"),
        # Boolean class expressions not allowed in EL
        p("owl:complementOf",           f"{_OWL}complementOf"),
        p("owl:unionOf",                f"{_OWL}unionOf"),
        # Restrictions forbidden in EL
        p("owl:allValuesFrom",          f"{_OWL}allValuesFrom"),
        p("owl:hasValue",               f"{_OWL}hasValue"),
        p("owl:hasSelf",                f"{_OWL}hasSelf"),
        # Property characteristics forbidden in EL
        p("owl:inverseOf",              f"{_OWL}inverseOf"),
        t("owl:FunctionalProperty",     f"{_OWL}FunctionalProperty"),
        t("owl:InverseFunctionalProperty", f"{_OWL}InverseFunctionalProperty"),
        t("owl:IrreflexiveProperty",    f"{_OWL}IrreflexiveProperty"),
        t("owl:AsymmetricProperty",     f"{_OWL}AsymmetricProperty"),
        t("owl:SymmetricProperty",      f"{_OWL}SymmetricProperty"),
        # Cardinality restrictions (EL allows only existential, not counting)
        _make_cardinality_pattern("el", graph_iri=graph_iri),
        # Negative property assertions
        t("owl:NegativeObjectPropertyAssertion", f"{_OWL}NegativeObjectPropertyAssertion"),
        t("owl:NegativeDataPropertyAssertion",   f"{_OWL}NegativeDataPropertyAssertion"),
        # owl:oneOf — over-approximate: any use flagged (EL allows 1-individual enumerations
        # in specific positions, but detecting that requires shape analysis; v1 flags all uses)
        p("owl:oneOf",                  f"{_OWL}oneOf"),
    ]


def make_el_patterns(graph_iri: str | None) -> list[Pattern]:
    """Return EL patterns scoped to the given named graph IRI, or default graph if None."""
    return _el_patterns(graph_iri=graph_iri)


# Default-graph version used in unit tests and anywhere no graph IRI is known
EL_PATTERNS: list[Pattern] = make_el_patterns(None)


# ---------------------------------------------------------------------------
# RL cardinality helpers
# ---------------------------------------------------------------------------

def _make_cardinality_gt1_pattern(
    profile: ProfileName,
    *,
    graph_iri: str | None = None,
) -> Pattern:
    """Detect max/cardinality predicates with value > 1.

    OWL 2 RL allows owl:maxCardinality and owl:maxQualifiedCardinality with values
    0 or 1, but not > 1.  This pattern uses xsd:integer() casting to compare the
    literal value — note that literals typed as xsd:nonNegativeInteger (the canonical
    type for cardinality values) are cast correctly by Pyoxigraph's SPARQL engine.
    """
    filter_iris = ", ".join(
        f"<{_OWL}{name}>"
        for name in (
            "maxCardinality",
            "cardinality",
            "qualifiedCardinality",
            "maxQualifiedCardinality",
        )
    )
    inner = (
        f"?s ?card ?val . "
        f"FILTER(?card IN ({filter_iris})) "
        f"FILTER(xsd:integer(?val) > 1)"
    )
    if graph_iri:
        inner = f"GRAPH <{graph_iri}> {{ {inner} }}"
    return Pattern(
        profile=profile,
        axiom_type="owl:cardinality-restriction-gt1",
        count_sparql=f"{_PREFIXES}SELECT (COUNT(*) AS ?n) WHERE {{ {inner} }}",
        sample_sparql=f"{_PREFIXES}SELECT ?s WHERE {{ {inner} }} LIMIT 10",
    )


def _make_min_cardinality_pattern(
    profile: ProfileName,
    *,
    graph_iri: str | None = None,
) -> Pattern:
    """Detect any use of owl:minCardinality or owl:minQualifiedCardinality.

    OWL 2 RL only allows owl:maxCardinality ≤ 1 and owl:maxQualifiedCardinality ≤ 1;
    minimum-cardinality restrictions are entirely forbidden.
    """
    filter_iris = ", ".join(
        f"<{_OWL}{name}>"
        for name in ("minCardinality", "minQualifiedCardinality")
    )
    inner = f"?s ?card ?o . FILTER(?card IN ({filter_iris}))"
    if graph_iri:
        inner = f"GRAPH <{graph_iri}> {{ {inner} }}"
    return Pattern(
        profile=profile,
        axiom_type="owl:min-cardinality-restriction",
        count_sparql=f"{_PREFIXES}SELECT (COUNT(*) AS ?n) WHERE {{ {inner} }}",
        sample_sparql=f"{_PREFIXES}SELECT ?s WHERE {{ {inner} }} LIMIT 10",
    )


# ---------------------------------------------------------------------------
# RL pattern catalog
# ---------------------------------------------------------------------------

def _rl_patterns(*, graph_iri: str | None = None) -> list[Pattern]:
    """Build the complete RL forbidden-pattern list.

    OWL 2 RL has *positional* restrictions — some constructs are forbidden only
    on the RHS of SubClassOf (superclass position), while others are forbidden
    everywhere.  In v1 we over-approximate: we flag ANY use of these constructs
    regardless of position, erring on the side of "not in RL" to avoid false
    negatives.  A comment marks each pattern with its W3C positional rule.

    Reference: https://www.w3.org/TR/owl2-profiles/#OWL_2_RL §5.2
    """
    def p(axiom_type: str, predicate: str) -> Pattern:
        return _make_basic_predicate_pattern("rl", axiom_type, predicate, graph_iri=graph_iri)

    def t(axiom_type: str, rdf_class: str) -> Pattern:
        return _make_basic_type_pattern("rl", axiom_type, rdf_class, graph_iri=graph_iri)

    return [
        # owl:oneOf — RL §5.2 superClass(CE): forbidden on RHS; also forbidden on LHS except
        # in the form { a } (one individual).  Over-approximate: flag any use.
        p("owl:oneOf",               f"{_OWL}oneOf"),
        # owl:hasSelf — entirely forbidden in RL (not allowed in superClass or subClass position)
        p("owl:hasSelf",             f"{_OWL}hasSelf"),
        # owl:disjointUnionOf — forbidden in RL
        p("owl:disjointUnionOf",     f"{_OWL}disjointUnionOf"),
        # owl:complementOf — forbidden in RL
        p("owl:complementOf",        f"{_OWL}complementOf"),
        # owl:AllDisjointClasses — RL allows pairwise disjoint between NAMED classes only;
        # over-approximate: flag any AllDisjointClasses usage
        t("owl:AllDisjointClasses",  f"{_OWL}AllDisjointClasses"),
        # Cardinality restrictions with N > 1 — RL allows ≤ 0 and ≤ 1 only
        _make_cardinality_gt1_pattern("rl", graph_iri=graph_iri),
        # Minimum cardinality — entirely forbidden in RL (only max ≤ 1 is allowed)
        _make_min_cardinality_pattern("rl", graph_iri=graph_iri),
        # owl:propertyChainAxiom — RL restricts the forms allowed (the chain must follow the
        # "complex role inclusions" discipline from OWL 2 DL).  Over-approximate: flag any use.
        p("owl:propertyChainAxiom",  f"{_OWL}propertyChainAxiom"),
    ]


def make_rl_patterns(graph_iri: str | None) -> list[Pattern]:
    """Return RL patterns scoped to the given named graph IRI, or default graph if None."""
    return _rl_patterns(graph_iri=graph_iri)


# Default-graph version used in unit tests
RL_PATTERNS: list[Pattern] = make_rl_patterns(None)


# ---------------------------------------------------------------------------
# QL pattern catalog
# ---------------------------------------------------------------------------

def _ql_patterns(*, graph_iri: str | None = None) -> list[Pattern]:
    """Build the complete QL forbidden-pattern list.

    OWL 2 QL is the most restrictive profile: roughly, only named classes and
    existentials over named properties are allowed on the LHS of SubClassOf, and
    the RHS is restricted to named classes and existentials.  Class expressions
    such as unions, intersections, cardinality restrictions, hasValue, and hasSelf
    are entirely forbidden.  Property characteristics beyond rdfs:subPropertyOf
    and owl:inverseOf (in limited forms) are forbidden.

    v1 over-approximations:
    - owl:disjointWith: QL allows pairwise disjoint between NAMED classes; we flag
      any use (false positives on pure named-class cases).

    Reference: https://www.w3.org/TR/owl2-profiles/#OWL_2_QL §6.2
    """
    def p(axiom_type: str, predicate: str) -> Pattern:
        return _make_basic_predicate_pattern("ql", axiom_type, predicate, graph_iri=graph_iri)

    def t(axiom_type: str, rdf_class: str) -> Pattern:
        return _make_basic_type_pattern("ql", axiom_type, rdf_class, graph_iri=graph_iri)

    return [
        # Disjointness — QL allows pairwise disjoint between NAMED classes; over-approximate
        p("owl:disjointWith",                    f"{_OWL}disjointWith"),
        t("owl:AllDisjointClasses",              f"{_OWL}AllDisjointClasses"),
        p("owl:disjointUnionOf",                 f"{_OWL}disjointUnionOf"),
        # Boolean class expressions — all forbidden in QL
        p("owl:complementOf",                    f"{_OWL}complementOf"),
        p("owl:unionOf",                         f"{_OWL}unionOf"),
        # Restrictions forbidden in QL
        p("owl:hasValue",                        f"{_OWL}hasValue"),
        p("owl:hasSelf",                         f"{_OWL}hasSelf"),
        p("owl:oneOf",                           f"{_OWL}oneOf"),
        # Cardinality — ALL cardinality restrictions are forbidden in QL (including ≤ 0 and ≤ 1)
        _make_cardinality_pattern("ql", graph_iri=graph_iri),
        # Property characteristics forbidden in QL
        t("owl:FunctionalProperty",              f"{_OWL}FunctionalProperty"),
        t("owl:InverseFunctionalProperty",       f"{_OWL}InverseFunctionalProperty"),
        t("owl:TransitiveProperty",              f"{_OWL}TransitiveProperty"),
        t("owl:IrreflexiveProperty",             f"{_OWL}IrreflexiveProperty"),
        t("owl:AsymmetricProperty",              f"{_OWL}AsymmetricProperty"),
        # Negative property assertions — forbidden in QL
        t("owl:NegativeObjectPropertyAssertion", f"{_OWL}NegativeObjectPropertyAssertion"),
        t("owl:NegativeDataPropertyAssertion",   f"{_OWL}NegativeDataPropertyAssertion"),
        # Property chain axioms — forbidden in QL
        p("owl:propertyChainAxiom",              f"{_OWL}propertyChainAxiom"),
    ]


def make_ql_patterns(graph_iri: str | None) -> list[Pattern]:
    """Return QL patterns scoped to the given named graph IRI, or default graph if None."""
    return _ql_patterns(graph_iri=graph_iri)


# Default-graph version used in unit tests
QL_PATTERNS: list[Pattern] = make_ql_patterns(None)


# ---------------------------------------------------------------------------
# Pattern executor
# ---------------------------------------------------------------------------

def run_pattern_count(
    store: pyoxigraph.Store,
    graph_iri: str | None,
    pattern: Pattern,
) -> tuple[int, list[dict]]:
    """Execute one pattern against a Pyoxigraph store.

    Returns (violation_count, sample_subjects).

    The graph_iri parameter is kept for API symmetry with the indexer but is
    unused here in v1 — the GRAPH clause is already baked into pattern.count_sparql
    and pattern.sample_sparql at construction time via make_el_patterns(graph_iri).
    """
    count_result = list(store.query(pattern.count_sparql))
    count = int(count_result[0]["n"].value) if count_result else 0
    samples: list[dict] = []
    if count > 0:
        for row in store.query(pattern.sample_sparql):
            subj = row["s"]
            iri = subj.value if hasattr(subj, "value") else str(subj)
            samples.append({"subject_iri": iri})
    return count, samples
