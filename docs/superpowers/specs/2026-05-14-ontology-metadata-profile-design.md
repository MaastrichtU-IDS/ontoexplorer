# Ontology Metadata Profile — Term-Level Annotation Standardisation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Per-version profiles that record which annotation property IRIs carry labels, definitions, synonyms, and deprecated flags — auto-detected from the ontology content, user-confirmable via a UI linked to the import flow.

**Architecture:** A new `ontology_profiles` Postgres table (one row per version) stores the mapping. A `detect_profile` Celery task runs after ingest and before index, querying Oxigraph to count property usage across OWL classes and matching against a server-side curated registry. The indexer reads the profile instead of a hardcoded predicate list. The UI exposes a post-import review banner and a dedicated Profile tab per version.

**Tech Stack:** Python/SQLAlchemy (new DB table + Alembic migration), FastAPI (4 new endpoints), Celery (new task in existing pipeline), React/TypeScript (OntologyPage banner + Profile tab), existing Oxigraph SPARQL client.

---

## Data Model

### `ontology_profiles` table

```sql
CREATE TABLE ontology_profiles (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id       UUID NOT NULL UNIQUE REFERENCES versions(id) ON DELETE CASCADE,
    label_props      TEXT[] NOT NULL DEFAULT '{}',
    definition_props TEXT[] NOT NULL DEFAULT '{}',
    synonym_props    TEXT[] NOT NULL DEFAULT '{}',
    deprecated_props TEXT[] NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'auto_detected',
                         -- 'auto_detected' | 'user_confirmed'
    unknown_props    JSONB NOT NULL DEFAULT '[]',
                         -- [{iri, count, pct_of_classes}] for unrecognised properties
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Array order is significant: the indexer and renderer use the **first matching property** as the primary value for labels and definitions. For synonyms, all matching properties contribute to the flat pool.

### Curated property registry

A server-side Python dict (`ontoexplorer/modules/profile/registry.py`) — not stored in the DB. Defines the known IRIs per role in default priority order:

| Role | IRIs (priority order) |
|---|---|
| `label` | `rdfs:label`, `skos:prefLabel`, `dcterms:title`, `dc:title`, `schema:name` |
| `definition` | `IAO:0000115`, `skos:definition`, `rdfs:comment`, `dcterms:description` |
| `synonym` | `skos:altLabel`, `oboInOwl:hasExactSynonym`, `oboInOwl:hasRelatedSynonym`, `oboInOwl:hasBroadSynonym`, `oboInOwl:hasNarrowSynonym` |
| `deprecated` | `owl:deprecated` |

Full IRIs used throughout (no prefix shorthand in code):
- `http://www.w3.org/2000/01/rdf-schema#label`
- `http://www.w3.org/2004/02/skos/core#prefLabel`
- `http://purl.org/dc/terms/title`
- `http://purl.org/dc/elements/1.1/title`
- `https://schema.org/name`
- `http://purl.obolibrary.org/obo/IAO_0000115`
- `http://www.w3.org/2004/02/skos/core#definition`
- `http://www.w3.org/2000/01/rdf-schema#comment`
- `http://purl.org/dc/terms/description`
- `http://www.w3.org/2004/02/skos/core#altLabel`
- `http://www.geneontology.org/formats/oboInOwl#hasExactSynonym`
- `http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym`
- `http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym`
- `http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym`
- `http://www.w3.org/2002/07/owl#deprecated`

---

## Pipeline

```
ingest → detect_profile → index → reason
                ↑
    user edits profile → PATCH /profile → re-index
```

### detect_profile task

New Celery task `detect_ontology_profile(version_id)`, registered in `tasks.py`, called immediately after `ingest_ontology` succeeds (before `index_ontology` is enqueued).

**Algorithm:**

1. Fetch the version's asserted graph IRI from Postgres.
2. For each IRI in the curated registry, run a SPARQL COUNT against Oxigraph:
   ```sparql
   SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {
     GRAPH <version_graph_iri> {
       ?s a <http://www.w3.org/2002/07/owl#Class> .
       ?s <property_iri> ?o .
     }
   }
   ```
3. Check the ontology header node for `mod:prefLabelProperty` (`https://w3id.org/mod#prefLabelProperty`) and `mod:definitionProperty` (`https://w3id.org/mod#definitionProperty`). If present, move those IRIs to position 0 in the respective list regardless of count.
4. For each role, include all curated IRIs with count > 0, ordered by descending count (with mod: boost applied).
5. Scan for any annotation property used on >5% of OWL classes that is NOT in the curated registry — store these as `unknown_props` JSONB on the profile row; surfaced via the `/candidates` API (no live Oxigraph query needed at read time).
6. Write the result to `ontology_profiles` (INSERT or UPDATE) with `status = 'auto_detected'`.
7. Enqueue `index_ontology`.

**Failure handling:** If `detect_profile` raises, log the error, write no profile row, and still enqueue `index_ontology`. The indexer falls back to the curated registry defaults when no profile row exists.

---

## API

All endpoints require authentication. `PATCH` and `POST` require ontology owner or admin.

Base path: `/api/v1/ontologies/{ontology_id}/versions/{version_id}/profile`

### GET `/profile`

Returns the stored profile for the version.

Response:
```json
{
  "version_id": "...",
  "label_props": ["http://www.w3.org/2000/01/rdf-schema#label"],
  "definition_props": ["http://purl.obolibrary.org/obo/IAO_0000115"],
  "synonym_props": ["http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"],
  "deprecated_props": ["http://www.w3.org/2002/07/owl#deprecated"],
  "status": "auto_detected",
  "updated_at": "2026-05-14T10:00:00Z"
}
```

Returns 404 if no profile row exists yet (detection still running or ingest failed).

### PATCH `/profile`

Save user edits. Sets `status = 'user_confirmed'`. Enqueues `index_ontology` for re-indexing.

Request body (all fields optional — omitted fields unchanged):
```json
{
  "label_props": ["http://www.w3.org/2004/02/skos/core#prefLabel"],
  "definition_props": ["http://purl.obolibrary.org/obo/IAO_0000115"],
  "synonym_props": ["http://www.w3.org/2004/02/skos/core#altLabel"],
  "deprecated_props": ["http://www.w3.org/2002/07/owl#deprecated"]
}
```

Returns the updated profile object.

### POST `/profile/detect`

Manually re-trigger auto-detection. Enqueues `detect_profile` task, which will then enqueue `index_ontology` on completion. Resets `status = 'auto_detected'`.

Returns `{"task_id": "...", "status": "queued"}`.

### GET `/profile/candidates`

Returns all annotation properties found in the ontology with usage counts, grouped by matched curated role and with unrecognised properties flagged separately.

Response:
```json
{
  "version_id": "...",
  "matched": {
    "label": [
      {"iri": "http://www.w3.org/2000/01/rdf-schema#label", "count": 842, "mod_declared": true}
    ],
    "definition": [
      {"iri": "http://www.w3.org/2000/01/rdf-schema#comment", "count": 790, "mod_declared": true}
    ],
    "synonym": [],
    "deprecated": [
      {"iri": "http://www.w3.org/2002/07/owl#deprecated", "count": 12, "mod_declared": false}
    ]
  },
  "unknown": [
    {"iri": "https://schema.org/alternateName", "count": 412, "pct_of_classes": 0.49}
  ]
}
```

---

## Indexer Changes

File: `ontoexplorer/modules/search/indexer.py`

Remove the hardcoded `_LABEL_PREDICATES` module-level constant. Replace with a `load_profile(version_id, db)` helper that:
1. Queries `ontology_profiles` for the version.
2. If no row exists, returns the curated registry defaults.

`build_index(version_id)` calls `load_profile` at the start and passes the result into the entity processing loop:

- **Primary label**: iterate `profile.label_props` in order; use the first value found on the entity.
- **Synonyms**: collect all values across all `profile.synonym_props` IRIs; deduplicate; join with `|` as today.
- **Definition**: iterate `profile.definition_props` in order; store first value found as a new `definition` field in the Redis hash (for search result snippets).
- **Deprecated skip**: entity is skipped if any `profile.deprecated_props` IRI has value `"true"^^xsd:boolean` — same logic as today, now driven by profile.

No changes to the Redis key schema or the sorted-set index structure.

---

## UI

### Post-import banner

Shown on OntologyPage in the version section after ingestion completes (`status = 'auto_detected'`).

**Normal case:**
```
Profile auto-detected · labels: rdfs:label · definitions: IAO:0000115 · synonyms: skos:altLabel   [Review →]
```

**Unknown properties found:**
```
Profile auto-detected · 2 unknown properties need role assignment   [Review →]
```

**After user confirms:**
```
Profile confirmed ✓   [Edit]
```

Banner is dismissed once status is `user_confirmed`. Clicking `[Review →]` or `[Edit]` navigates to the Profile tab.

### Profile tab (OntologyPage, per version)

A structured editor. Each role section shows an ordered, editable list of property IRIs. Properties detected in the ontology show their class usage count. Properties may be manually added (curated dropdown + free-text).

```
Labels
  [rdfs:label  (842 classes) ×]   [+ Add ▾]

Definitions
  [rdfs:comment  (790 classes) ×]   [+ Add ▾]

Synonyms
  (none detected)   [+ Add ▾]

Deprecated
  [owl:deprecated  (12 classes) ×]   [+ Add ▾]

── Unknown properties ────────────────────────────────
  schema:alternateName   412 classes (49%)
    [Assign role ▾]   [Ignore]

                              [Save and re-index]
```

`[+ Add ▾]` opens a dropdown of curated IRIs not yet assigned to this role, plus a free-text entry for custom IRIs. Order within a section is drag-reorderable (label and definition only — order matters for first-match semantics). Save triggers `PATCH /profile` and shows a "Re-indexing…" spinner.

---

## Error Handling

- `detect_profile` failure → profile row absent → indexer uses registry defaults → no user-visible error, banner does not appear (version appears as if profile not yet run)
- `PATCH /profile` with an empty `label_props` array → 422 validation error ("At least one label property is required")
- `POST /profile/detect` while detection already queued → 409 ("Detection already in progress")

---

## Testing

- Unit: `detect_profile` algorithm against a synthetic Oxigraph graph with known property counts; curated registry lookup; `load_profile` fallback to defaults
- Integration: full pipeline test — ingest a small ontology, assert profile row created with correct props, assert index uses those props for label/synonym lookup
- API: GET/PATCH/POST/candidates endpoints with auth, ownership, and validation cases
- Frontend: profile banner renders after ingest; profile tab saves and triggers re-index spinner
