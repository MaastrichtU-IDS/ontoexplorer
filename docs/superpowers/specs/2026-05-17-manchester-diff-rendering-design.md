# Manchester syntax rendering for diff axiom changes — Phase 1

**Status:** approved design
**Date:** 2026-05-17
**Scope:** Replace the raw `<predicate> <object>` rendering in the ontology version diff UI with Manchester OWL syntax for modified entities. Add a Protégé-style frame per modified entity.

Part of a four-phase effort. Subsequent phases (Manchester for added/removed entities, clickable IRIs, inferred-axiom diffs) live in their own spec documents.

## Background

The diff endpoint (`/api/v1/ontologies/{id}/diff?from=…&to=…`) returns per-entity changes. For each modified entity, `axiom_changes` is currently a list of `{op, axiom}` where `axiom` is the literal string `"<predicate> <object>"`. The frontend renders this verbatim with red/green coloring.

Two problems with the current display:

1. **Unreadable for class expressions.** A subClassOf change against an `owl:Restriction` blank node renders as `<rdfs:subClassOf> <_:fp:abc123…>` — fingerprinted but opaque.
2. **Loses semantic grouping.** Multiple changes against the same entity appear as a flat list of triples instead of a coherent frame.

This phase fixes both by switching the rendering to Manchester OWL syntax, grouped per entity into a Protégé-style frame.

## Architecture

A new module `ontoexplorer/modules/diff/manchester.py` is responsible for all RDF → Manchester rendering. `ontoexplorer/modules/diff/compute.py` invokes it once per modified entity. The module is a pure function over `(pyoxigraph.Store, NamedNode graph, …)` — no DB access, no async — so it can be exercised directly in unit tests against an in-memory store.

The renderer produces two outputs per modified entity:

- `manchester_frame: str` — a Protégé-style frame with `-` / `+` prefixes on changed lines. Newline-separated; the frontend splits on `\n` and colors per line.
- Each `axiom_changes[i].axiom` is upgraded from `"<predicate> <object>"` to a single Manchester axiom string (e.g. `"SubClassOf: hasTopping some Tomato"`).

API shape change is additive: `manchester_frame` is a new field on `DiffEntity`; the existing `axiom_changes` field keeps the same shape but its `axiom` string content changes format.

## Renderer module API

```python
# ontoexplorer/modules/diff/manchester.py

def render_axiom(
    store, graph, subject_iri, predicate_iri, object_value, *, labels
) -> str: ...

def render_class_expression(
    store, graph, node, *, labels, depth=0
) -> str: ...

def render_frame(
    store, graph, entity_iri, entity_type, axiom_changes, *, labels
) -> str: ...

def iri_to_label(store, graph, iri, *, labels) -> str: ...
```

`labels` is a `dict[str, str]` cache populated lazily per `run_diff` invocation so each IRI's `rdfs:label` lookup happens once. Fallback: when no `rdfs:label@en` exists, use the IRI's last path segment after the final `/` or `#`.

`render_class_expression` is recursive (intersection / union / nested restrictions). Depth is bounded to 10 to match the existing `_bnode_fingerprint` cap in `compute.py`; deeper nodes render as `…`.

## OWL construct coverage

Per the "Common + datatype restrictions" coverage choice from the brainstorming session.

### Axioms

| RDF predicate | Manchester keyword | Notes |
|---|---|---|
| `rdfs:subClassOf` | `SubClassOf:` | filler can be class IRI or class expression |
| `owl:equivalentClass` | `EquivalentTo:` | |
| `owl:disjointWith` | `DisjointWith:` | |
| `owl:disjointUnionOf` | `DisjointUnionOf:` | comma list |
| `rdfs:subPropertyOf` | `SubPropertyOf:` | |
| `owl:equivalentProperty` | `EquivalentTo:` | |
| `owl:inverseOf` | `InverseOf:` | |
| `rdfs:domain` / `rdfs:range` | `Domain:` / `Range:` | |
| `rdf:type owl:FunctionalProperty` etc. | `Characteristics: Functional` | one line per added/removed characteristic; multiple unchanged characteristics on the same line are not relevant since unchanged context is omitted |
| `owl:sameAs` / `owl:differentFrom` | `SameAs:` / `DifferentFrom:` | individual axioms |
| `rdf:type` (individual context) | `Types:` | |
| Property assertions on individuals | `Facts: hasTopping Tomato` | rendered per (predicate, object) pair |

The `rdf:type` triple that declares an entity's *meta*-class (e.g. `<Foo> rdf:type owl:Class`) is not emitted as an axiom line — it appears in the frame header. Property characteristics are grouped into a single `Characteristics:` line per entity.

### Class expressions

| RDF shape | Manchester |
|---|---|
| Named class | `Pizza` |
| `owl:Restriction` + `owl:onProperty p` + `owl:someValuesFrom C` | `p some C` |
| ditto + `owl:allValuesFrom` | `p only C` |
| ditto + `owl:hasValue v` | `p value v` |
| ditto + `owl:hasSelf "true"^^xsd:boolean` | `p Self` |
| `owl:cardinality n` (with optional `owl:onClass` for qualified) | `p exactly n [C]` |
| `owl:minCardinality` / `owl:minQualifiedCardinality` | `p min n [C]` |
| `owl:maxCardinality` / `owl:maxQualifiedCardinality` | `p max n [C]` |
| `owl:intersectionOf (RDF list)` | `(A and B and C)` |
| `owl:unionOf` | `(A or B or C)` |
| `owl:complementOf` | `not A` |
| `owl:oneOf` | `{a, b, c}` |
| `rdfs:Datatype` + `owl:onDatatype` + `owl:withRestrictions` (facet list) | `xsd:integer[>= 0, <= 120]` |

Facets recognized for datatype restrictions: `xsd:minInclusive`, `xsd:maxInclusive`, `xsd:minExclusive`, `xsd:maxExclusive`, `xsd:length`, `xsd:minLength`, `xsd:maxLength`, `xsd:pattern`.

### Fallback

If a blank node doesn't match any known class-expression pattern (malformed restriction, unsupported construct), `render_class_expression` returns the bnode's first-line fingerprint as `[bnode:<fp>]` and the parent axiom renders normally with that placeholder. The diff is preserved; it just isn't pretty for that one line.

## Frame structure

```
Class: SaltyPizza  (https://w3id.org/ontostart/pizza/SaltyPizza)
    SubClassOf:
-       hasTopping some Cheese
+       hasTopping some Tofu
    EquivalentTo:
+       hasTopping min 2 Vegetable
```

Rules:

- Header: `<EntityKeyword>: <label>  (<full IRI>)` where `EntityKeyword` is `Class` / `ObjectProperty` / `DataProperty` / `AnnotationProperty` / `Individual`, derived from `DiffEntity.entity_type` already set by `compute.py`.
- Axioms are grouped under their Manchester keyword. Keyword order matches the table in the "Axioms" section above.
- Within each keyword, removed lines (`-`) come before added lines (`+`).
- Indentation: keyword line at 4 spaces, axiom lines at 8 spaces (so the `-`/`+` marker sits at column 1, the axiom text starts at column 9).
- Only changed lines are included — unchanged context is omitted. The full IRI in the header lets the user navigate to the ontology page for context.
- Empty `manchester_frame` (entity has no recognized axiom changes) → field is `null`.

## Frontend changes

`HistoryTab.tsx` lines 117-130 replace the existing axiom_changes mapping with:

```tsx
{entity.manchester_frame && (
  <pre className="manchester-frame">
    {entity.manchester_frame.split('\n').map((line, i) => {
      const op = line.startsWith('-') ? 'removed'
               : line.startsWith('+') ? 'added' : null
      const color = op === 'added' ? '#3fb950'
                  : op === 'removed' ? '#f85149'
                  : 'var(--text)'
      return <div key={i} style={{ color }}>{line}</div>
    })}
  </pre>
)}
```

`DiffEntity` in `frontend/src/lib/api.ts` gains `manchester_frame: string | null`. `axiom_changes` is kept in the type and JSON for backward compatibility — the search filter at HistoryTab.tsx:194 still indexes it — but the visual rendering switches to the frame.

## Testing

- `tests/unit/test_manchester_render.py` — one focused test per construct from the coverage tables, plus the fallback path. Tests build minimal in-memory `pyoxigraph.Store` instances and call `render_axiom` / `render_class_expression` directly.
- Extend `tests/unit/test_diff_compute.py` with one frame-output test: a class with a `SubClassOf hasTopping some Tomato` restriction in one graph and `SubClassOf hasTopping some Cheese` in the other; assert `manchester_frame` contains exactly the two changed lines with `-` / `+` markers and the header line.
- No new integration tests. The existing pizza versions 0.0.11 vs 0.0.12 in the dev database are an end-to-end smoke.

## Out of scope (handled in later phases)

- **Phase 2:** Render Manchester for fully added / fully removed entities (not just modified ones). Today's `added` / `removed` lists carry entity metadata but no axioms; that needs new axiom-collection logic.
- **Phase 3:** Clickable IRIs / hover-for-label in the frame. This phase emits plain strings. To make IRIs interactive, the frame format would change to a token list — a backwards-incompatible API change.
- **Phase 4:** Diff over the inferred named graph in addition to the asserted graph. Reasoning closure can be large; the design needs to decide on a separate inferred section vs interleaved display vs an opt-in toggle.

## Risk and mitigation

- **Rendering performance.** Each modified entity triggers a Manchester render of every changed axiom. For a 1000-entity diff with deep class expressions this could be slow. Mitigation: the render is in-memory pyoxigraph (microsecond pattern lookups), and we cap recursion at depth 10. Empirically the existing diff over pizza (≈100 classes) returns in <1s; we'll re-measure with a larger ontology after implementation and add memoization if needed.
- **Format coverage gaps.** Real-world ontologies sometimes use constructs we haven't covered (e.g. `owl:propertyChainAxiom`, `owl:hasKey`). The fallback rule (`[bnode:<fp>]`) keeps the diff correct, just less pretty for those lines. If users hit specific common gaps, they're cheap to add.
- **No structured representation.** Phase 3 will want to swap the string for tokens. Designing Phase 1 around strings means Phase 3 is a breaking API change. Accepted trade-off: Phase 1 ships fast, Phase 3 is a well-bounded refactor.
