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
NOT help (pyhornedowl shares horned-owl's core). Dropping the offending axiom restores the
parse — the same store-level sanitization as ontology_type_fix / equiv_class_fix.

What's dropped, and why it's safe for CLASSIFICATION:

* ``owl:equivalentProperty`` with a kind mismatch, or with a bare ``rdf:Property`` operand:
  dropped. A mismatched equivalence is DL-illegal and unusable; a bare ``rdf:Property`` is
  not a usable OWL property. Lossless for the class hierarchy.
* ``rdfs:subPropertyOf``: dropped ONLY on an explicit two-different-OWL-kinds mismatch
  (e.g. ObjectProperty ⊑ DataProperty), which is DL-illegal — its "role edge" is meaningless.
  The bare-``rdf:Property`` heuristic is deliberately NOT applied to subPropertyOf: a bare
  property that horned-owl would promote to an object property by usage carries a real role
  edge, and role hierarchy *does* affect class subsumption (via ∃R.D / property chains), so
  dropping it could silently under-classify. We accept recovering fewer ontologies over that.

Not covered: a mismatch typed only in an external vocabulary the graph doesn't carry isn't
locally detectable (left for an upstream horned-owl fix, which has the kind info this shim
lacks); and a property punned as two kinds on ONE IRI makes kind() pick the first, so a
same-other-kind axiom survives and that ontology still aborts (a false-negative, not a
correctness bug).
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

_EQUIVALENT_PROPERTY = _OWL + "equivalentProperty"
_SUB_PROPERTY_OF = _RDFS + "subPropertyOf"
_OWL_KINDS = ("ObjectProperty", "DatatypeProperty", "AnnotationProperty")


def drop_mismatched_property_axioms(store) -> int:
    """Drop ``owl:equivalentProperty`` / ``rdfs:subPropertyOf`` triples whose two named
    operands have a locally-visible, DL-illegal property-kind mismatch (see the module
    docstring for the exact, classification-safe rule per predicate). Mutates ``store`` in
    place; returns the number of triples removed. Safe to call unconditionally.
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
    for pred, allow_bare in ((_EQUIVALENT_PROPERTY, True), (_SUB_PROPERTY_OF, False)):
        for q in list(store.quads_for_pattern(None, pyoxigraph.NamedNode(pred), None, None)):
            if not (isinstance(q.subject, pyoxigraph.NamedNode)
                    and isinstance(q.object, pyoxigraph.NamedNode)):
                continue
            ka, kb = kind(q.subject), kind(q.object)
            explicit_mismatch = ka in _OWL_KINDS and kb in _OWL_KINDS and ka != kb
            bare_mismatch = allow_bare and "bare" in (ka, kb)
            if explicit_mismatch or bare_mismatch:
                store.remove(q)
                removed += 1
    return removed
