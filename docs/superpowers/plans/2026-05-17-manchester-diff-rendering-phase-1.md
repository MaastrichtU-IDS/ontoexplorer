# Manchester Diff Rendering — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw `<predicate> <object>` axiom-change strings in the ontology version diff with Manchester OWL syntax, grouped per modified entity into a Protégé-style frame.

**Architecture:** A new pure-function module `ontoexplorer/modules/diff/manchester.py` walks the pyoxigraph store to render axioms and frames as plain strings. `compute.py` invokes it for each modified entity and adds a `manchester_frame: string | null` field to the API. The frontend renders the frame in a `<pre>` block, coloring lines by leading `-` / `+` marker.

**Tech Stack:** Python 3.11+, pyoxigraph (in-memory RDF queries), pytest, FastAPI (existing diff route), React + TypeScript, React Query.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ontoexplorer/modules/diff/manchester.py` | NEW | RDF → Manchester OWL rendering (label resolver, class expressions, axioms, frame) |
| `tests/unit/test_manchester_render.py` | NEW | Unit tests for every covered construct + fallback |
| `ontoexplorer/modules/diff/compute.py` | MODIFY | `_structural_triples` returns terms alongside fingerprints; `run_diff` calls the renderer for each modified entity |
| `tests/unit/test_diff_compute.py` | MODIFY | One frame-output test covering the end-to-end integration |
| `ontoexplorer/api/ontologies.py` | MODIFY (1-line) | Include `manchester_frame` in the JSON output of the diff endpoint (passes through existing `diff_data`) |
| `frontend/src/lib/api.ts` | MODIFY | Add `manchester_frame: string \| null` to `DiffEntity` type |
| `frontend/src/components/ManchesterFrame.tsx` | NEW | Small renderer component (~30 lines) used by `HistoryTab.tsx` |
| `frontend/src/components/HistoryTab.tsx` | MODIFY | Replace axiom_changes mapping with `<ManchesterFrame>` |

The renderer module is intentionally a single file. It's ~400 lines of cohesive logic — a dispatcher per RDF shape — and splitting would scatter related patterns across files. If it grows past ~600 lines we revisit splitting.

---

## Task 1: Scaffold `manchester.py` and its test file

**Files:**
- Create: `ontoexplorer/modules/diff/manchester.py`
- Create: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Create the empty module with constants and a docstring**

Write to `ontoexplorer/modules/diff/manchester.py`:

```python
"""RDF → Manchester OWL syntax rendering for the version diff.

Pure functions over a pyoxigraph.Store + named graph. No DB access, no async.
See docs/superpowers/specs/2026-05-17-manchester-diff-rendering-design.md.
"""
from __future__ import annotations

import hashlib
from typing import Literal

import pyoxigraph as ox

# Common IRI constants
_RDF_TYPE  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"
_RDF_REST  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"
_RDF_NIL   = "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"

_RDFS_LABEL    = "http://www.w3.org/2000/01/rdf-schema#label"
_RDFS_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
_RDFS_SUBPROP  = "http://www.w3.org/2000/01/rdf-schema#subPropertyOf"
_RDFS_DOMAIN   = "http://www.w3.org/2000/01/rdf-schema#domain"
_RDFS_RANGE    = "http://www.w3.org/2000/01/rdf-schema#range"

_OWL = "http://www.w3.org/2002/07/owl#"
_OWL_RESTRICTION    = _OWL + "Restriction"
_OWL_ON_PROPERTY    = _OWL + "onProperty"
_OWL_SOME_VALUES    = _OWL + "someValuesFrom"
_OWL_ALL_VALUES     = _OWL + "allValuesFrom"
_OWL_HAS_VALUE      = _OWL + "hasValue"
_OWL_HAS_SELF       = _OWL + "hasSelf"
_OWL_CARDINALITY    = _OWL + "cardinality"
_OWL_MIN_CARD       = _OWL + "minCardinality"
_OWL_MAX_CARD       = _OWL + "maxCardinality"
_OWL_QCARDINALITY   = _OWL + "qualifiedCardinality"
_OWL_MIN_QCARD      = _OWL + "minQualifiedCardinality"
_OWL_MAX_QCARD      = _OWL + "maxQualifiedCardinality"
_OWL_ON_CLASS       = _OWL + "onClass"
_OWL_ON_DATARANGE   = _OWL + "onDataRange"
_OWL_INTERSECTION   = _OWL + "intersectionOf"
_OWL_UNION          = _OWL + "unionOf"
_OWL_COMPLEMENT     = _OWL + "complementOf"
_OWL_ONE_OF         = _OWL + "oneOf"
_OWL_EQUIV_CLASS    = _OWL + "equivalentClass"
_OWL_DISJOINT_WITH  = _OWL + "disjointWith"
_OWL_DISJOINT_UNION = _OWL + "disjointUnionOf"
_OWL_EQUIV_PROP     = _OWL + "equivalentProperty"
_OWL_INVERSE_OF     = _OWL + "inverseOf"
_OWL_SAME_AS        = _OWL + "sameAs"
_OWL_DIFFERENT      = _OWL + "differentFrom"
_OWL_ON_DATATYPE    = _OWL + "onDatatype"
_OWL_WITH_RESTRICTIONS = _OWL + "withRestrictions"

_XSD = "http://www.w3.org/2001/XMLSchema#"
_XSD_STRING = _XSD + "string"
_XSD_BOOLEAN = _XSD + "boolean"
_XSD_TRUE_LITERAL = "true"

# Property characteristics: rdf:type values that map to Characteristics: keywords
_CHARACTERISTICS: dict[str, str] = {
    _OWL + "FunctionalProperty":        "Functional",
    _OWL + "InverseFunctionalProperty": "InverseFunctional",
    _OWL + "ReflexiveProperty":         "Reflexive",
    _OWL + "IrreflexiveProperty":       "Irreflexive",
    _OWL + "SymmetricProperty":         "Symmetric",
    _OWL + "AsymmetricProperty":        "Asymmetric",
    _OWL + "TransitiveProperty":        "Transitive",
}

# Datatype-restriction facet IRIs → Manchester operator strings.
_FACETS: dict[str, str] = {
    _XSD + "minInclusive":  ">=",
    _XSD + "maxInclusive":  "<=",
    _XSD + "minExclusive":  ">",
    _XSD + "maxExclusive":  "<",
    _XSD + "length":        "length",
    _XSD + "minLength":     "minLength",
    _XSD + "maxLength":     "maxLength",
    _XSD + "pattern":       "pattern",
}

# Class expression recursion depth (matches compute._BNODE_FP_MAX_DEPTH).
_MAX_DEPTH = 10
```

Write to `tests/unit/test_manchester_render.py`:

```python
"""Unit tests for ontoexplorer.modules.diff.manchester.

Each test builds a minimal in-memory pyoxigraph.Store with a single named
graph and exercises one renderer function directly.
"""
import pyoxigraph as ox
import pytest

# Re-exported constants/helpers will be imported as tasks land.

_GRAPH = ox.NamedNode("urn:test:graph")


def _store(*quads: tuple) -> ox.Store:
    """Build an in-memory store with one named graph containing the given quads."""
    store = ox.Store()
    store.add_graph(_GRAPH)
    for s, p, o in quads:
        store.add(ox.Quad(s, p, o, _GRAPH))
    return store
```

- [ ] **Step 2: Verify the test file can be discovered**

Run: `cd /home/micheldumontier/code/ontoexplorer && uv run pytest tests/unit/test_manchester_render.py --collect-only`
Expected: zero tests collected, exit code 5 (pytest's "no tests ran"), but no import errors.

- [ ] **Step 3: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): scaffold module and test file"
```

---

## Task 2: `iri_to_label` — label resolution with local-name fallback

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
from ontoexplorer.modules.diff.manchester import iri_to_label


def test_iri_to_label_uses_rdfs_label_en():
    iri = ox.NamedNode("http://example.org/Foo")
    store = _store(
        (iri, ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label"),
         ox.Literal("Foo Class", language="en")),
    )
    labels: dict[str, str] = {}
    assert iri_to_label(store, _GRAPH, iri.value, labels=labels) == "Foo Class"


def test_iri_to_label_falls_back_to_local_name_after_hash():
    iri = "http://example.org/ns#BarClass"
    store = _store()
    assert iri_to_label(store, _GRAPH, iri, labels={}) == "BarClass"


def test_iri_to_label_falls_back_to_local_name_after_slash():
    iri = "http://example.org/ns/Baz"
    store = _store()
    assert iri_to_label(store, _GRAPH, iri, labels={}) == "Baz"


def test_iri_to_label_falls_back_to_full_iri_when_no_separator():
    iri = "urn:weird-iri-no-separator"
    store = _store()
    assert iri_to_label(store, _GRAPH, iri, labels={}) == iri


def test_iri_to_label_caches_result():
    iri = "http://example.org/Foo"
    store = _store(
        (ox.NamedNode(iri),
         ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label"),
         ox.Literal("First", language="en")),
    )
    cache: dict[str, str] = {}
    assert iri_to_label(store, _GRAPH, iri, labels=cache) == "First"
    # Mutate the cache directly so we can prove it isn't queried again
    cache[iri] = "Cached"
    assert iri_to_label(store, _GRAPH, iri, labels=cache) == "Cached"


def test_iri_to_label_prefers_en_over_other_languages():
    iri = "http://example.org/Foo"
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Le Foo", language="fr")),
        (ox.NamedNode(iri), label_pred, ox.Literal("The Foo", language="en")),
    )
    assert iri_to_label(store, _GRAPH, iri, labels={}) == "The Foo"


def test_iri_to_label_takes_any_label_when_no_en():
    iri = "http://example.org/Foo"
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Le Foo", language="fr")),
    )
    assert iri_to_label(store, _GRAPH, iri, labels={}) == "Le Foo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: ImportError or 7 FAILED with `iri_to_label` not defined.

- [ ] **Step 3: Implement `iri_to_label`**

Append to `ontoexplorer/modules/diff/manchester.py`:

```python
def iri_to_label(
    store: ox.Store, graph: ox.NamedNode, iri: str, *, labels: dict[str, str]
) -> str:
    """Resolve an IRI to a display label.

    Order: cache hit → rdfs:label@en → any rdfs:label → local name after `#` or `/`
    → full IRI. The result is cached in `labels` so subsequent calls are O(1).
    """
    if iri in labels:
        return labels[iri]

    label_pred = ox.NamedNode(_RDFS_LABEL)
    en_label: str | None = None
    any_label: str | None = None
    for q in store.quads_for_pattern(ox.NamedNode(iri), label_pred, None, graph):
        if isinstance(q.object, ox.Literal):
            if q.object.language == "en" and en_label is None:
                en_label = q.object.value
            elif any_label is None:
                any_label = q.object.value
    chosen = en_label or any_label
    if chosen is None:
        # Local name fallback
        if "#" in iri:
            chosen = iri.rsplit("#", 1)[1]
        elif "/" in iri:
            chosen = iri.rsplit("/", 1)[1]
        else:
            chosen = iri
        if not chosen:
            chosen = iri
    labels[iri] = chosen
    return chosen
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): iri_to_label with rdfs:label and local-name fallback"
```

---

## Task 3: `_rdf_list_items` — RDF collection traversal helper

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
from ontoexplorer.modules.diff.manchester import _rdf_list_items


def _list_quads(items: list[ox.Term]) -> tuple[ox.BlankNode, list[tuple]]:
    """Build RDF list quads for `items`. Returns (head_bnode, [quads])."""
    quads: list[tuple] = []
    nil = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#nil")
    first_pred = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first")
    rest_pred  = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest")
    nodes = [ox.BlankNode(f"list_{i}") for i in range(len(items))]
    for i, item in enumerate(items):
        quads.append((nodes[i], first_pred, item))
        nxt = nodes[i + 1] if i + 1 < len(nodes) else nil
        quads.append((nodes[i], rest_pred, nxt))
    return nodes[0], quads


def test_rdf_list_items_empty_returns_empty():
    store = _store()
    nil = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#nil")
    assert _rdf_list_items(store, _GRAPH, nil) == []


def test_rdf_list_items_returns_ordered_named_nodes():
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    c = ox.NamedNode("http://example.org/C")
    head, quads = _list_quads([a, b, c])
    store = _store(*quads)
    items = _rdf_list_items(store, _GRAPH, head)
    assert [t.value for t in items] == [a.value, b.value, c.value]


def test_rdf_list_items_handles_literal_items():
    lit = ox.Literal("hello", language="en")
    iri = ox.NamedNode("http://example.org/X")
    head, quads = _list_quads([lit, iri])
    store = _store(*quads)
    items = _rdf_list_items(store, _GRAPH, head)
    assert len(items) == 2
    assert isinstance(items[0], ox.Literal)
    assert items[0].value == "hello"
    assert isinstance(items[1], ox.NamedNode)


def test_rdf_list_items_stops_at_cycle():
    # Pathological cycle: list_0 → list_0 (self-rest). Helper must not loop.
    first_pred = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first")
    rest_pred  = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest")
    head = ox.BlankNode("list_0")
    a = ox.NamedNode("http://example.org/A")
    store = _store(
        (head, first_pred, a),
        (head, rest_pred,  head),  # cycle
    )
    items = _rdf_list_items(store, _GRAPH, head)
    assert [t.value for t in items] == [a.value]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k _rdf_list`
Expected: 4 FAILED with `_rdf_list_items` not defined.

- [ ] **Step 3: Implement `_rdf_list_items`**

Append to `ontoexplorer/modules/diff/manchester.py`:

```python
def _rdf_list_items(
    store: ox.Store, graph: ox.NamedNode, head: ox.Term
) -> list[ox.Term]:
    """Walk an RDF collection from `head` and return its items in order.

    Stops at rdf:nil, at the first cycle, or if a node has no rdf:first/rdf:rest.
    Returns an empty list for rdf:nil.
    """
    first_pred = ox.NamedNode(_RDF_FIRST)
    rest_pred  = ox.NamedNode(_RDF_REST)
    items: list[ox.Term] = []
    visited: set[str] = set()
    node: ox.Term = head
    while True:
        # Stop at rdf:nil
        if isinstance(node, ox.NamedNode) and node.value == _RDF_NIL:
            break
        if not isinstance(node, ox.BlankNode):
            break
        if node.value in visited:
            break
        visited.add(node.value)

        first_obj: ox.Term | None = None
        rest_obj: ox.Term | None = None
        for q in store.quads_for_pattern(node, first_pred, None, graph):
            first_obj = q.object
            break
        for q in store.quads_for_pattern(node, rest_pred, None, graph):
            rest_obj = q.object
            break
        if first_obj is None:
            break
        items.append(first_obj)
        if rest_obj is None:
            break
        node = rest_obj
    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k _rdf_list`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): RDF collection traversal helper"
```

---

## Task 4: `render_class_expression` — named class and bnode dispatcher scaffold

This task lays the dispatcher foundation. Subsequent tasks fill in branches.

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
from ontoexplorer.modules.diff.manchester import render_class_expression


def test_render_named_class_returns_label():
    iri = "http://example.org/Pizza"
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Pizza", language="en")),
    )
    out = render_class_expression(store, _GRAPH, ox.NamedNode(iri), labels={})
    assert out == "Pizza"


def test_render_named_class_uses_local_name_when_no_label():
    iri = "http://example.org/Pizza"
    store = _store()
    out = render_class_expression(store, _GRAPH, ox.NamedNode(iri), labels={})
    assert out == "Pizza"


def test_render_literal_object_renders_with_quotes_and_lang():
    lit = ox.Literal("hello", language="en")
    store = _store()
    out = render_class_expression(store, _GRAPH, lit, labels={})
    assert out == '"hello"@en'


def test_render_literal_object_typed_renders_with_datatype():
    lit = ox.Literal(
        "42",
        datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer"),
    )
    store = _store()
    out = render_class_expression(store, _GRAPH, lit, labels={})
    assert out == '"42"^^xsd:integer'


def test_render_xsd_string_literal_omits_datatype():
    lit = ox.Literal(
        "hello",
        datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#string"),
    )
    store = _store()
    out = render_class_expression(store, _GRAPH, lit, labels={})
    assert out == '"hello"'


def test_render_unknown_bnode_returns_bnode_placeholder():
    # Bnode with no recognized class-expression predicate falls through to fallback.
    bnode = ox.BlankNode("unknown_xyz")
    store = _store(
        (bnode,
         ox.NamedNode("http://example.org/randomPred"),
         ox.NamedNode("http://example.org/Whatever")),
    )
    out = render_class_expression(store, _GRAPH, bnode, labels={})
    assert out.startswith("[bnode:")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k render_class_expression or render_named_class or render_literal or render_unknown_bnode or render_xsd_string`
Expected: 6 FAILED with `render_class_expression` not defined.

- [ ] **Step 3: Implement the dispatcher + literal renderer + fallback**

Append to `ontoexplorer/modules/diff/manchester.py`:

```python
def render_class_expression(
    store: ox.Store,
    graph: ox.NamedNode,
    node: ox.Term,
    *,
    labels: dict[str, str],
    depth: int = 0,
) -> str:
    """Render an RDF term as a Manchester class expression.

    Dispatches by term kind:
      - NamedNode → label / local-name
      - Literal   → "value"[@lang][^^xsd:datatype]
      - BlankNode → introspect outgoing triples, match an OWL pattern, recurse

    Depth-bounded; deeper than _MAX_DEPTH renders as `…`.
    """
    if depth >= _MAX_DEPTH:
        return "…"
    if isinstance(node, ox.NamedNode):
        return iri_to_label(store, graph, node.value, labels=labels)
    if isinstance(node, ox.Literal):
        return _render_literal(node)
    if isinstance(node, ox.BlankNode):
        return _render_bnode_expression(store, graph, node, labels=labels, depth=depth)
    return f"[unknown:{node!r}]"


def _render_literal(lit: ox.Literal) -> str:
    """Manchester-style literal: "value"[@lang][^^xsd:dtype]."""
    text = f'"{lit.value}"'
    if lit.language:
        return f"{text}@{lit.language}"
    if lit.datatype is not None and lit.datatype.value != _XSD_STRING:
        dt = lit.datatype.value
        if dt.startswith(_XSD):
            return f"{text}^^xsd:{dt[len(_XSD):]}"
        return f"{text}^^<{dt}>"
    return text


def _render_bnode_expression(
    store: ox.Store,
    graph: ox.NamedNode,
    node: ox.BlankNode,
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    """Dispatch a blank-node class expression to its specific renderer.

    Order of detection matches OWL2's structural specification. Falls back to
    `[bnode:<short-fp>]` when no pattern matches.
    """
    preds = _bnode_predicates(store, graph, node)

    # Each branch added in a subsequent task; for now everything falls through.

    return _bnode_fallback(store, graph, node)


def _bnode_predicates(
    store: ox.Store, graph: ox.NamedNode, node: ox.BlankNode
) -> dict[str, ox.Term]:
    """Map of predicate-IRI → first object found for this bnode.

    Sufficient for the OWL constructs we render (each has at most one object
    per predicate). RDF lists are walked separately via _rdf_list_items.
    """
    preds: dict[str, ox.Term] = {}
    for q in store.quads_for_pattern(node, None, None, graph):
        # First-wins; predicates we care about are functional in OWL2 anyway.
        preds.setdefault(q.predicate.value, q.object)
    return preds


def _bnode_fallback(
    store: ox.Store, graph: ox.NamedNode, node: ox.BlankNode
) -> str:
    """Short stable fingerprint for an unrecognized bnode (debugging aid)."""
    parts: list[str] = []
    for q in store.quads_for_pattern(node, None, None, graph):
        if isinstance(q.object, ox.NamedNode):
            o = q.object.value
        elif isinstance(q.object, ox.Literal):
            o = f'"{q.object.value}"'
        else:
            o = "_:b"
        parts.append(f"{q.predicate.value}\t{o}")
    parts.sort()
    fp = hashlib.sha1("\n".join(parts).encode()).hexdigest()[:8]
    return f"[bnode:{fp}]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: all 14 previous tests still pass + 6 new tests pass = 20 total.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): class expression dispatcher with named + literal + fallback"
```

---

## Task 5: Simple OWL restrictions (some / only / value / Self)

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
_OWL_RESTRICTION = ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction")
_OWL_ON_PROPERTY = ox.NamedNode("http://www.w3.org/2002/07/owl#onProperty")
_OWL_SOME = ox.NamedNode("http://www.w3.org/2002/07/owl#someValuesFrom")
_OWL_ALL  = ox.NamedNode("http://www.w3.org/2002/07/owl#allValuesFrom")
_OWL_HAS_VALUE = ox.NamedNode("http://www.w3.org/2002/07/owl#hasValue")
_OWL_HAS_SELF  = ox.NamedNode("http://www.w3.org/2002/07/owl#hasSelf")
_RDF_TYPE_N = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_XSD_TRUE = ox.Literal("true", datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#boolean"))


def test_restriction_some_values_from():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Tomato")
    r = ox.BlankNode("r1")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_SOME, c),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping some Tomato"


def test_restriction_all_values_from():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Tomato")
    r = ox.BlankNode("r2")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_ALL, c),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping only Tomato"


def test_restriction_has_value_iri():
    p = ox.NamedNode("http://example.org/hasTopping")
    v = ox.NamedNode("http://example.org/SpecificTomato")
    r = ox.BlankNode("r3")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_VALUE, v),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping value SpecificTomato"


def test_restriction_has_value_literal():
    p = ox.NamedNode("http://example.org/hasName")
    v = ox.Literal("Salty", language="en")
    r = ox.BlankNode("r4")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_VALUE, v),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == 'hasName value "Salty"@en'


def test_restriction_has_self_true():
    p = ox.NamedNode("http://example.org/hasPartOf")
    r = ox.BlankNode("r5")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_HAS_SELF, _XSD_TRUE),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasPartOf Self"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py::test_restriction_some_values_from -v`
Expected: FAILED — currently produces `[bnode:...]`.

- [ ] **Step 3: Wire restrictions into the bnode dispatcher**

Edit `_render_bnode_expression` in `ontoexplorer/modules/diff/manchester.py`. Replace the function body with:

```python
def _render_bnode_expression(
    store: ox.Store,
    graph: ox.NamedNode,
    node: ox.BlankNode,
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    preds = _bnode_predicates(store, graph, node)

    # Property restrictions: detected by presence of owl:onProperty.
    if _OWL_ON_PROPERTY in preds:
        return _render_restriction(store, graph, preds, labels=labels, depth=depth)

    return _bnode_fallback(store, graph, node)
```

Add the restriction renderer:

```python
def _render_restriction(
    store: ox.Store,
    graph: ox.NamedNode,
    preds: dict[str, ox.Term],
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    """Render an owl:Restriction.

    Required: owl:onProperty. Then exactly one of someValuesFrom / allValuesFrom /
    hasValue / hasSelf / cardinality-variants.
    """
    prop_term = preds[_OWL_ON_PROPERTY]
    prop_label = render_class_expression(
        store, graph, prop_term, labels=labels, depth=depth + 1
    )

    if _OWL_SOME_VALUES in preds:
        filler = render_class_expression(
            store, graph, preds[_OWL_SOME_VALUES], labels=labels, depth=depth + 1
        )
        return f"{prop_label} some {filler}"
    if _OWL_ALL_VALUES in preds:
        filler = render_class_expression(
            store, graph, preds[_OWL_ALL_VALUES], labels=labels, depth=depth + 1
        )
        return f"{prop_label} only {filler}"
    if _OWL_HAS_VALUE in preds:
        v = render_class_expression(
            store, graph, preds[_OWL_HAS_VALUE], labels=labels, depth=depth + 1
        )
        return f"{prop_label} value {v}"
    if _OWL_HAS_SELF in preds:
        v = preds[_OWL_HAS_SELF]
        if isinstance(v, ox.Literal) and v.value == _XSD_TRUE_LITERAL:
            return f"{prop_label} Self"
        # `hasSelf false` is not a standard Manchester construct; fall through.

    # Cardinality patterns are handled in a later task; until then, fallback.
    return f"[restriction:{prop_label}]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 25 passed (20 previous + 5 new).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): some/only/value/Self restrictions"
```

---

## Task 6: Cardinality restrictions (min / max / exactly, qualified + unqualified)

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
_OWL_CARD = ox.NamedNode("http://www.w3.org/2002/07/owl#cardinality")
_OWL_MIN_CARD = ox.NamedNode("http://www.w3.org/2002/07/owl#minCardinality")
_OWL_MAX_CARD = ox.NamedNode("http://www.w3.org/2002/07/owl#maxCardinality")
_OWL_QCARD = ox.NamedNode("http://www.w3.org/2002/07/owl#qualifiedCardinality")
_OWL_MIN_QCARD = ox.NamedNode("http://www.w3.org/2002/07/owl#minQualifiedCardinality")
_OWL_MAX_QCARD = ox.NamedNode("http://www.w3.org/2002/07/owl#maxQualifiedCardinality")
_OWL_ON_CLASS = ox.NamedNode("http://www.w3.org/2002/07/owl#onClass")
_XSD_NONNEG_INT = ox.NamedNode("http://www.w3.org/2001/XMLSchema#nonNegativeInteger")


def _int_lit(n: int) -> ox.Literal:
    return ox.Literal(str(n), datatype=_XSD_NONNEG_INT)


def test_restriction_cardinality_unqualified():
    p = ox.NamedNode("http://example.org/hasTopping")
    r = ox.BlankNode("rc1")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_CARD, _int_lit(3)),
    )
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping exactly 3"


def test_restriction_min_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    r = ox.BlankNode("rc2")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MIN_CARD, _int_lit(1)),
    )
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping min 1"


def test_restriction_max_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    r = ox.BlankNode("rc3")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MAX_CARD, _int_lit(5)),
    )
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping max 5"


def test_restriction_min_qualified_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Vegetable")
    r = ox.BlankNode("rc4")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MIN_QCARD, _int_lit(2)),
        (r, _OWL_ON_CLASS, c),
    )
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping min 2 Vegetable"


def test_restriction_max_qualified_cardinality():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Vegetable")
    r = ox.BlankNode("rc5")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_MAX_QCARD, _int_lit(4)),
        (r, _OWL_ON_CLASS, c),
    )
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping max 4 Vegetable"


def test_restriction_qualified_cardinality_exactly():
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Vegetable")
    r = ox.BlankNode("rc6")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_QCARD, _int_lit(2)),
        (r, _OWL_ON_CLASS, c),
    )
    assert render_class_expression(store, _GRAPH, r, labels={}) == "hasTopping exactly 2 Vegetable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k cardinality`
Expected: 6 FAILED — currently producing `[restriction:hasTopping]`.

- [ ] **Step 3: Extend `_render_restriction`**

In `ontoexplorer/modules/diff/manchester.py`, replace the trailing block of `_render_restriction` (the `[restriction:...]` fallback) with:

```python
    # Cardinality variants.
    for card_pred, kw in (
        (_OWL_CARDINALITY,  "exactly"),
        (_OWL_MIN_CARD,     "min"),
        (_OWL_MAX_CARD,     "max"),
        (_OWL_QCARDINALITY, "exactly"),
        (_OWL_MIN_QCARD,    "min"),
        (_OWL_MAX_QCARD,    "max"),
    ):
        if card_pred in preds:
            n = preds[card_pred]
            if not isinstance(n, ox.Literal):
                continue
            on_class = preds.get(_OWL_ON_CLASS) or preds.get(_OWL_ON_DATARANGE)
            if on_class is not None:
                filler = render_class_expression(
                    store, graph, on_class, labels=labels, depth=depth + 1
                )
                return f"{prop_label} {kw} {n.value} {filler}"
            return f"{prop_label} {kw} {n.value}"

    return f"[restriction:{prop_label}]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 31 passed (25 previous + 6 new).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): cardinality restrictions (min/max/exactly, qualified)"
```

---

## Task 7: Boolean class expressions (intersectionOf / unionOf / complementOf)

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
_OWL_INTERSECTION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#intersectionOf")
_OWL_UNION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#unionOf")
_OWL_COMPLEMENT_N = ox.NamedNode("http://www.w3.org/2002/07/owl#complementOf")


def test_intersection_of_named_classes():
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    head, list_quads = _list_quads([a, b])
    expr = ox.BlankNode("expr1")
    store = _store(
        (expr, _OWL_INTERSECTION_N, head),
        *list_quads,
    )
    assert render_class_expression(store, _GRAPH, expr, labels={}) == "(A and B)"


def test_union_of_named_classes():
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    c = ox.NamedNode("http://example.org/C")
    head, list_quads = _list_quads([a, b, c])
    expr = ox.BlankNode("expr2")
    store = _store(
        (expr, _OWL_UNION_N, head),
        *list_quads,
    )
    assert render_class_expression(store, _GRAPH, expr, labels={}) == "(A or B or C)"


def test_complement_of_named_class():
    a = ox.NamedNode("http://example.org/A")
    expr = ox.BlankNode("expr3")
    store = _store((expr, _OWL_COMPLEMENT_N, a))
    assert render_class_expression(store, _GRAPH, expr, labels={}) == "not A"


def test_intersection_inside_restriction():
    """Nested: hasTopping some (A and B)."""
    p = ox.NamedNode("http://example.org/hasTopping")
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    head, list_quads = _list_quads([a, b])
    inter = ox.BlankNode("inter")
    r = ox.BlankNode("r_nested")
    store = _store(
        (inter, _OWL_INTERSECTION_N, head),
        *list_quads,
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_SOME, inter),
    )
    out = render_class_expression(store, _GRAPH, r, labels={})
    assert out == "hasTopping some (A and B)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k intersection or union or complement`
Expected: 4 FAILED.

- [ ] **Step 3: Wire Boolean expressions into the dispatcher**

In `_render_bnode_expression`, add branches BEFORE the `_OWL_ON_PROPERTY` check:

```python
    if _OWL_INTERSECTION in preds:
        return _render_junction(
            store, graph, preds[_OWL_INTERSECTION], "and", labels=labels, depth=depth
        )
    if _OWL_UNION in preds:
        return _render_junction(
            store, graph, preds[_OWL_UNION], "or", labels=labels, depth=depth
        )
    if _OWL_COMPLEMENT in preds:
        inner = render_class_expression(
            store, graph, preds[_OWL_COMPLEMENT], labels=labels, depth=depth + 1
        )
        return f"not {inner}"
```

Then add the helper:

```python
def _render_junction(
    store: ox.Store,
    graph: ox.NamedNode,
    list_head: ox.Term,
    op: str,
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    """Render intersectionOf / unionOf as `(A op B op C)`."""
    items = _rdf_list_items(store, graph, list_head)
    if not items:
        return f"({op})"
    parts = [
        render_class_expression(store, graph, it, labels=labels, depth=depth + 1)
        for it in items
    ]
    return "(" + f" {op} ".join(parts) + ")"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 35 passed (31 previous + 4 new).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): intersectionOf / unionOf / complementOf"
```

---

## Task 8: Enumeration (oneOf) and datatype restrictions

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
_OWL_ONE_OF_N = ox.NamedNode("http://www.w3.org/2002/07/owl#oneOf")
_OWL_ON_DT = ox.NamedNode("http://www.w3.org/2002/07/owl#onDatatype")
_OWL_WITH_R = ox.NamedNode("http://www.w3.org/2002/07/owl#withRestrictions")
_XSD_INT = ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer")
_XSD_MIN_INC = ox.NamedNode("http://www.w3.org/2001/XMLSchema#minInclusive")
_XSD_MAX_INC = ox.NamedNode("http://www.w3.org/2001/XMLSchema#maxInclusive")


def test_one_of_named_individuals():
    a = ox.NamedNode("http://example.org/Alice")
    b = ox.NamedNode("http://example.org/Bob")
    c = ox.NamedNode("http://example.org/Carol")
    head, list_quads = _list_quads([a, b, c])
    expr = ox.BlankNode("enum1")
    store = _store(
        (expr, _OWL_ONE_OF_N, head),
        *list_quads,
    )
    assert render_class_expression(store, _GRAPH, expr, labels={}) == "{Alice, Bob, Carol}"


def test_datatype_restriction_range():
    """xsd:integer[>= 0, <= 120]"""
    dt_expr = ox.BlankNode("dt1")
    facet1 = ox.BlankNode("facet1")
    facet2 = ox.BlankNode("facet2")
    head, list_quads = _list_quads([facet1, facet2])
    store = _store(
        (dt_expr, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#Datatype")),
        (dt_expr, _OWL_ON_DT, _XSD_INT),
        (dt_expr, _OWL_WITH_R, head),
        (facet1, _XSD_MIN_INC, _int_lit(0)),
        (facet2, _XSD_MAX_INC, _int_lit(120)),
        *list_quads,
    )
    out = render_class_expression(store, _GRAPH, dt_expr, labels={})
    assert out == "xsd:integer[>= 0, <= 120]"


def test_datatype_restriction_pattern():
    """xsd:string[pattern "[A-Z]+"]"""
    dt_expr = ox.BlankNode("dt2")
    facet = ox.BlankNode("facet_p")
    head, list_quads = _list_quads([facet])
    xsd_string = ox.NamedNode("http://www.w3.org/2001/XMLSchema#string")
    xsd_pattern = ox.NamedNode("http://www.w3.org/2001/XMLSchema#pattern")
    store = _store(
        (dt_expr, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#Datatype")),
        (dt_expr, _OWL_ON_DT, xsd_string),
        (dt_expr, _OWL_WITH_R, head),
        (facet, xsd_pattern, ox.Literal("[A-Z]+")),
        *list_quads,
    )
    out = render_class_expression(store, _GRAPH, dt_expr, labels={})
    assert out == 'xsd:string[pattern "[A-Z]+"]'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k one_of or datatype_restriction`
Expected: 3 FAILED.

- [ ] **Step 3: Wire oneOf and datatype restrictions into the dispatcher**

Add a branch in `_render_bnode_expression` (after Boolean, before Restriction):

```python
    if _OWL_ONE_OF in preds:
        items = _rdf_list_items(store, graph, preds[_OWL_ONE_OF])
        parts = [
            render_class_expression(store, graph, it, labels=labels, depth=depth + 1)
            for it in items
        ]
        return "{" + ", ".join(parts) + "}"

    if _OWL_ON_DATATYPE in preds and _OWL_WITH_RESTRICTIONS in preds:
        return _render_datatype_restriction(
            store, graph, preds, labels=labels, depth=depth
        )
```

Add the helper:

```python
def _render_datatype_restriction(
    store: ox.Store,
    graph: ox.NamedNode,
    preds: dict[str, ox.Term],
    *,
    labels: dict[str, str],
    depth: int,
) -> str:
    """Render rdfs:Datatype + owl:onDatatype + owl:withRestrictions as
    `<datatype>[facet1 v1, facet2 v2]`. Falls back to bare datatype label when
    the facet list is empty or unrecognized.
    """
    base = preds[_OWL_ON_DATATYPE]
    base_label = render_class_expression(store, graph, base, labels=labels, depth=depth + 1)
    if isinstance(base, ox.NamedNode) and base.value.startswith(_XSD):
        base_label = f"xsd:{base.value[len(_XSD):]}"

    items = _rdf_list_items(store, graph, preds[_OWL_WITH_RESTRICTIONS])
    facet_strs: list[str] = []
    for item in items:
        if not isinstance(item, ox.BlankNode):
            continue
        for q in store.quads_for_pattern(item, None, None, graph):
            facet_iri = q.predicate.value
            if facet_iri not in _FACETS:
                continue
            op = _FACETS[facet_iri]
            value_str = _render_literal(q.object) if isinstance(q.object, ox.Literal) else str(q.object.value)
            if op == "pattern":
                facet_strs.append(f'pattern {value_str}')
            elif op in ("length", "minLength", "maxLength"):
                inner = q.object.value if isinstance(q.object, ox.Literal) else value_str
                facet_strs.append(f"{op} {inner}")
            else:
                inner = q.object.value if isinstance(q.object, ox.Literal) else value_str
                facet_strs.append(f"{op} {inner}")
    if not facet_strs:
        return base_label
    return f"{base_label}[" + ", ".join(facet_strs) + "]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 38 passed (35 previous + 3 new).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): oneOf and datatype restrictions"
```

---

## Task 9: Depth limit test

**Files:**
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add depth-limit test**

Append to `tests/unit/test_manchester_render.py`:

```python
def test_depth_limit_returns_ellipsis():
    """A deeply nested intersection chain renders as `…` once depth exceeds _MAX_DEPTH."""
    p = ox.NamedNode("http://example.org/p")
    a = ox.NamedNode("http://example.org/A")
    quads: list[tuple] = []
    # Build 12 nested restrictions: r0 → r1 → r2 → ... → A
    # r_i: p some r_{i+1}
    last: ox.Term = a
    for i in reversed(range(12)):
        r = ox.BlankNode(f"deep_{i}")
        quads.append((r, _RDF_TYPE_N, _OWL_RESTRICTION))
        quads.append((r, _OWL_ON_PROPERTY, p))
        quads.append((r, _OWL_SOME, last))
        last = r
    store = _store(*quads)
    out = render_class_expression(store, _GRAPH, last, labels={})
    assert "…" in out, f"expected depth-limit ellipsis, got: {out}"
```

- [ ] **Step 2: Run test to verify it passes (depth limit was implemented in Task 4)**

Run: `uv run pytest tests/unit/test_manchester_render.py::test_depth_limit_returns_ellipsis -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_manchester_render.py
git commit -m "test(diff/manchester): depth-limit regression test for class expressions"
```

---

## Task 10: `render_axiom` — class axioms

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
from ontoexplorer.modules.diff.manchester import render_axiom

_RDFS_SUB_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
_OWL_EQUIV_CLASS_N = ox.NamedNode("http://www.w3.org/2002/07/owl#equivalentClass")
_OWL_DISJOINT_N = ox.NamedNode("http://www.w3.org/2002/07/owl#disjointWith")
_OWL_DISJOINT_UNION_N = ox.NamedNode("http://www.w3.org/2002/07/owl#disjointUnionOf")


def test_axiom_subclassof_named():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Food")
    store = _store()
    out = render_axiom(
        store, _GRAPH, subj, _RDFS_SUB_N.value, obj, labels={}
    )
    assert out == "SubClassOf: Food"


def test_axiom_subclassof_restriction():
    subj = "http://example.org/Pizza"
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Tomato")
    r = ox.BlankNode("axr1")
    store = _store(
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_SOME, c),
    )
    out = render_axiom(store, _GRAPH, subj, _RDFS_SUB_N.value, r, labels={})
    assert out == "SubClassOf: hasTopping some Tomato"


def test_axiom_equivalent_class():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Food")
    store = _store()
    out = render_axiom(store, _GRAPH, subj, _OWL_EQUIV_CLASS_N.value, obj, labels={})
    assert out == "EquivalentTo: Food"


def test_axiom_disjoint_with():
    subj = "http://example.org/Pizza"
    obj = ox.NamedNode("http://example.org/Pasta")
    store = _store()
    out = render_axiom(store, _GRAPH, subj, _OWL_DISJOINT_N.value, obj, labels={})
    assert out == "DisjointWith: Pasta"


def test_axiom_unknown_predicate_returns_none():
    """A predicate outside the coverage table returns None, signalling the caller to fall back."""
    subj = "http://example.org/X"
    obj = ox.NamedNode("http://example.org/Y")
    store = _store()
    out = render_axiom(
        store, _GRAPH, subj, "http://example.org/unknownPred", obj, labels={}
    )
    assert out is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k axiom`
Expected: 5 FAILED with `render_axiom` not defined.

- [ ] **Step 3: Implement `render_axiom`**

Append to `ontoexplorer/modules/diff/manchester.py`:

```python
# Predicate-keyed dispatch for axioms whose Manchester rendering is
# `<Keyword>: <class-or-property-expression>`. The frame layer groups changes
# by keyword; this function only emits a single axiom line.
_CLASS_AXIOMS: dict[str, str] = {
    _RDFS_SUBCLASS:      "SubClassOf",
    _OWL_EQUIV_CLASS:    "EquivalentTo",
    _OWL_DISJOINT_WITH:  "DisjointWith",
    _OWL_DISJOINT_UNION: "DisjointUnionOf",
}


def render_axiom(
    store: ox.Store,
    graph: ox.NamedNode,
    subject_iri: str,
    predicate_iri: str,
    object_term: ox.Term,
    *,
    labels: dict[str, str],
) -> str | None:
    """Render a single axiom (predicate + object) as a Manchester line.

    Returns None when the predicate is not in the coverage table; callers should
    treat None as "fall back to `<predicate> <object>` rendering".
    """
    keyword = _CLASS_AXIOMS.get(predicate_iri)
    if keyword is None:
        return None
    filler = render_class_expression(store, graph, object_term, labels=labels)
    return f"{keyword}: {filler}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 44 passed (39 previous + 5 new).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): render_axiom for class axioms"
```

---

## Task 11: `render_axiom` — property axioms and individual axioms

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
_RDFS_SUBPROP_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subPropertyOf")
_OWL_EQUIV_PROP_N = ox.NamedNode("http://www.w3.org/2002/07/owl#equivalentProperty")
_OWL_INVERSE_OF_N = ox.NamedNode("http://www.w3.org/2002/07/owl#inverseOf")
_RDFS_DOMAIN_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#domain")
_RDFS_RANGE_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#range")
_OWL_SAME_AS_N = ox.NamedNode("http://www.w3.org/2002/07/owl#sameAs")
_OWL_DIFFERENT_N = ox.NamedNode("http://www.w3.org/2002/07/owl#differentFrom")
_OWL_FUNCTIONAL_N = ox.NamedNode("http://www.w3.org/2002/07/owl#FunctionalProperty")
_OWL_TRANSITIVE_N = ox.NamedNode("http://www.w3.org/2002/07/owl#TransitiveProperty")


def test_axiom_subproperty_of():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDFS_SUBPROP_N.value,
        ox.NamedNode("http://example.org/hasIngredient"),
        labels={},
    )
    assert out == "SubPropertyOf: hasIngredient"


def test_axiom_equivalent_property():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _OWL_EQUIV_PROP_N.value,
        ox.NamedNode("http://example.org/hasCovering"),
        labels={},
    )
    assert out == "EquivalentTo: hasCovering"


def test_axiom_inverse_of():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _OWL_INVERSE_OF_N.value,
        ox.NamedNode("http://example.org/toppingOf"),
        labels={},
    )
    assert out == "InverseOf: toppingOf"


def test_axiom_domain():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDFS_DOMAIN_N.value,
        ox.NamedNode("http://example.org/Pizza"),
        labels={},
    )
    assert out == "Domain: Pizza"


def test_axiom_range():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDFS_RANGE_N.value,
        ox.NamedNode("http://example.org/Topping"),
        labels={},
    )
    assert out == "Range: Topping"


def test_axiom_characteristics_functional():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDF_TYPE_N.value,
        _OWL_FUNCTIONAL_N,
        labels={},
    )
    assert out == "Characteristics: Functional"


def test_axiom_characteristics_transitive():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/hasTopping", _RDF_TYPE_N.value,
        _OWL_TRANSITIVE_N,
        labels={},
    )
    assert out == "Characteristics: Transitive"


def test_axiom_rdf_type_non_characteristic_returns_none():
    """rdf:type whose object isn't one of the 7 OWL property characteristics → None.

    The frame header already shows the entity's declared type; non-characteristic
    rdf:type triples are not surfaced as Manchester axioms.
    """
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _RDF_TYPE_N.value,
        ox.NamedNode("http://www.w3.org/2002/07/owl#Class"),
        labels={},
    )
    assert out is None


def test_axiom_same_as():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", _OWL_SAME_AS_N.value,
        ox.NamedNode("http://example.org/AliceFoo"),
        labels={},
    )
    assert out == "SameAs: AliceFoo"


def test_axiom_different_from():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", _OWL_DIFFERENT_N.value,
        ox.NamedNode("http://example.org/Bob"),
        labels={},
    )
    assert out == "DifferentFrom: Bob"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 10 new FAILEDs.

- [ ] **Step 3: Extend `render_axiom`**

Replace the `render_axiom` body in `ontoexplorer/modules/diff/manchester.py` with:

```python
_PROPERTY_AXIOMS: dict[str, str] = {
    _RDFS_SUBPROP:    "SubPropertyOf",
    _OWL_EQUIV_PROP:  "EquivalentTo",
    _OWL_INVERSE_OF:  "InverseOf",
    _RDFS_DOMAIN:     "Domain",
    _RDFS_RANGE:      "Range",
}

_INDIVIDUAL_AXIOMS: dict[str, str] = {
    _OWL_SAME_AS:     "SameAs",
    _OWL_DIFFERENT:   "DifferentFrom",
}


def render_axiom(
    store: ox.Store,
    graph: ox.NamedNode,
    subject_iri: str,
    predicate_iri: str,
    object_term: ox.Term,
    *,
    labels: dict[str, str],
) -> str | None:
    """Render a single (predicate, object) pair as a Manchester axiom line.

    Returns None when the predicate is outside the coverage table; the caller
    is expected to render a `<predicate> <object>` fallback in that case.
    """
    # Property characteristics: rdf:type with an OWL characteristic class.
    if predicate_iri == _RDF_TYPE and isinstance(object_term, ox.NamedNode):
        char = _CHARACTERISTICS.get(object_term.value)
        if char is not None:
            return f"Characteristics: {char}"
        return None  # other rdf:type triples belong in the frame header

    keyword = (
        _CLASS_AXIOMS.get(predicate_iri)
        or _PROPERTY_AXIOMS.get(predicate_iri)
        or _INDIVIDUAL_AXIOMS.get(predicate_iri)
    )
    if keyword is None:
        return None

    filler = render_class_expression(store, graph, object_term, labels=labels)
    return f"{keyword}: {filler}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 54 passed (44 previous + 10 new).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): property axioms, characteristics, individual axioms"
```

---

## Task 12: Individual `Types:` and `Facts:` rendering

For an individual (entity_type='individual'), `rdf:type X` should render as `Types: X` (with X a class expression), and arbitrary property assertions render as `Facts: predicate object`. This requires `render_axiom` to know the entity type.

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
def test_axiom_individual_types():
    """For an individual, rdf:type X renders as `Types: X`."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", _RDF_TYPE_N.value,
        ox.NamedNode("http://example.org/Person"),
        labels={},
        entity_type="individual",
    )
    assert out == "Types: Person"


def test_axiom_individual_property_assertion():
    """For an individual, an arbitrary predicate renders as `Facts: predicate object`."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", "http://example.org/hasFriend",
        ox.NamedNode("http://example.org/Bob"),
        labels={},
        entity_type="individual",
    )
    assert out == "Facts: hasFriend Bob"


def test_axiom_individual_property_assertion_literal():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Alice", "http://example.org/age",
        ox.Literal("30", datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer")),
        labels={},
        entity_type="individual",
    )
    assert out == 'Facts: age "30"^^xsd:integer'


def test_axiom_non_individual_unknown_predicate_still_returns_none():
    """For non-individuals, unknown predicates should NOT auto-convert to Facts:."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", "http://example.org/random",
        ox.NamedNode("http://example.org/Bar"),
        labels={},
        entity_type="class",
    )
    assert out is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k individual or non_individual`
Expected: 4 FAILED — `render_axiom` doesn't accept `entity_type` kwarg.

- [ ] **Step 3: Add `entity_type` to `render_axiom`**

Replace the current `render_axiom` signature and body:

```python
def render_axiom(
    store: ox.Store,
    graph: ox.NamedNode,
    subject_iri: str,
    predicate_iri: str,
    object_term: ox.Term,
    *,
    labels: dict[str, str],
    entity_type: str | None = None,
) -> str | None:
    """Render a single (predicate, object) pair as a Manchester axiom line.

    `entity_type` (one of 'class', 'object_property', 'data_property',
    'annotation_property', 'individual') changes the meaning of rdf:type and
    of unknown predicates:

      * On individuals: rdf:type → `Types: X`; any other predicate → `Facts: p o`.
      * On properties: rdf:type with an OWL characteristic class → `Characteristics: Functional` etc.
      * Other unrecognized predicates → None (caller falls back).
    """
    # Individuals: rdf:type → Types, anything else → Facts.
    if entity_type == "individual":
        if predicate_iri == _RDF_TYPE:
            filler = render_class_expression(store, graph, object_term, labels=labels)
            return f"Types: {filler}"
        if predicate_iri in _INDIVIDUAL_AXIOMS:
            keyword = _INDIVIDUAL_AXIOMS[predicate_iri]
            filler = render_class_expression(store, graph, object_term, labels=labels)
            return f"{keyword}: {filler}"
        # Property assertion: predicate is some property, object is the value.
        prop_label = iri_to_label(store, graph, predicate_iri, labels=labels)
        value_label = render_class_expression(store, graph, object_term, labels=labels)
        return f"Facts: {prop_label} {value_label}"

    # Property characteristics: rdf:type with an OWL characteristic class.
    if predicate_iri == _RDF_TYPE and isinstance(object_term, ox.NamedNode):
        char = _CHARACTERISTICS.get(object_term.value)
        if char is not None:
            return f"Characteristics: {char}"
        return None  # other rdf:type triples belong in the frame header

    keyword = (
        _CLASS_AXIOMS.get(predicate_iri)
        or _PROPERTY_AXIOMS.get(predicate_iri)
        or _INDIVIDUAL_AXIOMS.get(predicate_iri)
    )
    if keyword is None:
        return None
    filler = render_class_expression(store, graph, object_term, labels=labels)
    return f"{keyword}: {filler}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 58 passed (54 previous + 4 new).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): individual Types: and Facts: rendering"
```

---

## Task 13: `render_frame` — header, keyword grouping, ordering

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
from ontoexplorer.modules.diff.manchester import render_frame


def test_render_frame_class_header_with_label():
    iri = "http://example.org/Pizza"
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Pizza", language="en")),
    )
    frame = render_frame(
        store, iri, "class", axiom_changes=[], labels={}
    )
    # Empty axiom changes → None (per spec, empty frame is not surfaced).
    assert frame is None


def test_render_frame_class_with_single_subclass_change():
    iri = "http://example.org/SaltyPizza"
    p = ox.NamedNode("http://example.org/hasTopping")
    c = ox.NamedNode("http://example.org/Anchovy")
    r = ox.BlankNode("r_axiom")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (ox.NamedNode(iri), label_pred, ox.Literal("Salty Pizza", language="en")),
        (r, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r, _OWL_ON_PROPERTY, p),
        (r, _OWL_SOME, c),
    )
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUBCLASS, "object": r,
             "graph": _GRAPH},
        ],
        labels={},
    )
    assert frame is not None
    expected = (
        f"Class: Salty Pizza  ({iri})\n"
        "    SubClassOf:\n"
        "+       hasTopping some Anchovy"
    )
    assert frame == expected


def test_render_frame_removed_then_added_under_same_keyword():
    iri = "http://example.org/SaltyPizza"
    p = ox.NamedNode("http://example.org/hasTopping")
    cheese = ox.NamedNode("http://example.org/Cheese")
    tofu = ox.NamedNode("http://example.org/Tofu")
    r_old = ox.BlankNode("r_old")
    r_new = ox.BlankNode("r_new")
    store = _store(
        (r_old, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r_old, _OWL_ON_PROPERTY, p),
        (r_old, _OWL_SOME, cheese),
        (r_new, _RDF_TYPE_N, _OWL_RESTRICTION),
        (r_new, _OWL_ON_PROPERTY, p),
        (r_new, _OWL_SOME, tofu),
    )
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added",   "predicate": _RDFS_SUBCLASS, "object": r_new, "graph": _GRAPH},
            {"op": "removed", "predicate": _RDFS_SUBCLASS, "object": r_old, "graph": _GRAPH},
        ],
        labels={},
    )
    expected = (
        f"Class: SaltyPizza  ({iri})\n"
        "    SubClassOf:\n"
        "-       hasTopping some Cheese\n"
        "+       hasTopping some Tofu"
    )
    assert frame == expected


def test_render_frame_multiple_keywords_ordered():
    iri = "http://example.org/Foo"
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            # Mixed order — render_frame must group and order them.
            {"op": "added",   "predicate": _OWL_EQUIV_CLASS,  "object": b, "graph": _GRAPH},
            {"op": "added",   "predicate": _RDFS_SUBCLASS,    "object": a, "graph": _GRAPH},
        ],
        labels={},
    )
    expected = (
        f"Class: Foo  ({iri})\n"
        "    SubClassOf:\n"
        "+       A\n"
        "    EquivalentTo:\n"
        "+       B"
    )
    assert frame == expected


def test_render_frame_object_property_header():
    iri = "http://example.org/hasTopping"
    p2 = ox.NamedNode("http://example.org/hasCovering")
    store = _store()
    frame = render_frame(
        store, iri, "object_property",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUBPROP, "object": p2, "graph": _GRAPH},
        ],
        labels={},
    )
    expected = (
        f"ObjectProperty: hasTopping  ({iri})\n"
        "    SubPropertyOf:\n"
        "+       hasCovering"
    )
    assert frame == expected


def test_render_frame_individual_with_facts_and_types():
    iri = "http://example.org/Alice"
    person = ox.NamedNode("http://example.org/Person")
    bob = ox.NamedNode("http://example.org/Bob")
    store = _store()
    frame = render_frame(
        store, iri, "individual",
        axiom_changes=[
            {"op": "added", "predicate": _RDF_TYPE,           "object": person, "graph": _GRAPH},
            {"op": "added", "predicate": "http://example.org/hasFriend", "object": bob, "graph": _GRAPH},
        ],
        labels={},
    )
    expected = (
        f"Individual: Alice  ({iri})\n"
        "    Types:\n"
        "+       Person\n"
        "    Facts:\n"
        "+       hasFriend Bob"
    )
    assert frame == expected


def test_render_frame_unknown_predicate_falls_back_to_raw_form():
    iri = "http://example.org/Foo"
    obj = ox.NamedNode("http://example.org/Bar")
    pred = "http://example.org/myCustomPred"
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": pred, "object": obj, "graph": _GRAPH},
        ],
        labels={},
    )
    # Unknown predicate → frame omits that line; with no other changes the frame is None.
    assert frame is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k render_frame`
Expected: 7 FAILED with `render_frame` not defined.

- [ ] **Step 3: Implement `render_frame`**

Append to `ontoexplorer/modules/diff/manchester.py`:

```python
# Order in which keywords appear in the frame. Predicates not in the table are
# emitted at the end under "Other:" (or omitted, for unrecognized ones).
# Tuples: (predicate, manchester-keyword, applicable-entity-types).
_FRAME_KEYWORD_ORDER: list[tuple[str, str, set[str] | None]] = [
    # Class axioms
    (_RDFS_SUBCLASS,      "SubClassOf",       {"class"}),
    (_OWL_EQUIV_CLASS,    "EquivalentTo",     {"class"}),
    (_OWL_DISJOINT_WITH,  "DisjointWith",     {"class"}),
    (_OWL_DISJOINT_UNION, "DisjointUnionOf",  {"class"}),
    # Property axioms
    (_RDFS_SUBPROP,       "SubPropertyOf",
        {"object_property", "data_property", "annotation_property"}),
    (_OWL_EQUIV_PROP,     "EquivalentTo",
        {"object_property", "data_property"}),
    (_OWL_INVERSE_OF,     "InverseOf",        {"object_property"}),
    (_RDFS_DOMAIN,        "Domain",
        {"object_property", "data_property", "annotation_property"}),
    (_RDFS_RANGE,         "Range",
        {"object_property", "data_property", "annotation_property"}),
    # Property characteristics — special predicate (rdf:type) handled via its own keyword.
    (_RDF_TYPE,           "Characteristics",
        {"object_property", "data_property"}),
    # Individual axioms
    (_RDF_TYPE,           "Types",            {"individual"}),
    (_OWL_SAME_AS,        "SameAs",           {"individual"}),
    (_OWL_DIFFERENT,      "DifferentFrom",    {"individual"}),
    # Property assertions for individuals — wildcard predicate, handled below.
]

_ENTITY_KEYWORD: dict[str, str] = {
    "class":               "Class",
    "object_property":     "ObjectProperty",
    "data_property":       "DataProperty",
    "annotation_property": "AnnotationProperty",
    "individual":          "Individual",
}


def render_frame(
    store: ox.Store,
    entity_iri: str,
    entity_type: str,
    axiom_changes: list[dict],
    *,
    labels: dict[str, str],
) -> str | None:
    """Render a Protégé-style Manchester frame for one modified entity.

    `axiom_changes` is a list of dicts with keys:
      op:        'added' | 'removed'
      predicate: str (predicate IRI)
      object:    ox.Term
      graph:     ox.NamedNode (which named graph this change came from — needed
                 because bnode IDs differ between from-graph and to-graph)

    Returns None when no axiom_changes produce a renderable line.
    """
    # Render every change to a (op, keyword, line_text). Drop lines whose predicate
    # isn't covered (render_axiom returns None) — they don't appear in the frame.
    rendered: list[tuple[str, str, str]] = []  # (keyword, op, text)
    for change in axiom_changes:
        line = render_axiom(
            store, change["graph"], entity_iri,
            change["predicate"], change["object"],
            labels=labels, entity_type=entity_type,
        )
        if line is None:
            continue
        keyword, _, body = line.partition(": ")
        rendered.append((keyword, change["op"], body))

    if not rendered:
        return None

    # Group by keyword, preserving _FRAME_KEYWORD_ORDER. Unknown keywords go
    # to the end in insertion order.
    keyword_order: list[str] = []
    seen: set[str] = set()
    for pred, kw, types in _FRAME_KEYWORD_ORDER:
        if (types is None or entity_type in types) and kw not in seen:
            keyword_order.append(kw)
            seen.add(kw)
    # Always include 'Facts' last for individuals (assertion lines).
    if entity_type == "individual" and "Facts" not in seen:
        keyword_order.append("Facts")
        seen.add("Facts")
    # Any leftover keywords we didn't anticipate.
    for kw, _, _ in rendered:
        if kw not in seen:
            keyword_order.append(kw)
            seen.add(kw)

    # Build the frame. At this point `axiom_changes` is non-empty (else we
    # returned None above), so we can safely take a graph from the first change
    # to resolve the entity's label if not yet cached.
    entity_keyword = _ENTITY_KEYWORD.get(entity_type, "Entity")
    entity_label = iri_to_label(
        store, axiom_changes[0]["graph"], entity_iri, labels=labels,
    )
    lines: list[str] = [f"{entity_keyword}: {entity_label}  ({entity_iri})"]

    for kw in keyword_order:
        kw_lines = [(op, body) for k, op, body in rendered if k == kw]
        if not kw_lines:
            continue
        lines.append(f"    {kw}:")
        # Removed first, then added, alphabetical within each.
        removed = sorted([b for op, b in kw_lines if op == "removed"])
        added   = sorted([b for op, b in kw_lines if op == "added"])
        for body in removed:
            lines.append(f"-       {body}")
        for body in added:
            lines.append(f"+       {body}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v`
Expected: 65 passed (58 previous + 7 new).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): render_frame with header, keyword grouping, ordering"
```

---

## Task 14: Refactor `_structural_triples` to return terms alongside fingerprints

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`
- Modify: `tests/unit/test_diff_compute.py`

- [ ] **Step 1: Add a test that verifies the new return shape**

Append to `tests/unit/test_diff_compute.py`:

```python
def test_structural_triples_returns_terms_with_fingerprints():
    """The refactored helper must return both the comparable (pred, repr) set
    AND a lookup from (pred, repr) -> the actual ox.Term object, so the
    Manchester renderer can walk bnode subgraphs later."""
    from ontoexplorer.modules.diff.compute import _structural_triples
    iri = ox.NamedNode("http://example.org/Foo")
    obj_uri = ox.NamedNode("http://example.org/Bar")
    obj_bn  = ox.BlankNode("b1")
    store = ox.Store()
    g = ox.NamedNode("urn:test")
    store.add_graph(g)
    store.add(ox.Quad(iri, _RDFS_SC, obj_uri, g))
    store.add(ox.Quad(iri, _RDFS_SC, obj_bn,  g))
    store.add(ox.Quad(obj_bn, _RDF_TYPE,
                      ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction"), g))

    triples, terms = _structural_triples(store, g, iri.value)
    # Comparable set: two entries
    assert len(triples) == 2
    # NamedNode entry — direct lookup
    named_key = ("http://www.w3.org/2000/01/rdf-schema#subClassOf",
                 "http://example.org/Bar")
    assert named_key in triples
    assert terms[named_key].value == "http://example.org/Bar"
    assert isinstance(terms[named_key], ox.NamedNode)
    # BlankNode entry — repr is a fingerprint
    bn_keys = [k for k in triples if k[1].startswith("_:fp:")]
    assert len(bn_keys) == 1
    assert isinstance(terms[bn_keys[0]], ox.BlankNode)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_diff_compute.py::test_structural_triples_returns_terms_with_fingerprints -v`
Expected: FAILED — `_structural_triples` currently returns a bare set.

- [ ] **Step 3: Refactor `_structural_triples`**

In `ontoexplorer/modules/diff/compute.py`, replace the existing `_structural_triples`:

```python
def _structural_triples(
    store: ox.Store, graph: ox.NamedNode, iri: str
) -> tuple[set[tuple[str, str]], dict[tuple[str, str], ox.Term]]:
    """Return (comparable set, term lookup) for (predicate, object) triples.

    The comparable set is what `run_diff` set-diffs across versions; bnode
    objects are represented by their content fingerprint so structurally
    identical bnodes collapse. The lookup maps each (predicate, repr) key back
    to the original ox.Term, so the Manchester renderer can walk the bnode
    subgraph for display.
    """
    triples: set[tuple[str, str]] = set()
    terms: dict[tuple[str, str], ox.Term] = {}
    for q in store.quads_for_pattern(ox.NamedNode(iri), None, None, graph):
        if isinstance(q.object, ox.NamedNode):
            key = (q.predicate.value, q.object.value)
            triples.add(key)
            terms[key] = q.object
        elif isinstance(q.object, ox.BlankNode):
            fp = _bnode_fingerprint(store, graph, q.object.value)
            key = (q.predicate.value, f"_:fp:{fp}")
            triples.add(key)
            terms[key] = q.object
    return triples, terms
```

- [ ] **Step 4: Update existing `run_diff` callers**

In `run_diff` (same file), in the loop where `_structural_triples` is called, replace:

```python
            from_struct = _structural_triples(store, from_graph, iri)
            to_struct   = _structural_triples(store, to_graph, iri)
```

with:

```python
            from_struct, from_terms = _structural_triples(store, from_graph, iri)
            to_struct,   to_terms   = _structural_triples(store, to_graph, iri)
```

Leave the rest of the loop unchanged for now (next task wires the Manchester output in).

- [ ] **Step 5: Run all tests to verify nothing regressed**

Run: `uv run pytest tests/unit/test_diff_compute.py -v`
Expected: all previous tests pass + the new test passes.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/modules/diff/compute.py tests/unit/test_diff_compute.py
git commit -m "refactor(diff/compute): _structural_triples returns terms alongside fingerprints"
```

---

## Task 15: Integrate `render_frame` and `render_axiom` into `run_diff`

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`
- Modify: `tests/unit/test_diff_compute.py`

- [ ] **Step 1: Add a failing integration test**

Append to `tests/unit/test_diff_compute.py`:

```python
def test_run_diff_produces_manchester_frame_for_modified_entity():
    """A class whose only change is a SubClassOf restriction swap should yield
    a manchester_frame with header + keyword + - and + lines."""
    pizza = ox.NamedNode("http://example.org/Pizza")
    p = ox.NamedNode("http://example.org/hasTopping")
    cheese = ox.NamedNode("http://example.org/Cheese")
    tofu = ox.NamedNode("http://example.org/Tofu")
    OR = ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction")
    ON_P = ox.NamedNode("http://www.w3.org/2002/07/owl#onProperty")
    SOME = ox.NamedNode("http://www.w3.org/2002/07/owl#someValuesFrom")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")

    s = _store(
        from_quads=[
            (pizza, _RDF_TYPE, _OWL_CLASS),
            (pizza, label_pred, ox.Literal("Pizza", language="en")),
            (pizza, _RDFS_SC, ox.BlankNode("rOld")),
            (ox.BlankNode("rOld"), _RDF_TYPE, OR),
            (ox.BlankNode("rOld"), ON_P, p),
            (ox.BlankNode("rOld"), SOME, cheese),
        ],
        to_quads=[
            (pizza, _RDF_TYPE, _OWL_CLASS),
            (pizza, label_pred, ox.Literal("Pizza", language="en")),
            (pizza, _RDFS_SC, ox.BlankNode("rNew")),
            (ox.BlankNode("rNew"), _RDF_TYPE, OR),
            (ox.BlankNode("rNew"), ON_P, p),
            (ox.BlankNode("rNew"), SOME, tofu),
        ],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 1
    mod = diff_data["modified"][0]
    assert mod["iri"] == pizza.value
    frame = mod.get("manchester_frame")
    assert frame is not None, "manchester_frame must be populated for modified entities"
    expected = (
        f"Class: Pizza  ({pizza.value})\n"
        "    SubClassOf:\n"
        "-       hasTopping some Cheese\n"
        "+       hasTopping some Tofu"
    )
    assert frame == expected


def test_run_diff_axiom_changes_use_manchester_strings():
    """Each axiom_changes entry's axiom string is in Manchester format, not raw triple."""
    pizza = ox.NamedNode("http://example.org/Pizza")
    food = ox.NamedNode("http://example.org/Food")
    s = _store(
        from_quads=[(pizza, _RDF_TYPE, _OWL_CLASS)],
        to_quads=[
            (pizza, _RDF_TYPE, _OWL_CLASS),
            (pizza, _RDFS_SC, food),
        ],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    mod = diff_data["modified"][0]
    axiom_strs = [a["axiom"] for a in mod["axiom_changes"]]
    assert axiom_strs == ["SubClassOf: Food"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k manchester or axiom_changes_use_manchester`
Expected: 2 FAILED — `manchester_frame` key missing; axiom strings still in `<p> <o>` form.

- [ ] **Step 3: Wire renderer calls into `run_diff`**

In `ontoexplorer/modules/diff/compute.py`:

Near the top of the file, add the import:

```python
from ontoexplorer.modules.diff import manchester as _mos
```

In `run_diff`, inside the existing entity-comparison loop, replace the existing `axiom_changes` and the surrounding `modified_list.append(...)` block with:

```python
            if from_lits == to_lits and from_struct == to_struct:
                continue

            # Literal-level diff (unchanged from before).
            from_lits_map = {(p, lang): v for p, lang, v in from_lits - to_lits}
            to_lits_map   = {(p, lang): v for p, lang, v in to_lits   - from_lits}
            literal_changes = [
                {
                    "predicate": pred,
                    "lang": lang,
                    "removed": from_lits_map.get((pred, lang)),
                    "added":   to_lits_map.get((pred, lang)),
                }
                for pred, lang in sorted(
                    set(from_lits_map) | set(to_lits_map),
                    key=lambda t: (t[0], t[1] or ""),
                )
            ]

            # Structural-axiom diff: build (op, predicate, object_term, graph)
            # tuples first so the renderer can walk each bnode in its origin graph.
            change_records: list[dict] = []
            for p_iri, o_repr in sorted(from_struct - to_struct):
                change_records.append({
                    "op": "removed",
                    "predicate": p_iri,
                    "object": from_terms[(p_iri, o_repr)],
                    "graph": from_graph,
                })
            for p_iri, o_repr in sorted(to_struct - from_struct):
                change_records.append({
                    "op": "added",
                    "predicate": p_iri,
                    "object": to_terms[(p_iri, o_repr)],
                    "graph": to_graph,
                })

            # Manchester axiom_changes strings + frame.
            axiom_changes: list[dict] = []
            for rec in change_records:
                axiom_str = _mos.render_axiom(
                    store, rec["graph"], iri,
                    rec["predicate"], rec["object"],
                    labels=labels, entity_type=entity_type,
                )
                if axiom_str is None:
                    axiom_str = f"<{rec['predicate']}> <{rec['object'].value}>"
                axiom_changes.append({"op": rec["op"], "axiom": axiom_str})

            manchester_frame = _mos.render_frame(
                store, iri, entity_type, change_records, labels=labels,
            )

            label = _first_label(store, to_graph, iri) or _first_label(store, from_graph, iri)
            modified_list.append({
                "iri": iri,
                "label": label,
                "entity_type": entity_type,
                "literal_changes": literal_changes,
                "axiom_changes": axiom_changes,
                "manchester_frame": manchester_frame,
            })
```

Before the entity loop, after `from_graph` / `to_graph` are defined, add the shared label cache:

```python
    labels: dict[str, str] = {}
```

(Put it adjacent to `added_list`, `removed_list`, `modified_list`.)

- [ ] **Step 4: Run all tests to verify they pass**

Run: `uv run pytest tests/unit/test_diff_compute.py tests/unit/test_manchester_render.py -v`
Expected: all previous tests pass + the 2 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/compute.py tests/unit/test_diff_compute.py
git commit -m "feat(diff/compute): emit manchester_frame and Manchester axiom strings"
```

---

## Task 16: Add `manchester_frame` to the API contract

**Files:**
- Modify: `frontend/src/lib/api.ts`

The backend already returns `manchester_frame` as part of `diff_data.modified[]` (via the pass-through in `compute_diff` and the existing `/diff` route — no API code change needed since FastAPI serializes the dict directly). Only the TypeScript type needs updating.

- [ ] **Step 1: Add the field to `DiffEntity`**

In `frontend/src/lib/api.ts`, find the `DiffEntity` interface (around line 100):

```typescript
export interface DiffEntity {
  iri: string
  label: string | null
  entity_type: DiffEntityType
  literal_changes: DiffLiteralChange[]
  axiom_changes: DiffAxiomChange[]
}
```

Add the new field:

```typescript
export interface DiffEntity {
  iri: string
  label: string | null
  entity_type: DiffEntityType
  literal_changes: DiffLiteralChange[]
  axiom_changes: DiffAxiomChange[]
  manchester_frame: string | null
}
```

- [ ] **Step 2: Run frontend type-check to verify no regressions**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors related to `DiffEntity`. (The pre-existing error in `Sparql.test.tsx` from earlier session should still be the only failure — unrelated.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(api): add manchester_frame to DiffEntity type"
```

---

## Task 17: New `ManchesterFrame` frontend component

**Files:**
- Create: `frontend/src/components/ManchesterFrame.tsx`

- [ ] **Step 1: Create the component**

Write to `frontend/src/components/ManchesterFrame.tsx`:

```tsx
import React from 'react'

interface Props {
  frame: string
}

/**
 * Renders a Protégé-style Manchester OWL frame as a monospace block.
 * Lines starting with `-` are red (removed); `+` are green (added);
 * everything else is the default text color (header / keyword lines).
 */
export default function ManchesterFrame({ frame }: Props) {
  return (
    <pre
      style={{
        margin: 0,
        padding: '0.5rem 0.75rem',
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 4,
        fontFamily: 'var(--font-mono, ui-monospace, monospace)',
        fontSize: 12,
        lineHeight: 1.45,
        whiteSpace: 'pre',
        overflowX: 'auto',
      }}
    >
      {frame.split('\n').map((line, i) => {
        const color =
          line.startsWith('-') ? '#f85149' :
          line.startsWith('+') ? '#3fb950' :
          'var(--text)'
        return (
          <div key={i} style={{ color }}>{line}</div>
        )
      })}
    </pre>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ManchesterFrame.tsx
git commit -m "feat(frontend): ManchesterFrame component"
```

---

## Task 18: Wire `ManchesterFrame` into `HistoryTab.tsx`

**Files:**
- Modify: `frontend/src/components/HistoryTab.tsx`

- [ ] **Step 1: Replace the axiom_changes mapping**

In `frontend/src/components/HistoryTab.tsx`, find lines 117-130 (the `hasAxiom` block) and replace:

```tsx
          {hasAxiom && (
            <div>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Axiom changes</div>
              {entity.axiom_changes.map((ac, i) => (
                <div key={i} style={{ color: ac.op === 'added' ? '#3fb950' : '#f85149', fontSize: 10 }}>
                  <HighlightedText
                    text={`${ac.op === 'added' ? '+' : '−'} ${ac.axiom}`}
                    query={search}
                    color={ac.op === 'added' ? '#3fb950' : '#f85149'}
                  />
                </div>
              ))}
            </div>
          )}
```

with:

```tsx
          {entity.manchester_frame && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Axiom changes</div>
              <ManchesterFrame frame={entity.manchester_frame} />
            </div>
          )}
```

Add the import at the top of the file (after the existing imports):

```tsx
import ManchesterFrame from './ManchesterFrame'
```

The pre-existing variable `hasAxiom` near line 53 is now unused for rendering but still consumed by the keyboard-filter logic at line 186 (`changeFilter === 'axiom'`). Leave it in place — its truthiness still matches the new render condition (a non-empty `axiom_changes` array implies the frame will have content, modulo unknown predicates which the user is unlikely to filter on anyway).

- [ ] **Step 2: Run frontend type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Visual verification in the browser**

- Ensure dev servers are running: `docker compose ps` should show `api` and `frontend` healthy.
- Open `http://localhost:5173/ontologies/pizza` in a browser.
- Navigate to the History tab.
- Select version 0.0.11 in the "from" dropdown and 0.0.12 in the "to" dropdown (or vice versa).
- Confirm that for any modified entity, the **Axiom changes** block now shows a Protégé-style frame with `Class: <label>  (<IRI>)`, a `SubClassOf:` keyword line, and `-` / `+` axiom lines in red / green.

(The pizza versions 0.0.11 and 0.0.12 happen to be semantically identical after the bnode-fingerprint fix from earlier in the session, so `modified` may be empty for this specific pair. Use whatever ontology has real differences in your local DB, or temporarily ingest a third pizza version with a different topping.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/HistoryTab.tsx
git commit -m "feat(frontend): render Manchester frame in diff Axiom changes block"
```

---

## Self-Review Checklist

Run through this once before declaring the plan complete.

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| `iri_to_label` (Renderer module API) | Task 2 |
| `render_class_expression` (Renderer module API) | Tasks 4-9 |
| `render_axiom` (Renderer module API) | Tasks 10-12 |
| `render_frame` (Renderer module API) | Task 13 |
| Axiom coverage table (SubClassOf, EquivalentTo, DisjointWith, DisjointUnionOf, SubPropertyOf, EquivalentTo property, InverseOf, Domain, Range, Characteristics, SameAs, DifferentFrom, Types, Facts) | Tasks 10-12 |
| Class expression coverage table (named, some/only/value/Self, cardinality, intersection/union/complement, oneOf, datatype restriction) | Tasks 4-8 |
| Fallback for unrecognized bnodes (`[bnode:<fp>]`) | Task 4 |
| Depth limit at 10 | Tasks 4, 9 |
| Frame structure (header, keyword grouping, ordering, `-` before `+`) | Task 13 |
| Empty frame → null | Task 13 (`test_render_frame_class_header_with_label`) |
| Frontend renders frame in `<pre>` with line coloring | Tasks 17-18 |
| `DiffEntity.manchester_frame: string \| null` field | Task 16 |
| `axiom_changes[i].axiom` upgraded to Manchester format | Task 15 |
| Backend integration in `compute.py` | Tasks 14-15 |

All spec sections are addressed.

**2. Placeholder scan:** none of "TBD", "TODO", "implement later", "fill in details", "Add appropriate error handling", "Similar to Task N" appear. Every step has explicit code or commands.

**3. Type consistency:**

- `render_axiom(...)` signature: `(store, graph, subject_iri, predicate_iri, object_term, *, labels, entity_type=None) -> str | None` — used consistently from Task 10 onward.
- `render_frame(...)` signature: `(store, entity_iri, entity_type, axiom_changes, *, labels) -> str | None` — `axiom_changes` is `list[dict]` with keys `op`, `predicate`, `object`, `graph`. Used consistently in Tasks 13 and 15.
- `_structural_triples(...)` return type changes in Task 14 from `set[tuple[str, str]]` to `tuple[set, dict]`. Task 15 updates the caller. No intermediate task between 14 and 15 calls the old shape.
- `manchester_frame` field name spelled consistently in API type (Task 16), backend dict (Task 15), and frontend component (Tasks 17-18).

**4. Self-check on testability:** every implementation task has a test step before it, and an expected outcome (PASS / FAIL with reason).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-manchester-diff-rendering-phase-1.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
