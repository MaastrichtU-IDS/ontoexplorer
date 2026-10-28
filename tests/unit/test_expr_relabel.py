"""Expression-internal label overlay (#364 follow-on: half-labelled axioms).

A class/usage axiom is rendered in two parts: the leading class/property comes
from `label_fn` (entity_index), but the restriction body is rendered against the
blank-node closure store, which carries no named-IRI `rdfs:label`. So a
restriction's `onProperty` and filler fell back to the raw local name, and an
axiom showed half-labelled:

    has action SubClassOf CLCO_0002502 some CLCO_0000108     (bug)
    has action SubClassOf has subject some clinician         (fixed)

`_collect_expr_iris` + `_apply_expr_labels` close the gap as a post-pass over the
already-built structures, overlaying the entity_index label wherever one exists.
These tests drive the REAL renderers to produce the fragment output, then prove
the overlay repairs it.
"""
import pyoxigraph as ox

from ontoexplorer.api.ontologies import (
    _apply_expr_labels,
    _build_class_expr,
    _collect_expr_iris,
    _sparql_class_usage,
)

_GRAPH = ox.NamedNode("urn:test:graph")
_OWL = "http://www.w3.org/2002/07/owl#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def _store(*quads):
    s = ox.Store()
    s.add_graph(_GRAPH)
    for subj, p, o in quads:
        s.add(ox.Quad(subj, p, o, _GRAPH))
    return s


def _n(iri):
    return ox.NamedNode(iri)


def _local(iri):
    frag = iri.rstrip("/")
    return frag.split("#")[-1] if "#" in frag else frag.split("/")[-1]


def _mos_text(tokens):
    return "".join(t["v"] if t["t"] == "text" else t["label"] for t in tokens)


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_collect_gathers_named_ast_nodes_and_iri_tokens_nested():
    ast = {"type": "some",
           "property": {"type": "named", "iri": "urn:p", "label": "p"},
           "filler": {"type": "or", "operands": [
               {"type": "named", "iri": "urn:a", "label": "a"},
               {"type": "named", "iri": "urn:b", "label": "b"},
           ]}}
    tokens = [{"t": "iri", "iri": "urn:c", "label": "c"},
              {"t": "text", "v": " some "},
              {"t": "iri", "iri": "urn:d", "label": "d"}]
    acc = set()
    _collect_expr_iris([ast, tokens], acc)
    assert acc == {"urn:p", "urn:a", "urn:b", "urn:c", "urn:d"}


def test_collect_and_apply_handle_sibling_iri_label_pairs():
    # The domain-of / usage table row shape: "<x>_iri" + "<x>_label" plain fields
    # (not expression nodes). The overlay must relabel these too.
    rows = [
        {"prop_iri": "urn:p", "prop_label": "p", "range_iri": "urn:r", "range_label": "r"},
        {"class_iri": "urn:c", "class_label": "c", "filler_iri": "urn:f", "filler_label": "f"},
    ]
    acc = set()
    _collect_expr_iris(rows, acc)
    assert acc == {"urn:p", "urn:r", "urn:c", "urn:f"}

    _apply_expr_labels(rows, {"urn:p": "has part", "urn:f": "clinician"})
    assert rows[0]["prop_label"] == "has part"
    assert rows[0]["range_label"] == "r"          # urn:r absent -> untouched
    assert rows[1]["filler_label"] == "clinician"
    assert rows[1]["class_label"] == "c"          # urn:c absent -> untouched


def test_apply_overlays_only_named_slots_and_only_known_iris():
    ast = {"type": "some",
           "property": {"type": "named", "iri": "urn:p", "label": "urn:p-frag"},
           "filler": {"type": "named", "iri": "urn:x", "label": "x-frag"}}
    tokens = [{"t": "iri", "iri": "urn:p", "label": "urn:p-frag"},
              {"t": "text", "v": " some "}]
    labels = {"urn:p": "has subject"}   # urn:x deliberately absent
    _apply_expr_labels([ast, tokens], labels)
    assert ast["property"]["label"] == "has subject"
    assert ast["filler"]["label"] == "x-frag"       # unknown IRI untouched
    assert tokens[0]["label"] == "has subject"
    assert tokens[1] == {"t": "text", "v": " some "}  # text token untouched


# ── against the real renderers ───────────────────────────────────────────────

def test_class_usage_restriction_body_is_relabelled_from_entity_index():
    # Parent SubClassOf (hasChild some Man). Labels live ONLY in entity_index
    # (not as rdfs:label in the graph), exactly like the production CLCO case.
    man = _n("http://ex/Man")
    parent = _n("http://ex/Parent")
    has_child = _n("http://ex/hasChild")
    store = _store(
        (man, _n(_RDF + "type"), _n(_OWL + "Class")),
        (parent, _n(_RDF + "type"), _n(_OWL + "Class")),
        (has_child, _n(_RDF + "type"), _n(_OWL + "ObjectProperty")),
        (parent, _n(_RDFS + "subClassOf"), ox.BlankNode("r")),
    )
    # (blank node structure added separately so the BlankNode id is stable)
    r = ox.BlankNode("r")
    store.add(ox.Quad(r, _n(_OWL + "onProperty"), has_child, _GRAPH))
    store.add(ox.Quad(r, _n(_OWL + "someValuesFrom"), man, _GRAPH))

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
    disj_q = f"""PREFIX owl: <{_OWL}>
        SELECT ?class WHERE {{ GRAPH <{_GRAPH.value}> {{ ?class owl:disjointWith <{man.value}> }} }}"""
    # The leading class uses label_fn; the body uses the store -> local names.
    rows = _sparql_class_usage(store, _GRAPH.value, cu_q, 0, 10, disj_q, _local, {}, man.value)
    assert len(rows) == 1
    # BEFORE overlay: body is bare local names (the reported bug).
    assert _mos_text(rows[0]["manchester"]) == "Parent SubClassOf hasChild some Man"

    # Overlay the entity_index labels (display source of truth on the page).
    idx = {
        "http://ex/Parent": "parenthood",
        "http://ex/hasChild": "has child",
        "http://ex/Man": "man",
    }
    iris = set()
    _collect_expr_iris(rows, iris)
    assert iris == set(idx)
    _apply_expr_labels(rows, idx)
    # AFTER overlay: the whole axiom is labelled, body included.
    assert _mos_text(rows[0]["manchester"]) == "parenthood SubClassOf has child some man"


def test_build_class_expr_restriction_is_relabelled():
    # `p some X` AST: property + filler carry fragment labels from a fragment
    # label_fn; the overlay replaces them with entity_index labels.
    r = ox.BlankNode("r")
    store = _store(
        (r, _n(_RDF + "type"), _n(_OWL + "Restriction")),
        (r, _n(_OWL + "onProperty"), _n("http://ex/p")),
        (r, _n(_OWL + "someValuesFrom"), _n("http://ex/X")),
    )
    ast = _build_class_expr(store, _GRAPH, r, _local)
    assert ast["property"]["label"] == "p" and ast["filler"]["label"] == "X"

    _apply_expr_labels(ast, {"http://ex/p": "has part", "http://ex/X": "finding"})
    assert ast["property"]["label"] == "has part"
    assert ast["filler"]["label"] == "finding"
