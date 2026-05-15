# Ontology-Level Metadata Profile Design

**Date:** 2026-05-15
**Status:** Approved

## Problem

Ontology-level metadata (title, description, creator, license, homepage, etc.) lives in the `owl:Ontology` block of every ontology file but is never extracted, standardized, or cached. The platform currently:

- Queries all predicates on the ontology IRI on-the-fly from Oxigraph at page load time
- Displays them as a flat, unordered list with no normalization
- Has no canonical title/description for list pages, search results, headers, or the Admin table
- Provides no API for harmonized metadata retrieval

Different ontologies use different properties for the same concept (e.g. `rdfs:label` vs `dcterms:title` vs `dc:title` for the ontology title), with no way for an admin to resolve the ambiguity.

## Goal

A per-version **ontology metadata profile** system that:

1. Detects which properties an ontology uses for each metadata role
2. Caches resolved values in Postgres for platform-wide consumption
3. Exposes a curation UI so admins can override auto-detected mappings
4. Provides a bulk harmonized metadata API endpoint

This mirrors the term-level annotation profile (label/definition/synonym/deprecated on OWL classes) but applies to the `owl:Ontology` node.

## Reference

The [ontostart template](https://github.com/micheldumontier/ontostart/blob/main/ontostart.ttl) defines 28 annotation properties on the ontology header and serves as the authoritative reference for which properties matter.

---

## Architecture

### New table: `ontology_meta_profiles`

One row per version. Stores both the role→IRI mapping (the "profile") and the resolved values (the "cache").

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | UUID |
| `version_id` | FK → versions.id, UNIQUE, CASCADE | One profile per version |
| `title_props` | JSON | Ordered IRI list for title role |
| `shortname_props` | JSON | dcterms:alternative, owl:acronym, vann:preferredNamespacePrefix |
| `description_props` | JSON | |
| `creator_props` | JSON | dc:creator, dcterms:creator, pav:authoredBy |
| `contributor_props` | JSON | |
| `publisher_props` | JSON | |
| `license_props` | JSON | dcterms:license, dcterms:rights |
| `homepage_props` | JSON | foaf:homepage, dcat:accessURL, schema:includedInDataCatalog |
| `version_info_props` | JSON | owl:versionInfo |
| `prefix_props` | JSON | vann:preferredNamespacePrefix |
| `namespace_uri_props` | JSON | vann:preferredNamespaceUri |
| `created_props` | JSON | dcterms:created, dcterms:issued |
| `modified_props` | JSON | dcterms:modified |
| `language_props` | JSON | dcterms:language |
| `citation_props` | JSON | dcterms:bibliographicCitation |
| `funding_props` | JSON | schema:funding |
| `status_props` | JSON | mod:status |
| `syntax_props` | JSON | mod:hasSyntax, mod:hasRepresentationLanguage |
| `resolved` | JSON | Extracted values (see shape below) |
| `candidates_data` | JSON | All predicates found on owl:Ontology node |
| `status` | String | `auto_detected` \| `user_confirmed` |
| `created_at` | DateTime(tz) | |
| `updated_at` | DateTime(tz) | |

### `resolved` JSON shape

```json
{
  "title": "Basic Formal Ontology",
  "shortname": "BFO",
  "description": "An upper-level ontology for the biomedical domain.",
  "creators": ["https://orcid.org/0000-0001-5765-0065"],
  "contributors": [],
  "publishers": [],
  "license": "https://creativecommons.org/licenses/by/4.0/",
  "homepage": "https://basic-formal-ontology.org",
  "version_info": "2.0.0",
  "prefix": "bfo",
  "namespace_uri": "http://purl.obolibrary.org/obo/bfo/",
  "created": "2022-01-01",
  "modified": "2025-05-14",
  "language": "http://lexvo.org/id/iso639-1/en",
  "citation": "Smith et al., 2022",
  "funding": null,
  "status": "active",
  "syntax": "http://www.w3.org/ns/formats/Turtle"
}
```

Multi-value roles (`creators`, `contributors`, `publishers`) are arrays; all others are single strings or null.

---

## Curated Registry

Located at `ontoexplorer/modules/meta_profile/registry.py`. Defines 18 roles with priority-ordered IRI lists:

| Role | Primary IRIs | Fallbacks |
|---|---|---|
| title | `dcterms:title`, `rdfs:label` | `dc:title` |
| shortname | `dcterms:alternative` | `owl:acronym`, `vann:preferredNamespacePrefix` |
| description | `dcterms:description`, `rdfs:comment` | `dc:description` |
| creator | `dcterms:creator` | `dc:creator`, `pav:authoredBy` |
| contributor | `dcterms:contributor` | |
| publisher | `dcterms:publisher` | |
| license | `dcterms:license` | `dcterms:rights` |
| homepage | `foaf:homepage` | `dcat:accessURL`, `schema:includedInDataCatalog` |
| version_info | `owl:versionInfo` | |
| prefix | `vann:preferredNamespacePrefix` | |
| namespace_uri | `vann:preferredNamespaceUri` | |
| created | `dcterms:created` | `dcterms:issued` |
| modified | `dcterms:modified` | |
| language | `dcterms:language` | |
| citation | `dcterms:bibliographicCitation` | |
| funding | `schema:funding` | |
| status | `mod:status` | |
| syntax | `mod:hasSyntax` | `mod:hasRepresentationLanguage` |

---

## Detection Pipeline

```
ingest_ontology completes
  ├── detect_profile.delay(version_id)         ← term-level (existing, unchanged)
  └── detect_meta_profile.delay(version_id)    ← ontology-level (new, independent)
        │
        ├── fetch ontology IRI from versions table
        ├── one SPARQL query: SELECT ?pred ?obj WHERE { GRAPH <g> { <onto_iri> ?pred ?obj } }
        ├── for each role: find which registered IRIs are present → build priority list
        │   (MOD-declared props: mod:prefLabelProperty equivalent not applicable here;
        │    order by: registry priority among detected IRIs)
        ├── _resolve_values(): for each role, take value of first detected IRI
        │   (multi-value roles collect all values across all detected IRIs)
        ├── write / update ontology_meta_profiles row
        └── if ontologies.shortname IS NULL → set from resolved.shortname
```

Detection requires **one SPARQL query** (not N per property) because there is a single subject. The detector does not need Celery retry chaining into indexing — metadata is display-only, not indexing-critical.

---

## API Endpoints

All under `/api/v1`. Auth required (existing `require_auth` dependency).

| Method | Path | Description |
|---|---|---|
| `GET` | `/ontologies/{id}/{vid}/meta` | Harmonized metadata for one version |
| `PATCH` | `/ontologies/{id}/{vid}/meta` | Update role IRI lists; re-resolves values in-process; sets `user_confirmed` |
| `POST` | `/ontologies/{id}/{vid}/meta/detect` | Re-trigger detection; returns `{task_id, status: "queued"}` |
| `GET` | `/ontologies/{id}/{vid}/meta/candidates` | All predicates found on owl:Ontology node |
| `GET` | `/meta?ids=id1,id2,…` | Bulk harmonized metadata; returns latest `ready` version's resolved JSON per ontology ID; silently omits ontologies with no profile yet |

`PATCH` validation: `title_props` must not be empty (422 if blank list supplied).

The `PATCH` endpoint re-resolves values in-process by re-querying the Oxigraph named graph — no Celery task needed since a single-node SPARQL query is fast.

---

## Frontend Changes

### New files
- `frontend/src/hooks/useOntologyMeta.ts` — `useOntologyMeta`, `useMetaCandidates`, `usePatchMeta`, `useDetectMeta`, `useBulkOntologyMeta`
- `frontend/src/components/MetaProfileEditor.tsx` — curation UI; same pattern as `ProfileEditor.tsx` but with 18 role sections

### Modified files
| File | Change |
|---|---|
| `frontend/src/lib/api.ts` | `OntologyMetaProfile`, `MetaResolved`, `MetaPatch` types; `api.ontologies.meta.*` and `api.meta.bulk()` methods |
| `frontend/src/pages/OntologyPage.tsx` | Header shows `resolved.title`; Info tab replaced by structured metadata display using `resolved`; new "Metadata" tab with `MetaProfileEditor`; banner for auto-detected state |
| `frontend/src/pages/Ontologies.tsx` | List rows show `resolved.title` + `resolved.description` snippet |
| `frontend/src/pages/AdminPage.tsx` | Table includes title column from `resolved.title` |

The OntologyPage gains a third tab: **Info** (structured metadata from `resolved`) | **Metadata** (curation) | **Profile** (term-level annotation profile, unchanged).

---

## Error Handling

- `detect_meta_profile` failure → log error, return cleanly; no downstream chain
- Ontology has no `owl:Ontology` node → `candidates_data` is empty, all role lists are empty, `resolved` fields are null
- `resolved.shortname` null after detection → `ontologies.shortname` left unchanged
- `GET /meta?ids=…` → silently omits ontologies with no profile row; client checks for missing entries
- `PATCH title_props: []` → 422

---

## Testing

### Backend (pytest)
- Registry: default lists non-empty, all expected IRIs present, `default_meta_profile()` returns all 18 roles
- `_resolve_values()`: given a predicate→value dict, returns correct resolved JSON for single-value and multi-value roles
- `run_meta_detection()`: mock Oxigraph one-query response → correct role lists + resolved JSON written to DB
- Celery task: enqueues on ingest completion, handles failure gracefully, shortname auto-population
- API: `GET` 404 when no profile, `PATCH` round-trip, `POST detect` returns task_id, bulk `GET /meta` returns subset when some IDs have no profile

### Frontend
- TypeScript type-check only (`tsc --noEmit`), consistent with existing pattern

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `ontoexplorer/modules/meta_profile/__init__.py` | package marker |
| Create | `ontoexplorer/modules/meta_profile/registry.py` | 18 role IRI lists + `default_meta_profile()` |
| Create | `ontoexplorer/modules/meta_profile/detector.py` | SPARQL scan, `run_meta_detection()`, `load_meta_profile()` |
| Create | `ontoexplorer/api/meta_profile.py` | 5 REST endpoints |
| Create | `alembic/versions/????_ontology_meta_profiles.py` | DB migration |
| Create | `tests/integration/test_meta_profile.py` | backend tests |
| Create | `frontend/src/hooks/useOntologyMeta.ts` | React Query hooks |
| Create | `frontend/src/components/MetaProfileEditor.tsx` | curation UI |
| Modify | `ontoexplorer/models/db.py` | add `OntologyMetaProfile` model |
| Modify | `ontoexplorer/modules/jobs/tasks.py` | add `detect_meta_profile` task |
| Modify | `ontoexplorer/modules/ingestion/pipeline.py` | enqueue `detect_meta_profile` after ingest |
| Modify | `ontoexplorer/main.py` | register `meta_profile_router` |
| Modify | `frontend/src/lib/api.ts` | types + `api.ontologies.meta.*` + `api.meta.bulk()` |
| Modify | `frontend/src/pages/OntologyPage.tsx` | header title, Metadata tab, structured Info display |
| Modify | `frontend/src/pages/Ontologies.tsx` | title + description in list rows |
| Modify | `frontend/src/pages/AdminPage.tsx` | title column in table |
