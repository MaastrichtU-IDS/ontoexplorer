# Clickable IRIs and hover-for-label in the Manchester diff frame — Phase 3

**Status:** approved design
**Date:** 2026-05-17
**Depends on:** [Phase 1 — Manchester rendering for modified entities](2026-05-17-manchester-diff-rendering-design.md), [Phase 2 — added / removed entity frames](2026-05-17-manchester-diff-added-removed-design.md)
**Scope:** Replace the flat-string `manchester_frame` output from Phases 1 / 2 with a structured token list, enabling clickable in-ontology IRIs and hover-for-IRI tooltips.

## Background

Phases 1 and 2 emit `manchester_frame` as a single `string` with `+ ` / `- ` line prefixes. The rendered frame shows human-readable labels (`Pizza`, `hasTopping some Tomato`), but the user has no way to drill into an entity from the diff view — labels are inert text. This phase makes every IRI reference within the frame clickable when the IRI is part of the ontology version's named graph, with the full IRI surfaced on hover.

## Architecture

The shape of `manchester_frame` changes from `string | null` to a structured token list:

```typescript
type ManchesterFrame = {
  lines: Array<{
    op: 'added' | 'removed' | null   // line-level marker for color/prefix
    tokens: Array<
      | { t: 'text', v: string }      // includes whitespace, punctuation, keywords
      | { t: 'iri', label: string, iri: string, in_ontology: boolean }
    >
  }>
} | null
```

Backend renderer changes:

- `render_frame` returns a structured `ManchesterFrame` object instead of a string. Indentation is embedded in `text` tokens; the frontend renders tokens linearly without needing to compute layout.
- Each IRI that previously rendered into a Manchester string (entity references in axioms, fillers in class expressions, frame header IRI) now emits an `iri` token.
- All non-IRI text (keywords like `SubClassOf:`, operators like `some` / `and`, punctuation, whitespace) emits `text` tokens.

The breaking JSON change is acceptable since `manchester_frame` was introduced in Phase 1 specifically for UI consumption and has no documented external consumer.

## Determining `in_ontology`

One SPARQL pre-pass at the start of `run_diff` populates a set of IRIs that the ontology version "knows about":

```sparql
SELECT DISTINCT ?iri FROM <named-graph> WHERE { ?iri ?p ?o }
```

Plus a second pass for IRIs appearing only as objects:

```sparql
SELECT DISTINCT ?iri FROM <named-graph> WHERE { ?s ?p ?iri . FILTER(isIRI(?iri)) }
```

The union is cached as `known_iris: set[str]` alongside the `labels` dict for the duration of the `run_diff` call. The renderer sets `in_ontology = iri in known_iris` when emitting each IRI token.

This includes asserted entities, entities pulled in via `owl:imports` closure (since those triples are merged into the same named graph by the ingestion pipeline), and entities referenced only as fillers or types. External IRIs that the version's graph does not mention at all are excluded.

Cost: two `SELECT DISTINCT` queries over a single named graph; negligible relative to the rest of the diff computation. For pizza's ~2000-triple graph these take milliseconds; for a 1M-triple ontology they take a fraction of a second.

## Click behavior

- `in_ontology: true` → frontend renders the token as a React Router `<Link>` to `/ontologies/<shortname>/<entity-slug>`. Same tab. Back-button restores the diff view.
- `in_ontology: false` → frontend renders the token as a plain `<span>` with `title={iri}` only. No href, default cursor.

`entity-slug` is derived from the IRI using whatever helper exists in the frontend for the ontology entity-page route. If no helper exists, the implementation will URL-encode the full IRI as a path segment (the entity page route must accept that form).

## Hover behavior

Plain HTML `title={iri}` attribute on every IRI token's rendered element. Browser native tooltip. No third-party tooltip library. The user sees the label in the frame text and gets the full IRI on hover after the OS-default tooltip delay (~500ms).

## Frontend renderer

`HistoryTab.tsx` replaces the Phase 1/2 `<pre>`-line-splitter with a structured renderer:

```tsx
{frame.lines.map((line, i) => (
  <div key={i} style={{ color: lineColor(line.op), fontFamily: 'monospace' }}>
    <span>{lineMarker(line.op)}</span>
    {line.tokens.map((t, j) =>
      t.t === 'text'
        ? <span key={j}>{t.v}</span>
        : t.in_ontology
          ? <Link key={j}
                  to={entityUrl(shortname, t.iri)}
                  title={t.iri}
                  style={{ color: 'inherit', textDecoration: 'underline' }}>
              {t.label}
            </Link>
          : <span key={j} title={t.iri}>{t.label}</span>
    )}
  </div>
))}
```

`lineMarker(op)` returns `'+ '` / `'- '` / `'  '`. CSS keeps a monospace font so the Manchester layout reads as code, and underline-on-link visually distinguishes navigable references.

## `axiom_changes` field

The per-axiom `axiom_changes[i].axiom` string (Phase 1 format) is retained in the JSON for backwards compatibility with any non-UI API consumer. The UI ignores it in Phase 3 and renders only from `manchester_frame.lines`. We can prune the field in a later cleanup.

## Migration

Phase 3 changes `manchester_frame` from `string | null` to the new object shape directly. There is no parallel field, no deprecation window. Backend and frontend ship the change in one PR. If Phase 3 is implemented before Phase 1 has shipped to production, Phase 1 / 2 can emit the new token shape from the start and the string format becomes a historical design-doc artifact.

## Testing

- `tests/unit/test_manchester_render.py` gains:
  - `render_frame` returns a `ManchesterFrame` with `lines: [...]` shape.
  - For a class with a restriction whose filler is a named class in the same graph: two `iri` tokens are emitted (subject + filler), both with `in_ontology: true`.
  - For a class whose filler is an IRI absent from the graph: `iri` token has `in_ontology: false`.
  - Label fallback: an IRI without `rdfs:label@en` emits a token where `label` is the local name.
- `tests/unit/test_diff_compute.py` gains: `_known_iris` SPARQL pre-pass returns IRIs from both asserted triples and import-closure triples (test with a tiny synthetic import-closure setup).
- `frontend/src/components/HistoryTab.test.tsx` (new) tests the renderer component with a fixture frame: one `iri` token with `in_ontology=true` renders as `<a>` with `href`, `title`, and underline; one with `in_ontology=false` renders as `<span>` with `title` only and no `href`.

## Risk and mitigation

- **Entity-page slug rule mismatch.** The entity-page route may expect a slugified ID rather than a raw local name (e.g., for entities with non-URL-safe characters). The implementation will reuse whatever slug helper the dashboard already has; if none exists, URL-encoding the full IRI as a single path segment is the fallback (the entity route must accept that).
- **`in_ontology` false positives.** An IRI that appears only as the object of a triple — e.g., `ex:Foo a ex:UnknownMetaclass` — will be marked `in_ontology: true` even though no triples *describe* `ex:UnknownMetaclass`. Clicking lands on a sparse entity page. Acceptable: matches "the diff mentions this thing, let me look at it," and better than a dead link.
- **Payload growth.** Tokenized frames are roughly 2-3x the byte size of the flat-string equivalent. For typical diffs (≤50 modified entities, ≤30 axioms each) this is tens of KB. Negligible. If we later see very large diffs we can compress server-side or paginate at the entity level.
- **Right-click "open in new tab" still works.** React Router `<Link>` renders an `<a href>` underneath, so users who want a new tab can shift-click / cmd-click as usual. No special handling needed.

## Out of scope (Phase 4)

- Diff over the inferred named graph (`urn:ontology:…:inferred`) in addition to the asserted graph. Phase 4.
- Side-panel preview on click (open entity definition next to the diff). Offered as an option during brainstorming, not chosen — same-tab navigation is simpler and fits the current app navigation pattern.
- Custom non-OS tooltip with richer hover content (entity type + a few axioms + back-references). Defer until users ask for it; HTML `title` is good enough as a baseline.
