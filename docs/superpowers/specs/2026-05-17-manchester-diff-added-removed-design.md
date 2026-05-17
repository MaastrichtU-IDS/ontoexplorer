# Manchester syntax rendering for added / removed diff entities — Phase 2

**Status:** approved design
**Date:** 2026-05-17
**Depends on:** [Phase 1 — Manchester rendering for modified entities](2026-05-17-manchester-diff-rendering-design.md)
**Scope:** Extend the Manchester rendering of Phase 1 to fully-added and fully-removed entities in the version diff. Add support for annotation axioms.

## Background

Phase 1 introduced `manchester_frame: string | null` for **modified** entities only. The `added` and `removed` lists in `OntologyDiff.diff_data` carry only entity metadata (IRI, label, entity_type) — no triples, no rendered frame. The UI shows them as a bare "+ Class: Foo" or "- Class: Foo" line, which is correct but uninformative.

This phase populates `manchester_frame` for added and removed entities as well, so the user can see what the entity contributes (added) or what was lost (removed) without leaving the diff view. It also extends the renderer to handle annotation axioms (`rdfs:label`, `rdfs:comment`, common Dublin Core / SKOS terms, plus any `owl:AnnotationProperty` discovered in the graph).

## Architecture

One helper added to `ontoexplorer/modules/diff/compute.py`:

```python
def _axioms_for_entity(
    store: ox.Store, graph: ox.NamedNode, iri: str
) -> list[tuple[str, ox.Term]]:
    """Return all (predicate, object) pairs for `iri` in `graph`,
    excluding the declaring rdf:type triple (which appears in the frame header
    via the entity_type field)."""
```

`run_diff` calls it for every `added` and `removed` entity. The result is passed through `render_frame` with a new `op` keyword parameter:

```python
def render_frame(
    store, graph, entity_iri, entity_type, axiom_changes, *,
    labels, op: Literal["added", "removed", "modified"] = "modified",
) -> str: ...
```

When `op` is `"added"` or `"removed"`, every line in the rendered frame (including the header, keyword lines, and axiom lines) gets prefixed with `+ ` or `- ` respectively. When `op` is `"modified"`, the Phase 1 per-line marker logic applies and unchanged context lines (header, keywords) get no prefix.

`run_diff` passes the entity's axioms as the `axiom_changes` argument for added/removed entities — same data structure as Phase 1, except every entry has the same op value. The renderer doesn't need to know which list (added/removed/modified) the entity came from; it only needs the op.

## Annotation axiom support

A new `Annotations:` block is rendered at the top of every frame, before logical keyword blocks. An axiom counts as an annotation when its predicate is:

1. In a hardcoded set of well-known annotation properties:
   - `rdfs:label`, `rdfs:comment`, `rdfs:seeAlso`, `rdfs:isDefinedBy`
   - `dc:title`, `dc:description`, `dc:creator` (legacy `http://purl.org/dc/elements/1.1/` namespace)
   - `dcterms:title`, `dcterms:description`, `dcterms:creator`, `dcterms:license`
   - `skos:prefLabel`, `skos:altLabel`, `skos:definition`, `skos:scopeNote`, `skos:example`
   - `owl:versionInfo`, `owl:deprecated`, `owl:priorVersion`, `owl:incompatibleWith`
2. OR typed `owl:AnnotationProperty` in the named graph. Discovered via one SPARQL query per `run_diff` invocation, cached alongside `labels`.

Format:

```
    Annotations:
        rdfs:label "Margherita Pizza"@en,
        rdfs:comment "Classic Neapolitan pizza"@en
```

- Predicate displayed as a CURIE when the namespace is one of the hardcoded prefix set (`rdfs:`, `dc:`, `dcterms:`, `skos:`, `owl:`). Otherwise the full IRI in angle brackets: `<https://example.org/some-vocab/term>`.
- Literal objects: `"value"` with optional `@lang` and optional `^^<datatype>` (suppressed when datatype is `xsd:string`).
- IRI / blank-node objects (rare for annotations but legal): rendered via the existing class-expression renderer.
- Multiple annotation lines sorted by `(predicate, lang, value)` for stable output across runs.

Annotation predicates are excluded from `_axioms_for_entity`'s logical-axiom pass and routed to the new `Annotations:` block. This means the modified-frame view (Phase 1) also gains annotation rendering for free when an annotation value changes — a useful side effect.

## Frame example (added entity)

```
+ Class: Margherita  (https://w3id.org/ontostart/pizza/Margherita)
+     Annotations:
+         rdfs:label "Margherita Pizza"@en,
+         rdfs:comment "Classic Neapolitan pizza"@en
+     SubClassOf:
+         Pizza,
+         hasTopping some Tomato,
+         hasTopping some Mozzarella
```

Removed entities are identical with `-` substituted for `+`. An entity with no axioms beyond its declaration produces a single-line frame: `+ Class: BareClass  (...)`.

## Frontend changes

The same `<pre>`-with-line-coloring renderer from Phase 1 now also displays `manchester_frame` for added and removed entries. Coloring rule (already in the Phase 1 implementation):

- Line starting with `+ ` → green
- Line starting with `- ` → red
- Anything else → default text color

`DiffEntity` in `frontend/src/lib/api.ts` keeps the single `manchester_frame: string | null` field; no schema change needed.

The existing `added` / `removed` rendering loop in `HistoryTab.tsx` mounts the same frame component below the entity name and IRI chip. Truthy-check on `manchester_frame` so entities that produce empty frames (no recognizable axioms) just show the bare entity line.

## Testing

- `tests/unit/test_manchester_render.py` gains tests:
  - `render_frame(op="added")` produces uniform `+ ` prefix on every line including header and keyword lines.
  - `render_frame(op="removed")` produces uniform `- ` prefix on every line.
  - `render_frame(op="modified")` produces no prefix on header / keyword lines (Phase 1 regression check).
  - Annotation block renders `rdfs:label`, `dc:description`, an `owl:AnnotationProperty`-declared custom predicate, sorted alphabetically.
- `tests/unit/test_diff_compute.py` gains tests:
  - Added class with one `SubClassOf` and one `rdfs:label` yields a frame with both blocks, `+ ` on every line.
  - Removed individual with `rdf:type` (declaring it as `NamedIndividual`) and a property assertion yields a `Types:` and `Facts:` block with `- ` prefixes.
  - Bare added class (only the declaring `rdf:type owl:Class`) yields a single-line `+ Class: BareClass (...)` frame.

## Risk and mitigation

- **Frame size for heavily-annotated entities.** Real-world ontologies (e.g. SNOMED, GO) often have dozens of annotations per class — multilingual labels, definitions, examples. Phase 2 does NOT truncate. If diff frames become unwieldy in practice we add a `... and N more` collapse rule in a follow-up; deferred since the Phase 2 frame is currently shown inline and the diff view already has scrolling.
- **Annotation property discovery cost.** The `SELECT ?p WHERE { ?p a owl:AnnotationProperty }` pre-pass runs once per `run_diff` invocation over both `from_graph` and `to_graph`. Cost is negligible (typical ontologies have <100 annotation properties), and the result is cached for the rest of the run.
- **Annotations on a modified entity that didn't change.** Phase 1 only shows changed axioms. With annotations now in scope, a modified-frame view will only include changed annotation lines, not all annotations. The header still shows the canonical label, so the user has context.

## Out of scope (Phase 3+)

- Clickable IRIs / hover-for-label on the rendered frame text — Phase 3.
- Diffing inferred axioms — Phase 4.
- Truncation / collapse UI for very long frames — deferred until we see real-world bloat.
- Datatype property assertions on individuals using complex datatypes (e.g. `xsd:integer[>= 0]` ranges) — covered by Phase 1's datatype-restriction support, no new work.
