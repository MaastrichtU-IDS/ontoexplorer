# Cross-repository entity browsing (`/browse`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every clickable repository-wide statistic on the Home page a destination that actually surfaces the entities (or logical content) it counts, via a new two-mode `/browse` page.

**Architecture:** A new `/browse` route mirrors Home's two-mode layout. **List mode** is a cross-repository, **keyset-paginated** listing of one entity type, served by one new public endpoint `GET /api/v1/entities` that runs a single SQL query over the existing Postgres `entity_index` table. Keyset (cursor) pagination — not `OFFSET` — is used so the listing stays O(page) at 100M+ entities. **Query mode** reuses Home's existing MOS structured-query component. The seven Home stat cards get rewired: Ontologies → `/ontologies`, the five entity types → `/browse?type=<t>`, Axioms → `/browse?mode=query`.

**Tech Stack:** FastAPI + SQLAlchemy (async) + Alembic (backend), React + react-router + @tanstack/react-query + Vitest/testing-library (frontend), pytest (backend tests, SQLite in-memory).

## Global Constraints

- Backend API prefix is `/api/v1`. The new endpoint is **public** (no auth dependency), like `GET /api/v1/stats/public`.
- Entity type allow-list (exact strings): `class`, `object_property`, `data_property`, `annotation_property`, `individual`.
- Version-status filter (mirror existing `pg_search`): exclude versions whose `status` is in `('pending','failed','deprecated')`.
- Pagination is **keyset (cursor)**, never `OFFSET`. Sort/cursor key is the tuple `(primary_label_norm, iri, version_id)` (unique — `(version_id, iri)` is the PK). The `cursor` query param is an opaque `base64(json)` blob; the client only echoes back the `next` value the server returned.
- The keyset comparison is written in **expanded** form (`a > :a OR (a = :a AND b > :b) OR ...`), not SQL row-value syntax, so it runs identically on Postgres and the SQLite test DB.
- `approx_total` is a **cached** count (best-effort Redis, TTL 300s) with a direct `COUNT(*)` fallback when Redis is unavailable; it is display-only and never drives paging.
- Default page size: `50`.
- Follow existing frontend conventions: inline `style={{...}}` with `var(--...)` tokens, react-query hooks, `slugFromIri` for ontology URLs.
- Term-page URL format (from Home): `/ontologies/${slugFromIri(ont.iri)}/${version_id}?term=${encodeURIComponent(iri)}`.

---

### Task 1: Backend `GET /api/v1/entities` endpoint (keyset paginated)

**Files:**
- Modify: `ontoexplorer/modules/search/pg_search.py` (add `_LISTABLE_TYPES`, cursor codec, `list_entities_by_type`, `count_entities_by_type`)
- Create: `ontoexplorer/api/entities.py`
- Modify: `ontoexplorer/main.py` (register router)
- Test: `tests/integration/test_entities.py`

**Interfaces:**
- Produces: `encode_entity_cursor(label: str, iri: str, version: str) -> str` and `decode_entity_cursor(s: str) -> tuple[str, str, str] | None` (returns `None` on any malformed input).
- Produces: `list_entities_by_type(db, entity_type: str, limit: int, after: tuple[str, str, str] | None) -> tuple[list[dict], str | None]` — returns `(rows, next_cursor)`; each row a dict with keys `iri, label, short, type, version_id, ontology_id, source`; `next_cursor` is `None` on the last page.
- Produces: `count_entities_by_type(db, entity_type: str) -> int`.
- Produces: HTTP `GET /api/v1/entities?type=<t>&limit=<n>&cursor=<opaque>` → `{ "entities": [...], "next": str|null, "approx_total": int, "limit": int }`.
- Consumes: existing `_row_to_dict` and `text` in `pg_search.py`; `get_db` from `ontoexplorer.database`; `_get_redis` from `ontoexplorer.modules.search.indexer`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_entities.py`:

```python
"""Integration tests for the cross-repository entity listing endpoint."""
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion, EntityIndex

pytestmark = pytest.mark.anyio


async def _seed(db_session):
    ont = Ontology(id="o1", iri="http://ex.org/onto", shortname="onto")
    db_session.add(ont)
    ready = OntologyVersion(
        id="v-ready", ontology_id="o1", minio_key="k1",
        sha256="sha-ready", format="owl", status="ready",
    )
    dep = OntologyVersion(
        id="v-dep", ontology_id="o1", minio_key="k2",
        sha256="sha-dep", format="owl", status="deprecated",
    )
    db_session.add_all([ready, dep])

    def _ei(vid, iri, etype, label):
        return EntityIndex(
            version_id=vid, iri=iri, ontology_id="o1", type=etype,
            primary_label=label, primary_label_norm=label.lower(),
            short=iri.split("/")[-1], source="onto", search_text=label.lower(),
        )

    db_session.add_all([
        _ei("v-ready", "http://ex.org/Cell", "class", "cell"),
        _ei("v-ready", "http://ex.org/Apoptosis", "class", "apoptosis"),
        _ei("v-ready", "http://ex.org/Nucleus", "class", "nucleus"),
        _ei("v-ready", "http://ex.org/hasPart", "object_property", "has part"),
        # under a deprecated version — must be excluded
        _ei("v-dep", "http://ex.org/Ghost", "class", "ghost"),
    ])
    await db_session.commit()


async def test_lists_classes_excluding_deprecated_versions(client, db_session):
    await _seed(db_session)
    resp = await client.get("/api/v1/entities?type=class")
    assert resp.status_code == 200
    body = resp.json()
    assert body["approx_total"] == 3  # ghost (deprecated version) excluded
    labels = [e["label"] for e in body["entities"]]
    assert labels == ["apoptosis", "cell", "nucleus"]  # alphabetical by norm
    assert body["next"] is None  # only 3 rows, default limit 50
    assert body["entities"][0]["ontology_id"] == "o1"
    assert body["entities"][0]["type"] == "class"


async def test_filters_by_type(client, db_session):
    await _seed(db_session)
    body = (await client.get("/api/v1/entities?type=object_property")).json()
    assert body["approx_total"] == 1
    assert body["entities"][0]["label"] == "has part"


async def test_keyset_pagination(client, db_session):
    await _seed(db_session)
    page1 = (await client.get("/api/v1/entities?type=class&limit=2")).json()
    assert [e["label"] for e in page1["entities"]] == ["apoptosis", "cell"]
    assert page1["next"] is not None
    page2 = (await client.get(f"/api/v1/entities?type=class&limit=2&cursor={page1['next']}")).json()
    assert [e["label"] for e in page2["entities"]] == ["nucleus"]
    assert page2["next"] is None  # last page


async def test_unknown_type_is_rejected(client, db_session):
    await _seed(db_session)
    assert (await client.get("/api/v1/entities?type=bogus")).status_code == 422


async def test_bad_cursor_is_rejected(client, db_session):
    await _seed(db_session)
    assert (await client.get("/api/v1/entities?type=class&cursor=not-base64!!")).status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_entities.py -q`
Expected: FAIL — `404` responses (route not registered) / import errors.

- [ ] **Step 3: Add the cursor codec + query/count functions to `pg_search.py`**

Append to `ontoexplorer/modules/search/pg_search.py` (it already imports `text` and defines `_row_to_dict`; add `import base64` and `import json` at the top of the file if not present):

```python
_LISTABLE_TYPES = {
    "class", "object_property", "data_property", "annotation_property", "individual",
}


def encode_entity_cursor(label: str, iri: str, version: str) -> str:
    raw = json.dumps({"l": label, "i": iri, "v": version}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_entity_cursor(s: str) -> tuple[str, str, str] | None:
    """Decode an opaque cursor to (label_norm, iri, version_id); None if malformed."""
    try:
        d = json.loads(base64.urlsafe_b64decode(s.encode()))
        return (d["l"], d["i"], d["v"])
    except Exception:
        return None


async def list_entities_by_type(
    db: AsyncSession,
    entity_type: str,
    limit: int,
    after: tuple[str, str, str] | None,
) -> tuple[list[dict], str | None]:
    """Keyset-paginated cross-repository listing of one `entity_index.type`.

    Ordered by (primary_label_norm, iri, version_id). `after` is the last row's
    key from the previous page, or None for the first page. Returns (rows,
    next_cursor); next_cursor is None on the final page. Fetches limit+1 rows to
    detect whether a further page exists. Occurrences are NOT de-duplicated
    across ontologies. Excludes pending/failed/deprecated versions.
    """
    params: dict = {"t": entity_type, "lim": limit + 1}
    keyset = ""
    if after is not None:
        al, ai, av = after
        keyset = """
          AND ( ei.primary_label_norm > :al
                OR (ei.primary_label_norm = :al AND ei.iri > :ai)
                OR (ei.primary_label_norm = :al AND ei.iri = :ai AND ei.version_id > :av) )
        """
        params |= {"al": al, "ai": ai, "av": av}

    list_sql = text(f"""
        SELECT ei.iri, ei.primary_label, ei.short, ei.type,
               ei.version_id, ei.ontology_id, ei.source, ei.primary_label_norm
        FROM entity_index ei
        JOIN versions v ON v.id = ei.version_id
        WHERE v.status NOT IN ('pending','failed','deprecated')
          AND ei.type = :t
          {keyset}
        ORDER BY ei.primary_label_norm, ei.iri, ei.version_id
        LIMIT :lim
    """)
    rows = (await db.execute(list_sql, params)).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_entity_cursor(last.primary_label_norm, last.iri, last.version_id)
    return [_row_to_dict(r) for r in page], next_cursor


async def count_entities_by_type(db: AsyncSession, entity_type: str) -> int:
    count_sql = text("""
        SELECT COUNT(*)
        FROM entity_index ei
        JOIN versions v ON v.id = ei.version_id
        WHERE v.status NOT IN ('pending','failed','deprecated')
          AND ei.type = :t
    """)
    return int((await db.execute(count_sql, {"t": entity_type})).scalar_one())
```

- [ ] **Step 4: Create the endpoint router `ontoexplorer/api/entities.py`**

```python
"""Cross-repository entity listing — GET /api/v1/entities."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.modules.search.pg_search import (
    _LISTABLE_TYPES,
    count_entities_by_type,
    decode_entity_cursor,
    list_entities_by_type,
)

router = APIRouter(prefix="/api/v1", tags=["entities"])

_COUNT_TTL = 300  # seconds


async def _approx_total(db: AsyncSession, entity_type: str) -> int:
    """Cached COUNT(*) per type; direct count when Redis is unavailable."""
    key = f"entities_count:{entity_type}"
    r = None
    try:
        from ontoexplorer.modules.search.indexer import _get_redis
        r = _get_redis()
        cached = r.get(key)
        if cached is not None:
            return int(cached)
    except Exception:
        r = None
    total = await count_entities_by_type(db, entity_type)
    try:
        if r is not None:
            r.setex(key, _COUNT_TTL, total)
    except Exception:
        pass
    return total


@router.get("/entities", summary="Cross-repository keyset-paginated entity listing by type")
async def list_entities(
    type: str = Query(..., description="class | object_property | data_property | annotation_property | individual"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="Opaque pagination cursor from a previous response's `next`"),
    db: AsyncSession = Depends(get_db),
):
    if type not in _LISTABLE_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown entity type: {type}")
    after = None
    if cursor:
        after = decode_entity_cursor(cursor)
        if after is None:
            raise HTTPException(status_code=422, detail="invalid cursor")
    entities, next_cursor = await list_entities_by_type(db, type, limit, after)
    approx_total = await _approx_total(db, type)
    return {"entities": entities, "next": next_cursor, "approx_total": approx_total, "limit": limit}
```

- [ ] **Step 5: Register the router in `ontoexplorer/main.py`**

Add the import near the other API imports (e.g. next to `from ontoexplorer.api.global_search import router as global_search_router`):

```python
from ontoexplorer.api.entities import router as entities_router
```

Add the include next to the other `app.include_router(...)` calls (e.g. right after `app.include_router(global_search_router)`):

```python
    app.include_router(entities_router)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/integration/test_entities.py -q`
Expected: PASS (5 passed).

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/modules/search/pg_search.py ontoexplorer/api/entities.py ontoexplorer/main.py tests/integration/test_entities.py
git commit -m "feat(entities): keyset-paginated cross-repository entity listing endpoint"
```

---

### Task 2: Index on `entity_index (type, primary_label_norm, iri, version_id)`

**Files:**
- Modify: `ontoexplorer/models/db.py` (add `__table_args__` Index to `EntityIndex`)
- Create: `alembic/versions/<rev>_add_type_label_index_entity_index.py`
- Test: `tests/unit/test_entity_index_type_label_index.py`

**Interfaces:**
- Produces: a btree index `ix_entity_index_type_label` on `entity_index (type, primary_label_norm, iri, version_id)` — equality on `type` then the keyset range scan over the sort tuple. Declared in ORM metadata (so the SQLite test DB builds it) and as an Alembic migration (for Postgres).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_entity_index_type_label_index.py`:

```python
"""The keyset index backing /entities listing must exist and match the sort key."""
from ontoexplorer.models.db import EntityIndex


def test_type_label_index_declared():
    names = {ix.name for ix in EntityIndex.__table__.indexes}
    assert "ix_entity_index_type_label" in names
    ix = next(ix for ix in EntityIndex.__table__.indexes if ix.name == "ix_entity_index_type_label")
    cols = [c.name for c in ix.columns]
    assert cols == ["type", "primary_label_norm", "iri", "version_id"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_entity_index_type_label_index.py -q`
Expected: FAIL — `ix_entity_index_type_label` not in the index set.

- [ ] **Step 3: Add the Index to the `EntityIndex` model**

In `ontoexplorer/models/db.py`, ensure `Index` is in the `from sqlalchemy import ...` line (add it if missing). Add a `__table_args__` to `EntityIndex` directly under `__tablename__`:

```python
    __tablename__ = "entity_index"
    __table_args__ = (
        Index(
            "ix_entity_index_type_label",
            "type", "primary_label_norm", "iri", "version_id",
        ),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_entity_index_type_label_index.py -q`
Expected: PASS.

- [ ] **Step 5: Find the current migration head**

Run: `.venv/bin/alembic heads`
Expected: prints one revision id (e.g. `f0a1b2c3d4e5 (head)`). Use that value as `down_revision` below.

- [ ] **Step 6: Create the Alembic migration**

Create `alembic/versions/a1b2c3d4e5f6_add_type_label_index_entity_index.py` (pick any unused 12-char hex for the revision id; set `down_revision` to the head from Step 5):

```python
"""add keyset index on entity_index (type, primary_label_norm, iri, version_id)

Backs the cross-repository /entities keyset listing: equality on type, then a
range scan over the (primary_label_norm, iri, version_id) sort tuple.

Revision ID: a1b2c3d4e5f6
Revises: <HEAD_FROM_STEP_5>
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "<HEAD_FROM_STEP_5>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_entity_index_type_label",
        "entity_index",
        ["type", "primary_label_norm", "iri", "version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_index_type_label", table_name="entity_index")
```

- [ ] **Step 7: Verify the migration file is valid and there is a single head**

Run: `.venv/bin/alembic heads`
Expected: prints `a1b2c3d4e5f6 (head)` (single head). If it reports multiple heads, fix `down_revision` to the Step 5 value.

- [ ] **Step 8: Commit**

```bash
git add ontoexplorer/models/db.py alembic/versions/a1b2c3d4e5f6_add_type_label_index_entity_index.py tests/unit/test_entity_index_type_label_index.py
git commit -m "feat(entities): keyset index on entity_index(type, label, iri, version)"
```

---

### Task 3: Frontend `/browse` page (List + Query modes) with data layer

**Files:**
- Modify: `frontend/src/lib/api.ts` (add `EntityRow` type + `api.entities.list`)
- Create: `frontend/src/hooks/useEntities.ts`
- Modify: `frontend/src/pages/Home.tsx` (export `MOSQuery`)
- Create: `frontend/src/pages/Browse.tsx`
- Modify: `frontend/src/App.tsx` (register `/browse` route)
- Test: `frontend/src/pages/Browse.test.tsx`

**Interfaces:**
- Consumes: the Task 1 HTTP contract `{ entities, next, approx_total, limit }`.
- Produces: `api.entities.list({ type, limit, cursor?, lang?, q? })`, `EntityRow`, `useEntities(params)`, and a page component `Browse` mounted at `/browse` reading `mode|type` from the URL and keeping cursor position in component state.
- Consumes: `MOSQuery` (now exported from `./Home`), `useOntologies`, `slugFromIri`.

- [ ] **Step 1: Add the API client method and type in `frontend/src/lib/api.ts`**

Add the type near the other exported interfaces (e.g. next to `SearchResult`):

```typescript
export interface EntityRow {
  iri: string
  label: string
  short: string
  type: string
  version_id: string
  ontology_id: string
  source: string
}
```

Add an `entities` group inside `export const api = { ... }` (e.g. right after the `ontologies: { ... }` group):

```typescript
  entities: {
    list: (params: { type: string; limit: number; cursor?: string | null; lang?: string | null; q?: string }) => {
      const p = new URLSearchParams({ type: params.type, limit: String(params.limit) })
      if (params.cursor) p.set('cursor', params.cursor)
      if (params.lang) p.set('lang', params.lang)
      if (params.q) p.set('q', params.q)
      return request<{ entities: EntityRow[]; next: string | null; approx_total: number; limit: number }>(
        `/entities?${p}`
      )
    },
  },
```

- [ ] **Step 2: Create the `useEntities` hook `frontend/src/hooks/useEntities.ts`**

```typescript
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useEntities(params: { type: string; limit: number; cursor?: string | null; lang?: string | null; q?: string }) {
  return useQuery({
    queryKey: ['entities', params.type, params.limit, params.cursor ?? '', params.lang ?? '', params.q ?? ''],
    queryFn: () => api.entities.list(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
}
```

- [ ] **Step 3: Export `MOSQuery` from `frontend/src/pages/Home.tsx`**

Change the declaration `function MOSQuery({ relation, onRelationChange }: {` to:

```typescript
export function MOSQuery({ relation, onRelationChange }: {
```

(No other change to Home in this task.)

- [ ] **Step 4: Write the failing page test `frontend/src/pages/Browse.test.tsx`**

```typescript
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Browse from './Browse'

const CLASS_PAGE = {
  entities: [
    { iri: 'http://ex.org/Cell', label: 'cell', short: 'Cell', type: 'class', version_id: 'v1', ontology_id: 'o1', source: 'onto' },
  ],
  next: 'CURSOR2', approx_total: 3, limit: 50,
}
let mockEntities: any = { data: CLASS_PAGE, isFetching: false, isError: false }
const useEntitiesSpy = vi.fn(() => mockEntities)
vi.mock('../hooks/useEntities', () => ({ useEntities: (p: any) => useEntitiesSpy(p) }))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({ ontologies: [{ id: 'o1', iri: 'http://ex.org/onto', created_at: '2024-01-01' }] }),
}))

vi.mock('./Home', () => ({ MOSQuery: () => <div data-testid="mos-query" /> }))

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/browse" element={<Browse />} /></Routes>
    </MemoryRouter>
  )
}

test('list mode: renders an entity row linking to its term page', () => {
  mockEntities = { data: CLASS_PAGE, isFetching: false, isError: false }
  renderAt('/browse?type=class')
  const link = screen.getByRole('link', { name: /cell/i })
  expect(link).toHaveAttribute('href', expect.stringContaining('term=http%3A%2F%2Fex.org%2FCell'))
})

test('list mode: Next advances using the returned cursor', () => {
  mockEntities = { data: CLASS_PAGE, isFetching: false, isError: false }
  useEntitiesSpy.mockClear()
  renderAt('/browse?type=class')
  fireEvent.click(screen.getByRole('button', { name: /Next/i }))
  const lastCall = useEntitiesSpy.mock.calls.at(-1)![0]
  expect(lastCall.cursor).toBe('CURSOR2')
})

test('list mode: switching type tab resets the cursor', () => {
  mockEntities = { data: CLASS_PAGE, isFetching: false, isError: false }
  useEntitiesSpy.mockClear()
  renderAt('/browse?type=class')
  fireEvent.click(screen.getByRole('button', { name: /Next/i }))  // cursor now CURSOR2
  fireEvent.click(screen.getByRole('button', { name: 'Object Properties' }))
  const lastCall = useEntitiesSpy.mock.calls.at(-1)![0]
  expect(lastCall.type).toBe('object_property')
  expect(lastCall.cursor ?? null).toBeNull()
})

test('query mode: renders the MOS query component', () => {
  renderAt('/browse?mode=query')
  expect(screen.getByTestId('mos-query')).toBeInTheDocument()
})

test('list mode empty state', () => {
  mockEntities = { data: { entities: [], next: null, approx_total: 0, limit: 50 }, isFetching: false, isError: false }
  renderAt('/browse?type=data_property')
  expect(screen.getByText(/No data properties in the repository yet/i)).toBeInTheDocument()
})
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Browse.test.tsx`
Expected: FAIL — cannot resolve `./Browse`.

- [ ] **Step 6: Create the page `frontend/src/pages/Browse.tsx`**

```tsx
import { Link, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import { useEntities } from '../hooks/useEntities'
import { useOntologies } from '../hooks/useOntologies'
import { EntityRow, slugFromIri } from '../lib/api'
import { MOSQuery } from './Home'

const PAGE_SIZE = 50

type EntityType = 'class' | 'object_property' | 'data_property' | 'annotation_property' | 'individual'

const TYPE_TABS: { value: EntityType; label: string }[] = [
  { value: 'class', label: 'Classes' },
  { value: 'object_property', label: 'Object Properties' },
  { value: 'data_property', label: 'Data Properties' },
  { value: 'annotation_property', label: 'Annotation Properties' },
  { value: 'individual', label: 'Individuals' },
]

const TYPE_BADGE: Record<string, string> = {
  class: 'CLASS', object_property: 'OP', data_property: 'DP',
  annotation_property: 'AP', individual: 'IND',
}

function EntityListRows({ rows }: { rows: EntityRow[] }) {
  const { ontologies } = useOntologies()
  function pathFor(r: EntityRow): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont || !r.version_id) return null
    return `/ontologies/${slugFromIri(ont.iri)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }
  function ontName(r: EntityRow): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont) return null
    if (ont.shortname) return ont.shortname
    const last = ont.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? ont.iri
    return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
  }
  return (
    <ul style={{ listStyle: 'none', marginTop: '0.5rem' }}>
      {rows.map(r => {
        const path = pathFor(r)
        const name = ontName(r)
        const inner = (
          <>
            <span style={{
              fontSize: 9, padding: '1px 5px', borderRadius: 3,
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              color: 'var(--text-dim)', flexShrink: 0, fontWeight: 600, letterSpacing: 0.3,
            }}>{TYPE_BADGE[r.type] ?? r.type}</span>
            <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{r.label}</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
            {name && (
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 3,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0, fontWeight: 500,
              }}>{name}</span>
            )}
          </>
        )
        const style: React.CSSProperties = {
          padding: '8px 10px', borderRadius: 'var(--radius-sm)',
          display: 'flex', gap: 10, alignItems: 'baseline',
          borderBottom: '1px solid var(--border)', textDecoration: 'none',
        }
        return path ? (
          <li key={`${r.version_id}:${r.iri}`}>
            <Link to={path} style={style}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >{inner}</Link>
          </li>
        ) : (
          <li key={`${r.version_id}:${r.iri}`} style={{ ...style, color: 'var(--text-dim)' }}>{inner}</li>
        )
      })}
    </ul>
  )
}

function ListMode({ type, onType }: { type: EntityType; onType: (t: EntityType) => void }) {
  // Cursor stack: `stack` holds the cursors for previous pages; `cursor` is the
  // current page's start (null = first page). Keyset paging — no offset.
  const [cursor, setCursor] = useState<string | null>(null)
  const [stack, setStack] = useState<(string | null)[]>([])
  const { data, isFetching, isError } = useEntities({ type, limit: PAGE_SIZE, cursor })
  const rows = data?.entities ?? []
  const next = data?.next ?? null
  const approxTotal = data?.approx_total ?? 0
  const typeLabel = TYPE_TABS.find(t => t.value === type)?.label.toLowerCase() ?? 'entities'

  function switchType(t: EntityType) {
    setStack([]); setCursor(null); onType(t)
  }
  function goNext() {
    if (!next) return
    setStack(s => [...s, cursor]); setCursor(next)
  }
  function goPrev() {
    setStack(s => {
      if (s.length === 0) return s
      const copy = [...s]; const prev = copy.pop() ?? null; setCursor(prev); return copy
    })
  }

  const btn = (disabled: boolean): React.CSSProperties => ({
    background: 'none', border: '1px solid var(--border)', borderRadius: 4,
    color: disabled ? 'var(--text-dim)' : 'var(--text)', fontSize: 12,
    padding: '4px 12px', cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.4 : 1,
  })

  return (
    <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: '1rem' }}>
        {TYPE_TABS.map(t => (
          <button key={t.value} type="button" onClick={() => switchType(t.value)} style={{
            fontSize: 12, padding: '4px 12px', borderRadius: 12,
            background: type === t.value ? 'var(--accent)' : 'var(--bg-secondary)',
            border: '1px solid ' + (type === t.value ? 'var(--accent)' : 'var(--border)'),
            color: type === t.value ? 'var(--on-accent)' : 'var(--text-muted)',
            cursor: 'pointer', fontWeight: type === t.value ? 600 : 400,
          }}>{t.label}</button>
        ))}
      </div>

      {isError && (
        <p style={{ color: 'var(--error)', textAlign: 'center', marginTop: '2rem' }}>
          Could not load {typeLabel}. Try again.
        </p>
      )}
      {!isError && approxTotal === 0 && rows.length === 0 && !isFetching && (
        <p style={{ color: 'var(--text-dim)', textAlign: 'center', marginTop: '2rem' }}>
          No {typeLabel} in the repository yet
        </p>
      )}
      {!isError && (rows.length > 0 || approxTotal > 0) && (
        <>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>
            ~{approxTotal.toLocaleString()} {typeLabel}
          </div>
          <EntityListRows rows={rows} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'center' }}>
            <button type="button" onClick={goPrev} disabled={stack.length === 0} style={btn(stack.length === 0)}>
              ← Previous
            </button>
            <button type="button" onClick={goNext} disabled={!next} style={btn(!next)}>
              Next →
            </button>
          </div>
        </>
      )}
    </>
  )
}

export default function Browse() {
  const [params, setParams] = useSearchParams()
  const mode = params.get('mode') === 'query' ? 'query' : 'list'
  const type = (params.get('type') as EntityType) || 'class'
  const [relation, setRelation] = useState<'subclasses' | 'superclasses' | 'equivalent'>('subclasses')

  function setMode(next: 'list' | 'query') {
    const p = new URLSearchParams(params)
    if (next === 'query') { p.set('mode', 'query') } else { p.delete('mode') }
    setParams(p, { replace: true })
  }
  function setType(next: EntityType) {
    const p = new URLSearchParams(params)
    p.set('type', next)
    setParams(p, { replace: true })
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '3rem 1.5rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 22, fontWeight: 700, marginBottom: '1rem', textAlign: 'center' }}>
        Browse the repository
      </h1>

      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
        <div style={{ display: 'flex', borderRadius: 'var(--radius)', overflow: 'hidden', border: '1px solid var(--border)' }}>
          {(['list', 'query'] as const).map(m => (
            <button key={m} onClick={() => setMode(m)} style={{
              padding: '7px 22px', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 500,
              background: mode === m ? 'var(--accent)' : 'transparent',
              color: mode === m ? 'var(--on-accent)' : 'var(--text-dim)',
            }}>{m === 'list' ? 'List' : 'Structured Query'}</button>
          ))}
        </div>
      </div>

      {mode === 'list' ? (
        // key=type remounts ListMode on type change so its cursor stack resets cleanly
        <ListMode key={type} type={type} onType={setType} />
      ) : (
        <>
          <p style={{ color: 'var(--text-dim)', fontSize: 12, textAlign: 'center', marginBottom: 12 }}>
            Probe the logical content with a Manchester expression, or{' '}
            <Link to="/sparql/gallery" style={{ color: 'var(--accent)' }}>browse axioms in SPARQL →</Link>
          </p>
          <MOSQuery relation={relation} onRelationChange={setRelation} />
        </>
      )}
    </div>
  )
}
```

Note: `ListMode` is mounted with `key={type}`, so switching type unmounts/remounts it and its `cursor`/`stack` reset to first-page automatically. The `onType`/`switchType` call still updates the URL `type`.

- [ ] **Step 7: Register the route in `frontend/src/App.tsx`**

Add the import beside the other page imports (e.g. next to `Ontologies`):

```typescript
import Browse from './pages/Browse'
```

Add the route right after the `/ontologies` routes block:

```tsx
      <Route path="/browse" element={<Shell><Browse /></Shell>} />
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/Browse.test.tsx`
Expected: PASS (5 passed).

- [ ] **Step 9: Typecheck and run the full frontend test suite**

Run: `cd frontend && npm run build && npx vitest run`
Expected: build succeeds (no TS errors from `EntityRow` / exported `MOSQuery`), all tests pass.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/hooks/useEntities.ts frontend/src/pages/Home.tsx frontend/src/pages/Browse.tsx frontend/src/App.tsx frontend/src/pages/Browse.test.tsx
git commit -m "feat(browse): two-mode /browse page (keyset list + MOS query)"
```

---

### Task 4: Rewire Home stat cards to `/browse`

**Files:**
- Modify: `frontend/src/pages/Home.tsx:595-621` (the `StatCard` `to` targets)
- Test: `frontend/src/pages/Home.test.tsx` (add link assertions)

**Interfaces:**
- Consumes: the `/browse?type=<t>` and `/browse?mode=query` routes from Task 3.

- [ ] **Step 1: Write the failing test in `frontend/src/pages/Home.test.tsx`**

The existing `stats.public` mock returns only `total_ontologies`, `total_classes`, `total_properties`. Update that mock object to include the fields the entity/axiom cards need, then assert the links. Change the `stats` mock line to:

```typescript
      stats: { public: () => Promise.resolve({
        total_ontologies: 5, total_classes: 1000,
        total_object_properties: 50, total_data_properties: 20,
        total_annotation_properties: 10, total_individuals: 30, total_axioms: 5000,
      }) },
```

Add these tests at the end of the file:

```typescript
test('Classes stat card links to /browse?type=class', async () => {
  renderHome()
  const link = await screen.findByRole('link', { name: /Classes/i })
  expect(link).toHaveAttribute('href', '/browse?type=class')
})

test('Axioms stat card links to /browse in query mode', async () => {
  renderHome()
  const link = await screen.findByRole('link', { name: /Axioms/i })
  expect(link).toHaveAttribute('href', '/browse?mode=query')
})

test('Ontologies stat card still links to /ontologies', async () => {
  renderHome()
  const link = await screen.findByRole('link', { name: /Ontologies/i })
  expect(link).toHaveAttribute('href', '/ontologies')
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Home.test.tsx`
Expected: FAIL — the Classes/Axioms links still point to `/ontologies`.

- [ ] **Step 3: Update the `StatCard` `to` targets in `Home.tsx`**

In the `publicStats && (...)` block (around lines 595-621), change each `to`:

```tsx
          <StatCard label="Ontologies" value={publicStats.total_ontologies} to="/ontologies" />
          <StatCard label="Classes" value={publicStats.total_classes}
            subtitle={publicStats.unique_classes != null ? `${publicStats.unique_classes.toLocaleString()} unique` : undefined}
            to="/browse?type=class" />
          {publicStats.total_object_properties > 0 && (
            <StatCard label="Object Properties" value={publicStats.total_object_properties}
              subtitle={publicStats.unique_object_properties != null ? `${publicStats.unique_object_properties.toLocaleString()} unique` : undefined}
              to="/browse?type=object_property" />
          )}
          {publicStats.total_data_properties > 0 && (
            <StatCard label="Data Properties" value={publicStats.total_data_properties}
              subtitle={publicStats.unique_data_properties != null ? `${publicStats.unique_data_properties.toLocaleString()} unique` : undefined}
              to="/browse?type=data_property" />
          )}
          {publicStats.total_annotation_properties > 0 && (
            <StatCard label="Annotation Properties" value={publicStats.total_annotation_properties}
              subtitle={publicStats.unique_annotation_properties != null ? `${publicStats.unique_annotation_properties.toLocaleString()} unique` : undefined}
              to="/browse?type=annotation_property" />
          )}
          {publicStats.total_individuals > 0 && (
            <StatCard label="Individuals" value={publicStats.total_individuals}
              subtitle={publicStats.unique_individuals != null ? `${publicStats.unique_individuals.toLocaleString()} unique` : undefined}
              to="/browse?type=individual" />
          )}
          {publicStats.total_axioms > 0 && (
            <StatCard label="Axioms" value={publicStats.total_axioms} to="/browse?mode=query" />
          )}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/Home.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Home.tsx frontend/src/pages/Home.test.tsx
git commit -m "feat(home): point entity stat cards at /browse (Axioms -> query mode)"
```

---

## Self-Review

**Spec coverage:**
- Two-mode `/browse` page → Task 3 ✓
- List mode backed by `entity_index`, single SQL, **keyset** paginated, cached approx count → Task 1 ✓
- Keyset index `(type, primary_label_norm, iri, version_id)` → Task 2 ✓
- Type tabs (5 types), URL `type`/`mode` state, cursor position in component state, rows link to term pages → Task 3 ✓
- No de-duplication across ontologies (count matches occurrence counts) → Task 1 ✓
- Query mode reuses `MOSQuery` → Task 3 (export + import) ✓
- Axiom fallback = link to SPARQL gallery → Task 3 (query-mode header note) ✓
- Stat-card routing table → Task 4 ✓
- Empty / error / last-page states → Task 3 `ListMode` ✓
- Testing: keyset paging (no overlap/gap, `next` null on last page), approx count, migration/index, frontend page + Home wiring → Tasks 1-4 ✓

**Optional `q` search box:** the endpoint and client accept `q`, but List mode v1 ships without a search input (YAGNI — the spec marks it conditional). Plumbing is present for a later addition; no task depends on it. Not a gap.

**Placeholder scan:** the only intentional fill-ins are the Alembic `revision`/`down_revision` ids in Task 2, resolved by the `alembic heads` command in Steps 5/7 — not code placeholders.

**Type consistency:**
- Cursor codec ↔ query fn: `encode_entity_cursor(label, iri, version)` produces what `decode_entity_cursor` returns as `(label, iri, version)`, matching the `after` tuple `list_entities_by_type` consumes. The endpoint passes `decode_entity_cursor(cursor)` straight into `after`. ✓
- `list_entities_by_type` returns `(rows, next_cursor)`; the endpoint maps these to response keys `entities` / `next`. ✓
- `_row_to_dict` output keys (`iri,label,short,type,version_id,ontology_id,source`) match `EntityRow` and the sort tuple uses `primary_label_norm`/`iri`/`version_id` which the SELECT includes. ✓
- Frontend `api.entities.list` / `useEntities` params (`type,limit,cursor?,lang?,q?`) and response (`entities,next,approx_total,limit`) are consistent across Task 3. ✓
- `MOSQuery` prop shape (`{relation,onRelationChange}`) matches Home's existing signature. ✓

## Out of scope

- A List-mode free-text search box (plumbing exists; UI deferred).
- A NavBar link to `/browse` (entry is via Home stat cards).
- Faceting List mode by ontology.
- Any cross-repo raw-axiom (triple) listing — delegated to SPARQL.
- Migrating the primary triplestore to QLever — a separate strategic evaluation; keyset pagination makes `/browse` scale on the current substrate.
