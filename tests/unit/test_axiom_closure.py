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
    _adc_map_via_sparql,
    _axiom_closure_construct,
    _bnode_walk_store,
    _build_class_expr,
    _sparql_usage,
)

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
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


def _label(iri):
    return iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1]


def test_adc_map_via_sparql_walks_members_list():
    # owl:AllDisjointClasses over an rdf:List, resolved with a property path
    # (owl:members/rdf:rest*/rdf:first) instead of a blank-node deref.
    g = ox.NamedNode("urn:g")
    adc = ox.BlankNode()
    l0, l1, l2 = ox.BlankNode(), ox.BlankNode(), ox.BlankNode()
    A, B, C = ox.NamedNode("urn:A"), ox.NamedNode("urn:B"), ox.NamedNode("urn:C")
    FIRST = ox.NamedNode(_RDF + "first")
    REST = ox.NamedNode(_RDF + "rest")
    NIL = ox.NamedNode(_RDF + "nil")
    store = ox.Store()
    store.add_graph(g)
    for s, p, o in [
        (adc, ox.NamedNode(_RDF + "type"), ox.NamedNode(_OWL + "AllDisjointClasses")),
        (adc, ox.NamedNode(_OWL + "members"), l0),
        (l0, FIRST, A), (l0, REST, l1),
        (l1, FIRST, B), (l1, REST, l2),
        (l2, FIRST, C), (l2, REST, NIL),
    ]:
        store.add(ox.Quad(s, p, o, g))

    adc_map = _adc_map_via_sparql(store, "urn:g")
    assert sorted(adc_map["urn:A"]) == ["urn:B", "urn:C"]
    assert sorted(adc_map["urn:B"]) == ["urn:A", "urn:C"]
    assert sorted(adc_map["urn:C"]) == ["urn:A", "urn:B"]


def test_sparql_usage_renders_restriction_manchester():
    # `C subClassOf (P some D)` should render `C SubClassOf P some D` as Manchester
    # tokens with the filler as a resolvable IRI. Embedded store, so the walk is
    # native (the closure path is exercised end-to-end against a live server).
    g = ox.NamedNode("urn:g")
    base = "http://example.org/"
    C, P, D = ox.NamedNode(base + "C"), ox.NamedNode(base + "P"), ox.NamedNode(base + "D")
    restr = ox.BlankNode()
    store = ox.Store()
    store.add_graph(g)
    for s, p, o in [
        (C, ox.NamedNode(_RDFS + "subClassOf"), restr),
        (restr, ox.NamedNode(_RDF + "type"), ox.NamedNode(_OWL + "Restriction")),
        (restr, ox.NamedNode(_OWL + "onProperty"), P),
        (restr, ox.NamedNode(_OWL + "someValuesFrom"), D),
        (C, ox.NamedNode(_RDFS + "label"), ox.Literal("C")),
        (D, ox.NamedNode(_RDFS + "label"), ox.Literal("D")),
    ]:
        store.add(ox.Quad(s, p, o, g))

    base_q = f"""
        PREFIX owl:  <{_OWL}>
        PREFIX rdfs: <{_RDFS}>
        SELECT ?class ?relation ?restrictType ?filler ?r WHERE {{ GRAPH <urn:g> {{
            ?class rdfs:subClassOf ?r . BIND("subClassOf" AS ?relation)
            ?r owl:onProperty <{base}P> . FILTER(isIRI(?class))
            ?r owl:someValuesFrom ?filler . BIND("some" AS ?restrictType)
        }} }}
        ORDER BY ?class
    """
    rows = _sparql_usage(store, "urn:g", base_q, 0, 10, _label, base + "P")
    assert len(rows) == 1
    row = rows[0]
    assert row["class_iri"] == base + "C"
    assert row["restriction"] == "some"
    assert row["filler_iri"] == base + "D"
    # Manchester carries the class, the property and the filler as IRI tokens.
    iri_tokens = [t for t in row["manchester"] if t.get("t") == "iri"]
    assert [t["iri"] for t in iri_tokens] == [base + "C", base + "P", base + "D"]
    text = "".join(t.get("v", "") for t in row["manchester"] if t.get("t") == "text")
    assert "SubClassOf" in text and "some" in text
