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

from ontoexplorer.modules.owl_profile.patterns import _PREFIXES
from ontoexplorer.modules.owl_profile.registry import ProfileViolation

# ---------------------------------------------------------------------------
# OWL 2 supported datatype map  (W3C OWL 2 Syntax §4.2)
# ---------------------------------------------------------------------------

OWL2_DATATYPES: frozenset[str] = frozenset({
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
    a) Literal values whose datatype IRI is not in OWL2_DATATYPES.
    b) Explicit rdfs:Datatype declarations with an IRI not in OWL2_DATATYPES.

    pyoxigraph supports GROUP BY + BIND(datatype(?o) AS ?dt) (verified).
    """
    violations: list[ProfileViolation] = []

    # Build a SPARQL IN-list for the allowed datatypes
    allowed_in = ", ".join(f"<{dt}>" for dt in sorted(OWL2_DATATYPES))

    # --- sub-check (a): literal datatypes ---
    inner_lit = (
        "?s ?p ?o . "
        "FILTER(isLiteral(?o)) "
        "BIND(datatype(?o) AS ?dt) "
        f"FILTER(?dt NOT IN ({allowed_in}))"
    )
    sparql_lit = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?dt WHERE { "
        + _graph_wrap(inner_lit, graph_iri)
        + " } LIMIT 100"
    )
    for row in store.query(sparql_lit):
        dt_iri = row["dt"].value
        violations.append(ProfileViolation(
            profile="dl",
            axiom_type="unsupported-datatype",
            subject_iri=dt_iri,
            details=f"Datatype <{dt_iri}> is not in the OWL 2 datatype map",
        ))

    # --- sub-check (b): explicit rdfs:Datatype declarations ---
    inner_decl = (
        "?dt a rdfs:Datatype . "
        f"FILTER(?dt NOT IN ({allowed_in}))"
    )
    sparql_decl = (
        f"{_PREFIXES}"
        "SELECT DISTINCT ?dt WHERE { "
        + _graph_wrap(inner_decl, graph_iri)
        + " } LIMIT 100"
    )
    seen = {v.subject_iri for v in violations}
    for row in store.query(sparql_decl):
        dt_iri = row["dt"].value
        if dt_iri not in seen:
            violations.append(ProfileViolation(
                profile="dl",
                axiom_type="unsupported-datatype",
                subject_iri=dt_iri,
                details=f"Declared datatype <{dt_iri}> is not in the OWL 2 datatype map",
            ))
            seen.add(dt_iri)
    return violations


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
    violations: list[ProfileViolation] = []
    violations.extend(_detect_punning(store, graph_iri))
    violations.extend(_detect_transitive_cycles(store, graph_iri))
    violations.extend(_detect_bad_datatypes(store, graph_iri))
    violations.extend(_detect_reserved_vocab(store, graph_iri))
    return violations
