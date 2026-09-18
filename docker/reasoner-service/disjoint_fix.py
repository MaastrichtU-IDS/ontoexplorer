"""Work around horned-owl's RDF reader dropping ``owl:AllDisjointClasses``.

horned-owl's RDF/XML reader silently drops ``owl:AllDisjointClasses`` axioms (the
``owl:members`` n-ary form). Binary ``owl:disjointWith``, ``SubClassOf`` and
``EquivalentClasses`` (with cardinality / union / allValuesFrom) all reconstruct
correctly — only the n-ary disjointness vanishes. For an ontology that states
class disjointness via ``AllDisjointClasses`` (nearly every OBO ontology) the
reasoner then cannot prove the members are pairwise distinct, so defined-class
subsumptions that depend on it (cardinality counting, covering axioms) are missed
— e.g. ``TraditionalFourCheesePizza`` is not classified under ``FourCheesePizza``.

Fix: read the ``AllDisjointClasses`` groups straight from the RDF (pyoxigraph
keeps them), then reinstate them as n-ary ``DisjointClasses`` axioms in whatever
syntax the reasoner is fed — OWL functional syntax for rustdl (its RDF/XML reader
is even lossier and drops injected pairwise ``disjointWith`` too), OWL/XML for the
Konclude / km subprocess backends. The reasoners parse both faithfully.

The proper long-term fix is upstream in horned-owl's RDF reader; this keeps the
service correct in the meantime.
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def all_disjoint_class_groups(store) -> list[list[str]]:
    """Every ``owl:AllDisjointClasses`` group as a list of named-class IRIs.

    Anonymous (blank-node) members are skipped — disjointness over anonymous
    class expressions is rare and out of scope for this reader work-around. A
    group with fewer than two named members is dropped (nothing to assert).
    """
    import pyoxigraph

    rdf_type = pyoxigraph.NamedNode(_RDF + "type")
    adc = pyoxigraph.NamedNode(_OWL + "AllDisjointClasses")
    members_pred = pyoxigraph.NamedNode(_OWL + "members")
    rdf_first = pyoxigraph.NamedNode(_RDF + "first")
    rdf_rest = pyoxigraph.NamedNode(_RDF + "rest")
    nil = _RDF + "nil"

    def rdf_list(head) -> list[str]:
        out: list[str] = []
        node = head
        seen: set[str] = set()
        while node is not None and getattr(node, "value", None) != nil:
            key = getattr(node, "value", None)
            if key is None or key in seen:  # cycle / malformed guard
                break
            seen.add(key)
            firsts = [q.object for q in store.quads_for_pattern(node, rdf_first, None, None)]
            if firsts and isinstance(firsts[0], pyoxigraph.NamedNode):
                out.append(firsts[0].value)
            rests = [q.object for q in store.quads_for_pattern(node, rdf_rest, None, None)]
            node = rests[0] if rests else None
        return out

    groups: list[list[str]] = []
    for q in store.quads_for_pattern(None, rdf_type, adc, None):
        for hq in store.quads_for_pattern(q.subject, members_pred, None, None):
            members = rdf_list(hq.object)
            if len(members) >= 2:
                groups.append(members)
    return groups


def has_all_disjoint_classes(store) -> bool:
    """Whether the store contains any ``owl:AllDisjointClasses`` axiom."""
    import pyoxigraph

    rdf_type = pyoxigraph.NamedNode(_RDF + "type")
    adc = pyoxigraph.NamedNode(_OWL + "AllDisjointClasses")
    for _ in store.quads_for_pattern(None, rdf_type, adc, None):
        return True
    return False


# ── syntax injection (pure string helpers, no RDF deps — unit-tested directly) ──

def inject_ofn_disjointness(ofn: str, groups: list[list[str]]) -> str:
    """Append an n-ary ``DisjointClasses(...)`` per group to an OWL functional
    ontology, and drop ``Import(...)`` statements (rustdl's OFN parser rejects
    unresolved offline imports)."""
    lines = [ln for ln in ofn.splitlines() if not ln.lstrip().startswith("Import(")]
    axioms = [
        "    DisjointClasses(" + " ".join(f"<{iri}>" for iri in group) + ")"
        for group in groups
    ]
    if not axioms:
        return "\n".join(lines) + "\n"
    # Insert before the final ``)`` that closes ``Ontology(...)``.
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == ")":
            lines[i:i] = axioms
            return "\n".join(lines) + "\n"
    # No standalone close found (unexpected): append defensively.
    return "\n".join(lines + axioms) + "\n)\n"


def inject_owx_disjointness(owx: str, groups: list[list[str]]) -> str:
    """Insert an OWL/XML ``<DisjointClasses>`` element per group before the
    closing ``</Ontology>`` tag."""
    if not groups:
        return owx
    from xml.sax.saxutils import quoteattr

    blocks = "".join(
        "<DisjointClasses>"
        + "".join(f"<Class IRI={quoteattr(iri)}/>" for iri in group)
        + "</DisjointClasses>"
        for group in groups
    )
    idx = owx.rfind("</Ontology>")
    if idx == -1:
        return owx  # not the shape we expected; leave untouched
    return owx[:idx] + blocks + owx[idx:]


# ── convenience builders (need pyoxigraph + pyhornedowl) ───────────────────────

def functional_with_disjointness(rdfxml, store) -> str:
    """OWL functional syntax for ``store``, with dropped ``AllDisjointClasses``
    reinstated. ``rdfxml`` is the RDF/XML serialization of the same graph."""
    import pyhornedowl

    src = rdfxml if isinstance(rdfxml, str) else bytes(rdfxml).decode("utf-8", "replace")
    ofn = pyhornedowl.open_ontology_from_string(src, "rdf").save_to_string("ofn")
    return inject_ofn_disjointness(ofn, all_disjoint_class_groups(store))


def owl_xml_with_disjointness(owx: str, store) -> str:
    """OWL/XML ``owx`` with dropped ``AllDisjointClasses`` reinstated."""
    return inject_owx_disjointness(owx, all_disjoint_class_groups(store))
