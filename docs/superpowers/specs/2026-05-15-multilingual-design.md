# Multilingual Ontology Support — Design Spec

**Date:** 2026-05-15
**Status:** Approved
**Scope:** Search, autocomplete, term display, and user preference management for multilingual RDF ontologies.

---

## Problem

Language tags are preserved through RDF ingestion and OWL-EL reasoning but stripped at every downstream step — the search index, the term detail API, and the frontend. When an ontology carries labels in multiple languages (e.g. GO in English, French, and Japanese; HP in English and German) only the first label encountered is indexed, the rest silently discarded. Users have no way to search or browse in their preferred language.

---

## Goals

- Index all language variants of labels, synonyms, and definitions in a single shared Redis index.
- Allow users to set a preferred language at three tiers (global profile, per-ontology, per-session), with the most specific tier winning.
- Surface cross-language search results ranked lower than preferred-language results, with a language badge.
- Display all language variants in term detail view, with user-configurable fallback behaviour when the preferred language has no label.
- Respect language preference in autocomplete and MOS expression queries.

---

## Non-Goals

- Machine translation of labels.
- Language detection for untagged literals.
- Separate per-language Redis indexes.
- Changing the annotation profile predicate-selection logic.

---

## Architecture Overview

```
User preference (3 tiers)
  └─ resolve_lang() helper → effective lang tag (or None = all)
       ├─ Search/autocomplete: two-scan Redis query → ranked results + lang badges
       ├─ Term detail API: SPARQL preserves lang() → labelled JSON arrays
       └─ Frontend: useLang() hook → ?lang= param on all requests
```

---

## Section 1: Language Preference Model

### Three-tier resolution (most specific wins)

| Tier | Storage | Scope |
|---|---|---|
| Session override | `localStorage["oe_lang_override"]` | Browser tab / until logout |
| Per-ontology override | `ontologies.preferred_lang` | One ontology, all users |
| Global user preference | `users.preferred_lang` | All ontologies for this user |
| System default | — | None (show all languages) |

The session override is passed as a `?lang=` query parameter on every API call. The API ignores stored preferences when `?lang=` is present.

### Fallback strategy

When the effective language is set but a term has no label in that language, the user's `lang_fallback_strategy` controls display:

| Value | Behaviour |
|---|---|
| `silent` | Show best available label without any indicator (default) |
| `show_all` | Show all language variants as a stacked list with lang badges |
| `indicate_missing` | Show `—` with a "no label in [lang]" note |

### Database migrations

**Migration 1 — `users` table:**
```sql
ALTER TABLE users ADD COLUMN preferred_lang VARCHAR;          -- BCP-47, nullable
ALTER TABLE users ADD COLUMN lang_fallback_strategy VARCHAR   -- default 'silent'
    NOT NULL DEFAULT 'silent';
```

**Migration 2 — `ontologies` table:**
```sql
ALTER TABLE ontologies ADD COLUMN preferred_lang VARCHAR;     -- BCP-47, nullable
```

---

## Section 2: Search Index

### Sorted-set key format

```
Current:  {norm}|{entity_type}|{iri}
New:      {norm}|{lang}|{entity_type}|{iri}
```

`{lang}` is the BCP-47 tag from the RDF literal (`"en"`, `"fr"`, `"nl"`), or `""` (empty string) for untagged literals. Empty string sorts before any alphabetic tag in Redis lex order.

Each `(iri, label, lang)` triple produces one sorted-set entry. A term with labels in three languages produces three entries.

### Entity hash

Replace flat string fields with JSON arrays preserving all language variants:

| Old field | New field | Format |
|---|---|---|
| `label` | `labels` | `[{"value": "cell death", "lang": "en"}, ...]` |
| `synonyms` | `synonyms` | `[{"value": "apoptosis", "lang": "en"}, ...]` |
| `definition` | `definitions` | `[{"value": "...", "lang": "en"}, ...]` |

A `primary_label` field is retained for fast display without a language query — defined as the first label with `lang="en"`, falling back to the first label in any language if no English label exists.

### Language inventory

A new Redis hash `search:entities:{vid}:langs` is written during index build:
```
"en" → 45231    (count of labels in this language for this version)
"fr" → 12400
""  → 3200      (untagged)
```

Used by `GET /ontologies/{id}/{vid}/languages`.

### Index schema version

`search:entities:{vid}:meta` gains a `schema_version` field. Current schema is `v1`; multilingual schema is `v2`. Query layer falls back to unfiltered results when it encounters a `v1` index.

### Query — two-scan approach

Mirrors the existing exact/prefix two-scan in `autocomplete.py`:

```
Scan 1 (preferred):  [{norm}|{lang}|  →  [{norm}|{lang}|\xff    → rank tier 0
Scan 2 (all):        [{norm}|         →  [{norm}|\xff            → rank tier 1 for IRIs not in scan 1
```

Results carry:
- `lang: str | null` — language of the matched label
- `cross_language: bool` — true when lang ≠ effective preference

Within each tier the existing exact → prefix → substring ordering is preserved.

### Memory estimate

A 50k-class ontology currently uses ~15 MB of Redis. With an average of 3 language variants per term, the sorted set grows to ~40 MB — well within normal budgets.

---

## Section 3: API

### Language resolution helper

```python
def resolve_lang(
    query_param: str | None,   # ?lang= from request (highest priority)
    ontology: Ontology,        # ontology.preferred_lang
    user: User | None,         # user.preferred_lang
) -> str | None:               # resolved BCP-47 tag, or None = all languages
```

### Modified endpoints

All search and autocomplete endpoints gain an optional `?lang=` query parameter:

```
GET /ontologies/{id}/{vid}/search?q=...&lang=fr
GET /ontologies/{id}/{vid}/autocomplete?q=...&lang=fr
GET /search?q=...&lang=fr
```

Search result hits gain:
```json
{
  "label": "mort cellulaire",
  "lang": "fr",
  "cross_language": false
}
```

### Term detail endpoint

`GET /ontologies/{id}/{vid}/terms/{iri}` — SPARQL query preserves `lang()` on all literals. Response shape:

```json
{
  "label": "cell death",
  "labels": [
    {"value": "cell death",      "lang": "en"},
    {"value": "mort cellulaire", "lang": "fr"}
  ],
  "definitions": [{"value": "...", "lang": "en"}],
  "synonyms":    [{"value": "apoptosis", "lang": "en"}],
  "properties": {
    "http://www.w3.org/2000/01/rdf-schema#label": [
      {"value": "cell death",      "lang": "en"},
      {"value": "mort cellulaire", "lang": "fr"}
    ]
  }
}
```

Top-level `label` remains (backwards compatibility) — first label in resolved language, or first label overall if none exists in that language. The `lang_fallback_strategy` is a display-only concern applied by the frontend; the API always returns the full `labels` array and a non-null `label`.

### User preference endpoints

```
GET  /auth/me    → adds: preferred_lang, lang_fallback_strategy
PATCH /auth/me   → accepts: {preferred_lang, lang_fallback_strategy}
PATCH /ontologies/{id}  → already exists; adds: preferred_lang
```

### New endpoint

```
GET /ontologies/{id}/{vid}/languages
→ [{"lang": "en", "label_count": 45231}, {"lang": "fr", "label_count": 12400}]
```

Reads from `search:entities:{vid}:langs` Redis hash. Returns empty list if version not yet indexed at schema v2.

---

## Section 4: Frontend

### Language picker

A compact dropdown added to:
- **NavBar** — session override, persisted to `localStorage["oe_lang_override"]`; cleared on logout
- **OntologyPage header** — per-ontology override, saved via `PATCH /ontologies/{id}`

Both dropdowns are populated from `GET /ontologies/{id}/{vid}/languages`. "All languages" clears the preference at that tier.

### Language badge

A small pill shown on search results and autocomplete suggestions when `cross_language: true`. Styled identically to the existing `[ind]` individual badge.

```
cell death  ·  [fr]
```

### TermPanel display

Labels, definitions, and synonyms show inline `[en]` / `[fr]` badges whenever multiple languages are present. The `lang_fallback_strategy` controls what is shown when the preferred language has no label:

| Strategy | Rendering |
|---|---|
| `silent` | Best available label, no indicator |
| `show_all` | Stacked list of all variants with lang badges |
| `indicate_missing` | `—` with "no label in [lang]" note |

### `useLang()` hook

```ts
function useLang(ontologyId?: string): {
  effectiveLang: string | null        // resolved preference for current context
  setSessionLang: (lang: string | null) => void
  setOntologyLang: (lang: string | null) => void   // calls PATCH /ontologies/{id}
}
```

All search and autocomplete hooks read `effectiveLang` and append `&lang=` to their requests automatically.

### Profile page (`/profile`)

Adds a "Language" section to the existing `Profile.tsx`:
- **Preferred language** — dropdown + free-text BCP-47 input
- **Fallback strategy** — three radio options

Saved via `PATCH /auth/me`. Unauthenticated users only get the session picker in the NavBar.

---

## Section 5: Rollout & Re-index Strategy

### Phase 1 — Database *(minutes)*

Run two Alembic migrations. All new columns are nullable with safe defaults; no data migration required.

### Phase 2 — Backend deployed, old index live *(minutes)*

Deploy updated API and worker. `?lang=` parameters are accepted but `resolve_lang()` returns `None` (all languages) until indexes are rebuilt. Search continues working unchanged. `/languages` returns an empty list.

### Phase 3 — Re-index all versions *(hours, background)*

Trigger via `POST /admin/reindex`. During each version's rebuild the old keys are deleted at the start and repopulated at the end — a brief gap of seconds per version where search returns no results for that version, then resumes with full multilingual data. Large ontologies (GO, UBERON) take the most time.

### Phase 4 — Frontend deployed

Language picker appears in NavBar. Users who have not set a preference see `effectiveLang = null` and experience no change. No user action required.

### Re-index on profile change

The existing `PATCH /profile → re-index` pipeline triggers a full re-index which now produces multilingual output. No changes required.

---

## File Inventory

### Backend
| File | Change |
|---|---|
| `alembic/versions/` | Two new migrations |
| `ontoexplorer/models/db.py` | Add `preferred_lang`, `lang_fallback_strategy` to `User`; `preferred_lang` to `Ontology` |
| `ontoexplorer/models/api.py` | Update request/response schemas |
| `ontoexplorer/modules/search/indexer.py` | SPARQL adds `lang(?label)`, hash writes JSON arrays, writes langs inventory, sets schema v2 |
| `ontoexplorer/modules/search/evaluator.py` | Two-scan with lang param, `cross_language` flag in results |
| `ontoexplorer/modules/search/autocomplete.py` | Pass lang through; badge metadata in completions |
| `ontoexplorer/api/auth.py` | `GET/PATCH /auth/me` expose language preference fields |
| `ontoexplorer/api/ontologies.py` | `resolve_lang()` helper; `/terms/{iri}` preserves lang(); new `/languages` endpoint; `PATCH` accepts `preferred_lang` |
| `ontoexplorer/api/search.py` | `?lang=` param wired to evaluator |
| `ontoexplorer/api/global_search.py` | `?lang=` param wired to evaluator |

### Frontend
| File | Change |
|---|---|
| `frontend/src/hooks/useLang.ts` | New hook — three-tier resolution, localStorage sync |
| `frontend/src/hooks/useOntologyLanguages.ts` | New hook — fetches `/languages` endpoint |
| `frontend/src/components/NavBar.tsx` | Add language picker (session tier) |
| `frontend/src/components/TermPanel.tsx` | Language-tagged labels/definitions/synonyms; fallback strategy rendering |
| `frontend/src/pages/OntologyPage.tsx` | Add per-ontology language picker |
| `frontend/src/pages/Profile.tsx` | Add language preference section |
| `frontend/src/lib/api.ts` | Update term detail types; add `/languages` client call |
