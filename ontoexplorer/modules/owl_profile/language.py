"""Language / expressivity tier detection: RDF · RDFS · RDFS-Plus · OWL.

The OWL 2 profile detector (pyowl2_profiles) only answers "which of EL/RL/QL/DL
is this in?". RDFS is a *strict subset* of all four, so a plain RDFS vocabulary
is reported as OWL 2 DL — or, when its untyped / ``rdfs:Class`` style breaks DL's
typing discipline, as OWL Full — and is never identified as what it actually is.
Many LOV vocabularies are exactly this.

This module adds a second, coarser axis computed from a handful of cheap SPARQL
``ASK``s (no reasoner, no whole-graph render), classifying an ontology by the
*heaviest* modelling construct it actually uses:

  * ``owl``       — uses OWL class expressions / restrictions / negation /
                    cardinality / keys / property chains → read the OWL 2 profile
                    (DL/EL/RL/QL/Full) for the detail.
  * ``rdfs-plus`` — beyond RDFS but still lightweight: named class/property
                    equivalence, property characteristics (transitive, symmetric,
                    functional, inverse), identity (sameAs/differentFrom), and the
                    owl:Class / owl:ObjectProperty / owl:DatatypeProperty
                    declarations that a taxonomy-only ontology carries.
  * ``rdfs``      — RDFS schema only (rdfs:Class / rdf:Property / subClassOf /
                    subPropertyOf / domain / range) and no OWL logical construct.
  * ``rdf``       — no schema at all (instance data only).

owl:Ontology headers and annotation machinery (owl:AnnotationProperty,
owl:versionInfo, owl:imports, owl:deprecated, …) do NOT elevate the tier — RDFS
vocabularies routinely carry them.
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

LANGUAGE_TIERS: tuple[str, ...] = ("rdf", "rdfs", "rdfs-plus", "owl")
TIER_LABELS: dict[str, str] = {
    "rdf": "RDF",
    "rdfs": "RDFS",
    "rdfs-plus": "RDFS-Plus",
    "owl": "OWL",
}

# ── Construct ladders (checked most-expressive first, short-circuit) ──────────
# Each entry is (local_name, as_type): as_type=True matches `?s rdf:type owl:X`,
# False matches `?s owl:X ?o`.

# Full-OWL machinery: class expressions, restrictions, negation, cardinality,
# keys, property chains, n-ary disjointness. ANY present ⇒ tier "owl".
_OWL_CONSTRUCTS: tuple[tuple[str, bool], ...] = (
    ("Restriction", True), ("onProperty", False),
    ("someValuesFrom", False), ("allValuesFrom", False),
    ("hasValue", False), ("hasSelf", False),
    ("minCardinality", False), ("maxCardinality", False), ("cardinality", False),
    ("minQualifiedCardinality", False), ("maxQualifiedCardinality", False),
    ("qualifiedCardinality", False), ("onClass", False), ("onDataRange", False),
    ("unionOf", False), ("intersectionOf", False), ("complementOf", False),
    ("oneOf", False), ("disjointWith", False), ("disjointUnionOf", False),
    ("AllDisjointClasses", True), ("AllDisjointProperties", True),
    ("AllDifferent", True), ("NegativePropertyAssertion", True),
    ("propertyDisjointWith", False), ("hasKey", False), ("propertyChainAxiom", False),
)

# Beyond RDFS but "RDFS-Plus" lightweight: declarations + named equivalence +
# property characteristics + identity. ANY present (and no full-OWL) ⇒ "rdfs-plus".
_RDFSPLUS_CONSTRUCTS: tuple[tuple[str, bool], ...] = (
    ("Class", True), ("ObjectProperty", True), ("DatatypeProperty", True),
    ("TransitiveProperty", True), ("SymmetricProperty", True),
    ("AsymmetricProperty", True), ("ReflexiveProperty", True),
    ("IrreflexiveProperty", True),
    ("FunctionalProperty", True), ("InverseFunctionalProperty", True),
    ("inverseOf", False), ("equivalentClass", False), ("equivalentProperty", False),
    ("sameAs", False), ("differentFrom", False),
)

# RDFS schema signals. ANY present (and nothing above) ⇒ "rdfs".
_RDFS_CONSTRUCTS: tuple[tuple[str, str, bool], ...] = (
    (_RDFS, "Class", True), (_RDFS, "Datatype", True),
    (_RDFS, "ContainerMembershipProperty", True),
    (_RDF, "Property", True),
    (_RDFS, "subClassOf", False), (_RDFS, "subPropertyOf", False),
    (_RDFS, "domain", False), (_RDFS, "range", False),
)


def _asker(store, graph_iri: str | None):
    """Return a function ask(ns, local, as_type) -> bool over the named graph."""
    def _wrap(inner: str) -> str:
        body = f"GRAPH <{graph_iri}> {{ {inner} }}" if graph_iri else inner
        return f"ASK {{ {body} }}"

    def ask(ns: str, local: str, as_type: bool) -> bool:
        if as_type:
            inner = f"?s <{_RDF}type> <{ns}{local}>"
        else:
            inner = f"?s <{ns}{local}> ?o"
        return bool(store.query(_wrap(inner)))

    return ask


def detect_language(store, graph_iri: str | None = None) -> dict:
    """Classify the ontology's language tier. Returns
    ``{"tier": <id>, "label": <display>, "construct": <first match or None>}``.
    """
    ask = _asker(store, graph_iri)

    for local, as_type in _OWL_CONSTRUCTS:
        if ask(_OWL, local, as_type):
            return _result("owl", f"owl:{local}")
    for local, as_type in _RDFSPLUS_CONSTRUCTS:
        if ask(_OWL, local, as_type):
            return _result("rdfs-plus", f"owl:{local}")
    for ns, local, as_type in _RDFS_CONSTRUCTS:
        if ask(ns, local, as_type):
            prefix = "rdfs" if ns == _RDFS else "rdf"
            return _result("rdfs", f"{prefix}:{local}")
    return _result("rdf", None)


def _result(tier: str, construct: str | None) -> dict:
    return {"tier": tier, "label": TIER_LABELS[tier], "construct": construct}
