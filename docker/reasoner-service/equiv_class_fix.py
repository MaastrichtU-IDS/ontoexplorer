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
operand of an ``owl:equivalentClass`` that has NO ``rdf:type`` at all as an
``owl:Class``. An ``owl:equivalentClass`` axiom semantically requires both operands
to be classes, so the declaration is entailed by the axiom and lossless. Operands
that already carry *any* ``rdf:type`` are left untouched (never override an existing
declaration — that would risk creating punning that itself breaks the parse), as are
blank-node (anonymous class-expression) operands.

The proper long-term fix is upstream in horned-owl's RDF reader (treat a used
undeclared class as an implicit declaration rather than a fatal error); this keeps
the service classifying in the meantime.
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def inject_equivalent_class_declarations(store) -> list[str]:
    """Declare as ``owl:Class`` every named ``owl:equivalentClass`` operand that has
    no ``rdf:type`` at all. Mutates ``store`` in place; returns the sorted list of
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
        subj = pyoxigraph.NamedNode(iri)
        has_type = any(True for _ in store.quads_for_pattern(subj, rdf_type, None, None))
        if has_type:
            continue
        store.add(pyoxigraph.Quad(subj, rdf_type, owl_class))
        injected.append(iri)
    return sorted(injected)
