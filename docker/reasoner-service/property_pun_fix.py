"""Work around horned-owl aborting on a property axiom that puns property kinds.

The reasoner (rustdl, PyO3/horned-owl) classifies via horned-owl's strict RDF reader.
OWL 2 DL forbids a property from being more than one kind (object / data / annotation),
so when an ``owl:equivalentProperty`` or ``rdfs:subPropertyOf`` axiom links two
properties of different kinds, the reader ABORTS the whole parse::

    Validity Error: Types of two properties do not match: IRI(a), IRI(b)

This is extremely common in cross-vocabulary alignments — e.g. ``dct:creator``
(an annotation / bare ``rdf:Property``) stated ``owl:equivalentProperty`` ``foaf:maker``
(an object property), or ``vcard:org`` (object) vs ``vcard:organization-name`` (data).
These ontologies INDEX fine; only the strict reasoner path chokes. Switching parser does
NOT help (pyhornedowl shares horned-owl's core). The alignment axiom is irrelevant to the
class hierarchy a DL reasoner computes, so dropping it is lossless for classification and
restores the parse — the same store-level sanitization as ontology_type_fix / equiv_class_fix.

Scope: this drops only the axioms whose kind mismatch is VISIBLE in the ontology's own
graph (at least one operand explicitly typed a different OWL property kind, or a bare
``rdf:Property``). Where both operands are typed only in an external vocabulary the graph
doesn't carry, the mismatch isn't locally detectable and these are left for the upstream
horned-owl fix (tolerate the mismatch in the reader, which has the kind info this shim lacks).
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

_PROP_AXIOMS = (_OWL + "equivalentProperty", _RDFS + "subPropertyOf")
_OWL_KINDS = ("ObjectProperty", "DatatypeProperty", "AnnotationProperty")


def drop_mismatched_property_axioms(store) -> int:
    """Drop every ``owl:equivalentProperty`` / ``rdfs:subPropertyOf`` triple whose two
    named operands have a locally-visible property-kind mismatch — different OWL kinds,
    or either operand typed only as a bare ``rdf:Property``. Mutates ``store`` in place;
    returns the number of triples removed. Safe to call unconditionally.
    """
    import pyoxigraph

    rdf_type = pyoxigraph.NamedNode(_RDF + "type")

    def kind(node) -> str | None:
        types = {
            q.object.value
            for q in store.quads_for_pattern(node, rdf_type, None, None)
            if isinstance(q.object, pyoxigraph.NamedNode)
        }
        for k in _OWL_KINDS:
            if _OWL + k in types:
                return k
        if _RDF + "Property" in types:
            return "bare"
        return None

    removed = 0
    for pred in _PROP_AXIOMS:
        for q in list(store.quads_for_pattern(None, pyoxigraph.NamedNode(pred), None, None)):
            if not (isinstance(q.subject, pyoxigraph.NamedNode)
                    and isinstance(q.object, pyoxigraph.NamedNode)):
                continue
            ka, kb = kind(q.subject), kind(q.object)
            mismatch = (
                (ka in _OWL_KINDS and kb in _OWL_KINDS and ka != kb)  # two different OWL kinds
                or "bare" in (ka, kb)                                 # a non-OWL rdf:Property operand
            )
            if mismatch:
                store.remove(q)
                removed += 1
    return removed
