# SPARQL Page — Starter Query Library + Admin Import

## Context

Sub-project D of six in the SPARQL-page improvement plan. Sub-projects A (scope toolbar), C (IRI autocomplete + prefix autoload), and E (result enrichment) have shipped.

This sub-project adds a curated **starter query library** to the SPARQL page sidebar and an **admin import flow** that lets administrators load starter libraries by paste, file upload, or URL fetch. Both `.rq` (with metadata comments) and JSON-library formats are supported.

## Goal

1. **For users:** open `/sparql`, click into the sidebar's "Starters" tab, see a curated list of OntoExplorer-relevant SPARQL queries grouped by category, click one to load it into the editor. Works for both signed-in and anonymous users.

2. **For admins:** open the admin page, paste/upload/URL-fetch a starter library, get a created/skipped/errors report.

No widely-adopted standard exists for "SPARQL query libraries". We ship a small JSON schema for batch import (`{ starters: [...] }`) and accept single `.rq` files with leading `# @key value` metadata comments — a convention used informally by OBO/EBI example collections.

## Approach

### Data model

Add two columns to the existing `saved_queries` table:

- `is_starter: bool NOT NULL DEFAULT FALSE`
- `category: VARCHAR(64) NULL` — free-text grouping label

Create a synthetic `system` user (id stable, e.g. `'00000000-0000-0000-0000-000000000000'`) to own all starter rows. The existing `user_id` foreign-key stays as-is; no nulls needed and no model changes beyond the two columns.

The existing `tags`/`is_public`/`name`/`description`/`query_text` fields are reused. Starters always have `is_public=true`.

### Seed set

The Alembic migration that adds the columns also inserts ~10 starters covering OntoExplorer's core capabilities. Categories and example names:

- **Exploration** — "All classes in scope", "All properties in scope", "All individuals in scope"
- **Profile** — "OWL 2 DL violations", "OWL 2 EL violations"
- **Diff** — "Triples in V2 not in V1" (with `<VERSION_URI_HERE>` placeholders)
- **Term lookup** — "Find term by label", "Subclasses of class" (`<URI_HERE>` placeholder)
- **Reasoning** — "Inferred axioms about term"

These rely on the scope toolbar being set, so most use `GRAPH ?g { ... }` patterns. Queries with parameters use a literal placeholder token (`<URI_HERE>`, `<VERSION_URI_HERE>`, `"label"`) that the user replaces by hand after insertion. IRI autocomplete from sub-project C helps with the IRI replacements.

### Read API (backend)

- `GET /api/v1/sparql/starters` — no auth required. Returns `{ starters: [{ id, name, description, category, tags, query_text, updated_at }, ...] }` ordered by `(category, name)`.
- `GET /api/v1/sparql/queries/public` (existing) — modified to add `WHERE is_starter = FALSE` so starters don't appear in the public gallery.
- `GET /api/v1/sparql/queries` (existing — my queries) — modified to filter `is_starter = FALSE` (defensive; user_id-based queries already exclude them since they're owned by `system`, but explicit).

### Import API (backend)

`POST /api/v1/sparql/starters/import` — admin-only via the existing `is_admin` dependency. Three intake shapes:

| Mode | Request body |
|---|---|
| Paste text | `Content-Type: application/json`, body `{ "text": "..." }` |
| File upload | `Content-Type: multipart/form-data` with a `file` field |
| URL fetch | `Content-Type: application/json`, body `{ "source_url": "https://..." }` |

The backend reads the text (from `text`, `file`, or `urlopen(source_url)`) and runs a parser:

1. **Format detection:** strip leading whitespace. If the first non-whitespace char is `{` or `[` → JSON library. Otherwise → `.rq` with metadata.
2. **JSON library parse:** validate shape `{ starters: [{ name: str, description?: str, category?: str, tags?: str[], query_text: str }, ...] }`. Each entry's `name` and `query_text` are required.
3. **`.rq` with metadata parse:** read leading `# @key value` lines (must be at top, before any non-comment line). Keys: `name` (required), `description`, `category`, `tags` (comma-separated). Body after the comment block is `query_text`.
4. For each parsed starter: skip if name already exists in `saved_queries` (any `is_starter=true` row); else INSERT with `user_id = <system>`, `is_starter=true`, `is_public=true`.
5. Return `{ created: N, skipped: N, errors: [{ index, name?, reason }, ...] }`.

**URL fetch constraints:**
- Scheme must be `https://`, with one exception: `http://localhost`/`http://127.0.0.1` allowed for development.
- Response must be ≤ 1 MB. Read with a hard cap, reject on overflow.
- 5-second timeout.
- Follow redirects up to 3 hops.
- Errors map to HTTP 400 with descriptive `detail`.

### Read UI (frontend)

`QuerySidebar` adds a third view-mode `starters` alongside the existing `list` (my queries) and `form` (save form). A small segmented control in the header switches between `My` and `Starters` when in non-form mode. Anonymous users see Starters by default (no `My` tab); signed-in users see both tabs with `My` as the default.

The Starters view:
- Groups entries by `category` (collapsible section headers)
- Each entry: name (clickable) + dimmed 2-line description
- Click → `yasguiRef.current?.getTab()?.getYasqe()?.setValue(starter.query_text)` (same pattern as `loadQuery`)

No edit/delete affordances on starter rows. Users cannot modify them through the UI.

### Admin UI (frontend)

A new collapsible section on `AdminPage` titled "Starter Queries". Three input zones in a single panel:

1. **Paste** — textarea + Import button
2. **Upload** — `<input type="file" accept=".json,.rq">` + Import button
3. **URL** — text field + Import button

Result row beneath each shows `Imported N · Skipped N · M errors` and an expandable list of errors. The same `StarterQueriesPanel` component handles all three with internal state for the active mode.

Admins can't edit/delete via this UI — they manage via SQL or by deleting + re-importing.

## Edge cases

| Case | Behaviour |
|---|---|
| Import: starter with same name already exists | Skip; record `{ reason: "duplicate name" }`. Existing row untouched. |
| JSON entry missing `name` or `query_text` | Skip; record reason. |
| `.rq` body has no `# @name` line | Reject whole import (return 400). |
| JSON body has invalid structure (not `{ starters: [...] }`) | Return 400. |
| URL fetch times out | Return 400 with timeout message. |
| URL fetch returns non-2xx | Return 400 with upstream status. |
| URL response > 1 MB | Return 400. |
| URL scheme not https (and not localhost) | Return 400. |
| Anonymous user opens sidebar | Starters tab visible; My tab hidden; Save button hidden. |
| Signed-in user with zero saved queries | My tab empty-state ("No saved queries yet"); Starters tab works. |
| Starter's query_text references graphs no longer in store | Yasgui shows zero results; not our problem to validate at import. |
| Click starter while editor has unsaved query | Editor content is overwritten. (Matches current `loadQuery` behaviour.) |
| Duplicate categories in seed | Treat as the same group; case-sensitive match. |

## Backend changes

- **Migration:** `alembic/versions/<rev>_add_starter_to_saved_queries.py`
  - Add `is_starter`, `category` columns to `saved_queries`
  - INSERT `system` user row
  - INSERT seed starters

- **Model:** `ontoexplorer/models/db.py` — add the two columns to `SavedQuery`

- **API:** `ontoexplorer/api/sparql_queries.py`
  - New `GET /sparql/starters`
  - New `POST /sparql/starters/import` (admin-only)
  - Modify `/public` and `/` listings to filter `is_starter=false`

- **Parser module:** `ontoexplorer/modules/sparql_starters/parser.py`
  - `detect_format(text: str) -> Literal["json", "rq"]`
  - `parse_json_library(text: str) -> list[StarterDraft]` (raises `ValueError` on malformed)
  - `parse_rq_with_metadata(text: str) -> StarterDraft` (raises `ValueError` on missing name)
  - `StarterDraft` dataclass: `name, description, category, tags, query_text`

- **Fetcher:** small helper inside the API module to fetch a URL with size cap + timeout + scheme guard.

## Frontend changes

- **`frontend/src/lib/api.ts`**
  - `api.savedQueries.listStarters(): Promise<{ starters: StarterQuery[] }>`
  - `api.admin.importStarters(payload: ImportPayload): Promise<{ created, skipped, errors }>`
  - `ImportPayload` union: `{ text: string } | { source_url: string } | { file: File }`

- **`frontend/src/components/QuerySidebar.tsx`** — add `starters` view, segmented tab switch, anonymous-user handling.

- **`frontend/src/components/admin/StarterQueriesPanel.tsx`** — new panel with three import zones.

- **`frontend/src/pages/AdminPage.tsx`** — mount `StarterQueriesPanel` (collapsible section).

## Testing

**Backend unit tests (`parser_test.py`):**

- `detect_format` distinguishes `{...}`/`[...]` from `# @...` and bare SELECT.
- `parse_json_library` accepts well-formed; rejects missing-keys; rejects non-array.
- `parse_rq_with_metadata` extracts name/description/category/tags; rejects missing `# @name`; preserves the body verbatim.

**Backend integration tests (`tests/integration/test_sparql_starters.py`):**

- `GET /starters` returns seeded starters, ordered by category then name.
- `GET /queries/public` excludes starters.
- `POST /starters/import` with paste-JSON adds N rows.
- `POST /starters/import` with paste-`.rq` adds 1 row.
- `POST /starters/import` URL mode rejects http:// (non-localhost).
- `POST /starters/import` URL mode rejects oversized response (mock a 2 MB body).
- `POST /starters/import` returns 403 for non-admin.
- Duplicate names result in `skipped` count, not 500.

**Frontend tests:**

- `QuerySidebar` — Starters tab visible for anonymous user; clicking a starter calls `setValue` on Yasgui.
- `QuerySidebar` — Signed-in user sees both tabs; default is My.
- `StarterQueriesPanel` — each of the three import zones calls the right `api.admin.importStarters` shape.

## Out of scope

- Admin UI for editing or deleting individual starters (SQL only in v1).
- Per-starter usage analytics.
- Parameterization engine (placeholders are literal tokens user replaces by hand).
- Git-repo URL imports (only direct file URLs supported).
- Nested categories / sub-categories.
- Syntax-validating SPARQL at import time.
- Granting non-admin users the ability to import.
- Localized starter names/descriptions.

## Open questions

None. Ready for implementation planning.
