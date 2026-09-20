# Admin Panel Implementation Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/admin` page that gives an authenticated admin a live view of service health, per-ontology pipeline state, and recent job history — auto-refreshing every 10 seconds.

**Architecture:** Single consolidated backend endpoint (`GET /api/v1/admin/overview`) aggregates service health, Redis-based reasoning status, and recent jobs in one call. Frontend consumes it with React Query `refetchInterval: 10s`. Access is controlled by an `ADMIN_EMAILS` env-var allowlist checked server-side; `is_admin` is surfaced on `/auth/me` so the navbar shows the link only to admins.

**Tech Stack:** FastAPI (backend), React + React Query (frontend), Redis DB 0 (broker/search) + Redis DB 2 (ELK classification cache), existing Postgres `jobs` table.

---

## Access Control

- Add `admin_emails: str = ""` to `Settings` in `ontoexplorer/config.py` (comma-separated list, e.g. `admin@example.org`).
- A helper `is_admin(user) -> bool` checks `user.email` against the parsed list.
- `GET /api/v1/admin/overview` returns **403** if the authenticated user is not admin.
- `GET /auth/me` gains `is_admin: bool` in its response, so the frontend can conditionally render the Admin nav link.
- No DB migration required — no schema changes.

---

## Backend

### New file: `ontoexplorer/api/admin.py`

Single router with one endpoint:

```
GET /api/v1/admin/overview
```

**Auth:** Requires session or API-key auth (`require_auth` dependency) **plus** `is_admin(user)` check → 403 if not admin.

**Response shape:**

```json
{
  "services": {
    "postgres": "ok",
    "redis": "ok",
    "minio": "ok",
    "elk": "ok",
    "celery_queue_depth": 4
  },
  "ontologies": [
    {
      "id": "3e9868d3-...",
      "shortname": "cl",
      "iri": "http://purl.obolibrary.org/obo/cl.owl",
      "version_id": "f7204efb-...",
      "triple_count": 777527,
      "ingestion_status": "ingested",
      "indexed": true,
      "reasoning_status": "ready",
      "version_created_at": "2026-05-13T19:45:00Z"
    }
  ],
  "jobs": [
    {
      "id": "...",
      "type": "reason",
      "version_id": "a69fdb16-...",
      "ontology_shortname": "mp",
      "status": "running",
      "started_at": "2026-05-13T20:43:05Z",
      "finished_at": null,
      "error": null
    }
  ]
}
```

**Service checks** (run concurrently via `asyncio.gather`):

| Check | How |
|---|---|
| `postgres` | `SELECT 1` via SQLAlchemy async session |
| `redis` | `PING` on Redis DB 0 |
| `minio` | HTTP GET `{minio_endpoint}/minio/health/live` |
| `elk` | HTTP GET `{elk_service_url}/health` |
| `celery_queue_depth` | `LLEN celery` on Redis DB 0 |

Each returns `"ok"` or `"error: <message>"` (queue depth is an integer).

**Ontology pipeline** (single DB query + Redis checks):

1. Query all ontologies joined to their latest version (`ORDER BY created_at DESC`).
2. For each version:
   - `indexed`: `EXISTS search:meta:{version_id}` on Redis DB 0.
   - `reasoning_status`:
     - `EXISTS classification:{version_id}` on Redis DB 2 → `"ready"`
     - Otherwise → HTTP `GET {elk_service_url}/classify/{version_id}`:
       - `409` with `"in progress"` in body → `"running"`
       - `409` otherwise → `"not_started"`
       - `404` → `"not_started"`
     - These ELK calls only fire for non-ready versions; typically ≤5 at any time. Run them concurrently.

**Jobs**: `SELECT jobs JOIN versions JOIN ontologies ORDER BY created_at DESC LIMIT 50`. The join resolves `ontology_shortname` from `ontologies.shortname`.

### Modified: `ontoexplorer/api/auth.py`

`GET /auth/me` response gains `is_admin: bool`:
```python
return {**existing_fields, "is_admin": is_admin(user)}
```

### Modified: `ontoexplorer/config.py`

```python
admin_emails: str = ""  # comma-separated; empty = no admin access
```

### Registration

Add `admin.router` to the FastAPI app in `ontoexplorer/main.py` alongside the other `include_router` calls.

---

## Frontend

### New file: `frontend/src/hooks/useAdminOverview.ts`

```ts
export function useAdminOverview() {
  return useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: () => api.admin.overview(),
    refetchInterval: 10_000,
    staleTime: 0,
  })
}
```

### New file: `frontend/src/pages/AdminPage.tsx`

Three vertically-stacked sections:

**1. Service Health row** — six cards: Postgres, Redis, MinIO, ELK, Worker (derived: "ok" if worker has processed a job in the last 5 min, else "unknown"), Queue depth. Status dots: green = ok, orange = degraded/queued, red = error.

**2. Ontology Pipeline table** — columns: Ontology, Triples, Ingestion, Indexed, Reasoning, Updated. Sorted by reasoning status (not-started → running → ready). Status badges: green dot for done/ready, blue spinner label for running, grey dash for not-started/queued, red ✕ for error.

**3. Recent Jobs table** — columns: Type (colour-coded: ingest=purple, index=blue, reason=teal), Ontology, Status, Duration, Started. Last 50 jobs, newest first. Failed rows highlighted with a subtle red background.

**Access guard:** At the top of `AdminPage`, check `user?.is_admin`; redirect to `/` if false.

**Auto-refresh indicator:** Small "● live · refreshes every 10s" badge in the header, plus "Last updated Ns ago" counter.

### Modified: `frontend/src/lib/api.ts`

- Add `is_admin: boolean` to `UserProfile` type.
- Add `admin: { overview: () => request<AdminOverview>('/admin/overview') }` to the `api` object.
- Add `AdminOverview` type matching the response shape above.

### Modified: `frontend/src/App.tsx`

```tsx
<Route element={<Shell><AuthGuard /></Shell>}>
  {/* existing dashboard routes */}
  <Route path="/admin" element={<AdminPage />} />
</Route>
```

### Modified: `frontend/src/components/NavBar.tsx`

Show "Admin" link conditionally:
```tsx
{user?.is_admin && <NavLink to="/admin">Admin</NavLink>}
```

---

## Files Summary

| File | Change |
|---|---|
| `ontoexplorer/api/admin.py` | **New** — admin router + overview endpoint |
| `ontoexplorer/config.py` | Add `admin_emails` setting |
| `ontoexplorer/api/auth.py` | Add `is_admin` to `/auth/me` response |
| `ontoexplorer/main.py` | Register admin router |
| `frontend/src/hooks/useAdminOverview.ts` | **New** — React Query hook |
| `frontend/src/pages/AdminPage.tsx` | **New** — admin page component |
| `frontend/src/lib/api.ts` | Add `AdminOverview` type + `api.admin.overview()` |
| `frontend/src/App.tsx` | Add `/admin` route |
| `frontend/src/components/NavBar.tsx` | Conditional Admin link |
| `.env.example` | Add `ADMIN_EMAILS=` entry |

No database migrations required.
