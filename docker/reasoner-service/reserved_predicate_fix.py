"""Drop triples whose PREDICATE is an RDF/XML reserved syntax term.

rustdl (PyO3/horned-owl) classifies by first serialising the asserted graph to
RDF/XML (horned-owl's complete reader is the RDF/XML one), then parsing that.
RDF/XML cannot represent a triple whose predicate is one of its own reserved
syntax terms (rdf:about, rdf:resource, rdf:parseType, …): those are XML
attributes/elements in the RDF/XML grammar, not property IRIs. So pyoxigraph's
serializer ABORTS the whole classification before reasoning even starts::

    OSError: RDF/XML reserved syntax term is not allowed as a predicate

This happens on published content that leaked an RDF/XML syntax attribute into
the graph as data — e.g. the MEX vocabularies (mex-core, mex-perf) carry a stray
``<…/mex-perf> rdf:about "…/mex-doc-perf#"`` on the ontology node (the object is
even a plain literal). Such a triple carries no OWL/RDFS meaning — a reserved
syntax term is never a usable predicate — so dropping it before the serialize is
lossless for classification and lets the ontology reason. Same store-level
sanitisation as ontology_type_fix / equiv_class_fix / property_pun_fix.

This is NOT a horned-owl issue: horned-owl never sees the triple; the abort is in
the RDF/XML writer, which correctly refuses to emit a graph RDF/XML cannot
represent. The deeper fix — feed horned-owl N-Triples/Turtle directly and skip
the lossy RDF/XML round-trip (which also drops owl:AllDisjointClasses) — is a
rustdl change tracked separately.
"""
from __future__ import annotations

_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

# RDF/XML syntax-reserved terms: the coreSyntaxTerms, the two syntax attributes
# (rdf:li, rdf:datatype) and the retired oldTerms. None can be a property IRI, so
# none is serialisable as a predicate in RDF/XML. Container-membership properties
# (rdf:_1, rdf:_2, …) are NOT reserved and are deliberately left untouched, as is
# rdf:type (a normal, serialisable predicate).
_RESERVED = frozenset(_RDF + t for t in (
    "RDF", "Description", "ID", "about", "parseType", "resource", "nodeID",
    "datatype", "li", "aboutEach", "aboutEachPrefix", "bagID",
))


def drop_reserved_syntax_predicate_triples(store) -> int:
    """Drop every triple whose predicate is an RDF/XML reserved syntax term
    (see the module docstring). Mutates ``store`` in place; returns the number of
    triples removed. Safe to call unconditionally."""
    import pyoxigraph

    removed = 0
    for pred in _RESERVED:
        for q in list(store.quads_for_pattern(None, pyoxigraph.NamedNode(pred), None, None)):
            store.remove(q)
            removed += 1
    return removed
