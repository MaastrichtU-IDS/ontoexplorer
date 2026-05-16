# Ontology Version Diff & Changelog Design

## Problem

OntoExplorer ingests multiple versions of the same ontology over time but provides no way to understand what changed between them. Curators re-ingesting a new GO release, administrators monitoring a repository, and downstream consumers who depend on specific terms all need to answer: "what actually changed?"

## Goal

Compute, store, and surface a structured diff between any two versions of an ontology. Pair it with an optional LLM-generated changelog narrative. Expose both through a History tab on the ontology page and a REST API.

## Scope

- **In scope:** asserted axioms only; consecutive versions pre-computed automatically; arbitrary version pairs computed on demand and cached; term-centric view with literal and axiom change detail; LLM changelog narrative (opt-in).
- **Out of scope:** inferred (ELK) hierarchy diffs, import-chain diffs, cross-ontology impact analysis (planned separately as subsystem B).

---

## Architecture

Three sequenced subsystems, each independently deployable:

1. **Diff compute + storage** — Celery task, Postgres table, API endpoints
2. **History tab UI** — React components integrated into OntologyPage
3. **LLM changelog** — narrative generation endpoint and UI button

---

## Subsystem 1: Diff Compute + Storage

### Data model

New table `ontology_diffs`:

```sql
CREATE TABLE ontology_diffs (
    id          TEXT PRIMARY KEY,
    ontology_id TEXT NOT NULL REFERENCES ontologies(id) ON DELETE CASCADE,
    version_from_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    version_to_id   TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | failed
    summary     JSONB,
    diff_data   JSONB,
    narrative   TEXT,           -- NULL until LLM generates it
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (version_from_id, version_to_id)
);
```

### `summary` shape

```json
{
  "added": 23,
  "removed": 5,
  "modified": 47,
  "literal_changes": 31,
  "axiom_changes": 22,
  "by_entity_type": {
    "class":               {"added": 20, "removed": 4,  "modified": 37},
    "object_property":     {"added": 2,  "removed": 1,  "modified": 6},
    "data_property":       {"added": 1,  "removed": 0,  "modified": 2},
    "annotation_property": {"added": 0,  "removed": 0,  "modified": 1},
    "individual":          {"added": 0,  "removed": 0,  "modified": 1}
  }
}
```

### `diff_data` shape

```json
{
  "added": [
    {"iri": "http://...", "label": "mitochondrial rRNA modification", "entity_type": "class"}
  ],
  "removed": [
    {"iri": "http://...", "label": "reproduction (obsolete)", "entity_type": "class"}
  ],
  "modified": [
    {
      "iri": "http://purl.obolibrary.org/obo/GO_0000001",
      "label": "mitochondrial genome maintenance",
      "entity_type": "class",
      "literal_changes": [
        {
          "predicate": "http://www.w3.org/2000/01/rdf-schema#label",
          "lang": "en",
          "removed": "mitochondrial inheritance",
          "added": "mitochondrial genome maintenance"
        },
        {
          "predicate": "http://purl.obolibrary.org/obo/IAO_0000115",
          "lang": "en",
          "removed": null,
          "added": "The maintenance of the..."
        }
      ],
      "axiom_changes": [
        {"op": "removed", "axiom": "SubClassOf(<GO_0000001> <GO_0006996>)"},
        {"op": "added",   "axiom": "SubClassOf(<GO_0000001> <GO_0006259>)"}
      ]
    }
  ]
}
```

A term with no literal or axiom changes after comparison is excluded from `modified`.

### Compute algorithm

Celery task `compute_diff(version_from_id: str, version_to_id: str)`:

1. Load both Oxigraph named graphs via `asyncio.to_thread`.
2. For each entity type (`owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`, `owl:AnnotationProperty`, `owl:NamedIndividual`): collect all IRIs from each graph.
3. Set operations: `added = to_iris − from_iris`, `removed = from_iris − to_iris`, `shared = from_iris ∩ to_iris`.
4. For each IRI in `shared`: fetch all `(predicate, object)` pairs from both graphs.
   - **Literal changes:** pairs where `object` is a literal; compare the two sets; record added/removed with predicate and language tag.
   - **Axiom changes:** pairs where `object` is a URI or blank node (structural triples); compare sets; record added/removed as Manchester-style strings.
   - If no changes in either: skip (entity unchanged).
5. Assemble `summary` and `diff_data`; write to `ontology_diffs` with `status = 'ready'`.
6. On any unhandled exception: write `status = 'failed'`.

Blank-node handling: blank nodes in axiom objects are serialized to a stable string representation (N-Triples fragment) for comparison, since their identity across graphs is structural not by ID.

### Auto-trigger

In the `ingest_ontology` Celery task, after status transitions to `"indexed"`:

```python
prev = await db.scalar(
    select(OntologyVersion)
    .where(OntologyVersion.ontology_id == ontology_id,
           OntologyVersion.id != version_id,
           OntologyVersion.status.in_(["indexed", "ready"]))
    .order_by(OntologyVersion.created_at.desc())
    .limit(1)
)
if prev:
    compute_diff.delay(str(prev.id), str(version_id))
```

### API endpoints

```
# Consecutive diff for a version (pre-computed)
GET /api/v1/ontologies/{id}/{vid}/diff
→ 200 {status, summary, diff_data, narrative}
→ 404 if no previous version exists
→ 202 {status: "pending"} while Celery task is running

# Arbitrary pair — cached if previously computed, else enqueues
GET /api/v1/ontologies/{id}/diff?from={vid1}&to={vid2}
→ 200 {status, summary, diff_data, narrative}   if ready
→ 202 {status: "pending", job_id}               if computing
→ 404 if either version not found

# Trigger computation explicitly
POST /api/v1/ontologies/{id}/diff/compute?from={vid1}&to={vid2}
→ 202 {job_id}

# Generate (or retrieve cached) LLM narrative — see Subsystem 3
POST /api/v1/ontologies/{id}/{vid}/diff/narrative
→ 200 {narrative: "..."}
```

---

## Subsystem 2: History Tab UI

### Integration

A new `"History"` tab is added to the existing tab row on `OntologyPage` (alongside Overview, Profile, Metadata). It renders only when the selected version has at least one diff (consecutive or otherwise).

### Component tree

```
HistoryTab
├── DiffVersionPicker        — "Compare v2024-01 → v2024-02 (current)"
├── DiffOperationToggles     — +23 added  −5 removed  ~47 modified (toggleable)
├── DiffFilters
│   ├── TypeChips            — All / Class / Obj. property / Data property / Ann. property / Individual
│   ├── ChangeChips          — All / Literal / Axiom
│   └── KeywordSearch        — searches label, IRI, changed values; highlights matches
├── ResultCount              — "Showing 14 of 75 entities matching 'mitochondrial'"
├── DiffChangelog            — LLM narrative block (see Subsystem 3)
└── DiffEntityList
    └── DiffEntityRow (×N)
        ├── collapsed: IRI, label, entity type, literal/axiom badges
        └── expanded:
            ├── LiteralChangesSection  — predicate, lang, removed (red), added (green)
            └── AxiomChangesSection    — removed (red), added (green)
```

### Filter logic

All filters compose (AND). Client-side — `diff_data` is fetched once and filtered in memory:

- **Operation toggles:** show/hide the added, removed, and/or modified sublists independently.
- **Type chips:** restrict to entities of the selected `entity_type`.
- **Change chips:** for the modified list, restrict to entities that have at least one change of the selected type (`literal_changes.length > 0` or `axiom_changes.length > 0`).
- **Keyword search:** case-insensitive substring match against `label`, `iri`, and all `literal_changes[*].removed|added` and `axiom_changes[*].axiom` strings.

### Version picker behaviour

- Default "from" version: the immediately preceding version (by `created_at`) of the one currently viewed.
- Default "to" version: the currently viewed version.
- Changing either dropdown calls `GET /diff?from=…&to=…`; shows a spinner while pending.
- If status is `"pending"`, polls every 3 s (same pattern as ELK reasoning status).

### Keyword search highlighting

Matched substrings are wrapped in `<mark>` elements. The colour of the highlight inherits from the operation context (green for added, red for removed, amber for modified row header).

---

## Subsystem 3: LLM Changelog Narrative

### Generation

`POST /api/v1/ontologies/{id}/{vid}/diff/narrative`:

1. Load the `ontology_diffs` row for `(prev_vid, vid)`.
2. If `narrative` is already set: return it immediately.
3. Build a prompt from `summary` (not `diff_data` — keeps the prompt small):

```
Summarise the changes between two versions of an ontology in 2–3 sentences suitable for release notes.
Be specific about counts and entity types. Do not start with "This version" or "In this version".

From: {version_from.version_iri or version_from.id}
To:   {version_to.version_iri or version_to.id}

Changes:
- Added:    {added} entities ({by_entity_type breakdown})
- Removed:  {removed} entities ({by_entity_type breakdown})
- Modified: {modified} entities — {literal_changes} with literal changes, {axiom_changes} with axiom changes
```

4. Call `anthropic.Anthropic().messages.create(model="claude-haiku-4-5-20251001", max_tokens=300, ...)`.
5. Store the result in `ontology_diffs.narrative`; return `{narrative: "..."}`.

The endpoint is synchronous (waits for the Haiku response, typically < 2 s). No Celery task needed.

### UI

The `DiffChangelog` component:

- If `narrative` is `null` and no generation in progress: shows a **"Generate changelog"** button (green, top-right of the History tab).
- While generating: button becomes a spinner.
- Once available: renders the narrative text in a muted italic block with a copy button (⎘).
- Narrative persists across page reloads (stored server-side).

---

## Data Flow Summary

```
ingest_ontology completes
        │
        ▼
compute_diff(prev_vid, new_vid)          ← Celery, auto-triggered
        │
        ▼
ontology_diffs row (status=ready)
        │
        ├─► GET /{id}/{vid}/diff         ← consecutive diff (History tab default)
        ├─► GET /{id}/diff?from=&to=     ← arbitrary pair
        │
        └─► POST /{id}/{vid}/diff/narrative  ← on demand, stores result
                │
                ▼
            Claude Haiku → narrative column
```

---

## Key Design Decisions

| Concern | Decision | Rationale |
|---|---|---|
| Diff granularity | Term-centric primary; literal vs. axiom change types | Curators think in terms of entities, not triples; two change types map cleanly to annotation vs. structural edits |
| Storage | Postgres JSONB | `diff_data` for GO can be ~1–5 MB; JSONB handles this; no separate store needed |
| Blank nodes | Serialize to N-Triples fragment for comparison | Blank node IDs are graph-local; structural content is the identity |
| Consecutive auto-trigger | After ingest, look up latest ready version | Zero configuration; covers the common case; arbitrary pairs still on demand |
| Arbitrary pair caching | Same `ontology_diffs` table, unique on (from, to) | First request pays the compute cost; all subsequent requests are instant |
| Client-side filtering | Fetch full `diff_data` once, filter in memory | Avoids N API calls for filter changes; diff data fits comfortably in memory for typical ontologies |
| LLM model | claude-haiku-4-5 | Fast and cheap for a summarisation task over a small structured input |
| Narrative generation | Synchronous endpoint, stored on first call | Simple; Haiku is fast enough; no webhook or polling needed |
| Asserted-only scope | No imports, no inferred | Cleanest boundary; import diffs and impact analysis are separate subsystems |
