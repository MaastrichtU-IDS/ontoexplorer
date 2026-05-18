# Manchester Diff — Phase 2 (Added/Removed Entities + Annotations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `manchester_frame` for fully-added and fully-removed entities in the version diff, and render annotation axioms (`rdfs:label`, `dc:*`, `dcterms:*`, `skos:*`, `owl:versionInfo`, plus discovered `owl:AnnotationProperty`-typed predicates) as a new `Annotations:` block at the top of every frame.

**Architecture:** A new private helper `_axioms_for_entity` in `compute.py` collects all triples for an entity (excluding the declaring `rdf:type owl:Class` triple) and passes them through the existing `render_frame` with a new `op` keyword parameter that controls whether marker prefixes are uniform (`+`/`-` on every line, for added/removed) or per-line (`+`/`-` only on changed lines, for modified — Phase 1 behavior). The annotation block is added inside `render_axiom` and `render_frame`'s keyword-ordering table.

**Tech Stack:** Python 3.11+, pyoxigraph, pytest. Pure frontend change in `DiffResultView.tsx` to show the frame inside expanded added/removed rows.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ontoexplorer/modules/diff/manchester.py` | MODIFY | Add annotation constants, annotation-property discovery, render annotation lines, accept `op` parameter on `render_frame` for uniform-marker mode |
| `ontoexplorer/modules/diff/compute.py` | MODIFY | New `_axioms_for_entity` helper; call `render_frame(op="added"|"removed")` in the added/removed loops of `_run_diff_core` |
| `tests/unit/test_manchester_render.py` | MODIFY | Tests for the new `op` parameter, annotation rendering, and the predicate-discovery helper |
| `tests/unit/test_diff_compute.py` | MODIFY | End-to-end frames for added class, removed individual, bare added class |
| `frontend/src/components/DiffResultView.tsx` | MODIFY | Show `manchester_frame` inside expanded added/removed rows (currently only shown for modified) |

The Phase 1 contract (`manchester_frame: string | null`) stays the same — Phase 2 only changes what populates it.

---

## Task 1: Annotation property constants and CURIE prefix map

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`

- [ ] **Step 1: Add the constants**

In `ontoexplorer/modules/diff/manchester.py`, immediately after the existing `_OWL_*` and `_XSD_*` constant block (before `_CHARACTERISTICS`), add:

```python
# Well-known annotation properties — predicates whose value is metadata about
# the subject rather than a logical axiom. The Manchester `Annotations:`
# keyword block groups all of these.
_DC = "http://purl.org/dc/elements/1.1/"
_DCTERMS = "http://purl.org/dc/terms/"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

_RDFS_SEE_ALSO       = _RDFS + "seeAlso"
_RDFS_IS_DEFINED_BY  = _RDFS + "isDefinedBy"
_RDFS_COMMENT        = _RDFS + "comment"

_OWL_ANNOTATION_PROPERTY = _OWL + "AnnotationProperty"
_OWL_VERSION_INFO        = _OWL + "versionInfo"
_OWL_DEPRECATED          = _OWL + "deprecated"
_OWL_PRIOR_VERSION       = _OWL + "priorVersion"
_OWL_INCOMPATIBLE_WITH   = _OWL + "incompatibleWith"

# Predicates that always render as annotations regardless of graph context.
# Dynamically-discovered owl:AnnotationProperty entries are added on top of
# this set per run_diff invocation.
_BUILTIN_ANNOTATION_PROPS: frozenset[str] = frozenset({
    _RDFS_LABEL, _RDFS_COMMENT, _RDFS_SEE_ALSO, _RDFS_IS_DEFINED_BY,
    _DC + "title", _DC + "description", _DC + "creator",
    _DCTERMS + "title", _DCTERMS + "description",
    _DCTERMS + "creator", _DCTERMS + "license",
    _SKOS + "prefLabel", _SKOS + "altLabel", _SKOS + "definition",
    _SKOS + "scopeNote", _SKOS + "example",
    _OWL_VERSION_INFO, _OWL_DEPRECATED, _OWL_PRIOR_VERSION, _OWL_INCOMPATIBLE_WITH,
})

# Known namespaces for CURIE-style display of annotation predicates.
# Order matters: longest prefixes (dcterms before dc) must be tried first
# so dcterms:title doesn't shorten to dc:terms/title.
_CURIE_PREFIXES: list[tuple[str, str]] = [
    (_DCTERMS, "dcterms:"),
    (_DC,      "dc:"),
    (_SKOS,    "skos:"),
    (_RDFS,    "rdfs:"),
    (_OWL,     "owl:"),
    (_XSD,     "xsd:"),
]


def _to_curie(iri: str) -> str:
    """Return a `prefix:local` CURIE if iri starts with a known namespace,
    otherwise `<full-iri>` in angle brackets.
    """
    for ns, prefix in _CURIE_PREFIXES:
        if iri.startswith(ns):
            return f"{prefix}{iri[len(ns):]}"
    return f"<{iri}>"
```

- [ ] **Step 2: Sanity-check the constants import cleanly**

Run: `cd /home/micheldumontier/code/ontoexplorer && uv run python -c "from ontoexplorer.modules.diff.manchester import _BUILTIN_ANNOTATION_PROPS, _to_curie; print(len(_BUILTIN_ANNOTATION_PROPS), _to_curie('http://www.w3.org/2000/01/rdf-schema#label'))"`

Expected: `20 rdfs:label`

- [ ] **Step 3: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py
git commit -m "feat(diff/manchester): annotation property constants and CURIE prefix map"
```

---

## Task 2: `_discover_annotation_props` SPARQL helper

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add a failing test**

Append to `tests/unit/test_manchester_render.py`:

```python
from ontoexplorer.modules.diff.manchester import _discover_annotation_props


def test_discover_annotation_props_returns_explicit_annotation_property_iris():
    """SELECT ?p WHERE { ?p a owl:AnnotationProperty } over a graph."""
    custom = ox.NamedNode("http://example.org/myCustomAnnotation")
    other  = ox.NamedNode("http://example.org/notAnAnnotation")
    annotation_property = ox.NamedNode("http://www.w3.org/2002/07/owl#AnnotationProperty")
    class_node          = ox.NamedNode("http://www.w3.org/2002/07/owl#Class")
    store = _store(
        (custom, _RDF_TYPE_N, annotation_property),
        (other,  _RDF_TYPE_N, class_node),
    )
    discovered = _discover_annotation_props(store, _GRAPH)
    assert custom.value in discovered
    assert other.value not in discovered


def test_discover_annotation_props_returns_empty_for_graph_without_any():
    store = _store()
    discovered = _discover_annotation_props(store, _GRAPH)
    assert discovered == frozenset()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/micheldumontier/code/ontoexplorer && uv run pytest tests/unit/test_manchester_render.py -v -k discover_annotation_props 2>&1 | tail -5`

Expected: 2 FAILED with `_discover_annotation_props` not defined.

- [ ] **Step 3: Add the helper**

Append to `ontoexplorer/modules/diff/manchester.py`:

```python
def _discover_annotation_props(
    store: ox.Store, graph: ox.NamedNode,
) -> frozenset[str]:
    """Return the set of IRIs declared as owl:AnnotationProperty in `graph`.

    Augments `_BUILTIN_ANNOTATION_PROPS` for each run_diff invocation. Result
    is intended to be cached at the call site for the duration of the run.
    """
    rdf_type = ox.NamedNode(_RDF_TYPE)
    ap_class = ox.NamedNode(_OWL_ANNOTATION_PROPERTY)
    return frozenset(
        q.subject.value
        for q in store.quads_for_pattern(None, rdf_type, ap_class, graph)
        if isinstance(q.subject, ox.NamedNode)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k discover_annotation_props 2>&1 | tail -5`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): _discover_annotation_props SPARQL helper"
```

---

## Task 3: Render annotation axioms in `render_axiom`

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
_RDFS_LABEL_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
_RDFS_COMMENT_N = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#comment")
_DC_DESCRIPTION_N = ox.NamedNode("http://purl.org/dc/elements/1.1/description")
_OWL_VERSION_INFO_N = ox.NamedNode("http://www.w3.org/2002/07/owl#versionInfo")
_CUSTOM_ANN_N = ox.NamedNode("http://example.org/myAnn")


def test_render_axiom_rdfs_label_annotation():
    """A built-in annotation property emits 'Annotations: rdfs:label "Foo"@en'."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _RDFS_LABEL_N.value,
        ox.Literal("Foo", language="en"),
        labels={},
        annotation_props=_BUILTIN_ANNOTATION_PROPS,
    )
    assert out == 'Annotations: rdfs:label "Foo"@en'


def test_render_axiom_dc_description_annotation():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _DC_DESCRIPTION_N.value,
        ox.Literal("A thing"),
        labels={},
        annotation_props=_BUILTIN_ANNOTATION_PROPS,
    )
    assert out == 'Annotations: dc:description "A thing"'


def test_render_axiom_owl_version_info_annotation():
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Ont", _OWL_VERSION_INFO_N.value,
        ox.Literal("1.0.0"),
        labels={},
        annotation_props=_BUILTIN_ANNOTATION_PROPS,
    )
    assert out == 'Annotations: owl:versionInfo "1.0.0"'


def test_render_axiom_custom_annotation_property_via_dynamic_set():
    """A non-builtin predicate gets routed to Annotations: iff in annotation_props."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", _CUSTOM_ANN_N.value,
        ox.Literal("custom note"),
        labels={},
        annotation_props=frozenset({_CUSTOM_ANN_N.value}),
    )
    assert out == 'Annotations: <http://example.org/myAnn> "custom note"'


def test_render_axiom_custom_predicate_NOT_in_annotation_set_returns_none():
    """If a custom predicate isn't in annotation_props it falls through (None)."""
    out = render_axiom(
        _store(), _GRAPH,
        "http://example.org/Foo", "http://example.org/randomPred",
        ox.NamedNode("http://example.org/Bar"),
        labels={},
        annotation_props=frozenset(),  # not declared as annotation
    )
    assert out is None
```

Add the `_BUILTIN_ANNOTATION_PROPS` import to the existing imports at the top of the test file (only if not already present):

```python
from ontoexplorer.modules.diff.manchester import _BUILTIN_ANNOTATION_PROPS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k "annotation or version_info or dc_description" 2>&1 | tail -10`

Expected: 5 FAILED (TypeError: render_axiom got unexpected keyword argument 'annotation_props').

- [ ] **Step 3: Extend `render_axiom` with annotation support**

In `ontoexplorer/modules/diff/manchester.py`, replace the `render_axiom` function body. The signature now accepts an `annotation_props` keyword. When the predicate is in that set, emit `Annotations: <pred> <value>`:

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
    annotation_props: frozenset[str] = _BUILTIN_ANNOTATION_PROPS,
) -> str | None:
    """Render a single (predicate, object) pair as a Manchester axiom line.

    `annotation_props` is the per-run set of predicates that should render
    under the `Annotations:` keyword (built-ins plus any owl:AnnotationProperty
    discovered in the graph). When the predicate is in this set, output is
    `Annotations: <curie-or-iri> <value>`. Otherwise the existing dispatch
    runs (logical/property/characteristic/individual axioms).
    """
    # Annotation properties take precedence over everything else, so an
    # ontology that types e.g. rdfs:seeAlso as both annotation + logical
    # property still renders cleanly.
    if predicate_iri in annotation_props:
        pred_str = _to_curie(predicate_iri)
        value_str = _render_annotation_value(store, graph, object_term, labels=labels)
        return f"Annotations: {pred_str} {value_str}"

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


def _render_annotation_value(
    store: ox.Store, graph: ox.NamedNode, obj: ox.Term, *, labels: dict[str, str],
) -> str:
    """Render the object of an annotation axiom.

    - Literal → `"value"[@lang][^^xsd:dtype]` (xsd:string suppressed).
    - NamedNode → label / CURIE / local name via the existing class-expression renderer.
    - BlankNode → fallback class-expression rendering (uncommon for annotations).
    """
    if isinstance(obj, ox.Literal):
        return _render_literal(obj)
    return render_class_expression(store, graph, obj, labels=labels)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v 2>&1 | tail -5`

Expected: all previous tests still pass plus the 5 new annotation tests = total count increases by 5.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): render annotation axioms with CURIE predicates"
```

---

## Task 4: Add `Annotations:` to `_FRAME_KEYWORD_ORDER`

The `_FRAME_KEYWORD_ORDER` table drives the order of keyword blocks in the frame. `Annotations:` should appear FIRST (before logical keywords) and apply to ALL entity types.

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`

- [ ] **Step 1: Add `Annotations` entry**

In `ontoexplorer/modules/diff/manchester.py`, find the `_FRAME_KEYWORD_ORDER` list (around line 504). Prepend an entry at the top:

```python
_FRAME_KEYWORD_ORDER: list[tuple[str, str, set[str] | None]] = [
    # Annotations always appear first, for all entity types. The predicate
    # field here is a sentinel — annotation lines are detected by their
    # rendered keyword, not by a predicate match against _FRAME_KEYWORD_ORDER.
    ("__annotations__",   "Annotations",      None),
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
```

The `None` for the entity-types filter means "all entity types get this keyword."

- [ ] **Step 2: Run existing tests — `Annotations` must not appear when no annotation axioms are present**

Run: `uv run pytest tests/unit/test_manchester_render.py -v 2>&1 | tail -5`

Expected: all tests still pass (the `Annotations:` keyword is only added to `keyword_order`, not to `rendered`; the `if not kw_lines: continue` guard in `render_frame` ensures it doesn't appear when there are no annotation lines).

- [ ] **Step 3: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py
git commit -m "feat(diff/manchester): Annotations: keyword first in frame order"
```

---

## Task 5: `op` parameter on `render_frame` for uniform-marker mode

**Files:**
- Modify: `ontoexplorer/modules/diff/manchester.py`
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_manchester_render.py`:

```python
def test_render_frame_op_added_prefixes_every_line_with_plus():
    """When op='added', header, keyword, and axiom lines all start with '+ '."""
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        op="added",
    )
    assert frame is not None
    lines = frame.split("\n")
    assert all(line.startswith("+ ") for line in lines), \
        f"every line should start with '+ ', got:\n{frame}"


def test_render_frame_op_removed_prefixes_every_line_with_minus():
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "removed", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
        op="removed",
    )
    assert frame is not None
    lines = frame.split("\n")
    assert all(line.startswith("- ") for line in lines), \
        f"every line should start with '- ', got:\n{frame}"


def test_render_frame_op_modified_preserves_phase1_behavior():
    """op='modified' (the default) keeps the Phase 1 behavior:
    header and keyword lines have no prefix; axiom lines use per-change marker."""
    iri = "http://example.org/Pizza"
    food = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_SUB_N.value, "object": food, "graph": _GRAPH},
        ],
        labels={},
    )
    assert frame is not None
    lines = frame.split("\n")
    assert lines[0].startswith("Class: "), "header has no prefix in modified mode"
    assert "+       Food" in frame, "axiom line uses per-change marker"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_manchester_render.py -v -k "op_added or op_removed or op_modified_preserves" 2>&1 | tail -10`

Expected: 3 FAILED (TypeError: render_frame got an unexpected keyword argument 'op').

- [ ] **Step 3: Add `op` parameter to `render_frame`**

In `ontoexplorer/modules/diff/manchester.py`, replace the existing `render_frame` function. The new function adds an `op` keyword argument and a final pass that prefixes every line uniformly when `op != "modified"`:

```python
from typing import Literal

def render_frame(
    store: ox.Store,
    entity_iri: str,
    entity_type: str,
    axiom_changes: list[dict],
    *,
    labels: dict[str, str],
    annotation_props: frozenset[str] = _BUILTIN_ANNOTATION_PROPS,
    op: Literal["added", "removed", "modified"] = "modified",
) -> str | None:
    """Render a Protégé-style Manchester frame for one diff entity.

    `axiom_changes` is a list of dicts with keys:
      op:        'added' | 'removed' (modified-mode uses per-axiom op)
      predicate: str
      object:    ox.Term
      graph:     ox.NamedNode (which named graph this change came from)

    `op` parameter:
      - "modified" (default): Phase 1 behavior — header/keyword lines have
        no prefix; axiom lines use the per-change op marker.
      - "added" / "removed": uniform marker mode — EVERY line in the output
        is prefixed with '+ ' or '- ' respectively. Used for fully-added
        and fully-removed entities in the diff.

    Returns None when no axiom_changes produce a renderable line.
    """
    rendered: list[tuple[str, str, str]] = []  # (keyword, op, text)
    for change in axiom_changes:
        line = render_axiom(
            store, change["graph"], entity_iri,
            change["predicate"], change["object"],
            labels=labels, entity_type=entity_type,
            annotation_props=annotation_props,
        )
        if line is None:
            continue
        keyword, _, body = line.partition(": ")
        rendered.append((keyword, change["op"], body))

    if not rendered:
        # In added/removed mode we still want a header-only frame for entities
        # that have only the declaring rdf:type triple — the caller may pass
        # an empty axiom_changes for a bare class. Detect via `op` parameter.
        if op == "modified":
            return None
        # Fall through: render header only, uniformly prefixed.

    # Build the keyword order (annotations first, then logical, then per-type).
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

    # Entity-label lookup needs ONE graph; prefer the first change's graph,
    # else fall back to the to-graph mode (caller can pass a sentinel through
    # axiom_changes when rendering a bare entity).
    graph_for_label = axiom_changes[0]["graph"] if axiom_changes else None
    entity_keyword = _ENTITY_KEYWORD.get(entity_type, "Entity")
    if graph_for_label is not None:
        entity_label = iri_to_label(store, graph_for_label, entity_iri, labels=labels)
    else:
        entity_label = labels.get(entity_iri) or iri_to_label(
            store, ox.NamedNode("urn:never-used"), entity_iri, labels=labels,
        )
    lines: list[str] = [f"{entity_keyword}: {entity_label}  ({entity_iri})"]

    for kw in keyword_order:
        kw_lines = [(o, body) for k, o, body in rendered if k == kw]
        if not kw_lines:
            continue
        lines.append(f"    {kw}:")
        removed = sorted([b for o, b in kw_lines if o == "removed"])
        added   = sorted([b for o, b in kw_lines if o == "added"])
        for body in removed:
            lines.append(f"-       {body}")
        for body in added:
            lines.append(f"+       {body}")

    # Uniform-marker mode: replace per-line markers with the frame-level marker.
    if op == "added":
        return "\n".join(f"+ {strip_marker(line)}" for line in lines)
    if op == "removed":
        return "\n".join(f"- {strip_marker(line)}" for line in lines)
    return "\n".join(lines)


def strip_marker(line: str) -> str:
    """Strip a leading '-       ' or '+       ' marker (Phase 1 axiom line
    prefix) so the frame-level marker in uniform mode replaces it cleanly."""
    if line.startswith("-       ") or line.startswith("+       "):
        return "      " + line[8:]  # preserve 6-space indent under keyword
    return line
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_manchester_render.py -v 2>&1 | tail -5`

Expected: all existing tests still pass + 3 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/manchester.py tests/unit/test_manchester_render.py
git commit -m "feat(diff/manchester): op parameter on render_frame for uniform-marker mode"
```

---

## Task 6: Annotation block end-to-end test (frame contains `Annotations:`)

**Files:**
- Modify: `tests/unit/test_manchester_render.py`

- [ ] **Step 1: Add the integration test**

Append to `tests/unit/test_manchester_render.py`:

```python
def test_render_frame_with_annotations_block_at_top():
    """Frame for an entity with rdfs:label and rdfs:comment renders the
    Annotations: block first, then logical keyword blocks."""
    iri = "http://example.org/Pizza"
    pizza = ox.NamedNode(iri)
    food  = ox.NamedNode("http://example.org/Food")
    store = _store()
    frame = render_frame(
        store, iri, "class",
        axiom_changes=[
            {"op": "added", "predicate": _RDFS_LABEL_N.value,
             "object": ox.Literal("Pizza", language="en"), "graph": _GRAPH},
            {"op": "added", "predicate": _RDFS_COMMENT_N.value,
             "object": ox.Literal("A baked Italian dish"), "graph": _GRAPH},
            {"op": "added", "predicate": _RDFS_SUB_N.value,
             "object": food, "graph": _GRAPH},
        ],
        labels={},
        op="added",
    )
    assert frame is not None
    # Order: header → Annotations → SubClassOf
    annot_idx = frame.find("Annotations:")
    sub_idx   = frame.find("SubClassOf:")
    assert annot_idx >= 0 and sub_idx >= 0
    assert annot_idx < sub_idx, "Annotations: must appear before SubClassOf:"
    assert 'rdfs:label "Pizza"@en' in frame
    assert 'rdfs:comment "A baked Italian dish"' in frame
```

The test reuses `_RDFS_LABEL_N` and `_RDFS_COMMENT_N` constants already added in Task 3.

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_manchester_render.py::test_render_frame_with_annotations_block_at_top -v 2>&1 | tail -5`

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_manchester_render.py
git commit -m "test(diff/manchester): Annotations: block appears at top of frame"
```

---

## Task 7: `_axioms_for_entity` helper in `compute.py`

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`
- Modify: `tests/unit/test_diff_compute.py`

- [ ] **Step 1: Add a failing test**

Append to `tests/unit/test_diff_compute.py`:

```python
def test_axioms_for_entity_returns_all_outgoing_triples_except_declaring_type():
    """For a class declared as owl:Class with one rdfs:subClassOf and one
    rdfs:label, _axioms_for_entity returns the two non-declaration triples."""
    from ontoexplorer.modules.diff.compute import _axioms_for_entity

    iri = ox.NamedNode("http://example.org/Foo")
    parent = ox.NamedNode("http://example.org/Bar")
    label_pred = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
    store = ox.Store()
    g = ox.NamedNode("urn:test")
    store.add_graph(g)
    store.add(ox.Quad(iri, _RDF_TYPE, _OWL_CLASS, g))
    store.add(ox.Quad(iri, _RDFS_SC, parent, g))
    store.add(ox.Quad(iri, label_pred, ox.Literal("Foo", language="en"), g))

    axioms = _axioms_for_entity(store, g, iri.value)
    predicates = {p for p, _ in axioms}
    # rdf:type owl:Class is EXCLUDED (declaring triple)
    assert _RDF_TYPE.value not in predicates
    # The other two are INCLUDED
    assert _RDFS_SC.value in predicates
    assert "http://www.w3.org/2000/01/rdf-schema#label" in predicates
    assert len(axioms) == 2


def test_axioms_for_entity_keeps_non_declaring_rdf_type_triples():
    """A class can be typed both as owl:Class AND as some custom metaclass.
    Only the owl:Class declaration is excluded; other rdf:type triples remain
    so they can render as Characteristics or Types axioms."""
    from ontoexplorer.modules.diff.compute import _axioms_for_entity

    iri = ox.NamedNode("http://example.org/Foo")
    metaclass = ox.NamedNode("http://example.org/MyMetaclass")
    store = ox.Store()
    g = ox.NamedNode("urn:test")
    store.add_graph(g)
    store.add(ox.Quad(iri, _RDF_TYPE, _OWL_CLASS, g))
    store.add(ox.Quad(iri, _RDF_TYPE, metaclass, g))

    axioms = _axioms_for_entity(store, g, iri.value)
    # owl:Class declaration is excluded; metaclass triple remains.
    objects = [getattr(o, "value", str(o)) for _, o in axioms]
    assert _OWL_CLASS.value not in objects
    assert metaclass.value in objects
    assert len(axioms) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k _axioms_for_entity 2>&1 | tail -5`

Expected: 2 FAILED (ImportError: cannot import name '_axioms_for_entity').

- [ ] **Step 3: Add the helper**

In `ontoexplorer/modules/diff/compute.py`, add this function immediately after the existing `_structural_triples` helper (around line 79):

```python
def _axioms_for_entity(
    store: ox.Store, graph: ox.NamedNode, iri: str,
) -> list[tuple[str, ox.Term]]:
    """Return all outgoing (predicate, object) pairs for `iri` in `graph`,
    excluding the declaring `rdf:type` triple whose object is one of the
    five OWL/RDFS entity meta-classes (owl:Class, owl:ObjectProperty,
    owl:DatatypeProperty, owl:AnnotationProperty, owl:NamedIndividual).

    Used to collect the full axiom set for an entity in the added/removed
    buckets of the diff, where the entity is fully present on one side only.
    Non-meta-class rdf:type triples (e.g. property characteristics, individual
    types) are retained so render_axiom can route them appropriately.
    """
    meta_classes = set(_ENTITY_TYPES.values())
    triples: list[tuple[str, ox.Term]] = []
    for q in store.quads_for_pattern(ox.NamedNode(iri), None, None, graph):
        if (
            q.predicate.value == _RDF_TYPE
            and isinstance(q.object, ox.NamedNode)
            and q.object.value in meta_classes
        ):
            continue
        triples.append((q.predicate.value, q.object))
    return triples
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k _axioms_for_entity 2>&1 | tail -5`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/compute.py tests/unit/test_diff_compute.py
git commit -m "feat(diff/compute): _axioms_for_entity helper for added/removed frames"
```

---

## Task 8: Wire `render_frame` for added/removed entities in `_run_diff_core`

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`
- Modify: `tests/unit/test_diff_compute.py`

- [ ] **Step 1: Add a failing test**

Append to `tests/unit/test_diff_compute.py`:

```python
def test_run_diff_added_class_with_subclassof_and_label_yields_manchester_frame():
    """An added class with one rdfs:subClassOf and one rdfs:label should
    produce a manchester_frame on the added entry with both blocks and
    '+ ' prefixes on every line."""
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
    assert summary["added"] == 1
    added = diff_data["added"][0]
    assert added["iri"] == new_class.value
    frame = added.get("manchester_frame")
    assert frame is not None, "manchester_frame must be populated for added entities"
    # Header + Annotations + SubClassOf, every line '+ ' prefixed.
    lines = frame.split("\n")
    assert all(line.startswith("+ ") for line in lines), \
        f"every line should start with '+ ', got:\n{frame}"
    assert "Annotations:" in frame
    assert 'rdfs:label "New"@en' in frame
    assert "SubClassOf:" in frame


def test_run_diff_removed_class_yields_manchester_frame_with_minus_prefix():
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
    assert summary["removed"] == 1
    removed = diff_data["removed"][0]
    frame = removed.get("manchester_frame")
    assert frame is not None
    lines = frame.split("\n")
    assert all(line.startswith("- ") for line in lines)
    assert "SubClassOf:" in frame


def test_run_diff_bare_added_class_yields_header_only_frame():
    """A class declared with only `rdf:type owl:Class` and no other axioms
    produces a single-line frame: '+ Class: <name>  (<iri>)'."""
    bare = ox.NamedNode("http://example.org/Bare")
    s = _store(
        from_quads=[],
        to_quads=[(bare, _RDF_TYPE, _OWL_CLASS)],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    added = diff_data["added"][0]
    frame = added.get("manchester_frame")
    assert frame is not None
    # Exactly one line, header form.
    assert frame.count("\n") == 0
    assert frame.startswith("+ Class: ")
    assert "(http://example.org/Bare)" in frame
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_diff_compute.py -v -k "added_class_with_subclassof or removed_class_yields or bare_added" 2>&1 | tail -10`

Expected: 3 FAILED (the `added`/`removed` entities currently don't have `manchester_frame`).

- [ ] **Step 3: Wire up added/removed frame rendering in `_run_diff_core`**

In `ontoexplorer/modules/diff/compute.py`, find the `for iri in to_iris - from_iris:` loop in `_run_diff_core` (around line 140). Replace it AND the corresponding `for iri in from_iris - to_iris:` loop. The new code calls `_axioms_for_entity` for each side and feeds it through `render_frame` with the matching `op`. Also call `_mos._discover_annotation_props` ONCE per graph and pass the union to `render_frame`:

Locate the start of `_run_diff_core` and the `labels` cache line. Right after `labels: dict[str, str] = {}`, add:

```python
    # Discover owl:AnnotationProperty in both graphs once; union forms the
    # annotation_props set used by render_axiom/render_frame for every entity.
    annotation_props = (
        _mos._BUILTIN_ANNOTATION_PROPS
        | _mos._discover_annotation_props(store, from_graph)
        | _mos._discover_annotation_props(store, to_graph)
    )
```

Then replace the added-entity loop:

```python
        for iri in to_iris - from_iris:
            axioms = _axioms_for_entity(store, to_graph, iri)
            axiom_changes = [
                {"op": "added", "predicate": p, "object": o, "graph": to_graph}
                for p, o in axioms
            ]
            frame = _mos.render_frame(
                store, iri, entity_type, axiom_changes,
                labels=labels, annotation_props=annotation_props, op="added",
            )
            added_list.append({
                "iri": iri,
                "label": _first_label(store, to_graph, iri),
                "entity_type": entity_type,
                "manchester_frame": frame,
            })
```

And the removed-entity loop:

```python
        for iri in from_iris - to_iris:
            axioms = _axioms_for_entity(store, from_graph, iri)
            axiom_changes = [
                {"op": "removed", "predicate": p, "object": o, "graph": from_graph}
                for p, o in axioms
            ]
            frame = _mos.render_frame(
                store, iri, entity_type, axiom_changes,
                labels=labels, annotation_props=annotation_props, op="removed",
            )
            removed_list.append({
                "iri": iri,
                "label": _first_label(store, from_graph, iri),
                "entity_type": entity_type,
                "manchester_frame": frame,
            })
```

ALSO: update the modified-entity branch to pass `annotation_props` to `render_frame`:

```python
            manchester_frame = _mos.render_frame(
                store, iri, entity_type, change_records,
                labels=labels, annotation_props=annotation_props,
            )
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `uv run pytest tests/unit/test_diff_compute.py tests/unit/test_manchester_render.py -v 2>&1 | tail -10`

Expected: all existing tests still pass + 3 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/diff/compute.py tests/unit/test_diff_compute.py
git commit -m "feat(diff/compute): render manchester_frame for added/removed entities"
```

---

## Task 9: Frontend — show frame inside expanded added/removed rows

The Phase 1 frontend (`DiffResultView.tsx`) only shows the manchester_frame inside `expanded && op === 'modified'`. We need to show it for added/removed rows too.

**Files:**
- Modify: `frontend/src/components/DiffResultView.tsx`

- [ ] **Step 1: Read the current EntityRow expanded block**

Run: `grep -n "expanded && op === 'modified'\|manchester_frame" /home/micheldumontier/code/ontoexplorer/frontend/src/components/DiffResultView.tsx | head`

Locate the conditional that gates the expanded panel.

- [ ] **Step 2: Update the gating**

In `frontend/src/components/DiffResultView.tsx`, find the block:

```tsx
      {expanded && op === 'modified' && (
        <div style={{ padding: '4px 10px 10px 30px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {hasLiteral && (
```

Replace it with:

```tsx
      {expanded && (
        <div style={{ padding: '4px 10px 10px 30px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {op === 'modified' && hasLiteral && (
```

Then find the matching `{entity.manchester_frame && (...)}` block inside the same panel (around 15 lines down):

```tsx
          {entity.manchester_frame && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Axiom changes</div>
              <ManchesterFrame frame={entity.manchester_frame} />
            </div>
          )}
```

Replace with — different header label depending on op:

```tsx
          {entity.manchester_frame && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>
                {op === 'modified' ? 'Axiom changes' : op === 'added' ? 'Added entity' : 'Removed entity'}
              </div>
              <ManchesterFrame frame={entity.manchester_frame} />
            </div>
          )}
```

- [ ] **Step 3: Type-check**

Run: `cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -5`

Expected: no new errors (only the pre-existing Sparql.test.tsx fixture issue).

- [ ] **Step 4: Run frontend tests**

Run: `cd /home/micheldumontier/code/ontoexplorer/frontend && npx vitest run 2>&1 | tail -5`

Expected: all tests still pass.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/DiffResultView.tsx
git commit -m "feat(frontend): render manchester_frame for added/removed entity rows"
```

---

## Self-Review Checklist

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| `_axioms_for_entity` helper | Task 7 |
| `render_frame` `op` parameter | Task 5 |
| Built-in annotation property set | Task 1 |
| Dynamic owl:AnnotationProperty discovery | Task 2 |
| `Annotations:` block at top of frame | Task 4 + Task 6 (e2e test) |
| CURIE display of annotation predicates | Task 1 (`_to_curie`), Task 3 (used in render_axiom) |
| Literal value rendering with lang + datatype | Task 3 (`_render_annotation_value` delegates to `_render_literal`) |
| Sort annotation lines by (predicate, lang, value) | Task 5 (existing `sorted(...)` in render_frame applies to all keywords incl Annotations) |
| Added/removed frame uniform `+` / `-` prefix | Task 5 + Task 8 |
| Bare entity (single-line frame) | Task 8 (`test_run_diff_bare_added_class_yields_header_only_frame`) |
| Frontend renders frame for added/removed | Task 9 |

**2. Placeholder scan:** none of "TBD", "TODO", "implement later", "fill in details", "Similar to Task N" appear. Every code change shows the complete code.

**3. Type consistency:**

- `render_axiom` signature gains `annotation_props: frozenset[str] = _BUILTIN_ANNOTATION_PROPS` (Task 3). Called consistently with the keyword by `render_frame` in Task 5.
- `render_frame` signature gains `annotation_props: frozenset[str] = _BUILTIN_ANNOTATION_PROPS` and `op: Literal["added","removed","modified"] = "modified"` (Task 5). Called with `op="added"` / `op="removed"` from `_run_diff_core` in Task 8, with `op` omitted (defaults to "modified") for the existing modified-entity call.
- `_axioms_for_entity` returns `list[tuple[str, ox.Term]]` (Task 7). Consumer (Task 8) iterates `for p, o in axioms`.
- `_discover_annotation_props` returns `frozenset[str]` (Task 2). Combined with `_BUILTIN_ANNOTATION_PROPS` via `|` operator in Task 8.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-manchester-diff-added-removed-phase-2.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
