"""Work around horned-owl aborting on a property axiom that puns property kinds.

The reasoner (rustdl, PyO3/horned-owl) classifies via horned-owl's strict RDF reader.
OWL 2 DL forbids a property from being more than one kind (object / data / annotation),
so when an ``owl:equivalentProperty``, ``owl:propertyDisjointWith`` or
``rdfs:subPropertyOf`` axiom links two properties horned-owl can't reconcile to one
kind, the reader ABORTS the whole parse::

    Validity Error: Types of two properties do not match: IRI(a), IRI(b)

This is extremely common in cross-vocabulary alignments — e.g. ``dct:creator``
(an annotation / bare ``rdf:Property``) stated ``owl:equivalentProperty`` ``foaf:maker``
(an object property), or ``vcard:org`` (object) vs ``vcard:organization-name`` (data).
It also fires on malformed axioms that link a property to something that isn't a usable
property at all: a bare ``rdf:Property`` or ``owl:DeprecatedProperty`` (no kind), or a
node typed as a class / individual / SKOS concept (e.g. ``ldp:PreferEmptyContainer``
``owl:equivalentProperty`` another ``owl:Individual``; a property ``equivalentProperty``
a ``skos:Concept``). These ontologies INDEX fine; only the strict reasoner path chokes.
Switching parser does NOT help (pyhornedowl shares horned-owl's core). Dropping the
offending axiom restores the parse — the same store-level sanitization as
ontology_type_fix / equiv_class_fix.

What's dropped, and why it's safe for CLASSIFICATION:

* ``owl:equivalentProperty`` / ``owl:propertyDisjointWith`` with (a) an explicit two-OWL-
  kinds mismatch, or (b) an UNUSABLE operand — one with no real object/data/annotation
  kind that is a bare ``rdf:Property`` / ``owl:DeprecatedProperty``, or is typed only as a
  non-property (class / individual / SKOS concept): dropped. A mismatched or
  non-property-linked equivalence/disjointness is DL-illegal and carries no class-
  subsumption signal (property equivalence/disjointness acts on property extensions, and a
  link to a non-property / undeclared term is meaningless). Lossless for the class hierarchy.
* ``rdfs:subPropertyOf``: dropped ONLY on an explicit two-different-OWL-kinds mismatch
  (e.g. ObjectProperty ⊑ DataProperty), which is DL-illegal — its "role edge" is meaningless.
  The unusable-operand rule is deliberately NOT applied to subPropertyOf: a bare property
  that horned-owl would promote to an object property by usage carries a real role edge,
  and role hierarchy *does* affect class subsumption (via ∃R.D / property chains), so
  dropping it could silently under-classify. We accept recovering fewer ontologies over that.

A node with a real object/data kind is NEVER treated as unusable even if also (mis)typed
as a class — it is a punned entity horned-owl can still read as a property, so its axioms
are kept. A FULLY UNTYPED operand is also left alone: its kind is only knowable from usage
or an external vocabulary, so the mismatch is not locally decidable (left for an upstream
horned-owl fix, which has the kind info this shim lacks). A property punned as two kinds
on ONE IRI makes kind() pick the first, so a same-other-kind axiom survives and that
ontology still aborts (a false-negative, not a correctness bug).
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

_EQUIVALENT_PROPERTY = _OWL + "equivalentProperty"
_PROPERTY_DISJOINT_WITH = _OWL + "propertyDisjointWith"
_SUB_PROPERTY_OF = _RDFS + "subPropertyOf"
_OWL_KINDS = ("ObjectProperty", "DatatypeProperty", "AnnotationProperty")

# Types that make a node a NON-property: a property axiom linking one of these is
# malformed (a property equated/disjoint with a class, individual, or SKOS concept).
_NON_PROPERTY_TYPES = frozenset((
    _OWL + "Class", _RDFS + "Class", _OWL + "NamedIndividual",
    _OWL + "Individual", "http://www.w3.org/2004/02/skos/core#Concept",
))
# Marker-only typings that carry no usable object/data kind.
_MARKER_TYPES = frozenset((_RDF + "Property", _OWL + "DeprecatedProperty"))


def drop_mismatched_property_axioms(store) -> int:
    """Drop ``owl:equivalentProperty`` / ``owl:propertyDisjointWith`` /
    ``rdfs:subPropertyOf`` triples whose two named operands horned-owl can't reconcile
    to one property kind (see the module docstring for the exact, classification-safe
    rule per predicate). Mutates ``store`` in place; returns the number of triples
    removed. Safe to call unconditionally.
    """
    import pyoxigraph

    rdf_type = pyoxigraph.NamedNode(_RDF + "type")

    def types_of(node) -> set[str]:
        return {
            q.object.value
            for q in store.quads_for_pattern(node, rdf_type, None, None)
            if isinstance(q.object, pyoxigraph.NamedNode)
        }

    def kind(types: set[str]) -> str | None:
        for k in _OWL_KINDS:
            if _OWL + k in types:
                return k
        return None

    def unusable(types: set[str]) -> bool:
        # Can this node serve as a usable OWL property of a determinable kind?
        if kind(types) is not None:
            return False                       # has a real object/data/annotation kind
        if types & _NON_PROPERTY_TYPES:
            return True                        # only a class / individual / concept
        if types & _MARKER_TYPES:
            return True                        # marker-only: bare rdf:Property / DeprecatedProperty
        return False                           # fully untyped -> not locally decidable, leave alone

    removed = 0
    # equivalentProperty / propertyDisjointWith are n-ary symmetric property axioms with
    # little class-subsumption value, so they are dropped on an explicit kind clash OR an
    # unusable operand. subPropertyOf is kept conservative (its role edge can affect
    # subsumption via ∃R.D / chains): dropped ONLY on an explicit two-OWL-kinds mismatch,
    # never for a merely bare/unusable operand.
    for pred, drop_unusable in ((_EQUIVALENT_PROPERTY, True),
                                (_PROPERTY_DISJOINT_WITH, True),
                                (_SUB_PROPERTY_OF, False)):
        for q in list(store.quads_for_pattern(None, pyoxigraph.NamedNode(pred), None, None)):
            if not (isinstance(q.subject, pyoxigraph.NamedNode)
                    and isinstance(q.object, pyoxigraph.NamedNode)):
                continue
            ts, to = types_of(q.subject), types_of(q.object)
            ka, kb = kind(ts), kind(to)
            explicit_mismatch = ka in _OWL_KINDS and kb in _OWL_KINDS and ka != kb
            unusable_operand = drop_unusable and (unusable(ts) or unusable(to))
            if explicit_mismatch or unusable_operand:
                store.remove(q)
                removed += 1
    return removed
