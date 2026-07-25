"""Unit tests for Manchester rendering of "Used in axioms" (term usage).

`_sparql_usage` / `_sparql_class_usage` attach a `manchester` token list to each
usage row so the frontend can render the whole axiom in Manchester syntax with
clickable IRIs. These build a minimal in-memory store and assert the tokens.
"""
import pyoxigraph as ox

from ontoexplorer.api.ontologies import _sparql_usage, _sparql_class_usage

_GRAPH = ox.NamedNode("urn:test:graph")
_OWL = "http://www.w3.org/2002/07/owl#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def _store(*quads: tuple) -> ox.Store:
    store = ox.Store()
    store.add_graph(_GRAPH)
    for s, p, o in quads:
        store.add(ox.Quad(s, p, o, _GRAPH))
    return store


def _n(iri: str) -> ox.NamedNode:
    return ox.NamedNode(iri)


def _local(iri: str) -> str:
    frag = iri.rstrip("/")
    return frag.split("#")[-1] if "#" in frag else frag.split("/")[-1]


def _mos_text(tokens) -> str:
    return "".join(t["v"] if t["t"] == "text" else t["label"] for t in tokens)


def _clickable(tokens) -> dict:
    return {t["iri"]: t["in_ontology"] for t in tokens if t["t"] == "iri"}


def test_property_usage_renders_whole_restriction_axiom():
    man = _n("http://ex.org/Man")
    has_father = _n("http://ex.org/hasFather")
    r = ox.BlankNode()
    store = _store(
        (man, _n(_RDF + "type"), _n(_OWL + "Class")),
        (has_father, _n(_RDF + "type"), _n(_OWL + "ObjectProperty")),
        (man, _n(_RDFS + "subClassOf"), r),
        (r, _n(_OWL + "onProperty"), has_father),
        (r, _n(_OWL + "someValuesFrom"), man),
    )
    q = f"""
        PREFIX owl: <{_OWL}>
        PREFIX rdfs: <{_RDFS}>
        SELECT ?class ?relation ?restrictType ?filler ?r WHERE {{
            GRAPH <{_GRAPH.value}> {{
                {{ ?class rdfs:subClassOf ?r . BIND("subClassOf" AS ?relation) }}
                UNION {{ ?class owl:equivalentClass ?r . BIND("equivalentClass" AS ?relation) }}
                ?r owl:onProperty <{has_father.value}> .
                FILTER(isIRI(?class))
                {{ ?r owl:someValuesFrom ?filler . BIND("some" AS ?restrictType) }}
            }}
        }}
    """
    rows = _sparql_usage(store, q, _local, _GRAPH.value)
    assert len(rows) == 1
    toks = rows[0]["manchester"]
    assert _mos_text(toks) == "Man SubClassOf hasFather some Man"
    # Declared class + property are clickable (subjects of a triple in the graph).
    marks = _clickable(toks)
    assert marks["http://ex.org/Man"] is True
    assert marks["http://ex.org/hasFather"] is True


def test_property_usage_marks_external_filler_not_clickable():
    # A filler IRI that appears ONLY as an object (never described) is not a
    # term page, so it must not be clickable.
    cls = _n("http://ex.org/A")
    prop = _n("http://ex.org/p")
    external = _n("http://external.example/Thing")
    r = ox.BlankNode()
    store = _store(
        (cls, _n(_RDF + "type"), _n(_OWL + "Class")),
        (prop, _n(_RDF + "type"), _n(_OWL + "ObjectProperty")),
        (cls, _n(_RDFS + "subClassOf"), r),
        (r, _n(_OWL + "onProperty"), prop),
        (r, _n(_OWL + "allValuesFrom"), external),
    )
    q = f"""
        PREFIX owl: <{_OWL}>
        PREFIX rdfs: <{_RDFS}>
        SELECT ?class ?relation ?restrictType ?filler ?r WHERE {{
            GRAPH <{_GRAPH.value}> {{
                {{ ?class rdfs:subClassOf ?r . BIND("subClassOf" AS ?relation) }}
                ?r owl:onProperty <{prop.value}> .
                FILTER(isIRI(?class))
                {{ ?r owl:allValuesFrom ?filler . BIND("only" AS ?restrictType) }}
            }}
        }}
    """
    rows = _sparql_usage(store, q, _local, _GRAPH.value)
    toks = rows[0]["manchester"]
    assert _mos_text(toks) == "A SubClassOf p only Thing"
    assert _clickable(toks)["http://external.example/Thing"] is False


def test_class_usage_disjoint_renders_manchester():
    man = _n("http://ex.org/Man")
    woman = _n("http://ex.org/Woman")
    store = _store(
        (man, _n(_RDF + "type"), _n(_OWL + "Class")),
        (woman, _n(_RDF + "type"), _n(_OWL + "Class")),
        (woman, _n(_OWL + "disjointWith"), man),
    )
    cu_q = f"""
        PREFIX owl: <{_OWL}>
        PREFIX rdfs: <{_RDFS}>
        SELECT DISTINCT ?class ?relation ?prop ?restrictType ?r WHERE {{
            GRAPH <{_GRAPH.value}> {{
                {{ ?r owl:someValuesFrom <{man.value}> . ?r owl:onProperty ?prop . BIND("some" AS ?restrictType) }}
                {{ ?class rdfs:subClassOf ?r . FILTER(isIRI(?class)) BIND("subClassOf" AS ?relation) }}
            }}
        }}
    """
    disj_q = f"""
        PREFIX owl: <{_OWL}>
        SELECT ?class WHERE {{
            GRAPH <{_GRAPH.value}> {{ ?class owl:disjointWith <{man.value}> . FILTER(isIRI(?class)) }}
        }}
    """
    rows = _sparql_class_usage(store, cu_q, disj_q, _local, {}, man.value, _GRAPH.value)
    assert len(rows) == 1
    assert rows[0]["relation"] == "disjointWith"
    assert _mos_text(rows[0]["manchester"]) == "Woman DisjointWith Man"


def test_class_usage_as_filler_renders_manchester():
    # The term (Man) is the filler of a restriction on Parent: Parent SubClassOf
    # hasChild some Man → shows on Man's "used in axioms".
    man = _n("http://ex.org/Man")
    parent = _n("http://ex.org/Parent")
    has_child = _n("http://ex.org/hasChild")
    r = ox.BlankNode()
    store = _store(
        (man, _n(_RDF + "type"), _n(_OWL + "Class")),
        (parent, _n(_RDF + "type"), _n(_OWL + "Class")),
        (has_child, _n(_RDF + "type"), _n(_OWL + "ObjectProperty")),
        (parent, _n(_RDFS + "subClassOf"), r),
        (r, _n(_OWL + "onProperty"), has_child),
        (r, _n(_OWL + "someValuesFrom"), man),
    )
    cu_q = f"""
        PREFIX owl: <{_OWL}>
        PREFIX rdfs: <{_RDFS}>
        SELECT DISTINCT ?class ?relation ?prop ?restrictType ?r WHERE {{
            GRAPH <{_GRAPH.value}> {{
                {{ ?r owl:someValuesFrom <{man.value}> . ?r owl:onProperty ?prop . BIND("some" AS ?restrictType) }}
                {{ ?class rdfs:subClassOf ?r . FILTER(isIRI(?class)) BIND("subClassOf" AS ?relation) }}
            }}
        }}
    """
    disj_q = f"""
        PREFIX owl: <{_OWL}>
        SELECT ?class WHERE {{ GRAPH <{_GRAPH.value}> {{ ?class owl:disjointWith <{man.value}> . FILTER(isIRI(?class)) }} }}
    """
    rows = _sparql_class_usage(store, cu_q, disj_q, _local, {}, man.value, _GRAPH.value)
    assert len(rows) == 1
    assert _mos_text(rows[0]["manchester"]) == "Parent SubClassOf hasChild some Man"
