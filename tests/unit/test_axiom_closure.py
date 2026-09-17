"""Unit tests for the blank-node axiom closure helpers in
ontoexplorer.api.ontologies.

The HTTP store proxy cannot resolve a stored blank node by label, so term-detail
class-expression walks run against a per-term CONSTRUCT closure instead. These
tests lock in the two query-shape invariants that were subtle to get right:

  * seeds are INLINED, never passed via ``VALUES`` — a VALUES-bound term is not
    pushed into the property-path evaluation, turning ``?root (struct)* ?s`` into
    a whole-graph path scan that times out (0.02 s vs 30 s on GO);
  * ``rdfs:subClassOf`` / ``owl:equivalentClass`` are NEVER inside the
    transitively-repeated struct path — repeating them would climb the class
    hierarchy and pull the whole ontology into the closure.

They also check the embedded-store passthrough (workers keep a native store that
walks blank nodes directly, so no closure is materialised there).
"""
import pyoxigraph as ox

from ontoexplorer.api.ontologies import (
    _CLOSURE_STRUCT_PP,
    _axiom_closure_construct,
    _bnode_walk_store,
    _build_class_expr,
)

_OWL = "http://www.w3.org/2002/07/owl#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def test_struct_path_excludes_hierarchy_predicates():
    # subClassOf / equivalentClass must not sit inside the `(…)*` struct path,
    # or the closure climbs the class hierarchy and never terminates in time.
    assert _RDFS + "subClassOf" not in _CLOSURE_STRUCT_PP
    assert _OWL + "equivalentClass" not in _CLOSURE_STRUCT_PP
    # but the axiom-internal predicates it walks are present.
    assert _OWL + "someValuesFrom" in _CLOSURE_STRUCT_PP
    assert _OWL + "complementOf" in _CLOSURE_STRUCT_PP


def test_seeds_are_inlined_not_values_bound():
    seed = "https://w3id.org/sulo/Object"
    q = _axiom_closure_construct("urn:g", [seed])
    assert "VALUES ?seed" not in q          # no VALUES-bound seed (the timeout trap)
    assert f"<{seed}>" in q                  # seed inlined into the pattern
    assert "GRAPH <urn:g>" in q
    # entry hops in both directions are present.
    assert f"<{_RDFS}subClassOf>" in q


def test_seed_count_is_capped():
    from ontoexplorer.api.ontologies import _CLOSURE_MAX_SEEDS

    seeds = [f"urn:c:{i}" for i in range(_CLOSURE_MAX_SEEDS + 25)]
    q = _axiom_closure_construct("urn:g", seeds)
    assert "<urn:c:0>" in q                                  # first seed kept
    assert f"<urn:c:{_CLOSURE_MAX_SEEDS - 1}>" in q          # last seed at the cap kept
    assert f"<urn:c:{_CLOSURE_MAX_SEEDS}>" not in q          # first seed past the cap dropped
    assert f"<urn:c:{_CLOSURE_MAX_SEEDS + 20}>" not in q


def test_embedded_store_passthrough_walks_complement_natively():
    # A native (non-proxy) store is returned unchanged and walks blank nodes
    # directly — the complementOf case the proxy used to flatten and duplicate.
    g = ox.NamedNode("urn:g")
    C = ox.NamedNode("urn:C")
    restr = ox.BlankNode()
    comp = ox.BlankNode()
    store = ox.Store()
    store.add_graph(g)
    for s, p, o in [
        (C, ox.NamedNode(_RDFS + "subClassOf"), comp),
        (comp, ox.NamedNode(_OWL + "complementOf"), restr),
        (restr, ox.NamedNode(_RDFS + "type"), ox.NamedNode(_OWL + "Restriction")),
        (restr, ox.NamedNode(_OWL + "onProperty"), ox.NamedNode("urn:hasPart")),
        (restr, ox.NamedNode(_OWL + "someValuesFrom"), ox.NamedNode("urn:Process")),
    ]:
        store.add(ox.Quad(s, p, o, g))

    walk = _bnode_walk_store(store, "urn:g", ["urn:C"])
    assert walk is store  # embedded store returned unchanged

    def _label(iri):
        return iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1]

    exprs = [
        _build_class_expr(walk, g, q.object, _label)
        for q in walk.quads_for_pattern(C, ox.NamedNode(_RDFS + "subClassOf"), None, g)
        if isinstance(q.object, ox.BlankNode)
    ]
    assert exprs == [
        {
            "type": "not",
            "operand": {
                "type": "some",
                "property": {"type": "named", "iri": "urn:hasPart", "label": "hasPart"},
                "filler": {"type": "named", "iri": "urn:Process", "label": "Process"},
            },
        }
    ]
