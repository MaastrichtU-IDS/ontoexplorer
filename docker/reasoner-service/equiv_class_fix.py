"""Work around horned-owl rejecting an owl:equivalentClass with an undeclared operand.

The reasoner (rustdl, PyO3/horned-owl) classifies via horned-owl's strict RDF reader.
That reader ABORTS the whole parse when an ``owl:equivalentClass`` axiom has a named
operand that is not a declared class entity, e.g.::

    Validity Error: Unknown entity in equivalent class statement:
        [Iri(cc:Reproduction), OWL(EquivalentClass), Iri(...)]

The operand is a *used-but-undeclared* class — very common when an ontology aligns
to external vocabularies (cc:*, sioc:User, schema:LodgingBusiness, …) by equivalence
without re-declaring them, or simply omits the ``owl:Class`` declaration. These
ontologies INDEX fine (the indexer is lenient); only the strict reasoner path chokes.
Switching parser does NOT help — pyhornedowl shares horned-owl's core and fails
identically — so the fix is store-level input sanitization, like ontology_type_fix.

Fix: before serializing the store to RDF/XML for the reasoner, declare every named
operand of an ``owl:equivalentClass`` that is not already an ``owl:Class`` as an
``owl:Class``. An ``owl:equivalentClass`` axiom semantically requires both operands
to be classes, so the declaration is entailed by the axiom and lossless.

Crucially this covers two cases horned-owl both rejects:

* an operand with **no** ``rdf:type`` at all (the original case); and
* an operand that **is** typed, but not as ``owl:Class`` — e.g. ``owl:DeprecatedClass``,
  ``skos:Concept``/``skos:ConceptScheme``, or ``rdfs:Class``. horned-owl does not accept
  those as a class expression, so it aborts even though a declaration is present. (A real
  example: cwrc's ``SocialClassIdentity`` is ``owl:DeprecatedClass`` + ``skos:Concept``.)
  Adding ``owl:Class`` *alongside* the existing types is what makes the operand a class
  horned-owl recognises; the existing types are left in place.

Two operands are deliberately NOT touched:

* blank-node (anonymous class-expression) operands — not named entities; and
* an operand already typed as an OWL **property** (``owl:ObjectProperty`` /
  ``DatatypeProperty`` / ``AnnotationProperty``). Declaring such an entity ``owl:Class``
  would create a class/property pun that simply swaps the "Unknown entity" abort for a
  punning abort — net-no-gain, and the ontology is malformed anyway.

The proper long-term fix is upstream in horned-owl's RDF reader (treat a used
undeclared class as an implicit declaration rather than a fatal error); this keeps
the service classifying in the meantime.
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_XSD = "http://www.w3.org/2001/XMLSchema#"

# Reserved vocabulary namespaces. horned-owl recognises these built-in terms
# (owl:Thing, owl:Nothing, rdfs:Resource, …) natively without a Declaration, so
# an operand from one of them never triggers the "Unknown entity" abort — and
# declaring a built-in as owl:Class would be a redundant, slightly wrong axiom.
# Skip them so the injected count reflects only genuine external/undeclared
# classes.
_RESERVED_NS = (_OWL, _RDF, _RDFS, _XSD)

# Property kinds: an equivalentClass operand already typed as one of these must not
# be punned as a class (see module docstring).
_OWL_PROPERTY_KINDS = ("ObjectProperty", "DatatypeProperty", "AnnotationProperty")


def inject_equivalent_class_declarations(store) -> list[str]:
    """Declare as ``owl:Class`` every named ``owl:equivalentClass`` operand that is not
    already typed ``owl:Class`` (whether it has no type at all, or only non-``owl:Class``
    types such as ``owl:DeprecatedClass`` / ``skos:Concept`` / ``rdfs:Class``). Operands
    in a reserved vocabulary namespace (owl:/rdf:/rdfs:/xsd:) and operands already typed
    as an OWL property are skipped. Mutates ``store`` in place; returns the sorted list of
    IRIs declared (empty if there was nothing to fix). Safe to call unconditionally.
    """
    import pyoxigraph

    rdf_type = pyoxigraph.NamedNode(_RDF + "type")
    owl_class = pyoxigraph.NamedNode(_OWL + "Class")
    equivalent_class = pyoxigraph.NamedNode(_OWL + "equivalentClass")

    operands: set[str] = set()
    for q in store.quads_for_pattern(None, equivalent_class, None, None):
        for term in (q.subject, q.object):
            if isinstance(term, pyoxigraph.NamedNode):
                operands.add(term.value)

    injected: list[str] = []
    for iri in operands:
        if iri.startswith(_RESERVED_NS):
            continue
        subj = pyoxigraph.NamedNode(iri)
        types = {
            q.object.value
            for q in store.quads_for_pattern(subj, rdf_type, None, None)
            if isinstance(q.object, pyoxigraph.NamedNode)
        }
        if _OWL + "Class" in types:
            continue  # already a class horned-owl accepts
        if any(_OWL + k in types for k in _OWL_PROPERTY_KINDS):
            continue  # don't pun a property as a class — swaps one abort for another
        store.add(pyoxigraph.Quad(subj, rdf_type, owl_class))
        injected.append(iri)
    return sorted(injected)
