# Manchester Diff — Phase 3 (Clickable IRIs + Hover Tooltips) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat-string `manchester_frame` field (Phases 1 / 2) with a structured token tree so the frontend can render in-ontology IRIs as React Router links and surface the full IRI on hover.

**Architecture:** Every backend rendering helper (`render_class_expression`, `_render_restriction`, `_render_junction`, `_render_datatype_restriction`, `_render_literal`, `_render_annotation_value`, `render_axiom`, `render_frame`) changes its return type from `str` to a list of `ManchesterToken` (text or iri). A `_known_iris(store, graph) -> set[str]` SPARQL pre-pass once per `_run_diff_core` populates the `in_ontology` flag on every emitted IRI token. The frontend `ManchesterFrame` component is rewritten to consume the new shape and emit `<Link>` for in-ontology IRIs / `<span title>` for external ones.

**Tech Stack:** Python 3.11+ (TypedDict for token shapes, pyoxigraph for the SPARQL pre-pass), pytest. React + React Router on the frontend (`<Link>` with `?term=<iri>` query param).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ontoexplorer/modules/diff/manchester.py` | MODIFY | All renderers return tokens; new `_known_iris` and `_iri_token` helpers; new `ManchesterToken` / `ManchesterLine` / `ManchesterFrame` TypedDicts |
| `ontoexplorer/modules/diff/compute.py` | MODIFY | Compute `known_iris` once per run, thread through every `render_frame` call; replace `manchester_frame: str | None` with the structured object |
| `tests/unit/test_manchester_render.py` | MODIFY | Refactor existing tests to assert token shapes; add tests for `in_ontology` and clickability behavior |
| `tests/unit/test_diff_compute.py` | MODIFY | Update added/removed/modified frame assertions to read from the structured object; add `_known_iris` SPARQL test |
| `frontend/src/lib/api.ts` | MODIFY | Update `OntologyComparison` / diff types to new `manchester_frame` shape |
| `frontend/src/components/ManchesterFrame.tsx` | REWRITE | Render tokens; `<Link>` for in-ontology IRIs, `<span title>` otherwise |
| `frontend/src/components/ManchesterFrame.test.tsx` | CREATE | Test the new component renders links + tooltips correctly |
| `frontend/src/components/DiffResultView.tsx` | MODIFY | Accept `fromShortname` / `toShortname` props; pass per-entity shortname into `ManchesterFrame` |
| `frontend/src/pages/HistoryTab.tsx` / wherever DiffResultView is consumed | MODIFY | Pass the ontology shortname into `DiffResultView` |
| `frontend/src/pages/Compare.tsx` | MODIFY | Pass `fromShortname` / `toShortname` from the picked ontologies |

The flat-string `manchester_frame` field is removed in a single PR; per the spec, this is an intentional breaking JSON change with no external consumers.

---

## Task 1: Token type definitions + `_text_token` helper

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`

- [ ] **Step 1: Add the TypedDicts and a `_text` helper**

In `ontoexplorer/modules/diff/manchester.py`, near the top of the file (after the existing constants block, before `_to_curie`), add:

```python
from typing import TypedDict, Literal, NotRequired


class TextToken(TypedDict):
    t: Literal["text"]
    v: str


class IriToken(TypedDict):
    t: Literal["iri"]
    label: str
    iri: str
    in_ontology: bool


ManchesterToken = TextToken | IriToken


class ManchesterLine(TypedDict):
    op: Literal["added", "removed"] | None
    tokens: list[ManchesterToken]


class ManchesterFrame(TypedDict):
    lines: list[ManchesterLine]


def _text(v: str) -> TextToken:
    """Build a text token (whitespace, keyword, punctuation, operator)."""
    return {"t": "text", "v": v}
```

`Literal` may already be imported (from Phase 2 Task 5). If so, don't re-import — extend the existing `from typing import Literal` line to `from typing import Literal, TypedDict, NotRequired`.

- [ ] **Step 2: Sanity-check the import**

Run: `cd /path/to/ontoexplorer && uv run python -c "from ontoexplorer.modules.diff.manchester import _text, TextToken, IriToken, ManchesterLine, ManchesterFrame; print(_text('hi'))"`

Expected: `{'t': 'text', 'v': 'hi'}`

- [ ] **Step 3: Commit**

```bash
cd /path/to/ontoexplorer
git add ontoexplorer/modules/diff/manchester.py
git commit -m "feat(diff/manchester): token type definitions and _text helper"
```

---

## Task 2: `_known_iris` SPARQL pre-pass

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
from ontoexplorer.modules.diff.manchester import _known_iris


def test_known_iris_returns_subjects_and_iri_objects():
    """_known_iris collects every IRI that appears as subject OR as iri-typed object."""
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    c = ox.NamedNode("http://example.org/C")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = _store(
        (a, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2002/07/owl#Class")),
        (a, _RDFS_SUB_N, b),
        (a, label_pred, ox.Literal("A")),
        (b, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2002/07/owl#Class")),
        # c appears only as object, never as subject
    )
    store.add(ox.Quad(a, _RDFS_SUB_N, c, _GRAPH))
    known = _known_iris(store, _GRAPH)
    assert a.value in known
    assert b.value in known
    assert c.value in known
    # rdfs:label predicate IRI should NOT appear because the helper restricts
    # to subjects + iri-typed objects, and we never asked about predicates.
    # (Predicates also aren't in_ontology candidates.)
    # The literal "A" should NOT appear.
    assert '"A"' not in known


def test_known_iris_returns_empty_for_empty_graph():
    store = _store()
    assert _known_iris(store, _GRAPH) == frozenset()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /path/to/ontoexplorer && uv run pytest tests/unit/test_manchester_render.py -v -k known_iris 2>&1 | tail -5`

Expected: 2 FAILED (cannot import `_known_iris`).

- [ ] **Step 3: Add the helper**

Append to `ontoexplorer/modules/diff/manchester.py`:

```python
def _known_iris(store: ox.Store, graph: ox.NamedNode) -> frozenset[str]:
    """Return every IRI that appears as a subject OR an IRI-valued object in `graph`.

    Used to set `in_ontology=True` on IRI tokens when rendering Manchester
    frames: the frontend will turn matching tokens into clickable links to
    the entity's term page. IRIs reachable only as predicates are excluded
    (predicates are never click targets in this UI).
    """
    out: set[str] = set()
    for q in store.quads_for_pattern(None, None, None, graph):
        if isinstance(q.subject, ox.NamedNode):
            out.add(q.subject.value)
        if isinstance(q.object, ox.NamedNode):
            out.add(q.object.value)
    return frozenset(out)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k known_iris 2>&1 | tail -5`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): _known_iris SPARQL pre-pass for clickability"
```

---

## Task 3: `_iri_token` builder

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
from ontoexplorer.modules.diff.manchester import _iri_token


def test_iri_token_uses_label_when_known_and_marks_in_ontology():
    pizza = "http://example.org/Pizza"
    store = _store(
        (ox.NamedNode(pizza), _RDFS_LABEL_N, ox.Literal("Pizza", language="en")),
    )
    tok = _iri_token(
        store, _GRAPH, pizza,
        labels={pizza: "Pizza"},  # already cached
        known_iris=frozenset({pizza}),
    )
    assert tok == {"t": "iri", "label": "Pizza", "iri": pizza, "in_ontology": True}


def test_iri_token_falls_back_to_local_name_when_no_label():
    iri = "http://example.org/UnlabeledThing"
    tok = _iri_token(
        store=_store(), graph=_GRAPH, iri=iri,
        labels={}, known_iris=frozenset(),
    )
    assert tok == {"t": "iri", "label": "UnlabeledThing", "iri": iri, "in_ontology": False}


def test_iri_token_marks_external_iri_in_ontology_false():
    iri = "http://other.org/X"
    tok = _iri_token(
        store=_store(), graph=_GRAPH, iri=iri,
        labels={}, known_iris=frozenset({"http://example.org/Y"}),
    )
    assert tok["in_ontology"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k iri_token 2>&1 | tail -5`

Expected: 3 FAILED (cannot import `_iri_token`).

- [ ] **Step 3: Add the helper**

Append to `ontoexplorer/modules/diff/manchester.py`:

```python
def _iri_token(
    store: ox.Store,
    graph: ox.NamedNode,
    iri: str,
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
) -> IriToken:
    """Build an IRI token with display label and in_ontology flag.

    `labels` is the per-run cache populated incrementally as entities are
    rendered. `known_iris` is the pre-computed set from `_known_iris`.
    """
    label = iri_to_label(store, graph, iri, labels=labels)
    return {
        "t": "iri",
        "label": label,
        "iri": iri,
        "in_ontology": iri in known_iris,
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k iri_token 2>&1 | tail -5`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): _iri_token builder with in_ontology flag"
```

---

## Task 4: Convert `_render_literal` to return tokens

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Update the test for `_render_literal`**

Find any existing `test_render_literal_*` tests in `tests/unit/test_manchester_render.py`. Update them to assert the token shape. Add a fresh test as well:

```python
def test_render_literal_returns_single_text_token():
    out = _render_literal(ox.Literal("Pizza", language="en"))
    assert out == [{"t": "text", "v": '"Pizza"@en'}]


def test_render_literal_suppresses_xsd_string_datatype():
    out = _render_literal(ox.Literal("Pizza"))
    assert out == [{"t": "text", "v": '"Pizza"'}]


def test_render_literal_renders_xsd_integer():
    out = _render_literal(
        ox.Literal("42", datatype=ox.NamedNode("http://www.w3.org/2001/XMLSchema#integer")),
    )
    assert out == [{"t": "text", "v": '"42"^^xsd:integer'}]
```

If any pre-existing test asserts `_render_literal` returns a `str`, rewrite it to expect a list with one text token. There should be at most a handful.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k "render_literal" 2>&1 | tail -10`

Expected: existing render_literal tests FAIL (still return strings); the 3 new ones FAIL.

- [ ] **Step 3: Update `_render_literal`**

In `ontoexplorer/modules/diff/manchester.py`, replace the body of `_render_literal`:

```python
def _render_literal(lit: ox.Literal) -> list[ManchesterToken]:
    """Manchester-style literal as a single text token: "value"[@lang][^^xsd:dtype]."""
    text = f'"{lit.value}"'
    if lit.language:
        return [_text(f"{text}@{lit.language}")]
    if lit.datatype is not None and lit.datatype.value != _XSD_STRING:
        dt = lit.datatype.value
        if dt.startswith(_XSD):
            return [_text(f"{text}^^xsd:{dt[len(_XSD):]}")]
        return [_text(f"{text}^^<{dt}>")]
    return [_text(text)]
```

- [ ] **Step 4: Run to verify tests pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k "render_literal" 2>&1 | tail -5`

Expected: all `render_literal` tests pass. **Other tests in the file will fail** because they depend on the old `str` return type of `render_class_expression`/`render_axiom`/`render_frame` — those are fixed in subsequent tasks. Don't worry about them yet.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "refactor(diff/manchester): _render_literal returns token list"
```

---

## Task 5: Convert `render_class_expression` and bnode helpers to return tokens

This is the biggest refactor in the plan. Every helper that builds a Manchester class-expression substring (`_render_bnode_expression`, `_render_restriction`, `_render_junction`, `_render_datatype_restriction`, `_bnode_fallback`) now returns `list[ManchesterToken]`. Every caller switches from `f"{a} some {b}"` to `a + [_text(" some ")] + b`.

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add tests for `render_class_expression`**

Append to `tests/unit/test_manchester_render.py`:

```python
def test_render_class_expression_named_class_returns_iri_token():
    pizza = "http://example.org/Pizza"
    store = _store()
    out = render_class_expression(
        store, _GRAPH, ox.NamedNode(pizza),
        labels={pizza: "Pizza"},
        known_iris=frozenset({pizza}),
    )
    assert out == [{"t": "iri", "label": "Pizza", "iri": pizza, "in_ontology": True}]


def test_render_class_expression_some_restriction_emits_iri_text_iri():
    """Restriction (hasTopping some Tomato) → 3 tokens: prop IRI, ' some ', filler IRI."""
    has_topping = ox.NamedNode("http://example.org/hasTopping")
    tomato      = ox.NamedNode("http://example.org/Tomato")
    bnode = ox.BlankNode()
    store = _store(
        (bnode, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2002/07/owl#Restriction")),
        (bnode, ox.NamedNode("http://www.w3.org/2002/07/owl#onProperty"), has_topping),
        (bnode, ox.NamedNode("http://www.w3.org/2002/07/owl#someValuesFrom"), tomato),
    )
    out = render_class_expression(
        store, _GRAPH, bnode,
        labels={},
        known_iris=frozenset({has_topping.value, tomato.value}),
    )
    assert out == [
        {"t": "iri", "label": "hasTopping", "iri": has_topping.value, "in_ontology": True},
        {"t": "text", "v": " some "},
        {"t": "iri", "label": "Tomato", "iri": tomato.value, "in_ontology": True},
    ]


def test_render_class_expression_intersection_emits_with_and_separators():
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")
    bnode = ox.BlankNode()
    # Build an rdf:List of [a, b].
    n1, n2 = ox.BlankNode(), ox.BlankNode()
    store = _store(
        (bnode, _RDF_TYPE_N, ox.NamedNode("http://www.w3.org/2002/07/owl#Class")),
        (bnode, ox.NamedNode("http://www.w3.org/2002/07/owl#intersectionOf"), n1),
        (n1, ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first"), a),
        (n1, ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"), n2),
        (n2, ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#first"), b),
        (n2, ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"),
            ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#nil")),
    )
    out = render_class_expression(
        store, _GRAPH, bnode,
        labels={},
        known_iris=frozenset({a.value, b.value}),
    )
    # Tokens: (A) " and " (B)
    iri_tokens = [t for t in out if t["t"] == "iri"]
    text_tokens = [t for t in out if t["t"] == "text"]
    assert [t["iri"] for t in iri_tokens] == [a.value, b.value]
    assert " and " in [t["v"] for t in text_tokens]
```

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k "class_expression" 2>&1 | tail -10`

Expected: tests fail (signature mismatch — `known_iris` keyword arg).

- [ ] **Step 3: Replace `render_class_expression` and its descendants**

In `ontoexplorer/modules/diff/manchester.py`, replace these functions entirely. Every helper now takes `known_iris` as a keyword-only argument and returns `list[ManchesterToken]`. Concatenation replaces f-string interpolation.

```python
def render_class_expression(
    store: ox.Store,
    graph: ox.NamedNode,
    node: ox.Term,
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
    depth: int = 0,
) -> list[ManchesterToken]:
    if depth >= _MAX_DEPTH:
        return [_text("…")]
    if isinstance(node, ox.NamedNode):
        return [_iri_token(store, graph, node.value, labels=labels, known_iris=known_iris)]
    if isinstance(node, ox.Literal):
        return _render_literal(node)
    if isinstance(node, ox.BlankNode):
        return _render_bnode_expression(
            store, graph, node, labels=labels, known_iris=known_iris, depth=depth,
        )
    return [_text(f"[unknown:{node!r}]")]


def _render_bnode_expression(
    store: ox.Store,
    graph: ox.NamedNode,
    node: ox.BlankNode,
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
    depth: int,
) -> list[ManchesterToken]:
    preds = _bnode_predicates(store, graph, node)

    if _OWL_INTERSECTION in preds:
        return _render_junction(
            store, graph, preds[_OWL_INTERSECTION], "and",
            labels=labels, known_iris=known_iris, depth=depth,
        )
    if _OWL_UNION in preds:
        return _render_junction(
            store, graph, preds[_OWL_UNION], "or",
            labels=labels, known_iris=known_iris, depth=depth,
        )
    if _OWL_COMPLEMENT in preds:
        inner = render_class_expression(
            store, graph, preds[_OWL_COMPLEMENT],
            labels=labels, known_iris=known_iris, depth=depth + 1,
        )
        return [_text("not "), *inner]
    if _OWL_ONE_OF in preds:
        items = _rdf_list_items(store, graph, preds[_OWL_ONE_OF])
        rendered: list[list[ManchesterToken]] = [
            render_class_expression(store, graph, it, labels=labels, known_iris=known_iris, depth=depth + 1)
            for it in items
        ]
        toks: list[ManchesterToken] = [_text("{")]
        for i, r in enumerate(rendered):
            if i > 0:
                toks.append(_text(", "))
            toks.extend(r)
        toks.append(_text("}"))
        return toks
    if _OWL_ON_PROPERTY in preds:
        return _render_restriction(
            store, graph, preds, labels=labels, known_iris=known_iris, depth=depth,
        )
    if _OWL_ON_DATATYPE in preds:
        return _render_datatype_restriction(
            store, graph, preds, labels=labels, known_iris=known_iris, depth=depth,
        )
    return _bnode_fallback(store, graph, node)


def _render_restriction(
    store: ox.Store,
    graph: ox.NamedNode,
    preds: dict[str, ox.Term],
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
    depth: int,
) -> list[ManchesterToken]:
    prop_tokens = render_class_expression(
        store, graph, preds[_OWL_ON_PROPERTY],
        labels=labels, known_iris=known_iris, depth=depth + 1,
    )

    def _with_keyword(kw: str, filler_term: ox.Term) -> list[ManchesterToken]:
        filler = render_class_expression(
            store, graph, filler_term,
            labels=labels, known_iris=known_iris, depth=depth + 1,
        )
        return prop_tokens + [_text(f" {kw} ")] + filler

    if _OWL_SOME_VALUES in preds: return _with_keyword("some", preds[_OWL_SOME_VALUES])
    if _OWL_ALL_VALUES  in preds: return _with_keyword("only", preds[_OWL_ALL_VALUES])
    if _OWL_HAS_VALUE   in preds: return _with_keyword("value", preds[_OWL_HAS_VALUE])
    if _OWL_HAS_SELF    in preds:
        v = preds[_OWL_HAS_SELF]
        if (
            isinstance(v, ox.Literal)
            and v.value == _XSD_TRUE_LITERAL
            and v.datatype is not None
            and v.datatype.value == _XSD_BOOLEAN
        ):
            return prop_tokens + [_text(" Self")]
        # hasSelf false / non-boolean falls through.

    for card_pred, kw in (
        (_OWL_CARDINALITY, "exactly"),
        (_OWL_MIN_CARD,    "min"),
        (_OWL_MAX_CARD,    "max"),
    ):
        if card_pred in preds:
            n = preds[card_pred]
            if isinstance(n, ox.Literal):
                return prop_tokens + [_text(f" {kw} {n.value}")]

    for card_pred, kw in (
        (_OWL_QCARDINALITY, "exactly"),
        (_OWL_MIN_QCARD,    "min"),
        (_OWL_MAX_QCARD,    "max"),
    ):
        if card_pred in preds:
            n = preds[card_pred]
            if isinstance(n, ox.Literal):
                on_class = preds.get(_OWL_ON_CLASS) or preds.get(_OWL_ON_DATARANGE)
                if on_class is not None:
                    filler = render_class_expression(
                        store, graph, on_class,
                        labels=labels, known_iris=known_iris, depth=depth + 1,
                    )
                    return prop_tokens + [_text(f" {kw} {n.value} ")] + filler
                return prop_tokens + [_text(f" {kw} {n.value}")]

    return [_text("[restriction:")] + prop_tokens + [_text("]")]


def _render_junction(
    store: ox.Store,
    graph: ox.NamedNode,
    list_head: ox.Term,
    op: str,
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
    depth: int,
) -> list[ManchesterToken]:
    items = _rdf_list_items(store, graph, list_head)
    if not items:
        return [_text(f"[empty-{op}]")]
    pieces = [
        render_class_expression(store, graph, it, labels=labels, known_iris=known_iris, depth=depth + 1)
        for it in items
    ]
    toks: list[ManchesterToken] = []
    for i, p in enumerate(pieces):
        if i > 0:
            toks.append(_text(f" {op} "))
        toks.extend(p)
    return toks


def _render_datatype_restriction(
    store: ox.Store,
    graph: ox.NamedNode,
    preds: dict[str, ox.Term],
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
    depth: int,
) -> list[ManchesterToken]:
    # Existing logic prints `xsd:int[>= 0]` style facets. Keep the rendering
    # algorithm; only swap the str-concatenation for token-list concatenation.
    # See the pre-refactor function for the facet-walking logic — preserve it
    # verbatim and emit each substring as a _text token, while the on_datatype
    # IRI becomes an _iri_token.
    dt = preds[_OWL_ON_DATATYPE]
    if isinstance(dt, ox.NamedNode):
        base = [_iri_token(store, graph, dt.value, labels=labels, known_iris=known_iris)]
    else:
        base = render_class_expression(
            store, graph, dt, labels=labels, known_iris=known_iris, depth=depth + 1,
        )
    if _OWL_WITH_RESTRICTIONS not in preds:
        return base
    list_head = preds[_OWL_WITH_RESTRICTIONS]
    facet_nodes = _rdf_list_items(store, graph, list_head)
    facets: list[str] = []
    for fn in facet_nodes:
        if not isinstance(fn, ox.BlankNode):
            continue
        for q in store.quads_for_pattern(fn, None, None, graph):
            pred = q.predicate.value
            if pred.startswith(_XSD) and isinstance(q.object, ox.Literal):
                facets.append(f"{_FACET_OPS.get(pred, pred[len(_XSD):])} {q.object.value}")
    if not facets:
        return base
    return base + [_text("[" + ", ".join(facets) + "]")]


def _bnode_fallback(
    store: ox.Store, graph: ox.NamedNode, node: ox.BlankNode,
) -> list[ManchesterToken]:
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
    fp = hashlib.sha1("\n".join(parts).encode()).hexdigest()[:8] if parts else "empty"
    return [_text(f"[bnode:{fp}]")]
```

If `_render_datatype_restriction`'s pre-refactor body diverges from the simplified version above (for example, it handles additional patterns), preserve the divergent behavior — only swap the string returns for token lists. Read the existing function before replacing.

If `hashlib` isn't imported at the top of the file already, add `import hashlib`.

- [ ] **Step 4: Run new + adjacent tests**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k "class_expression or restriction or junction or bnode" 2>&1 | tail -15`

Expected: the new tests pass. Other tests still failing because `render_axiom` / `render_frame` haven't been updated yet — that's normal.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "refactor(diff/manchester): class expression renderers return tokens"
```

---

## Task 6: Convert `render_axiom` and `_render_annotation_value` to return tokens

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Rewrite the existing `render_axiom` tests to assert token shape**

Tests previously asserted strings like `'Annotations: rdfs:label "Foo"@en'`. Update them to inspect tokens. Below are the rewritten versions of the Phase 2 annotation tests. Replace the original Phase 2 annotation tests with these:

```python
def test_render_axiom_rdfs_label_annotation_emits_token_line():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _RDFS_LABEL_N.value,
        ox.Literal("Foo", language="en"),
        labels={},
        known_iris=frozenset(),
        annotation_props=_BUILTIN_ANNOTATION_PROPS,
    )
    assert out is not None
    # tokens: "Annotations: rdfs:label " + literal-text
    assert out[0]["t"] == "text"
    assert out[0]["v"] == "Annotations: rdfs:label "
    assert out[1] == {"t": "text", "v": '"Foo"@en'}


def test_render_axiom_custom_annotation_property_emits_iri_token_in_pred_position():
    """Non-CURIE annotation predicate renders as an IRI token (clickable when known)."""
    custom_pred = "http://example.org/myAnn"
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", custom_pred,
        ox.Literal("custom note"),
        labels={},
        known_iris=frozenset({custom_pred}),
        annotation_props=frozenset({custom_pred}),
    )
    assert out is not None
    # tokens: "Annotations: " + IriToken(custom_pred) + " " + text(literal)
    assert out[0] == {"t": "text", "v": "Annotations: "}
    assert out[1]["t"] == "iri"
    assert out[1]["iri"] == custom_pred
    assert out[1]["in_ontology"] is True


def test_render_axiom_subclassof_emits_keyword_text_then_iri_token():
    food = ox.NamedNode("http://example.org/Food")
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Pizza", _RDFS_SUB_N.value, food,
        labels={},
        known_iris=frozenset({food.value}),
    )
    assert out is not None
    assert out[0] == {"t": "text", "v": "SubClassOf: "}
    assert out[1] == {"t": "iri", "label": "Food", "iri": food.value, "in_ontology": True}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k "axiom" 2>&1 | tail -10`

Expected: existing render_axiom tests fail.

- [ ] **Step 3: Replace `render_axiom` and `_render_annotation_value`**

In `ontoexplorer/modules/diff/manchester.py`, replace these two functions. The new signature accepts `known_iris` (required). The keyword string (`"SubClassOf: "`, `"Annotations: "`, etc.) becomes a text token; the filler is tokens from `render_class_expression`.

```python
def render_axiom(
    store: ox.Store,
    graph: ox.NamedNode,
    subject_iri: str,
    predicate_iri: str,
    object_term: ox.Term,
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
    entity_type: str | None = None,
    annotation_props: frozenset[str] = _BUILTIN_ANNOTATION_PROPS,
) -> list[ManchesterToken] | None:
    """Return a token list `[keyword-text, ...filler-tokens]`, or None for non-renderable triples.

    The keyword text token always ends with `": "` so the caller can split on
    `": "` to recover the keyword for keyword-block grouping in render_frame.
    """
    if predicate_iri in annotation_props:
        curie = _to_curie(predicate_iri)
        if curie.startswith("<"):
            # Non-builtin namespace → emit predicate as a clickable IRI token.
            value = _render_annotation_value(
                store, graph, object_term, labels=labels, known_iris=known_iris,
            )
            return [
                _text("Annotations: "),
                _iri_token(store, graph, predicate_iri, labels=labels, known_iris=known_iris),
                _text(" "),
                *value,
            ]
        value = _render_annotation_value(
            store, graph, object_term, labels=labels, known_iris=known_iris,
        )
        return [_text(f"Annotations: {curie} "), *value]

    if entity_type == "individual":
        if predicate_iri == _RDF_TYPE:
            filler = render_class_expression(
                store, graph, object_term, labels=labels, known_iris=known_iris,
            )
            return [_text("Types: "), *filler]
        if predicate_iri in _INDIVIDUAL_AXIOMS:
            keyword = _INDIVIDUAL_AXIOMS[predicate_iri]
            filler = render_class_expression(
                store, graph, object_term, labels=labels, known_iris=known_iris,
            )
            return [_text(f"{keyword}: "), *filler]
        # Property assertion (Facts:).
        prop_tok = _iri_token(store, graph, predicate_iri, labels=labels, known_iris=known_iris)
        value = render_class_expression(
            store, graph, object_term, labels=labels, known_iris=known_iris,
        )
        return [_text("Facts: "), prop_tok, _text(" "), *value]

    if predicate_iri == _RDF_TYPE and isinstance(object_term, ox.NamedNode):
        char = _CHARACTERISTICS.get(object_term.value)
        if char is not None:
            return [_text(f"Characteristics: {char}")]
        return None

    keyword = (
        _CLASS_AXIOMS.get(predicate_iri)
        or _PROPERTY_AXIOMS.get(predicate_iri)
        or _INDIVIDUAL_AXIOMS.get(predicate_iri)
    )
    if keyword is None:
        return None
    filler = render_class_expression(
        store, graph, object_term, labels=labels, known_iris=known_iris,
    )
    return [_text(f"{keyword}: "), *filler]


def _render_annotation_value(
    store: ox.Store,
    graph: ox.NamedNode,
    obj: ox.Term,
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
) -> list[ManchesterToken]:
    if isinstance(obj, ox.Literal):
        return _render_literal(obj)
    return render_class_expression(
        store, graph, obj, labels=labels, known_iris=known_iris,
    )
```

- [ ] **Step 4: Run all `render_axiom` tests**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k axiom 2>&1 | tail -15`

Expected: all `render_axiom` tests pass. (`render_frame` tests still fail; fixed next task.)

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "refactor(diff/manchester): render_axiom returns token list"
```

---

## Task 7: Convert `render_frame` to return `ManchesterFrame`

`render_frame` previously assembled the frame as a list of formatted strings ("Class: Pizza  (...)", "    SubClassOf:", "+       Food"). Now it builds `ManchesterLine` records — each line is `{op, tokens}`. The `op` carries `+ `/`- ` / `null` for keyword/header lines.

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Rewrite `render_frame` tests to assert the structured shape**

Replace all existing `render_frame_*` tests in `tests/unit/test_manchester_render.py` with the rewritten versions below. The new tests inspect `frame["lines"]` rather than splitting strings.

```python
def test_render_frame_modified_class_returns_structured_lines():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
    )
    assert frame is not None
    # Header line: op=None, tokens contain the entity-keyword text and the entity-IRI token.
    header = frame["lines"][0]
    assert header["op"] is None
    assert any(t["t"] == "iri" and t["iri"] == iri for t in header["tokens"])
    # Keyword line for SubClassOf: op=None.
    kw_line = next(l for l in frame["lines"] if any(t.get("v") == "SubClassOf:" or "SubClassOf" in t.get("v", "") for t in l["tokens"] if t["t"] == "text"))
    assert kw_line["op"] is None
    # Added body line: op='added', tokens include the food IRI as iri token.
    body = next(
        l for l in frame["lines"]
        if l["op"] == "added"
        and any(t["t"] == "iri" and t["iri"] == food.value for t in l["tokens"])
    )
    assert body is not None


def test_render_frame_op_added_marks_every_line_with_op_added():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
        op="added",
    )
    assert frame is not None
    assert all(line["op"] == "added" for line in frame["lines"]), \
        f"every line must have op='added', got: {frame['lines']}"


def test_render_frame_op_removed_marks_every_line_with_op_removed():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "removed", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
        op="removed",
    )
    assert frame is not None
    assert all(line["op"] == "removed" for line in frame["lines"])


def test_render_frame_bare_added_class_yields_single_header_line():
    bare = "http://example.org/Bare"
    store = _store()
    frame = render_frame(
        store, bare, "class",
        axiom_changes=[],
        labels={},
        known_iris=frozenset({bare}),
        op="added",
    )
    assert frame is not None
    assert len(frame["lines"]) == 1
    header = frame["lines"][0]
    assert header["op"] == "added"
    # Header contains the entity IRI token.
    assert any(t["t"] == "iri" and t["iri"] == bare for t in header["tokens"])


def test_render_frame_annotations_block_appears_before_subclassof():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_LABEL_N.value,
             "object": ox.Literal("Pizza", language="en"), "graph": _GRAPH},
            {"op": "added", "predicate": _RDFS_SUB_N.value,
             "object": food, "graph": _GRAPH},
        ],
        labels={},
        known_iris=frozenset({iri, food.value}),
        op="added",
    )
    assert frame is not None
    keyword_indices = {}
    for i, line in enumerate(frame["lines"]):
        for t in line["tokens"]:
            if t["t"] == "text":
                if "Annotations:" in t["v"]:
                    keyword_indices.setdefault("Annotations", i)
                if "SubClassOf:" in t["v"]:
                    keyword_indices.setdefault("SubClassOf", i)
    assert "Annotations" in keyword_indices and "SubClassOf" in keyword_indices
    assert keyword_indices["Annotations"] < keyword_indices["SubClassOf"]
```

- [ ] **Step 2: Run to verify the rewritten tests fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k "render_frame" 2>&1 | tail -20`

Expected: all `render_frame` tests fail — old signature returns a string.

- [ ] **Step 3: Replace `render_frame` and remove `strip_marker`**

In `ontoexplorer/modules/diff/manchester.py`, replace `render_frame` with the new version below. **Delete the `strip_marker` helper** added in Phase 2 — it's no longer needed because the structured output expresses the marker via `line.op`, not by prefixing the string.

```python
def render_frame(
    store: ox.Store,
    entity_iri: str,
    entity_type: str,
    axiom_changes: list[dict],
    *,
    labels: dict[str, str],
    known_iris: frozenset[str],
    annotation_props: frozenset[str] = _BUILTIN_ANNOTATION_PROPS,
    op: Literal["added", "removed", "modified"] = "modified",
) -> ManchesterFrame | None:
    """Build a structured Manchester frame.

    Returns a dict `{lines: [{op, tokens}, ...]}` or None for modified entities
    that produced no renderable axiom lines.

    `op`:
      - "modified" → header/keyword lines get op=None; axiom lines carry the
        per-change op ('added'/'removed').
      - "added"/"removed" → every line in the frame (including header and
        keyword lines) gets op=<that value>. Used for fully-added / fully-removed
        entities so the frontend can apply a uniform line marker.
    """
    rendered: list[tuple[str, str, list[ManchesterToken]]] = []  # (keyword, op, body-tokens)
    for change in axiom_changes:
        line = render_axiom(
            store, change["graph"], entity_iri,
            change["predicate"], change["object"],
            labels=labels, known_iris=known_iris,
            entity_type=entity_type, annotation_props=annotation_props,
        )
        if line is None:
            continue
        # First text token always starts with `<keyword>: ` — strip it for grouping.
        assert line[0]["t"] == "text", "render_axiom must lead with a text token"
        kw_part, _, body_text = line[0]["v"].partition(": ")
        body_tokens: list[ManchesterToken] = [_text(body_text)] if body_text else []
        body_tokens.extend(line[1:])
        rendered.append((kw_part, change["op"], body_tokens))

    if not rendered and op == "modified":
        return None

    # Keyword ordering: Annotations first, then class/property/etc. axioms per type.
    keyword_order: list[str] = []
    seen: set[str] = set()
    for _, kw, types in _FRAME_KEYWORD_ORDER:
        if (types is None or entity_type in types) and kw not in seen:
            keyword_order.append(kw)
            seen.add(kw)
    if entity_type == "individual" and "Facts" not in seen:
        keyword_order.append("Facts")
        seen.add("Facts")
    for kw, _, _ in rendered:
        if kw not in seen:
            keyword_order.append(kw)
            seen.add(kw)

    # Header line.
    graph_for_label = axiom_changes[0]["graph"] if axiom_changes else None
    entity_keyword = _ENTITY_KEYWORD.get(entity_type, "Entity")
    if graph_for_label is not None:
        entity_label = iri_to_label(store, graph_for_label, entity_iri, labels=labels)
    else:
        entity_label = labels.get(entity_iri) or iri_to_label(
            store, ox.NamedNode("urn:never-used"), entity_iri, labels=labels,
        )
    in_onto = entity_iri in known_iris
    header_op: Literal["added", "removed"] | None = op if op != "modified" else None
    lines: list[ManchesterLine] = [{
        "op": header_op,
        "tokens": [
            _text(f"{entity_keyword}: "),
            {"t": "iri", "label": entity_label, "iri": entity_iri, "in_ontology": in_onto},
            _text(f"  ({entity_iri})"),
        ],
    }]

    for kw in keyword_order:
        kw_lines = [(o, body) for k, o, body in rendered if k == kw]
        if not kw_lines:
            continue
        lines.append({"op": header_op, "tokens": [_text(f"    {kw}:")]})
        removed = sorted(
            (body for o, body in kw_lines if o == "removed"),
            key=lambda toks: _body_sort_key(toks),
        )
        added = sorted(
            (body for o, body in kw_lines if o == "added"),
            key=lambda toks: _body_sort_key(toks),
        )
        for body in removed:
            line_op: Literal["added", "removed"] = op if op != "modified" else "removed"
            lines.append({"op": line_op, "tokens": [_text("        "), *body]})
        for body in added:
            line_op = op if op != "modified" else "added"
            lines.append({"op": line_op, "tokens": [_text("        "), *body]})

    return {"lines": lines}


def _body_sort_key(tokens: list[ManchesterToken]) -> str:
    """Stable sort key for body tokens — joins text + label values."""
    return "".join(
        t["v"] if t["t"] == "text" else t["label"] for t in tokens
    )
```

If your IDE warns about `Literal["added", "removed"] | None` reuse with re-narrowing, suppress by using `cast` from `typing` — but the code above should already type-check under Python 3.11.

- [ ] **Step 4: Run the whole render_manchester test file**

Run: `uv run pytest tests/unit/test_manchester_render.py -v 2>&1 | tail -10`

Expected: all tests pass (every Phase 1 / 2 test that touched `render_frame` has been rewritten for the new shape).

If any pre-existing test still asserts string output, rewrite it to assert tokens. The rewrite is mechanical: split lookup against `frame.split("\n")` becomes `frame["lines"]`, and string substrings become token traversal.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "refactor(diff/manchester): render_frame returns ManchesterFrame object"
```

---

## Task 8: Wire `known_iris` through `_run_diff_core`

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`
- Modify: `tests/unit/test_diff_compute.py`

- [ ] **Step 1: Rewrite the Phase 2 added/removed/modified frame tests for the new shape**

In `tests/unit/test_diff_compute.py`, find the tests `test_run_diff_added_class_with_subclassof_and_label_yields_manchester_frame`, `test_run_diff_removed_class_yields_manchester_frame_with_minus_prefix`, and `test_run_diff_bare_added_class_yields_header_only_frame`. Rewrite them to inspect `frame["lines"]`:

```python
def test_run_diff_added_class_yields_structured_frame_with_iri_tokens():
    new_class = ox.NamedNode("http://example.org/NewClass")
    parent    = ox.NamedNode("http://example.org/Parent")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    s = _store(
        from_quads=[],
        to_quads=[
            (new_class, _RDF_TYPE, _OWL_CLASS),
            (new_class, _RDFS_SC, parent),
            (new_class, label_pred, ox.Literal("New", language="en")),
        ],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    added = diff_data["added"][0]
    frame = added["manchester_frame"]
    assert frame is not None and "lines" in frame
    assert all(line["op"] == "added" for line in frame["lines"])
    # Header line has the new-class IRI as an in_ontology iri token.
    header = frame["lines"][0]
    assert any(
        t["t"] == "iri" and t["iri"] == new_class.value and t["in_ontology"] is True
        for t in header["tokens"]
    )
    # SubClassOf line contains the parent IRI as an in_ontology iri token.
    assert any(
        any(
            t["t"] == "iri" and t["iri"] == parent.value and t["in_ontology"] is True
            for t in line["tokens"]
        )
        for line in frame["lines"]
    )


def test_run_diff_removed_class_yields_frame_with_op_removed_lines():
    old_class = ox.NamedNode("http://example.org/OldClass")
    parent    = ox.NamedNode("http://example.org/Parent")
    s = _store(
        from_quads=[
            (old_class, _RDF_TYPE, _OWL_CLASS),
            (old_class, _RDFS_SC, parent),
        ],
        to_quads=[],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    frame = diff_data["removed"][0]["manchester_frame"]
    assert frame is not None
    assert all(line["op"] == "removed" for line in frame["lines"])


def test_run_diff_bare_added_class_yields_single_line_frame():
    bare = ox.NamedNode("http://example.org/Bare")
    s = _store(
        from_quads=[],
        to_quads=[(bare, _RDF_TYPE, _OWL_CLASS)],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    frame = diff_data["added"][0]["manchester_frame"]
    assert frame is not None
    assert len(frame["lines"]) == 1
    assert frame["lines"][0]["op"] == "added"


def test_run_diff_iri_referenced_in_filler_but_not_subject_marks_in_ontology_true():
    """An IRI that appears only as the object of a triple (never as subject)
    is still in_ontology=True, so it remains clickable."""
    a = ox.NamedNode("http://example.org/A")
    b = ox.NamedNode("http://example.org/B")  # appears only as object of A's subClassOf
    s = _store(
        from_quads=[],
        to_quads=[
            (a, _RDF_TYPE, _OWL_CLASS),
            (a, _RDFS_SC, b),
        ],
    )
    _, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    frame = diff_data["added"][0]["manchester_frame"]
    assert frame is not None
    # Find the B token in any line.
    found = False
    for line in frame["lines"]:
        for tok in line["tokens"]:
            if tok["t"] == "iri" and tok["iri"] == b.value:
                assert tok["in_ontology"] is True, "B should be in_ontology because it appears as object"
                found = True
    assert found, "B's iri token must appear in some line"


def test_run_diff_external_iri_in_filler_marks_in_ontology_false():
    """An IRI that appears as a filler but never anywhere in the to-graph
    is in_ontology=False. (Edge case: only constructible by manually injecting
    a triple whose object's IRI is referenced from the renderer but not stored.)
    Tested indirectly via Cat→DisjointWith Dog where Dog appears in graph.
    Skipping this case for v1; `_known_iris` covers subject + object union.
    """
    pass  # intentionally a no-op placeholder; see frontend test for the false case
```

The last test is a no-op stub — its purpose is to document that this case is exercised in the frontend test suite, where we can manually feed a token with `in_ontology=False` to the renderer. Remove the `pass` test if it makes the test file noisy.

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/unit/test_diff_compute.py -v 2>&1 | tail -10`

Expected: the rewritten tests fail (string vs dict mismatch).

- [ ] **Step 3: Update `_run_diff_core` to compute and thread `known_iris`**

In `ontoexplorer/modules/diff/compute.py`, find the line that computes `annotation_props` (added in Phase 2 Task 8). Right after it, add:

```python
    # Pre-compute the in-ontology IRI set for each side so render_frame can
    # decide which iri tokens become clickable links.
    known_iris_from = _mos._known_iris(store, from_graph)
    known_iris_to   = _mos._known_iris(store, to_graph)
    # For modified entities — entity is on both sides — we union the two sets:
    # an axiom-filler IRI that lives only on one side is still legitimately
    # part of the comparison context and should remain clickable.
    known_iris_union = known_iris_from | known_iris_to
```

Then update every `_mos.render_frame(...)` call to pass `known_iris=...`:

- Added-entity loop: `known_iris=known_iris_to`
- Removed-entity loop: `known_iris=known_iris_from`
- Modified-entity branch: `known_iris=known_iris_union`

The three call sites are in close proximity (see Phase 2 Task 8's edits). Read the current shape and modify in place.

- [ ] **Step 4: Run all unit tests**

Run: `cd /path/to/ontoexplorer && uv run pytest tests/unit/ 2>&1 | tail -3`

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/compute.py tests/unit/test_diff_compute.py
git commit -m "feat(diff/compute): thread known_iris through render_frame for clickability"
```

---

## Task 9: Update frontend `manchester_frame` type

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Update the type**

In `frontend/src/lib/api.ts`, find the `DiffEntity` (or equivalent) interface that contains `manchester_frame?: string | null`. Replace with:

```typescript
export type ManchesterTextToken = { t: 'text'; v: string }
export type ManchesterIriToken  = { t: 'iri'; label: string; iri: string; in_ontology: boolean }
export type ManchesterToken     = ManchesterTextToken | ManchesterIriToken

export type ManchesterLine = {
  op: 'added' | 'removed' | null
  tokens: ManchesterToken[]
}

export type ManchesterFrame = {
  lines: ManchesterLine[]
}
```

Then in the `DiffEntity` shape, change:

```diff
- manchester_frame?: string | null
+ manchester_frame?: ManchesterFrame | null
```

- [ ] **Step 2: TypeScript check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -15`

Expected: errors point at `ManchesterFrame.tsx` (the component still takes a string). Those are fixed in Task 10.

- [ ] **Step 3: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): ManchesterFrame token type definitions"
```

---

## Task 10: Rewrite `ManchesterFrame.tsx` to render tokens

**Files:**
- Modify: `frontend/src/components/ManchesterFrame.tsx`

- [ ] **Step 1: Replace the component**

Replace the entire body of `frontend/src/components/ManchesterFrame.tsx` with:

```tsx
import { Link } from 'react-router-dom'
import type { ManchesterFrame as Frame, ManchesterLine, ManchesterToken } from '../lib/api'

interface Props {
  frame: Frame
  /**
   * Ontology shortname used to build entity-page links for IRI tokens that
   * are in_ontology=true. If unset, all tokens render as inert spans (no Link).
   */
  shortname: string | null
}

const COLOR_BY_OP: Record<'added' | 'removed', string> = {
  added:   '#3fb950',
  removed: '#f85149',
}

function markerFor(op: ManchesterLine['op']): string {
  if (op === 'added')   return '+ '
  if (op === 'removed') return '- '
  return '  '
}

function colorFor(op: ManchesterLine['op']): string {
  if (op === 'added' || op === 'removed') return COLOR_BY_OP[op]
  return 'var(--text)'
}

function entityUrl(shortname: string, iri: string): string {
  return `/ontologies/${shortname}?term=${encodeURIComponent(iri)}`
}

function renderToken(
  tok: ManchesterToken,
  key: number,
  shortname: string | null,
): JSX.Element {
  if (tok.t === 'text') {
    return <span key={key}>{tok.v}</span>
  }
  if (tok.in_ontology && shortname) {
    return (
      <Link
        key={key}
        to={entityUrl(shortname, tok.iri)}
        title={tok.iri}
        style={{ color: 'inherit', textDecoration: 'underline' }}
      >
        {tok.label}
      </Link>
    )
  }
  return (
    <span key={key} title={tok.iri} style={{ cursor: 'help' }}>
      {tok.label}
    </span>
  )
}

export default function ManchesterFrame({ frame, shortname }: Props) {
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
      {frame.lines.map((line, i) => (
        <div key={i} style={{ color: colorFor(line.op) }}>
          {markerFor(line.op)}
          {line.tokens.map((t, j) => renderToken(t, j, shortname))}
        </div>
      ))}
    </pre>
  )
}
```

- [ ] **Step 2: Quick TS check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -15`

Expected: errors should now move to `DiffResultView.tsx` (the consumer doesn't pass `shortname` yet). That's fixed in Task 11.

- [ ] **Step 3: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/components/ManchesterFrame.tsx
git commit -m "refactor(frontend): ManchesterFrame renders tokens with clickable IRIs"
```

---

## Task 11: Pipe `shortname` into `DiffResultView` and its callers

**Files:**
- Modify: `frontend/src/components/DiffResultView.tsx`
- Modify: callers of `DiffResultView` (likely `frontend/src/pages/HistoryTab.tsx` or `OntologyPage.tsx` history-tab block, and `frontend/src/pages/Compare.tsx`)

- [ ] **Step 1: Add the prop to DiffResultView**

In `frontend/src/components/DiffResultView.tsx`, extend the `Props` interface:

```tsx
interface Props {
  data: DiffData
  summary?: DiffSummary
  variant: 'version-diff' | 'cross-compare'
  fromLabel?: string
  toLabel?: string
  fromShortname?: string | null
  toShortname?: string | null
}
```

In the `EntityRow` component, derive the right shortname per entity. The signature of `EntityRow` likely takes `entity`, `op`, etc.; add `fromShortname` and `toShortname` props. Per the spec's risk note ("modified entries are ambiguous"), modified entities pick the to-side shortname (the same ontology in version-diff mode; in cross-compare, the to-side is the convention for "shared (axioms differ)" rows).

Update `EntityRow` invocation in the `filtered.map(...)` block to pass these through:

```tsx
<EntityRow
  key={`${entity.op}-${entity.iri}`}
  entity={entity}
  op={entity.op}
  search={search}
  expanded={expanded.has(`${entity.op}-${entity.iri}`)}
  fromShortname={fromShortname ?? null}
  toShortname={toShortname ?? null}
  onToggle={...}
/>
```

Inside `EntityRow`, replace the `<ManchesterFrame frame={entity.manchester_frame} />` line with:

```tsx
<ManchesterFrame
  frame={entity.manchester_frame}
  shortname={
    op === 'removed'  ? fromShortname :
    op === 'added'    ? toShortname   :
                        toShortname   // modified → to-side
  }
/>
```

- [ ] **Step 2: Update the consumer in OntologyPage / HistoryTab**

Find where `DiffResultView` is rendered in the version-history flow. Pass:

```tsx
<DiffResultView
  data={diff.diff_data}
  summary={diff.summary}
  variant="version-diff"
  fromShortname={ontology.shortname}
  toShortname={ontology.shortname}
/>
```

Grep for the existing `<DiffResultView` JSX:

```bash
grep -rn "DiffResultView" frontend/src/ 2>&1 | head
```

- [ ] **Step 3: Update Compare.tsx consumer**

In `frontend/src/pages/Compare.tsx`, find the `<DiffResultView` invocation. Pass:

```tsx
<DiffResultView
  data={diff.diff_data}
  summary={diff.summary}
  variant="cross-compare"
  fromLabel={fromOnt?.shortname ?? 'A'}
  toLabel={toOnt?.shortname ?? 'B'}
  fromShortname={fromOnt?.shortname ?? null}
  toShortname={toOnt?.shortname ?? null}
/>
```

If the prop names for the picked ontologies differ, match what's actually in the file.

- [ ] **Step 4: Type-check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: no new errors related to ManchesterFrame.

- [ ] **Step 5: Run frontend tests to catch regressions**

Run: `cd /path/to/ontoexplorer/frontend && npx vitest run 2>&1 | tail -10`

Expected: same baseline as before (pre-existing failures persist; no new failures introduced).

- [ ] **Step 6: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/components/DiffResultView.tsx frontend/src/pages/
git commit -m "feat(frontend): pipe ontology shortname into ManchesterFrame for clickable IRIs"
```

---

## Task 12: Frontend component test for `ManchesterFrame`

**Files:**
- Create: `frontend/src/components/ManchesterFrame.test.tsx`

- [ ] **Step 1: Write the test file**

Create `frontend/src/components/ManchesterFrame.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ManchesterFrame from './ManchesterFrame'
import type { ManchesterFrame as Frame } from '../lib/api'

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

const PIZZA = 'http://example.org/Pizza'
const FOOD  = 'http://example.org/Food'
const EXTERNAL = 'http://other.org/ExternalThing'

const frame: Frame = {
  lines: [
    {
      op: null,
      tokens: [
        { t: 'text', v: 'Class: ' },
        { t: 'iri', label: 'Pizza', iri: PIZZA, in_ontology: true },
        { t: 'text', v: `  (${PIZZA})` },
      ],
    },
    {
      op: null,
      tokens: [{ t: 'text', v: '    SubClassOf:' }],
    },
    {
      op: 'added',
      tokens: [
        { t: 'text', v: '        ' },
        { t: 'iri', label: 'Food', iri: FOOD, in_ontology: true },
      ],
    },
    {
      op: 'removed',
      tokens: [
        { t: 'text', v: '        ' },
        { t: 'iri', label: 'External', iri: EXTERNAL, in_ontology: false },
      ],
    },
  ],
}

test('in_ontology=true tokens render as Link with href and tooltip', () => {
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  const link = screen.getByRole('link', { name: 'Pizza' })
  expect(link).toHaveAttribute('href', `/ontologies/pizza?term=${encodeURIComponent(PIZZA)}`)
  expect(link).toHaveAttribute('title', PIZZA)
})

test('in_ontology=false tokens render as plain span with tooltip only (no link)', () => {
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  const external = screen.getByText('External')
  expect(external.tagName).toBe('SPAN')
  expect(external).toHaveAttribute('title', EXTERNAL)
  expect(external).not.toHaveAttribute('href')
})

test('shortname=null disables linking even for in_ontology tokens', () => {
  wrap(<ManchesterFrame frame={frame} shortname={null} />)
  expect(screen.queryByRole('link')).toBeNull()
  const pizza = screen.getByText('Pizza')
  expect(pizza.tagName).toBe('SPAN')
})

test('added/removed lines use respective color and line marker', () => {
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  const addedFood = screen.getByText('Food')
  const addedLine = addedFood.closest('div')!
  expect(addedLine.style.color).toBe('rgb(63, 185, 80)')   // #3fb950
  expect(addedLine.textContent?.startsWith('+ ')).toBe(true)

  const removedExternal = screen.getByText('External')
  const removedLine = removedExternal.closest('div')!
  expect(removedLine.style.color).toBe('rgb(248, 81, 73)')  // #f85149
  expect(removedLine.textContent?.startsWith('- ')).toBe(true)
})
```

- [ ] **Step 2: Run the new tests**

Run: `cd /path/to/ontoexplorer/frontend && npx vitest run ManchesterFrame.test.tsx 2>&1 | tail -10`

Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
cd /path/to/ontoexplorer
git add frontend/src/components/ManchesterFrame.test.tsx
git commit -m "test(frontend): ManchesterFrame renders links and tooltips correctly"
```

---

## Self-Review Checklist

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| Token shape (`text` / `iri` with label, iri, in_ontology) | Task 1 |
| `known_iris` SPARQL pre-pass | Task 2 |
| In-ontology check at every IRI emission | Task 3 (helper), Tasks 5-7 (uses) |
| Indentation embedded in text tokens | Task 7 (`render_frame` emits `_text("    Kw:")` and `_text("        ")` for body indent) |
| All non-IRI text in text tokens | Tasks 5-7 |
| Click → `/ontologies/<shortname>?term=<iri>` | Task 10 (`entityUrl`) |
| Plain `title={iri}` tooltip | Task 10 |
| Right-click new-tab works (React Router `<Link>` renders `<a>`) | Task 10 — covered by using `<Link>` |
| `in_ontology=false` → inert span with tooltip | Task 10 + Task 12 test |
| Tests for the new component (link / no link / fallback label) | Task 12 |
| Tests for `_known_iris` (subjects + iri objects) | Task 2 |
| Out-of-scope explicitly: inferred-graph diff (Phase 4); side-panel preview; custom tooltip — none of these introduced | n/a |

**2. Placeholder scan:** every step shows complete code; no "TBD" / "implement later" / "similar to Task N" references. The one no-op placeholder test in Task 8 Step 1 is explicitly documented as a stub for a case better tested in Task 12 — if it's noisy, the implementer is told to remove it.

**3. Type consistency:**
- `render_frame`'s return type `ManchesterFrame | None` (Task 1, Task 7) is consumed in Task 9 by the TypeScript `ManchesterFrame | null`; the `lines` array maps 1:1.
- `_iri_token` (Task 3) is called from `render_class_expression` (Task 5), `render_axiom` (Task 6), and `render_frame` (Task 7) — all with the same `(store, graph, iri, *, labels, known_iris)` signature.
- `_known_iris` returns `frozenset[str]` (Task 2). Threaded through `render_axiom` / `render_frame` / `render_class_expression` as `known_iris: frozenset[str]` keyword.
- `ManchesterToken` in Python (TypedDict) and TypeScript (discriminated union on `t`) have matching field sets.

**4. Breaking change confirmation:**
- The `manchester_frame` field in API responses changes from `string | null` to `{ lines: [...] } | null`. The DB column is JSON, so old rows still parse but render incorrectly.
- After this PR ships, cached `OntologyDiff` rows from before Phase 3 must be invalidated. The implementer should add a final step (Task 13?) to `DELETE FROM ontology_diffs;` or migrate the DB rows. But per Phase 2 precedent (worker restart + manual DELETE), we'll handle this operationally rather than in code.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-manchester-diff-clickable-iris-phase-3.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
