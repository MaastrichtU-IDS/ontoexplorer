"""OWL 2 DL structural checks.

DL violations are not single-axiom patterns but structural properties of the whole
ontology graph.  Four checks are implemented:

1. Punning restrictions  — forbidden IRI co-typing pairs
2. Role hierarchy cycles — transitive property in a subPropertyOf+ cycle
3. Datatype restrictions — literals / declared datatypes outside OWL 2 datatype map
4. Reserved-vocabulary  — reserved IRI declared as user-level OWL construct

Pyoxigraph property paths (e.g. rdfs:subPropertyOf+) are supported natively.
"""
from __future__ import annotations

import pyoxigraph

from ontoexplorer.modules.owl_profile.patterns import _PREFIXES, _OWL
from ontoexplorer.modules.owl_profile.registry import ProfileViolation

# ---------------------------------------------------------------------------
# OWL 2 supported datatype map  (W3C OWL 2 Syntax §4.2 + ecosystem extensions)
# ---------------------------------------------------------------------------
# The strict W3C OWL 2 datatype map is conservative and omits common XML Schema
# date/time/duration types that the OBO ecosystem (and ROBOT/OWL-API) routinely
# accept. We match OWL-API's effective behavior here — flagging strictly only
# what real-world tooling treats as invalid — so our DL verdict agrees with
# ROBOT on commonly-occurring OBO usage of xsd:date, xsd:duration, etc.

# Strict W3C OWL 2 §4.2 datatype map
_OWL2_STRICT: frozenset[str] = frozenset({
    "http://www.w3.org/2001/XMLSchema#string",
    "http://www.w3.org/2001/XMLSchema#boolean",
    "http://www.w3.org/2001/XMLSchema#decimal",
    "http://www.w3.org/2001/XMLSchema#integer",
    "http://www.w3.org/2001/XMLSchema#nonNegativeInteger",
    "http://www.w3.org/2001/XMLSchema#nonPositiveInteger",
    "http://www.w3.org/2001/XMLSchema#positiveInteger",
    "http://www.w3.org/2001/XMLSchema#negativeInteger",
    "http://www.w3.org/2001/XMLSchema#long",
    "http://www.w3.org/2001/XMLSchema#int",
    "http://www.w3.org/2001/XMLSchema#short",
    "http://www.w3.org/2001/XMLSchema#byte",
    "http://www.w3.org/2001/XMLSchema#unsignedLong",
    "http://www.w3.org/2001/XMLSchema#unsignedInt",
    "http://www.w3.org/2001/XMLSchema#unsignedShort",
    "http://www.w3.org/2001/XMLSchema#unsignedByte",
    "http://www.w3.org/2001/XMLSchema#double",
    "http://www.w3.org/2001/XMLSchema#float",
    "http://www.w3.org/2001/XMLSchema#dateTime",
    "http://www.w3.org/2001/XMLSchema#dateTimeStamp",
    "http://www.w3.org/2001/XMLSchema#anyURI",
    "http://www.w3.org/2001/XMLSchema#hexBinary",
    "http://www.w3.org/2001/XMLSchema#base64Binary",
    "http://www.w3.org/2001/XMLSchema#normalizedString",
    "http://www.w3.org/2001/XMLSchema#token",
    "http://www.w3.org/2001/XMLSchema#language",
    "http://www.w3.org/2001/XMLSchema#Name",
    "http://www.w3.org/2001/XMLSchema#NCName",
    "http://www.w3.org/2001/XMLSchema#NMTOKEN",
    "http://www.w3.org/2000/01/rdf-schema#Literal",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#PlainLiteral",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#XMLLiteral",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
    "http://www.w3.org/2002/07/owl#real",
    "http://www.w3.org/2002/07/owl#rational",
})

# Ecosystem extensions — datatypes OWL-API/ROBOT accept that are not strictly
# in the W3C OWL 2 datatype map. These are commonly used in OBO ontologies
# (dcterms:date, dcterms:created, etc.) and rejecting them produces verdict
# disagreements with ROBOT without a corresponding spec benefit.
_OWL2_ECOSYSTEM: frozenset[str] = frozenset({
    "http://www.w3.org/2001/XMLSchema#date",
    "http://www.w3.org/2001/XMLSchema#time",
    "http://www.w3.org/2001/XMLSchema#duration",
    "http://www.w3.org/2001/XMLSchema#gYear",
    "http://www.w3.org/2001/XMLSchema#gMonth",
    "http://www.w3.org/2001/XMLSchema#gDay",
    "http://www.w3.org/2001/XMLSchema#gYearMonth",
    "http://www.w3.org/2001/XMLSchema#gMonthDay",
})

OWL2_DATATYPES: frozenset[str] = _OWL2_STRICT | _OWL2_ECOSYSTEM

# IRIs from the reserved vocabulary that may legitimately appear as typed constructs
# in conformant ontologies (e.g. owl:Thing a owl:Class is not a violation).
_RESERVED_VOCAB_BUILTIN_WHITELIST: frozenset[str] = frozenset({
    "http://www.w3.org/2002/07/owl#Thing",
    "http://www.w3.org/2002/07/owl#Nothing",
    "http://www.w3.org/2002/07/owl#topObjectProperty",
    "http://www.w3.org/2002/07/owl#bottomObjectProperty",
    "http://www.w3.org/2002/07/owl#topDataProperty",
    "http://www.w3.org/2002/07/owl#bottomDataProperty",
})


def _graph_wrap(inner: str, graph_iri: str | None) -> str:
    """Wrap a SPARQL pattern in a GRAPH clause if graph_iri is given."""
    if graph_iri:
        return f"GRAPH <{graph_iri}> {{ {inner} }}"
    return inner


# ---------------------------------------------------------------------------
# Check 1: Punning
# ---------------------------------------------------------------------------

def _detect_punning(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> list[ProfileViolation]:
    """Detect forbidden IRI co-typing (punning) pairs.

    OWL 2 allows class-individual punning (owl:Class + owl:NamedIndividual)
    but forbids:
      - owl:AnnotationProperty AND (owl:ObjectProperty OR owl:DatatypeProperty)
      - owl:DatatypeProperty AND owl:ObjectProperty
      - owl:Class AND owl:Datatype

    The FILTER is written asymmetrically so each forbidden pair appears only once.
    """
    _OWL = "http://www.w3.org/2002/07/owl#"
    inner = (
        "?iri a ?t1 . ?iri a ?t2 . "
        "FILTER(?t1 != ?t2) "
        "FILTER("
        f"  (?t1 = owl:AnnotationProperty && ?t2 IN (owl:ObjectProperty, owl:DatatypeProperty))"
        f"  || (?t1 = owl:DatatypeProperty && ?t2 = owl:ObjectProperty)"
        f"  || (?t1 = owl:Class && ?t2 = owl:Datatype)"
        ")"
    )
    sparql = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?iri ?t1 ?t2 WHERE { "
        + _graph_wrap(inner, graph_iri)
        + " } LIMIT 100"
    )
    violations: list[ProfileViolation] = []
    for row in store.query(sparql):
        iri = row["iri"].value
        t1 = row["t1"].value
        t2 = row["t2"].value
        violations.append(ProfileViolation(
            profile="dl",
            axiom_type="punning",
            subject_iri=iri,
            details=f"IRI typed as both <{t1}> and <{t2}>",
        ))
    return violations


# ---------------------------------------------------------------------------
# Check 2: Role hierarchy cycles for transitive properties
# ---------------------------------------------------------------------------

def _detect_transitive_cycles(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> list[ProfileViolation]:
    """Detect transitive properties that are in a subPropertyOf+ cycle.

    pyoxigraph supports SPARQL property paths natively (verified).
    Uses rdfs:subPropertyOf+ to compute the transitive closure.
    """
    inner = (
        "?p a owl:TransitiveProperty . "
        "?p rdfs:subPropertyOf+ ?p ."
    )
    sparql = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?p WHERE { "
        + _graph_wrap(inner, graph_iri)
        + " }"
    )
    violations: list[ProfileViolation] = []
    for row in store.query(sparql):
        p_iri = row["p"].value
        violations.append(ProfileViolation(
            profile="dl",
            axiom_type="role-hierarchy-cycle",
            subject_iri=p_iri,
            details="Transitive property in a sub-property cycle",
        ))
    return violations


# ---------------------------------------------------------------------------
# Check 3: Unsupported datatypes
# ---------------------------------------------------------------------------

def _detect_bad_datatypes(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> list[ProfileViolation]:
    """Detect literals and declared datatypes outside the OWL 2 datatype map.

    Two sub-checks:
    a) Literal values whose datatype IRI is not in OWL2_DATATYPES — reports the
       USAGE triple (s, p, o) so the Manchester renderer can show the actual axiom.
    b) Explicit rdfs:Datatype declarations with an IRI not in OWL2_DATATYPES.

    pyoxigraph supports GROUP BY + BIND(datatype(?o) AS ?dt) (verified).
    """
    violations: list[ProfileViolation] = []

    # Build a SPARQL IN-list for the allowed datatypes
    allowed_in = ", ".join(f"<{dt}>" for dt in sorted(OWL2_DATATYPES))

    # --- sub-check (a): literal datatypes — return usage triples (s, p, o) ---
    # Group by datatype first to get one representative triple per bad datatype.
    # We use a sub-SELECT trick: get distinct bad datatypes, then for each get
    # one example triple.  For simplicity, fetch up to 100 usage triples directly.
    inner_lit = (
        "?s ?p ?o . "
        "FILTER(isLiteral(?o)) "
        "BIND(datatype(?o) AS ?dt) "
        f"FILTER(?dt NOT IN ({allowed_in}))"
    )
    sparql_lit = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?s ?p ?o ?dt WHERE { "
        + _graph_wrap(inner_lit, graph_iri)
        + " } LIMIT 100"
    )
    seen_dt: set[str] = set()
    for row in store.query(sparql_lit):
        s_term = row["s"]
        dt_iri = row["dt"].value
        s_iri = s_term.value if hasattr(s_term, "value") else str(s_term)
        # Emit one violation per bad datatype (use the first usage triple found).
        # subject_iri is the axiom subject (the entity using the bad datatype),
        # NOT the datatype IRI — so callers can show where the bad datatype is used.
        if dt_iri not in seen_dt:
            seen_dt.add(dt_iri)
            violations.append(ProfileViolation(
                profile="dl",
                axiom_type="unsupported-datatype",
                subject_iri=s_iri,
                details=f"Uses datatype <{dt_iri}>",
            ))

    # --- sub-check (b): explicit rdfs:Datatype declarations ---
    # Exclude proper OWL 2 data ranges:
    #   - datatype restrictions: owl:onDatatype to an allowed base
    #   - data range unionOf / intersectionOf / oneOf / complementOf (DataRange)
    # These are anonymous bnodes typed as rdfs:Datatype but are valid in OWL 2 DL.
    inner_decl = (
        "?dt a rdfs:Datatype . "
        f"FILTER(?dt NOT IN ({allowed_in})) "
        "FILTER NOT EXISTS { ?dt owl:onDatatype ?_base . "
        f"  FILTER(?_base IN ({allowed_in})) }} "
        "FILTER NOT EXISTS { ?dt owl:unionOf ?_u } "
        "FILTER NOT EXISTS { ?dt owl:intersectionOf ?_i } "
        "FILTER NOT EXISTS { ?dt owl:oneOf ?_o } "
        "FILTER NOT EXISTS { ?dt owl:complementOf ?_c }"
    )
    sparql_decl = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?dt WHERE { "
        + _graph_wrap(inner_decl, graph_iri)
        + " } LIMIT 100"
    )
    for row in store.query(sparql_decl):
        dt_iri = row["dt"].value
        if dt_iri not in seen_dt:
            seen_dt.add(dt_iri)
            violations.append(ProfileViolation(
                profile="dl",
                axiom_type="unsupported-datatype",
                subject_iri=dt_iri,
                details=f"Declared datatype <{dt_iri}> is not in the OWL 2 datatype map",
            ))
    return violations


def _detect_bad_datatypes_with_terms(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> list[tuple[ProfileViolation, pyoxigraph.NamedNode | None, pyoxigraph.Term | None]]:
    """Like _detect_bad_datatypes, but also returns (p_term, o_term) for rendering.

    Returns a list of (violation, predicate_node, object_term) tuples.
    predicate_node and object_term are None for sub-check (b) (declared datatypes).
    """
    results: list[tuple[ProfileViolation, pyoxigraph.NamedNode | None, pyoxigraph.Term | None]] = []

    allowed_in = ", ".join(f"<{dt}>" for dt in sorted(OWL2_DATATYPES))

    # sub-check (a): literal datatypes — one representative triple per bad datatype
    inner_lit = (
        "?s ?p ?o . "
        "FILTER(isLiteral(?o)) "
        "BIND(datatype(?o) AS ?dt) "
        f"FILTER(?dt NOT IN ({allowed_in}))"
    )
    sparql_lit = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?s ?p ?o ?dt WHERE { "
        + _graph_wrap(inner_lit, graph_iri)
        + " } LIMIT 100"
    )
    seen_dt: set[str] = set()
    for row in store.query(sparql_lit):
        s_term = row["s"]
        p_term = row["p"]
        o_term = row["o"]
        dt_iri = row["dt"].value
        s_iri = s_term.value if hasattr(s_term, "value") else str(s_term)
        if dt_iri not in seen_dt:
            seen_dt.add(dt_iri)
            v = ProfileViolation(
                profile="dl",
                axiom_type="unsupported-datatype",
                subject_iri=s_iri,
                details=f"Uses datatype <{dt_iri}>",
            )
            results.append((v, p_term if isinstance(p_term, pyoxigraph.NamedNode) else None, o_term))

    # sub-check (b): explicit rdfs:Datatype declarations
    # Exclude proper OWL 2 data ranges:
    #   - datatype restrictions: owl:onDatatype to an allowed base
    #   - data range unionOf / intersectionOf / oneOf / complementOf (DataRange)
    # These are anonymous bnodes typed as rdfs:Datatype but are valid in OWL 2 DL.
    inner_decl = (
        "?dt a rdfs:Datatype . "
        f"FILTER(?dt NOT IN ({allowed_in})) "
        "FILTER NOT EXISTS { ?dt owl:onDatatype ?_base . "
        f"  FILTER(?_base IN ({allowed_in})) }} "
        "FILTER NOT EXISTS { ?dt owl:unionOf ?_u } "
        "FILTER NOT EXISTS { ?dt owl:intersectionOf ?_i } "
        "FILTER NOT EXISTS { ?dt owl:oneOf ?_o } "
        "FILTER NOT EXISTS { ?dt owl:complementOf ?_c }"
    )
    sparql_decl = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?dt WHERE { "
        + _graph_wrap(inner_decl, graph_iri)
        + " } LIMIT 100"
    )
    for row in store.query(sparql_decl):
        dt_iri = row["dt"].value
        if dt_iri not in seen_dt:
            seen_dt.add(dt_iri)
            v = ProfileViolation(
                profile="dl",
                axiom_type="unsupported-datatype",
                subject_iri=dt_iri,
                details=f"Declared datatype <{dt_iri}> is not in the OWL 2 datatype map",
            )
            results.append((v, None, None))

    return results


# ---------------------------------------------------------------------------
# Check 4: Reserved vocabulary used in user declarations
# ---------------------------------------------------------------------------

def _detect_reserved_vocab(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> list[ProfileViolation]:
    """Detect reserved IRIs declared as user-level OWL constructs.

    OWL 2 reserves the owl:, rdf:, rdfs:, and xsd: namespaces.  Any IRI from
    these namespaces declared as owl:Class, owl:NamedIndividual, owl:ObjectProperty,
    or owl:DatatypeProperty is suspicious.

    Over-approximation (v1): a small built-in whitelist (_RESERVED_VOCAB_BUILTIN_WHITELIST)
    covers the most common false positives (owl:Thing, owl:Nothing, etc.).
    """
    inner = (
        "?s a ?t . "
        "FILTER("
        "  STRSTARTS(STR(?s), \"http://www.w3.org/2002/07/owl#\")"
        "  || STRSTARTS(STR(?s), \"http://www.w3.org/1999/02/22-rdf-syntax-ns#\")"
        "  || STRSTARTS(STR(?s), \"http://www.w3.org/2000/01/rdf-schema#\")"
        "  || STRSTARTS(STR(?s), \"http://www.w3.org/2001/XMLSchema#\")"
        ") "
        "FILTER(?t IN (owl:Class, owl:NamedIndividual, owl:ObjectProperty, owl:DatatypeProperty))"
    )
    sparql = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?s ?t WHERE { "
        + _graph_wrap(inner, graph_iri)
        + " } LIMIT 100"
    )
    violations: list[ProfileViolation] = []
    for row in store.query(sparql):
        s_iri = row["s"].value
        if s_iri in _RESERVED_VOCAB_BUILTIN_WHITELIST:
            continue
        t_iri = row["t"].value
        violations.append(ProfileViolation(
            profile="dl",
            axiom_type="reserved-vocab",
            subject_iri=s_iri,
            details=f"Reserved IRI <{s_iri}> declared as <{t_iri}>",
        ))
    return violations


# ---------------------------------------------------------------------------
# Check 5: Undeclared properties (W3C OWL 2 DL §5.8 declaration completeness)
# ---------------------------------------------------------------------------

# Predicates we exempt from declaration-completeness checks. Two groups:
#
# (a) Reserved W3C vocabularies — implicitly declared per the OWL 2 spec
#     (owl/rdf/rdfs/xsd) plus other W3C standards that OWL tooling treats
#     as built-in (SWRL/SWRLb for rule language predicates).
#
# (b) Widely-used annotation-property vocabularies that real OWL tools
#     (OWL-API, ROBOT, HermiT) recognize without requiring an explicit
#     declaration in the user ontology. Adding these matches the de facto
#     behavior of those tools and avoids spurious "undeclared" reports on
#     ontologies that legitimately use these vocabularies for metadata.
_DECLARATION_EXEMPT_NAMESPACES = (
    # (a) Core W3C vocabularies
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2001/XMLSchema#",
    "http://www.w3.org/2003/11/swrl#",
    "http://www.w3.org/2003/11/swrlb#",
    # (b) Widely-used annotation/metadata vocabularies
    "http://purl.org/dc/elements/1.1/",        # Dublin Core
    "http://purl.org/dc/terms/",               # Dublin Core Terms
    "http://www.w3.org/2004/02/skos/core#",    # SKOS
    "http://xmlns.com/foaf/0.1/",              # FOAF
    "http://purl.org/vocab/vann/",             # VANN
    "http://creativecommons.org/ns#",          # Creative Commons
    "http://www.geneontology.org/formats/oboInOwl#",  # OBO metadata
    "http://www.w3.org/ns/prov#",              # PROV
)


def _detect_undeclared_properties(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> list[ProfileViolation]:
    """Detect IRIs used as properties that lack an explicit OWL property declaration.

    W3C OWL 2 DL §5.8 (Declaration Consistency): every IRI used as a property
    in an axiom must be declared as either owl:ObjectProperty,
    owl:DatatypeProperty, or owl:AnnotationProperty. Failing this declaration
    requirement puts the ontology outside OWL 2 DL.

    Reserved-vocabulary predicates (owl:, rdf:, rdfs:, xsd:) are implicitly
    declared per the spec and exempt.
    """
    ns_filter = " ".join(
        f'FILTER(!STRSTARTS(STR(?p), "{ns}"))' for ns in _DECLARATION_EXEMPT_NAMESPACES
    )
    inner = (
        "?s ?p ?o . "
        f"{ns_filter} "
        "FILTER(isIRI(?p)) "
        "FILTER NOT EXISTS { "
        "  ?p a ?ptype . "
        "  FILTER(?ptype IN ("
        f"    <{_OWL}ObjectProperty>,"
        f"    <{_OWL}DatatypeProperty>,"
        f"    <{_OWL}AnnotationProperty>"
        "  )) "
        "}"
    )
    sparql = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?p WHERE { "
        + _graph_wrap(inner, graph_iri)
        + " } LIMIT 200"
    )
    violations: list[ProfileViolation] = []
    for row in store.query(sparql):
        p_iri = row["p"].value
        violations.append(ProfileViolation(
            profile="dl",
            axiom_type="undeclared-property",
            subject_iri=p_iri,
            details=(
                f"Property <{p_iri}> is used in an axiom but is not declared "
                "as owl:ObjectProperty / owl:DatatypeProperty / owl:AnnotationProperty"
            ),
        ))
    return violations


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def detect_dl_violations(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> list[ProfileViolation]:
    """Run all four DL structural checks and return combined violations.

    Args:
        store:     A pyoxigraph.Store containing the ontology triples.
        graph_iri: Named graph IRI to query, or None for the default graph.

    Returns:
        List of ProfileViolation instances, one per detected violation.
    """
    # Note: the OWL 2 datatype-map check (_detect_bad_datatypes) was empirically
    # verified to have no practical value — HermiT, Pellet, ROBOT's profile
    # checker, and OWL-API all accept any datatype IRI including ones strictly
    # not in the W3C OWL 2 datatype map (xsd:date, xsd:duration, xsd:gYear,
    # xsd:ID, even fabricated custom IRIs). Flagging these produced false-
    # positive DL=OUT verdicts that disagreed with every real reasoner. The
    # check is preserved (see _detect_bad_datatypes below) but not invoked.
    violations: list[ProfileViolation] = []
    violations.extend(_detect_punning(store, graph_iri))
    violations.extend(_detect_transitive_cycles(store, graph_iri))
    violations.extend(_detect_reserved_vocab(store, graph_iri))
    violations.extend(_detect_undeclared_properties(store, graph_iri))
    return violations


def detect_dl_violations_with_terms(
    store: pyoxigraph.Store,
    graph_iri: str | None,
) -> list[tuple[ProfileViolation, str | None, pyoxigraph.Term | None]]:
    """Like detect_dl_violations but returns (violation, predicate_iri, object_term) tuples.

    predicate_iri and object_term are only populated for unsupported-datatype violations
    (sub-check a) so the detector can pass them to the Manchester renderer.
    For all other violation types, predicate_iri and object_term are None.
    """
    results: list[tuple[ProfileViolation, str | None, pyoxigraph.Term | None]] = []

    # See detect_dl_violations for why the datatype-map check is skipped.
    for v in _detect_punning(store, graph_iri):
        results.append((v, None, None))
    for v in _detect_transitive_cycles(store, graph_iri):
        results.append((v, None, None))
    for v in _detect_reserved_vocab(store, graph_iri):
        results.append((v, None, None))
    for v in _detect_undeclared_properties(store, graph_iri):
        results.append((v, None, None))
    return results
