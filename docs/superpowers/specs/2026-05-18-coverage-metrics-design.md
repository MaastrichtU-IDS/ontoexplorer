# Coverage Metrics — Design

## Goal

Quantify how well-populated each loaded ontology version is in terms of **labels**, **definitions**, and **multilingual content**, broken out by entity type (class / object property / data property / annotation property / individual). Surface the metrics two ways:

1. **Fleet view** on a new `/coverage` page — one row per ontology, sortable, click-through to detail.
2. **Per-version scorecard** as a new section on `OntologyPage.tsx`, with per-language breakdown.

This is a natural extension of the existing annotation-profile work: that subsystem detects *which* properties carry labels/definitions/synonyms per ontology; coverage metrics measure *how many* terms actually use them.

## Non-goals

- Synonym coverage (deferred).
- Other quality dimensions (deprecated handling, example use cases, axiom richness, etc.).
- Drilling into the specific terms that are missing data (this is a roll-up view, not a quality-gate report).
- Historical trend (we only compute coverage for the current version; no time-series).

## Architecture

### Computation: piggyback on the indexer

The indexer's `_populate_stats_cache` at [indexer.py:693](../../../ontoexplorer/modules/search/indexer.py#L693) runs at the end of every (re-)index and already has these in-memory dicts populated at [indexer.py:284-353](../../../ontoexplorer/modules/search/indexer.py#L284-L353):

- `entities: dict[iri, entity_type]` — every non-deprecated entity in the version
- `labels_by_iri: dict[iri, list[{value, lang}]]`
- `defs_by_iri: dict[iri, list[{value, lang}]]`
- `deprecated_iris: set[iri]`

Adding a sibling helper `_compute_coverage(entities, deprecated_iris, labels_by_iri, defs_by_iri) -> dict` is **O(entities)** and adds zero SPARQL queries. The output is written to a new Redis key alongside the stats cache, with the same TTL (`_SEARCH_TTL`).

### Storage: Redis only

New helper `_coverage_cache_key(version_id) -> "coverage:{version_id}"` mirroring `_stats_cache_key`. No DB migration. The Redis cache is repopulated on every reindex; if Redis is flushed and a coverage endpoint is hit before reindex, the API returns `404 "Coverage not computed — reindex pending"` (same shape as missing stats).

### Schema

Per-version coverage record:

```json
{
  "version_id": "uuid",
  "indexed_at": "2026-05-18T12:34:56Z",
  "by_type": {
    "class": {
      "total": 12345,
      "with_label": 12000,
      "with_definition": 8000,
      "multilingual": 450,
      "by_lang": { "en": 11800, "de": 320, "fr": 200, "": 7 }
    },
    "object_property":     { ...same shape... },
    "data_property":       { ...same shape... },
    "annotation_property": { ...same shape... },
    "individual":          { ...same shape... }
  }
}
```

Definitions:

- `total` = count of non-deprecated entities of this type.
- `with_label` = entities with ≥1 label literal under any `label_props` predicate.
- `with_definition` = entities with ≥1 definition under any `definition_props` predicate.
- `multilingual` = entities with labels in ≥2 **distinct** lang tags. Empty lang tag (`""`) is its own bucket. (An entity with `"foo"` and `"foo"@en` counts as multilingual; one with `"foo"@en` and `"bar"@en` does not.)
- `by_lang` = lang-tag → count of entities with at least one label in that tag. Keys are the lang tags as they appear in the data; empty string represents untagged literals.

Note: `by_lang` counts entities, not labels. An entity with two English labels increments `en` by 1, not 2.

### Fleet rollup schema

Returned by `GET /api/v1/coverage/public`:

```json
{
  "totals": {
    "class":              { "total": N, "with_label": N, "with_definition": N, "multilingual": N },
    "object_property":    { ...same... },
    "data_property":      { ...same... },
    "annotation_property":{ ...same... },
    "individual":         { ...same... }
  },
  "by_ontology": [
    {
      "ontology_id":   "uuid",
      "version_id":    "uuid",
      "shortname":     "go",
      "title":         "Gene Ontology",
      "indexed_at":    "2026-05-18T12:34:56Z",
      "by_type":       { ...same as per-version `by_type`, without by_lang to keep payload small... }
    },
    ...
  ]
}
```

`by_lang` is omitted from the fleet rollup to keep it compact; clients fetch the per-version endpoint for the language breakdown.

`totals` is a straight sum across all ontologies. Ontologies whose coverage cache is missing are silently skipped (same behavior as the existing `_stats_cache_key` rollup in `/stats/public`).

## API

### `GET /api/v1/coverage/public`

No auth (mirrors `/stats/public`). Returns the fleet rollup above. Implemented in a new file `ontoexplorer/api/coverage.py` registered in `main.py`.

### `GET /api/v1/ontologies/{ontology_id}/{version_id}/coverage`

Returns the per-version record. 404 if the cache key is absent. Lives in the same `coverage.py`.

Both endpoints read from Redis only — no SPARQL at request time.

## Frontend

### New page `/coverage` (Coverage.tsx)

Top: three summary cards across the fleet — *Label coverage*, *Definition coverage*, *Multilingual coverage* — each showing the weighted average across all ontologies for classes (since classes are usually the bulk).

Below: a sortable table, one row per ontology. Columns:

| Ontology | Classes | Class label % | Class def % | Class multilingual % | Props label % | Props def % | Indivs label % |

(Properties columns aggregate object + data + annotation properties to keep the table narrow.)

Click a row → navigate to `/ontologies/{slug}` and scroll to the Coverage section.

### `OntologyPage.tsx` — new Coverage section

A new collapsible section, similar to existing sections. Inside:

- Five mini-scorecards (one per entity type) each showing `with_label`, `with_definition`, `multilingual` as percentages and absolute counts.
- A language-distribution block below the cards: horizontal bar (or compact table) showing `by_lang` for *classes* only (the dominant entity type). Each bar segment shows lang code and count.
- "Last computed: {indexed_at}" footer.

### Nav

Add `Coverage` to the main nav (between `Stats` and existing entries — placement details deferred to implementation).

### API client

Two new functions in `frontend/src/lib/api.ts`:

- `api.coverage.fleet(): Promise<CoverageFleet>`
- `api.coverage.version(ontologyId, versionId): Promise<CoverageRecord>`

With TypeScript interfaces mirroring the schemas above.

## Edge cases

- **Deprecated entities** are excluded from `total` and all sub-counts (they're already filtered before label/def collection at [indexer.py:370-372](../../../ontoexplorer/modules/search/indexer.py#L370)).
- **Ontologies with zero entities of a given type** report `total: 0` and 0 for all sub-counts. UI renders `—` instead of `NaN%`.
- **Cache miss** (no coverage key in Redis): per-version endpoint returns 404; fleet endpoint silently skips the ontology and excludes it from totals. UI shows "Coverage not yet computed — will be available after the next reindex" placeholder when no version is cached.
- **Empty lang tag**: `""` is a legitimate bucket in `by_lang`. UI renders it as `(no lang)`.
- **Properties without an OWL type** (rare): the indexer doesn't bucket them into one of the five types; they don't appear in `entities` and are therefore ignored by coverage too. Acceptable — this matches search/stats behavior.

## Testing

- Unit test `_compute_coverage` with synthetic dicts: empty input; all entities labeled; mixed multilingual/monolingual; deprecated entities excluded; lang-tag bucketing including empty tag.
- Integration test: index a small fixture ontology end-to-end, hit `/api/v1/ontologies/{oid}/{vid}/coverage`, assert the shape and counts match expectations.
- Integration test: `/api/v1/coverage/public` aggregates across multiple cached versions; missing cache is silently skipped.
- Frontend: render `Coverage.tsx` against fixture data, assert table sorting and `—` rendering for zero-total cells; render the per-ontology section against fixture data, assert language bar rendering.
