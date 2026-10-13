"""Work around horned-owl aborting on a restriction over a wrong-kind property.

The reasoner (rustdl, PyO3/horned-owl) classifies via horned-owl's strict RDF
reader. OWL 2 class restrictions are only over OBJECT or DATA properties, and the
reader must map each ``owl:Restriction`` to ``ObjectSomeValuesFrom`` /
``DataSomeValuesFrom`` / cardinality by the kind of its ``owl:onProperty``. When
that property's declared kind is not usable for a restriction — an annotation
property, a bare ``rdf:Property``, an undeclared property, or a marker like
``owl:DeprecatedProperty`` with no real kind — the reader ABORTS the whole parse::

    Validity Error: Unexpected property kind in restriction

Common in metadata / upper vocabularies (qudt, ro, voag, seo, bioportalmetadata,
…) that write class restrictions over properties they declare as annotation
properties, leave as bare ``rdf:Property``, or never declare. These INDEX fine;
only the strict reasoner path chokes, and one bad restriction aborts the entire
ontology. Switching parser does not help (pyhornedowl shares horned-owl's core).

Fix: for each property used as a restriction ``onProperty``, infer the kind the
restriction REQUIRES from its filler and, when the property lacks a usable kind,
reconcile it — strip the annotation-property / bare-``rdf:Property`` /
``DeprecatedProperty`` typing that confuses the reader and add the required
``owl:ObjectProperty`` / ``owl:DatatypeProperty``. Same store-level sanitisation
as ontology_type_fix / equiv_class_fix / property_pun_fix.

Filler -> required kind:
* ``owl:onDataRange``, ``someValuesFrom`` / ``allValuesFrom`` a datatype, or a
  literal ``hasValue`` -> DATA.
* ``owl:onClass``, ``someValuesFrom`` / ``allValuesFrom`` a class expression, an
  IRI ``hasValue``, or a bare cardinality (no onClass / onDataRange) -> OBJECT.

Conservatism (no guessing):
* A property already carrying a valid matching OWL kind (ObjectProperty, or an
  object characteristic like Symmetric/Transitive/Functional/…, for an object
  restriction; DatatypeProperty for a data restriction) is left untouched.
* A property used across BOTH object and data restrictions in one ontology is a
  genuine pun the reader cannot represent either way — left to fail rather than
  guessed at (documented false-negative, not a correctness risk).
* A property that already has the OPPOSITE real OWL kind (e.g. DatatypeProperty
  but used in an object restriction) is likewise left alone — stripping a genuine
  kind claim could silently change semantics.
* A node already typed as a CLASS (owl:Class / rdfs:Class) that is (mis)used as an
  onProperty is NOT retyped — minting a class/property pun would corrupt the
  hierarchy. That restriction is left to fail rather than silently mis-modelled.

Safety: reclassifying an annotation/bare property as object/data adds a real
axiom that can affect the class hierarchy, so this is validated by diffing
classifications before/after on the corpus (as with property_pun_fix), not a
blind flip.
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_XSD = "http://www.w3.org/2001/XMLSchema#"

# Property typings that count as a valid OBJECT kind for a restriction.
_OBJECT_KINDS = frozenset(_OWL + k for k in (
    "ObjectProperty", "SymmetricProperty", "TransitiveProperty",
    "FunctionalProperty", "InverseFunctionalProperty", "ReflexiveProperty",
    "IrreflexiveProperty", "AsymmetricProperty",
))
_DATA_KIND = _OWL + "DatatypeProperty"
# Typings that are NOT usable as a restriction property and should be stripped
# when we reconcile (they are what confuse the reader; real object/data kinds are
# never stripped).
_STRIP_KINDS = frozenset((
    _OWL + "AnnotationProperty", _RDF + "Property", _OWL + "DeprecatedProperty",
))
# A node carrying any of these is a class, not a property — never retype it into a
# property (that would be a class/property pun that corrupts the hierarchy).
_CLASS_KINDS = frozenset((_OWL + "Class", _RDFS + "Class"))

# Datatype IRIs that mark a filler as a data range (beyond anything typed
# rdfs:Datatype or carrying owl:onDatatype in the graph).
_DATATYPE_IRIS = frozenset({
    _RDFS + "Literal", _RDF + "PlainLiteral", _RDF + "langString",
    _RDF + "XMLLiteral",
})


def _is_datatype(store, node) -> bool:
    import pyoxigraph
    if isinstance(node, pyoxigraph.Literal):
        return True
    if isinstance(node, pyoxigraph.NamedNode):
        if node.value.startswith(_XSD) or node.value in _DATATYPE_IRIS:
            return True
    # typed rdfs:Datatype, or a datatype restriction (owl:onDatatype), covers
    # both named and blank data ranges.
    rdf_type = pyoxigraph.NamedNode(_RDF + "type")
    if any(q.object == pyoxigraph.NamedNode(_RDFS + "Datatype")
           for q in store.quads_for_pattern(node, rdf_type, None, None)):
        return True
    if any(True for _ in store.quads_for_pattern(
            node, pyoxigraph.NamedNode(_OWL + "onDatatype"), None, None)):
        return True
    return False


def _required_kind(store, restriction) -> str | None:
    """'data' | 'object' | None (ambiguous) for the restriction node."""
    import pyoxigraph

    def obj(pred):
        for q in store.quads_for_pattern(restriction, pyoxigraph.NamedNode(_OWL + pred), None, None):
            return q.object
        return None

    if obj("onDataRange") is not None:
        return "data"
    if obj("onClass") is not None:
        return "object"
    for pred in ("someValuesFrom", "allValuesFrom"):
        t = obj(pred)
        if t is not None:
            return "data" if _is_datatype(store, t) else "object"
    hv = obj("hasValue")
    if hv is not None:
        return "data" if _is_datatype(store, hv) else "object"
    # bare cardinality (owl:cardinality / minCardinality / maxCardinality with no
    # onClass/onDataRange): horned-owl reads these as object restrictions.
    return None


def reconcile_restriction_property_kinds(store) -> int:
    """Reconcile the kind of every property used as a restriction ``onProperty``
    so horned-owl can build the restriction (see the module docstring for the
    exact, classification-safe rules). Mutates ``store`` in place; returns the
    number of properties retyped. Safe to call unconditionally.
    """
    import pyoxigraph

    rdf_type = pyoxigraph.NamedNode(_RDF + "type")
    on_prop = pyoxigraph.NamedNode(_OWL + "onProperty")

    # Collect the kinds each onProperty is REQUIRED to be, across all restrictions.
    required: dict[str, set[str]] = {}
    for q in store.quads_for_pattern(None, on_prop, None, None):
        p = q.object
        if not isinstance(p, pyoxigraph.NamedNode):
            continue  # anonymous / inverse property expression — out of scope
        rk = _required_kind(store, q.subject)
        req = required.setdefault(p.value, set())
        if rk is not None:
            req.add(rk)

    retyped = 0
    for piri, reqs in required.items():
        # Genuine object-vs-data pun across restrictions: cannot satisfy both,
        # leave it (documented false-negative).
        if reqs == {"object", "data"}:
            continue
        want = "data" if reqs == {"data"} else "object"  # {} (all ambiguous) -> object
        p = pyoxigraph.NamedNode(piri)
        kinds = {q.object.value for q in store.quads_for_pattern(p, rdf_type, None, None)
                 if isinstance(q.object, pyoxigraph.NamedNode)}

        # A class mis-used as an onProperty: never mint a class/property pun.
        if kinds & _CLASS_KINDS:
            continue

        has_object = bool(kinds & _OBJECT_KINDS)
        has_data = _DATA_KIND in kinds
        # Already valid for what the restriction needs -> nothing to do.
        if want == "object" and has_object:
            continue
        if want == "data" and has_data:
            continue
        # A genuine opposite real kind (not just annotation/bare) -> don't strip a
        # real claim; leave it to fail rather than silently change semantics.
        if want == "object" and has_data:
            continue
        if want == "data" and has_object:
            continue

        # Reconcile: strip the non-usable typings, add the required kind.
        for k in (kinds & _STRIP_KINDS):
            for q in list(store.quads_for_pattern(p, rdf_type, pyoxigraph.NamedNode(k), None)):
                store.remove(q)
        store.add(pyoxigraph.Quad(
            p, rdf_type,
            pyoxigraph.NamedNode(_DATA_KIND if want == "data" else _OWL + "ObjectProperty")))
        retyped += 1
    return retyped
