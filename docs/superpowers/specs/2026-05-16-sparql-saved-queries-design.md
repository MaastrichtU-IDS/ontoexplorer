# SPARQL Saved Queries — Design Spec

**Date:** 2026-05-16  
**Status:** Approved

---

## Overview

Let authenticated users save, load, and share SPARQL queries. Public queries appear in a browsable, searchable gallery filterable by ontology and author. A persistent sidebar on the SPARQL page gives quick access to personal queries; a dedicated `/sparql/gallery` route serves the public gallery.

---

## Goals

- Authenticated users can save the current editor query with a name, description, and tags
- Saved queries are private by default; users can mark them public
- Public queries appear in a gallery at `/sparql/gallery`, searchable by text and filterable by ontology shortname and author
- Any public query can be opened in the editor via a shareable URL (`/sparql?q=<id>`)
- Unauthenticated users can browse the gallery and open queries in the editor; they cannot save

---

## Data Model

One new table: `saved_queries`.

```python
class SavedQuery(Base):
    __tablename__ = "saved_queries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str]                        # required, not unique
    description: Mapped[str | None]
    query_text: Mapped[str]                  # raw SPARQL string
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    is_public: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="saved_queries")
```

Add `saved_queries` relationship to `User`:
```python
saved_queries: Mapped[list["SavedQuery"]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

Tags are a plain PostgreSQL `text[]` array — no normalisation table. Users enter tags via a combined control: a searchable dropdown of loaded ontology shortnames (from `/api/v1/ontologies`) plus free-form text entry. Both produce entries in the same array.

---

## Backend

### New file: `ontoexplorer/api/sparql_queries.py`

Router prefix: `/api/v1/sparql/queries`

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/` | required | Create a saved query |
| `GET` | `/` | required | List caller's queries |
| `GET` | `/public` | none | Gallery — search + filter public queries |
| `GET` | `/{id}` | conditional | Fetch one (public: no auth; private: must own) |
| `PATCH` | `/{id}` | required, must own | Update name / description / tags / visibility / text |
| `DELETE` | `/{id}` | required, must own | Delete |

**`GET /public` query parameters:**

| Param | Type | Description |
|---|---|---|
| `q` | string | Full-text search against name, description, and tags |
| `ontology` | string | Filter: tag must contain this value (ontology shortname) |
| `user_id` | UUID | Filter by author |
| `limit` | int (default 50) | Pagination |
| `offset` | int (default 0) | Pagination |

Response includes `user_display_name` (from the `User` row) so the gallery can show author names without a separate request.

**`GET /{id}` access rules:**
- `is_public = true` → returns 200 to anyone
- `is_public = false` → returns 200 to the owner, 404 to everyone else (not 403, to avoid leaking existence)

**Alembic migration:** new file in `alembic/versions/` creating the `saved_queries` table and `ARRAY` column.

### `ontoexplorer/main.py`

Include the new router:
```python
from ontoexplorer.api.sparql_queries import router as sparql_queries_router
app.include_router(sparql_queries_router)
```

---

## Frontend

### New files

- `frontend/src/pages/SparqlGallery.tsx` — the `/sparql/gallery` page
- `frontend/src/components/QuerySidebar.tsx` — the persistent sidebar used by the SPARQL page

### Modified files

- `frontend/src/pages/Sparql.tsx` — add `QuerySidebar`, handle `?q=<id>` on load
- `frontend/src/App.tsx` — add `/sparql/gallery` route
- `frontend/src/lib/api.ts` — add `savedQueries` API functions

---

### QuerySidebar (`frontend/src/components/QuerySidebar.tsx`)

Rendered to the left of YASGUI inside the SPARQL page. Width: `200px`, fixed, not resizable.

**When unauthenticated:** renders a narrow placeholder — "Sign in to save queries" — rather than hiding, so the layout doesn't shift on login.

**When authenticated, states:**

1. **List view** (default)
   - Header: "MY QUERIES" label + "＋ Save" button
   - Search bar (filters the list client-side by name and tags)
   - Scrollable list of the user's queries, sorted by `updated_at` desc
   - Each row: name (truncated), public 🔗 / private 🔒 icon, tag chips
   - Clicking a row loads that query into YASGUI (calls `getTab()?.getYasqe()?.setValue(text)`)
   - Footer: "→ Browse Gallery" link to `/sparql/gallery`

2. **Save/edit form** (replaces list, same panel)
   - Triggered by "＋ Save" (new) or clicking ✎ on a query row (edit)
   - Fields: Name (required), Description (textarea), Tags (combo input), Public toggle
   - Tags combo: shows searchable dropdown of ontology shortnames from `GET /api/v1/ontologies`; also accepts free-form input (Enter or comma to confirm); chips with ✕ to remove
   - Cancel restores list view without saving
   - Submit: `POST /api/v1/sparql/queries` (new) or `PATCH /api/v1/sparql/queries/{id}` (edit)

---

### SPARQL page (`frontend/src/pages/Sparql.tsx`)

**Layout change:** outer container becomes `display: flex; flex-direction: row` instead of column. `QuerySidebar` is rendered first, then the YASGUI `div` takes `flex: 1`.

**`?q=<id>` handling:** on mount, read `new URLSearchParams(location.search).get('q')`. If present:
1. `GET /api/v1/sparql/queries/{id}`
2. On success: call `yasguiRef.current.getTab()?.getYasqe()?.setValue(data.query_text)`
3. On 404: show a one-line error banner below the header — "Query not found or not accessible"

---

### SparqlGallery (`frontend/src/pages/SparqlGallery.tsx`)

Route: `/sparql/gallery`, wrapped in `<Shell>`.

**Layout:**
- Full-width header section (same `--bg-secondary` + border-bottom pattern as other pages): title "Query Gallery", query count, search bar, Ontology dropdown, Author dropdown
- Body: responsive two-column card grid (single column on narrow viewports)

**Each card:**
- Name (link — clicking navigates to `/sparql?q=<id>`)
- Description (up to 2 lines, truncated)
- Tag chips
- Author name · relative date

**Filters:**
- Search input: client-side debounce (300 ms), then re-fetches `GET /sparql/queries/public?q=...`
- Ontology dropdown: populated from `GET /api/v1/ontologies` (shortname list); adds `ontology=` param
- Author dropdown: populated from unique authors in the current result set; adds `user_id=` param

**Pagination:** "Load more" button appending next page (offset-based), not full page replacement.

---

### `frontend/src/lib/api.ts`

New `savedQueries` namespace:

```typescript
savedQueries: {
  create: (body: { name: string; description?: string; query_text: string; tags: string[]; is_public: boolean }) => Promise<SavedQuery>
  list: () => Promise<SavedQuery[]>
  listPublic: (params: { q?: string; ontology?: string; user_id?: string; limit?: number; offset?: number }) => Promise<SavedQuery[]>
  get: (id: string) => Promise<SavedQuery>
  update: (id: string, body: Partial<{ name: string; description: string; query_text: string; tags: string[]; is_public: boolean }>) => Promise<SavedQuery>
  delete: (id: string) => Promise<void>
}
```

---

## Shareable URL

When a query is public, its shareable link is `/sparql?q=<uuid>`. No separate "copy link" action is needed — the link is always `/sparql?q={id}` and the sidebar can display it next to public queries for easy copying.

---

## Error Handling

| Condition | Behaviour |
|---|---|
| `/sparql?q=<id>`, query is private, user not logged in | Redirect to `/login`; return to URL after auth |
| `/sparql?q=<id>`, query is private, wrong user | 404 → banner: "Query not found or not accessible" |
| `/sparql?q=<id>`, ID does not exist | 404 → same banner |
| Save form submitted with empty name | Client-side validation; submit disabled |
| Duplicate name (same user) | Allowed |
| Query deleted after being shared | Shared URL returns 404 → banner |
| Unauthenticated user on `/sparql` | Sidebar shows "Sign in to save queries" placeholder |
| Unauthenticated user on `/sparql/gallery` | Fully accessible; "Open ↗" navigates to `/sparql?q=<id>` |

---

## What This Does NOT Include

- Forking another user's query into your own library (defer)
- Query ratings or comments (defer)
- Editing another user's public query (not permitted; load + save as new instead)
- Rate limiting on the gallery endpoint (add if abuse observed)
