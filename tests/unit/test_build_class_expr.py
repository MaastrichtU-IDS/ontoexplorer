"""Unit tests for ontoexplorer.api.ontologies._build_class_expr.

Builds a minimal in-memory pyoxigraph store containing an OWL blank-node class
expression and checks the recursive AST it produces — in particular the
datatype-restriction and union cases that show up as fillers in the term
"Used in axioms" view.
"""
import pyoxigraph as ox

from ontoexplorer.api.ontologies import _build_class_expr

_GRAPH = ox.NamedNode("urn:test:graph")
_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_XSD = "http://www.w3.org/2001/XMLSchema#"


def _store(*quads: tuple) -> ox.Store:
    store = ox.Store()
    store.add_graph(_GRAPH)
    for s, p, o in quads:
        store.add(ox.Quad(s, p, o, _GRAPH))
    return store


def _label(iri: str) -> str:
    return iri.split("#")[-1] if "#" in iri else iri.rstrip("/").split("/")[-1]


def test_datatype_restriction_renders_recursively():
    """xsd:decimal[>= 0] as a blank-node datatype restriction -> structured AST,
    not {'type': 'unknown'}."""
    dt = ox.BlankNode("dt")
    lst = ox.BlankNode("lst")
    facet = ox.BlankNode("facet")
    store = _store(
        (dt, ox.NamedNode(_RDF + "type"), ox.NamedNode(_RDFS + "Datatype")),
        (dt, ox.NamedNode(_OWL + "onDatatype"), ox.NamedNode(_XSD + "decimal")),
        (dt, ox.NamedNode(_OWL + "withRestrictions"), lst),
        (lst, ox.NamedNode(_RDF + "first"), facet),
        (lst, ox.NamedNode(_RDF + "rest"), ox.NamedNode(_RDF + "nil")),
        (facet, ox.NamedNode(_XSD + "minInclusive"),
         ox.Literal("0", datatype=ox.NamedNode(_XSD + "decimal"))),
    )

    ast = _build_class_expr(store, _GRAPH, dt, _label)

    assert ast["type"] == "datatype_restriction"
    assert ast["datatype"] == {"type": "named", "iri": _XSD + "decimal", "label": "decimal"}
    assert ast["facets"] == [{"facet": "minInclusive", "value": "0"}]


def test_union_of_datatypes_renders_recursively():
    """unionOf (dateTime, dateTimeStamp) -> {'type': 'or', operands: [...]}."""
    node = ox.BlankNode("u")
    lst1 = ox.BlankNode("l1")
    lst2 = ox.BlankNode("l2")
    dt1 = ox.NamedNode(_XSD + "dateTime")
    dt2 = ox.NamedNode(_XSD + "dateTimeStamp")
    store = _store(
        (node, ox.NamedNode(_OWL + "unionOf"), lst1),
        (lst1, ox.NamedNode(_RDF + "first"), dt1),
        (lst1, ox.NamedNode(_RDF + "rest"), lst2),
        (lst2, ox.NamedNode(_RDF + "first"), dt2),
        (lst2, ox.NamedNode(_RDF + "rest"), ox.NamedNode(_RDF + "nil")),
    )

    ast = _build_class_expr(store, _GRAPH, node, _label)

    assert ast["type"] == "or"
    assert [op["iri"] for op in ast["operands"]] == [dt1.value, dt2.value]
