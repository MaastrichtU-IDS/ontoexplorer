# Admin Multi-Version View, Diff Pipeline Controls, and Configurable Paging — Design

**Date:** 2026-05-19
**Status:** Draft

## Goal

Extend the admin interface so that:

1. All versions of each ontology are visible (not only the latest), with per-version pipeline state and per-version action buttons.
2. The diff pipeline (`compute_diff`) can be triggered and inspected from admin — per consecutive version pair and as a bulk per-ontology recompute.
3. All three admin tables (Ontology Pipeline, Recent Jobs, Workers) gain configurable paging with a rows-per-page input (default 10), persisted in `localStorage` per table.

## Non-goals

- Cross-ontology diff (`/compare`) controls — already have their own page.
- Editing ontology metadata or deprecating versions from the admin pipeline (separate flows already exist).
- Replacing version bytes in place — versions remain immutable (SHA-256 keyed).
- Auth/role changes — the existing `_require_admin` dependency continues to gate everything.

## Architecture Overview

The current admin page ([`ontoexplorer/api/admin.py`](../../../ontoexplorer/api/admin.py), [`frontend/src/pages/AdminPage.tsx`](../../../frontend/src/pages/AdminPage.tsx)) shows one row per ontology, derived from the latest non-deprecated version. The four "action" endpoints (`ingest`, `index`, `embed`, `reason`) under `/admin/ontologies/{ontology_id}/*` all resolve to "latest non-deprecated" server-side and ignore which version the operator might mean.

This design keeps `/admin/overview` unchanged (one row per ontology, latest-version state) so the 10-second polling stays cheap. A new lazy endpoint `GET /admin/ontologies/{id}/versions` returns the full version history for a single ontology when the operator expands its row. Per-version actions and per-version diff queueing land on new routes keyed by `version_id`.

## Backend

### New endpoint: `GET /api/v1/admin/ontologies/{ontology_id}/versions`

Returns all versions of a single ontology (deprecated and non-deprecated), newest first, with the same fields as `AdminOntologyEntry` plus a `diff_vs_prev` block.

**Response shape (per version):**

```json
{
  "version_id": "<uuid>",
  "triple_count": 12345,
  "ingestion_status": "ingested" | "deprecated" | "pending" | "failed",
  "indexed": true,
  "embed_count": 4321,
  "reasoning_status": "ready" | "running" | "not_started",
  "version_created_at": "2026-04-22T10:11:12Z",
  "source_url": "https://...",
  "is_latest": true,
  "diff_vs_prev": {
    "previous_version_id": "<uuid>" | null,
    "status": "ready" | "running" | "pending" | "failed" | "missing" | "stale",
    "diff_id": "<uuid>" | null,
    "computed_at": "<iso>" | null
  }
}
```

**Top-level envelope:** `{ "ontology_id": "...", "versions": [ ... ] }`.

**`diff_vs_prev.status` derivation:**

- `missing` — no `OntologyDiff` row exists for `(previous_version_id, version_id)`.
- `pending` / `running` / `failed` — read from `OntologyDiff.status` (or, if no row yet, from a recent `Job` with `type='diff'` for this version).
- `stale` — `OntologyDiff.status == 'ready'`, but its `summary.inferred_status` shows either side not `"ready"` while the corresponding `Job(type='reason', status='done')` row exists. This is the same condition Phase 4's `refresh_stale_inferred_diffs` beat task detects.
- `ready` — `OntologyDiff.status == 'ready'` and not stale.

The oldest version has `previous_version_id: null` and `diff_vs_prev.status: "missing"` only when conceptually meaningful; the frontend renders `—` for that row.

The handler reuses helpers already in `admin.py` (`_search_redis`, `_reasoning_status`) and Phase 4's `_reasoning_status_for_version` from `ontoexplorer/modules/diff/compute.py`. Per-version embedding counts come from a single grouped query over `term_embeddings` for that ontology's versions.

### New per-version action endpoints

All accept the path parameter `version_id` (a UUID). All return `{ "status": "queued", "task_id": "..." }`.

- `POST /api/v1/admin/versions/{version_id}/index` → `index_ontology.delay(version_id=vid, ontology_id=oid)`
- `POST /api/v1/admin/versions/{version_id}/embed` → `embed_ontology.delay(version_id=vid, ontology_id=oid)`
- `POST /api/v1/admin/versions/{version_id}/reason` → `reason_ontology.delay(version_id=vid)`
- `POST /api/v1/admin/versions/{version_id}/ingest` → resolves the version's `source_url` (or parent `Ontology.iri` fallback with RDF content negotiation) and dispatches `ingest_ontology.delay(...)`. Behaviour matches today's latest-row re-ingest: if the fetched bytes hash to the same SHA-256 as an existing version, the ingestion pipeline detects the duplicate and is a no-op; if the bytes have changed, a NEW version is created. The endpoint does not edit the targeted version in place — versions are SHA-256 keyed and immutable by design.

The existing `/admin/ontologies/{ontology_id}/{action}` routes remain for the latest-version row controls (no behavioural change).

### New diff endpoints

- `POST /api/v1/admin/diffs/queue` — body `{from_version_id, to_version_id}`. Resolves `ontology_id` from the versions (must match between the two; reject with 422 if they belong to different ontologies). Dispatches `compute_diff.delay(from_version_id, to_version_id, ontology_id)`. Returns `{status: "queued", task_id: "...", diff_id?: "<uuid>"}` (if a row already exists, includes its id).
- `POST /api/v1/admin/ontologies/{ontology_id}/diffs/recompute-all` — selects all versions for the ontology ordered by `created_at ASC`, queues `compute_diff` for every consecutive `(v[i], v[i+1])` pair. Returns `{queued: N}`.

Both endpoints reuse the existing `compute_diff` Celery task — no changes to diff computation logic.

## Frontend

### Multi-version display: expandable rows

`OntologyTable` ([`frontend/src/pages/AdminPage.tsx`](../../../frontend/src/pages/AdminPage.tsx)) gains:

- A leading `▸/▾` caret column. Expansion tracked in `Set<ontologyId>` component state (not persisted).
- A new "Diff vs prev" column appended to the existing columns, applied to both parent and child rows.
- On expand, a `useQuery(['admin-versions', ontologyId], () => api.admin.versions(ontologyId))` fires. While loading, a single placeholder sub-row shows "Loading versions…". The query refreshes on the same 10-second interval as the parent overview while the row is expanded; it is invalidated manually after any action click.

**Child row layout:** identical column structure to the parent, so columns line up visually. The "Ontology" cell of a child row shows `↳ v.<short-id> · <created-at>` with a `deprecated` badge when applicable.

**Per-version action buttons** in child rows (re-index, re-embed, re-reason, re-ingest) reuse the existing `ActionButton` component. Action state maps are keyed by `version_id`. Click handlers dispatch to the per-version endpoints. Tooltip on re-ingest in any non-latest row: *"Re-fetches this version's source URL — creates a new version if the bytes have changed."*

**Per-ontology bulk diff button:** a small `⚖ Recompute all diffs` button appears in the parent "Ontology" cell, alongside existing buttons. Wires to `POST /admin/ontologies/{id}/diffs/recompute-all`. The button shows queued/error state via the same `UpdateState` pattern.

**Per-version diff button:** in the "Diff vs prev" column for any row with a `previous_version_id`. Label `⚖ diff`, retries become `✕ retry`, stale becomes `↻ refresh`. Click dispatches `POST /admin/diffs/queue` with `{from_version_id: previous_version_id, to_version_id: version_id}`. The oldest version shows `—`.

### Configurable paging

A reusable hook `usePagedTable<T>(rows: T[], scopeKey: string)` (in `frontend/src/hooks/usePagedTable.ts`):

- `pageSize` state, default 10, persisted in `localStorage` under `admin.rowsPerPage.<scopeKey>` (`ontologies`, `jobs`, `workers`).
- Invalid/missing/out-of-range values fall back to 10 without writing.
- `page` state resets to 0 when `pageSize` changes or the input list shrinks below the current page's start index.
- Returns `{paged, page, setPage, pageSize, setPageSize, totalPages, total}`.

A small `<TablePager scope=... total=... page=... pageSize=... onPage=... onPageSize=...>` component renders:

```
[Rows: __10__]                    11–20 of 47   ‹ Prev   Next ›
```

The Rows input is `<input type="number" min={1} max={500}>`, committed on blur or Enter. Negative/zero/NaN values fall back to default 10 without writing to storage.

**Applied to:**

- `OntologyTable` — replaces the hardcoded `PAGE_SIZE = 25` ([AdminPage.tsx:138](../../../frontend/src/pages/AdminPage.tsx#L138)) and the inline pagination block ([AdminPage.tsx:342-354](../../../frontend/src/pages/AdminPage.tsx#L342-L354)). Paging is by ontology, not by visible row — expansion sub-rows do not affect counts.
- `JobsTable` — adds paging within the 50 jobs the backend already returns. Default 10.
- `WorkersPanel` — adds paging within the live task list. Default 10.

### TypeScript types

Add to [`frontend/src/lib/api.ts`](../../../frontend/src/lib/api.ts):

```ts
export interface AdminVersionEntry {
  version_id: string
  triple_count: number | null
  ingestion_status: 'ingested' | 'deprecated' | 'pending' | 'failed' | string
  indexed: boolean
  embed_count: number
  reasoning_status: 'ready' | 'running' | 'not_started'
  version_created_at: string | null
  source_url: string | null
  is_latest: boolean
  diff_vs_prev: {
    previous_version_id: string | null
    status: 'ready' | 'running' | 'pending' | 'failed' | 'missing' | 'stale'
    diff_id: string | null
    computed_at: string | null
  }
}

export interface AdminVersionsResponse {
  ontology_id: string
  versions: AdminVersionEntry[]
}
```

New API client methods under `api.admin`:

```ts
versions: (ontologyId: string) => request<AdminVersionsResponse>(`/admin/ontologies/${ontologyId}/versions`),
queueIndexForVersion: (versionId: string) => request<{ status: string; task_id: string }>(`/admin/versions/${versionId}/index`, { method: 'POST' }),
queueEmbedForVersion: (versionId: string) => request<{ status: string; task_id: string }>(`/admin/versions/${versionId}/embed`, { method: 'POST' }),
queueReasonForVersion: (versionId: string) => request<{ status: string; task_id: string }>(`/admin/versions/${versionId}/reason`, { method: 'POST' }),
queueIngestForVersion: (versionId: string) => request<{ status: string; task_id: string }>(`/admin/versions/${versionId}/ingest`, { method: 'POST' }),
queueDiff: (fromVersionId: string, toVersionId: string) => request<{ status: string; task_id: string; diff_id?: string }>(`/admin/diffs/queue`, { method: 'POST', body: JSON.stringify({ from_version_id: fromVersionId, to_version_id: toVersionId }) }),
recomputeAllDiffs: (ontologyId: string) => request<{ queued: number }>(`/admin/ontologies/${ontologyId}/diffs/recompute-all`, { method: 'POST' }),
```

## Error Handling

- Per-version endpoints return 404 if the `version_id` is unknown, 422 if the version has no resolvable source for `ingest`, 422 on `/diffs/queue` if the two versions belong to different ontologies.
- Frontend uses the same `UpdateState = 'idle' | 'queued' | 'error'` pattern already in the admin page; failed POSTs flip the button to `✕ retry`.
- Lazy versions query: while loading shows "Loading versions…"; on error shows "Failed to load versions" with a one-click retry (`queryClient.invalidateQueries`).
- Invalid rows-per-page input silently falls back to 10 (no toast — admin tool, low-stakes).

## Testing

Backend (pytest):

- `tests/integration/test_admin_api.py` (extend or create): `GET /admin/ontologies/{id}/versions` returns expected shape; respects ordering; `diff_vs_prev.status` matches the underlying `OntologyDiff.status`; stale detection mirrors Phase 4 logic; new per-version action endpoints queue with the correct kwargs (mock `*.delay`); diff queue endpoint validates same-ontology; recompute-all returns correct count.

Frontend (Vitest):

- `usePagedTable.test.ts` — default 10, persists to localStorage, falls back on invalid input, page resets on size change.
- `AdminPage.test.tsx` (or focused tests on extracted sub-components): expansion fires the versions query; per-version action buttons hit the correct endpoint; "Diff vs prev" column renders the right status badges.

## Operational Notes

- No schema migrations required.
- No new Celery tasks — reuses `compute_diff`, `index_ontology`, `embed_ontology`, `reason_ontology`, `ingest_ontology`.
- Pre-existing 10-second `/admin/overview` polling is unchanged; the new lazy versions endpoint adds no work to the hot path.
- LocalStorage keys (`admin.rowsPerPage.{ontologies,jobs,workers}`) are forward-compatible; values outside `[1, 500]` are ignored.

## Risks / Open Questions

- Per-version "Diff vs prev" `status` derivation needs a single point of truth — propose adding a small helper `_diff_status_for_pair(db, from_vid, to_vid)` in `ontoexplorer/api/admin.py` that the new endpoint uses, sharing the same definition the Phase 4 stale-detection beat task implies.
- If the ontology has many versions (e.g., monthly snapshots over years), the lazy fetch could still return a long list. Paging the child rows is out-of-scope for v1; the existing rows-per-page setting on the parent table is what we keep configurable. If this proves painful, a follow-up could add per-ontology version paging.
