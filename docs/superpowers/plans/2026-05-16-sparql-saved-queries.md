# SPARQL Saved Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authenticated users save, load, and share SPARQL queries via a persistent sidebar; expose public queries in a browsable gallery at `/sparql/gallery`.

**Architecture:** New `saved_queries` DB table + FastAPI router + React sidebar component (200px, flex layout inside Sparql.tsx) + standalone gallery page at `/sparql/gallery`. Sidebar slides between list-view and save/edit form in-place. Shareable URL: `/sparql?q=<uuid>`.

**Tech Stack:** PostgreSQL (JSON column for tags — SQLite-compatible for tests), FastAPI + SQLAlchemy async, pytest with anyio + in-memory SQLite, React + TypeScript + Vite, `@tanstack/react-query`, existing `useAuth` hook.

---

## File Map

| Action | File |
|--------|------|
| Modify | `ontoexplorer/models/db.py` |
| Create | `alembic/versions/e2f3a4b5c6d7_add_saved_queries.py` |
| Create | `ontoexplorer/api/sparql_queries.py` |
| Modify | `ontoexplorer/main.py` |
| Create | `tests/unit/test_saved_queries_model.py` |
| Create | `tests/integration/test_sparql_queries.py` |
| Modify | `frontend/src/lib/api.ts` |
| Create | `frontend/src/components/QuerySidebar.tsx` |
| Modify | `frontend/src/pages/Sparql.tsx` |
| Create | `frontend/src/pages/SparqlGallery.tsx` |
| Modify | `frontend/src/App.tsx` |

---

### Task 1: SavedQuery model + migration

**Files:**
- Modify: `ontoexplorer/models/db.py`
- Create: `alembic/versions/e2f3a4b5c6d7_add_saved_queries.py`
- Create: `tests/unit/test_saved_queries_model.py`

**Note:** `tags` uses `JSON` (not `ARRAY(Text)`) so tests pass on SQLite in-memory. Behaviour is identical for storing string lists.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_saved_queries_model.py`:

```python
import uuid
import pytest
from sqlalchemy import select
from ontoexplorer.models.db import SavedQuery, User


@pytest.mark.anyio
async def test_saved_query_crud(db_session):
    user = User(
        id=str(uuid.uuid4()),
        email=f"sq-{uuid.uuid4()}@example.com",
        display_name="SQ User",
    )
    db_session.add(user)
    await db_session.commit()

    sq = SavedQuery(
        user_id=user.id,
        name="My query",
        description="A test query",
        query_text="SELECT * WHERE { ?s ?p ?o } LIMIT 10",
        tags=["hp", "mondo"],
        is_public=False,
    )
    db_session.add(sq)
    await db_session.commit()
    await db_session.refresh(sq)

    assert sq.id is not None
    assert sq.name == "My query"
    assert sq.tags == ["hp", "mondo"]
    assert sq.is_public is False
    assert sq.created_at is not None

    result = await db_session.execute(
        select(SavedQuery).where(SavedQuery.user_id == user.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].id == sq.id
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /home/micheldumontier/code/ontoexplorer
uv run pytest tests/unit/test_saved_queries_model.py -v
```

Expected: `ImportError: cannot import name 'SavedQuery'`

- [ ] **Step 3: Add model to db.py**

In `ontoexplorer/models/db.py`, in the `User` class body (after the last existing relationship on ~line 40), add:

```python
    saved_queries: Mapped[list["SavedQuery"]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

At the end of `ontoexplorer/models/db.py`, append:

```python
class SavedQuery(Base):
    __tablename__ = "saved_queries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="saved_queries")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_saved_queries_model.py -v
```

Expected: PASS

- [ ] **Step 5: Create the alembic migration**

Create `alembic/versions/e2f3a4b5c6d7_add_saved_queries.py`:

```python
"""add saved_queries table

Revision ID: e2f3a4b5c6d7
Revises: f58beb3f4610
Create Date: 2026-05-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'f58beb3f4610'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'saved_queries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_saved_queries_user_id', 'saved_queries', ['user_id'])
    op.create_index('ix_saved_queries_is_public', 'saved_queries', ['is_public'])


def downgrade() -> None:
    op.drop_index('ix_saved_queries_is_public', table_name='saved_queries')
    op.drop_index('ix_saved_queries_user_id', table_name='saved_queries')
    op.drop_table('saved_queries')
```

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/models/db.py \
        alembic/versions/e2f3a4b5c6d7_add_saved_queries.py \
        tests/unit/test_saved_queries_model.py
git commit -m "feat(saved-queries): add SavedQuery model and migration"
```

---

### Task 2: API router

**Files:**
- Create: `ontoexplorer/api/sparql_queries.py`
- Modify: `ontoexplorer/main.py`
- Create: `tests/integration/test_sparql_queries.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_sparql_queries.py`:

```python
"""Integration tests for saved SPARQL queries API."""
import pytest

BASE = "/api/v1/sparql/queries"


@pytest.mark.anyio
async def test_create_and_list(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    resp = await client.post(
        BASE,
        json={
            "name": "My query",
            "description": "Test",
            "query_text": "SELECT * WHERE { ?s ?p ?o } LIMIT 10",
            "tags": ["hp", "mondo"],
            "is_public": False,
        },
        headers=auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "My query"
    assert body["tags"] == ["hp", "mondo"]
    assert body["is_public"] is False
    qid = body["id"]

    resp = await client.get(BASE, headers=auth)
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()["queries"]]
    assert qid in ids


@pytest.mark.anyio
async def test_private_query_access(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    resp = await client.post(
        BASE,
        json={"name": "private", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": [], "is_public": False},
        headers=auth,
    )
    qid = resp.json()["id"]

    # Owner can access
    assert (await client.get(f"{BASE}/{qid}", headers=auth)).status_code == 200
    # Unauthenticated gets 404 (not 403 — don't leak existence)
    assert (await client.get(f"{BASE}/{qid}")).status_code == 404


@pytest.mark.anyio
async def test_public_query_no_auth(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    resp = await client.post(
        BASE,
        json={"name": "public", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": ["go"], "is_public": True},
        headers=auth,
    )
    qid = resp.json()["id"]

    resp = await client.get(f"{BASE}/{qid}")
    assert resp.status_code == 200
    assert resp.json()["is_public"] is True


@pytest.mark.anyio
async def test_public_gallery_and_filter(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    await client.post(
        BASE,
        json={"name": "Gallery query", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": ["hp"], "is_public": True},
        headers=auth,
    )

    resp = await client.get(f"{BASE}/public")
    assert resp.status_code == 200
    names = [q["name"] for q in resp.json()["queries"]]
    assert "Gallery query" in names

    resp = await client.get(f"{BASE}/public?ontology=hp")
    assert resp.status_code == 200
    for q in resp.json()["queries"]:
        assert "hp" in q["tags"]

    resp = await client.get(f"{BASE}/public?q=Gallery")
    assert resp.status_code == 200
    names = [q["name"] for q in resp.json()["queries"]]
    assert "Gallery query" in names


@pytest.mark.anyio
async def test_update_and_delete(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    resp = await client.post(
        BASE,
        json={"name": "to-update", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": [], "is_public": False},
        headers=auth,
    )
    qid = resp.json()["id"]

    resp = await client.patch(f"{BASE}/{qid}", json={"name": "updated"}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated"

    resp = await client.delete(f"{BASE}/{qid}", headers=auth)
    assert resp.status_code == 204

    assert (await client.get(f"{BASE}/{qid}", headers=auth)).status_code == 404


@pytest.mark.anyio
async def test_unauthenticated_create_returns_401(client):
    resp = await client.post(
        BASE,
        json={"name": "q", "query_text": "SELECT ?s WHERE { ?s ?p ?o }", "tags": [], "is_public": False},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/integration/test_sparql_queries.py -v
```

Expected: All fail with 404 (router not yet registered)

- [ ] **Step 3: Create the API router**

Create `ontoexplorer/api/sparql_queries.py`:

```python
"""Saved SPARQL queries endpoints."""

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import SavedQuery, User
from ontoexplorer.modules.auth.dependencies import get_current_user, require_auth

router = APIRouter(prefix="/api/v1/sparql/queries", tags=["sparql-queries"])


class SavedQueryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    query_text: str
    tags: list[str] = []
    is_public: bool = False


class SavedQueryPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    query_text: Optional[str] = None
    tags: Optional[list[str]] = None
    is_public: Optional[bool] = None


def _serialize(sq: SavedQuery, user_display_name: Optional[str] = None) -> dict:
    d = {
        "id": sq.id,
        "user_id": sq.user_id,
        "name": sq.name,
        "description": sq.description,
        "query_text": sq.query_text,
        "tags": sq.tags or [],
        "is_public": sq.is_public,
        "created_at": sq.created_at.isoformat() if sq.created_at else None,
        "updated_at": sq.updated_at.isoformat() if sq.updated_at else None,
    }
    if user_display_name is not None:
        d["user_display_name"] = user_display_name
    return d


@router.post("", status_code=201)
async def create_saved_query(
    body: SavedQueryCreate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    sq = SavedQuery(
        user_id=user.id,
        name=body.name.strip(),
        description=body.description,
        query_text=body.query_text,
        tags=body.tags,
        is_public=body.is_public,
    )
    db.add(sq)
    await db.commit()
    await db.refresh(sq)
    return _serialize(sq)


@router.get("")
async def list_saved_queries(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SavedQuery)
        .where(SavedQuery.user_id == user.id)
        .order_by(SavedQuery.updated_at.desc())
    )
    return {"queries": [_serialize(q) for q in result.scalars().all()]}


@router.get("/public")
async def list_public_queries(
    q: Optional[str] = Query(None),
    ontology: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(SavedQuery, User.display_name)
        .join(User, SavedQuery.user_id == User.id)
        .where(SavedQuery.is_public == True)  # noqa: E712
    )
    if user_id:
        stmt = stmt.where(SavedQuery.user_id == user_id)

    rows = (await db.execute(stmt)).all()

    out = []
    for sq, display_name in rows:
        if q:
            haystack = f"{sq.name} {sq.description or ''} {' '.join(sq.tags or [])}"
            if q.lower() not in haystack.lower():
                continue
        if ontology and ontology not in (sq.tags or []):
            continue
        out.append(_serialize(sq, display_name))

    out.sort(key=lambda x: x["updated_at"] or "", reverse=True)
    return {"queries": out[offset: offset + limit], "total": len(out)}


@router.get("/{query_id}")
async def get_saved_query(
    query_id: str,
    user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SavedQuery).where(SavedQuery.id == query_id))
    sq = result.scalar_one_or_none()
    if sq is None or (not sq.is_public and (user is None or user.id != sq.user_id)):
        raise HTTPException(status_code=404, detail="Query not found or not accessible")
    return _serialize(sq)


@router.patch("/{query_id}")
async def update_saved_query(
    query_id: str,
    body: SavedQueryPatch,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SavedQuery).where(SavedQuery.id == query_id))
    sq = result.scalar_one_or_none()
    if sq is None or sq.user_id != user.id:
        raise HTTPException(status_code=404, detail="Query not found or not accessible")

    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="name cannot be empty")
        sq.name = body.name.strip()
    if body.description is not None:
        sq.description = body.description
    if body.query_text is not None:
        sq.query_text = body.query_text
    if body.tags is not None:
        sq.tags = body.tags
    if body.is_public is not None:
        sq.is_public = body.is_public

    sq.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(sq)
    return _serialize(sq)


@router.delete("/{query_id}", status_code=204)
async def delete_saved_query(
    query_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SavedQuery).where(SavedQuery.id == query_id))
    sq = result.scalar_one_or_none()
    if sq is None or sq.user_id != user.id:
        raise HTTPException(status_code=404, detail="Query not found or not accessible")
    await db.delete(sq)
    await db.commit()
```

- [ ] **Step 4: Register the router in main.py**

In `ontoexplorer/main.py`, add after the existing sparql import (~line 13):

```python
from ontoexplorer.api.sparql_queries import router as sparql_queries_router
```

Add after `app.include_router(sparql_router)` (~line 53):

```python
    app.include_router(sparql_queries_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_sparql_queries.py tests/unit/test_saved_queries_model.py -v
```

Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/sparql_queries.py \
        ontoexplorer/main.py \
        tests/integration/test_sparql_queries.py
git commit -m "feat(saved-queries): add API router with CRUD and public gallery"
```

---

### Task 3: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add SavedQuery type**

In `frontend/src/lib/api.ts`, after the `WebhookDelivery` interface (~line 361), add:

```typescript
export interface SavedQuery {
  id: string
  user_id: string
  name: string
  description: string | null
  query_text: string
  tags: string[]
  is_public: boolean
  created_at: string
  updated_at: string
  user_display_name?: string
}
```

- [ ] **Step 2: Add savedQueries namespace to the api object**

In `frontend/src/lib/api.ts`, add `savedQueries` inside the `export const api = {` block, after `webhooks`:

```typescript
  savedQueries: {
    create: (body: { name: string; description?: string; query_text: string; tags: string[]; is_public: boolean }) =>
      request<SavedQuery>('/sparql/queries', { method: 'POST', body: JSON.stringify(body) }),

    list: () =>
      request<{ queries: SavedQuery[] }>('/sparql/queries'),

    listPublic: (params: { q?: string; ontology?: string; user_id?: string; limit?: number; offset?: number }) => {
      const p = new URLSearchParams()
      if (params.q) p.set('q', params.q)
      if (params.ontology) p.set('ontology', params.ontology)
      if (params.user_id) p.set('user_id', params.user_id)
      if (params.limit !== undefined) p.set('limit', String(params.limit))
      if (params.offset !== undefined) p.set('offset', String(params.offset))
      return request<{ queries: SavedQuery[]; total: number }>(`/sparql/queries/public?${p}`)
    },

    get: (id: string) =>
      request<SavedQuery>(`/sparql/queries/${id}`),

    update: (id: string, body: Partial<{ name: string; description: string; query_text: string; tags: string[]; is_public: boolean }>) =>
      request<SavedQuery>(`/sparql/queries/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

    delete: (id: string) =>
      request<void>(`/sparql/queries/${id}`, { method: 'DELETE' }),
  },
```

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit
```

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(saved-queries): add SavedQuery type and API client methods"
```

---

### Task 4: QuerySidebar component

**Files:**
- Create: `frontend/src/components/QuerySidebar.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/QuerySidebar.tsx`:

```tsx
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import Yasgui from '@triply/yasgui'
import { useAuth } from '../hooks/useAuth'
import { api, SavedQuery } from '../lib/api'

interface Props {
  yasguiRef: React.RefObject<InstanceType<typeof Yasgui> | null>
}

interface FormState {
  name: string
  description: string
  tags: string[]
  tagInput: string
  is_public: boolean
}

const EMPTY_FORM: FormState = { name: '', description: '', tags: [], tagInput: '', is_public: false }

export default function QuerySidebar({ yasguiRef }: Props) {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [queries, setQueries] = useState<SavedQuery[]>([])
  const [search, setSearch] = useState('')
  const [view, setView] = useState<'list' | 'form'>('list')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [ontologyNames, setOntologyNames] = useState<string[]>([])
  const [showTagSuggestions, setShowTagSuggestions] = useState(false)
  const tagInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!user) return
    api.savedQueries.list().then(r => setQueries(r.queries)).catch(() => {})
  }, [user])

  useEffect(() => {
    api.ontologies.list(0, 200)
      .then(r => setOntologyNames(r.ontologies.map(o => o.shortname).filter(Boolean) as string[]))
      .catch(() => {})
  }, [])

  function loadQuery(sq: SavedQuery) {
    setActiveId(sq.id)
    yasguiRef.current?.getTab()?.getYasqe()?.setValue(sq.query_text)
  }

  function openSaveForm() {
    setForm(EMPTY_FORM)
    setEditingId(null)
    setView('form')
  }

  function openEditForm(sq: SavedQuery, e: React.MouseEvent) {
    e.stopPropagation()
    setForm({ name: sq.name, description: sq.description ?? '', tags: sq.tags, tagInput: '', is_public: sq.is_public })
    setEditingId(sq.id)
    setView('form')
  }

  function cancelForm() {
    setForm(EMPTY_FORM)
    setEditingId(null)
    setView('list')
  }

  async function submitForm(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) return
    setSaving(true)
    try {
      const queryText = editingId
        ? (queries.find(q => q.id === editingId)?.query_text ?? '')
        : (yasguiRef.current?.getTab()?.getYasqe()?.getValue() ?? '')
      const payload = {
        name: form.name.trim(),
        description: form.description || undefined,
        query_text: queryText,
        tags: form.tags,
        is_public: form.is_public,
      }
      if (editingId) {
        const updated = await api.savedQueries.update(editingId, payload)
        setQueries(qs => qs.map(q => q.id === editingId ? updated : q))
      } else {
        const created = await api.savedQueries.create(payload)
        setQueries(qs => [created, ...qs])
      }
      cancelForm()
    } finally {
      setSaving(false)
    }
  }

  async function deleteQuery(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    await api.savedQueries.delete(id)
    setQueries(qs => qs.filter(q => q.id !== id))
    if (activeId === id) setActiveId(null)
  }

  function addTag(tag: string) {
    const t = tag.trim()
    if (t && !form.tags.includes(t)) {
      setForm(f => ({ ...f, tags: [...f.tags, t], tagInput: '' }))
    } else {
      setForm(f => ({ ...f, tagInput: '' }))
    }
    setShowTagSuggestions(false)
  }

  function handleTagKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addTag(form.tagInput)
    } else if (e.key === 'Escape') {
      setShowTagSuggestions(false)
    }
  }

  const filteredQueries = queries.filter(q =>
    q.name.toLowerCase().includes(search.toLowerCase()) ||
    q.tags.some(t => t.toLowerCase().includes(search.toLowerCase()))
  )

  const tagSuggestions = form.tagInput
    ? ontologyNames.filter(n => n.toLowerCase().includes(form.tagInput.toLowerCase()) && !form.tags.includes(n)).slice(0, 6)
    : []

  const base: React.CSSProperties = {
    width: 200,
    flexShrink: 0,
    background: 'var(--bg-secondary)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    fontSize: '0.75rem',
    overflow: 'hidden',
  }

  if (!user) {
    return (
      <div style={{ ...base, alignItems: 'center', justifyContent: 'center', padding: '1rem', textAlign: 'center' }}>
        <span style={{ color: 'var(--text-dim)', fontSize: '0.7rem', lineHeight: 1.5 }}>
          Sign in to save queries
        </span>
      </div>
    )
  }

  return (
    <div style={base}>
      {/* Header */}
      <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.05em' }}>MY QUERIES</span>
        {view === 'list' ? (
          <button
            onClick={openSaveForm}
            style={{ background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 3, padding: '2px 7px', fontSize: '0.65rem', fontWeight: 700, cursor: 'pointer' }}
          >＋ Save</button>
        ) : (
          <span onClick={cancelForm} style={{ color: 'var(--text-dim)', cursor: 'pointer', fontSize: '0.7rem' }}>✕ cancel</span>
        )}
      </div>

      {view === 'list' && (
        <>
          {/* Search */}
          <div style={{ padding: '5px 8px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
            <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 3, padding: '3px 7px', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ color: 'var(--text-dim)', fontSize: '0.7rem' }}>⌕</span>
              <input
                type="text"
                placeholder="Search my queries…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{ background: 'transparent', border: 'none', outline: 'none', color: 'var(--text)', fontSize: '0.7rem', width: '100%' }}
              />
            </div>
          </div>

          {/* List */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filteredQueries.length === 0 && (
              <div style={{ padding: '10px', color: 'var(--text-dim)', fontSize: '0.65rem', textAlign: 'center' }}>
                {search ? 'No matches' : 'No saved queries yet'}
              </div>
            )}
            {filteredQueries.map(q => (
              <div
                key={q.id}
                onClick={() => loadQuery(q)}
                style={{
                  padding: '5px 10px',
                  borderBottom: '1px solid rgba(51,65,85,0.4)',
                  cursor: 'pointer',
                  background: activeId === q.id ? 'rgba(34,197,94,0.08)' : undefined,
                  borderLeft: activeId === q.id ? '2px solid var(--accent)' : '2px solid transparent',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: activeId === q.id ? 'var(--text)' : 'var(--text-muted)', fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                    {q.name}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 3, flexShrink: 0 }}>
                    <span style={{ color: q.is_public ? 'var(--accent-blue)' : 'var(--text-dim)', fontSize: '0.6rem' }}>
                      {q.is_public ? '🔗' : '🔒'}
                    </span>
                    <span
                      onClick={e => openEditForm(q, e)}
                      style={{ color: 'var(--text-dim)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 2px' }}
                    >✎</span>
                    <span
                      onClick={e => deleteQuery(q.id, e)}
                      style={{ color: 'var(--text-dim)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 2px' }}
                    >✕</span>
                  </div>
                </div>
                {q.tags.length > 0 && (
                  <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginTop: 1 }}>
                    {q.tags.slice(0, 3).join(' · ')}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Footer */}
          <div style={{ padding: '6px 10px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
            <span
              onClick={() => navigate('/sparql/gallery')}
              style={{ color: 'var(--accent-blue)', fontSize: '0.65rem', cursor: 'pointer' }}
            >→ Browse Gallery</span>
          </div>
        </>
      )}

      {view === 'form' && (
        <form
          onSubmit={submitForm}
          style={{ flex: 1, overflowY: 'auto', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6, background: 'var(--bg)' }}
        >
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginBottom: 2 }}>Name *</div>
            <input
              required
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--accent)', borderRadius: 3, padding: '3px 6px', color: 'var(--text)', fontSize: '0.7rem', boxSizing: 'border-box' }}
            />
          </div>

          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginBottom: 2 }}>Description</div>
            <textarea
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              rows={2}
              style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 3, padding: '3px 6px', color: 'var(--text)', fontSize: '0.7rem', resize: 'none', boxSizing: 'border-box' }}
            />
          </div>

          <div style={{ position: 'relative' }}>
            <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginBottom: 2 }}>Tags</div>
            <div
              style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 3, padding: '3px 6px', display: 'flex', gap: 3, flexWrap: 'wrap', alignItems: 'center', minHeight: 26, cursor: 'text' }}
              onClick={() => tagInputRef.current?.focus()}
            >
              {form.tags.map(t => (
                <span key={t} style={{ background: 'rgba(103,232,249,0.1)', border: '1px solid rgba(103,232,249,0.3)', color: 'var(--accent-blue)', borderRadius: 3, padding: '1px 4px', fontSize: '0.6rem', display: 'flex', alignItems: 'center', gap: 2 }}>
                  {t}
                  <span
                    onClick={e => { e.stopPropagation(); setForm(f => ({ ...f, tags: f.tags.filter(x => x !== t) })) }}
                    style={{ cursor: 'pointer' }}
                  >✕</span>
                </span>
              ))}
              <input
                ref={tagInputRef}
                value={form.tagInput}
                onChange={e => { setForm(f => ({ ...f, tagInput: e.target.value })); setShowTagSuggestions(true) }}
                onKeyDown={handleTagKeyDown}
                onFocus={() => setShowTagSuggestions(true)}
                onBlur={() => setTimeout(() => setShowTagSuggestions(false), 150)}
                placeholder="+tag…"
                style={{ background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-dim)', fontSize: '0.7rem', minWidth: 40, flex: 1 }}
              />
            </div>
            {showTagSuggestions && tagSuggestions.length > 0 && (
              <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 3, zIndex: 10, maxHeight: 120, overflowY: 'auto' }}>
                {tagSuggestions.map(s => (
                  <div
                    key={s}
                    onMouseDown={() => addTag(s)}
                    style={{ padding: '3px 8px', color: 'var(--text-muted)', fontSize: '0.7rem', cursor: 'pointer' }}
                  >{s}</div>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text-muted)', fontSize: '0.7rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={form.is_public}
                onChange={e => setForm(f => ({ ...f, is_public: e.target.checked }))}
                style={{ accentColor: 'var(--accent)' }}
              />
              Public
            </label>
            <button
              type="submit"
              disabled={!form.name.trim() || saving}
              style={{ background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 3, padding: '2px 8px', fontSize: '0.7rem', fontWeight: 700, cursor: 'pointer', opacity: (!form.name.trim() || saving) ? 0.5 : 1 }}
            >{saving ? '…' : 'Save'}</button>
          </div>
        </form>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compilation**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit
```

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/QuerySidebar.tsx
git commit -m "feat(saved-queries): add QuerySidebar component"
```

---

### Task 5: Update Sparql.tsx

**Files:**
- Modify: `frontend/src/pages/Sparql.tsx`

Replace the full content of `frontend/src/pages/Sparql.tsx`:

- [ ] **Step 1: Rewrite Sparql.tsx**

```tsx
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import Yasgui from '@triply/yasgui'
import '@triply/yasgui/build/yasgui.min.css'
import './Sparql.css'
import QuerySidebar from '../components/QuerySidebar'
import { api } from '../lib/api'

const DEFAULT_QUERY = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

# All triples are stored in named graphs (one per ontology version).
# Use GRAPH ?g { ... } to query across all ontologies, or bind ?g to
# a specific graph IRI to query a single ontology version.

SELECT ?class ?label WHERE {
  GRAPH ?g {
    ?class a owl:Class .
    OPTIONAL { ?class rdfs:label ?label }
  }
}
LIMIT 100`

export default function Sparql() {
  const containerRef = useRef<HTMLDivElement>(null)
  const yasguiRef = useRef<InstanceType<typeof Yasgui> | null>(null)
  const location = useLocation()
  const [queryError, setQueryError] = useState<string | null>(null)

  useEffect(() => {
    if (!containerRef.current || yasguiRef.current) return

    yasguiRef.current = new Yasgui(containerRef.current, {
      persistenceId: null,
      requestConfig: {
        endpoint: '/api/v1/sparql/content',
        method: 'POST',
        acceptHeaderSelect: 'application/sparql-results+json',
        acceptHeaderGraph: 'text/turtle',
      },
      endpointCatalogueOptions: {
        getData: () => [
          { endpoint: '/api/v1/sparql/content', title: 'OntoExplorer — Ontology Content' },
        ],
      },
    })

    const qId = new URLSearchParams(location.search).get('q')
    if (qId) {
      api.savedQueries.get(qId)
        .then(sq => {
          yasguiRef.current?.getTab()?.getYasqe()?.setValue(sq.query_text)
        })
        .catch(() => {
          setQueryError('Query not found or not accessible')
          yasguiRef.current?.getTab()?.getYasqe()?.setValue(DEFAULT_QUERY)
        })
    } else {
      yasguiRef.current.getTab()?.getYasqe()?.setValue(DEFAULT_QUERY)
    }

    return () => {
      if (yasguiRef.current) {
        if (typeof yasguiRef.current.destroy === 'function') {
          yasguiRef.current.destroy()
        } else if (containerRef.current) {
          containerRef.current.innerHTML = ''
        }
        yasguiRef.current = null
      }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{
      height: 'calc(100vh - var(--nav-height))',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      background: 'var(--bg)',
    }}>
      <div style={{
        padding: '0.6rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'baseline',
        gap: '0.75rem',
      }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text)' }}>SPARQL</h1>
        <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
          Query the full ontology graph · read-only · SPARQL 1.1
        </span>
      </div>
      {queryError && (
        <div style={{
          padding: '0.4rem 1.5rem',
          background: 'rgba(239,68,68,0.1)',
          borderBottom: '1px solid rgba(239,68,68,0.3)',
          color: '#f87171',
          fontSize: 'var(--font-size-sm)',
          flexShrink: 0,
        }}>
          {queryError}
        </div>
      )}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'row', overflow: 'hidden', minHeight: 0 }}>
        <QuerySidebar yasguiRef={yasguiRef} />
        <div ref={containerRef} style={{ flex: 1, minHeight: 0 }} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compilation**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit
```

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Sparql.tsx
git commit -m "feat(saved-queries): add sidebar layout and ?q= query loading to Sparql page"
```

---

### Task 6: SparqlGallery page + App.tsx route

**Files:**
- Create: `frontend/src/pages/SparqlGallery.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create SparqlGallery.tsx**

Create `frontend/src/pages/SparqlGallery.tsx`:

```tsx
import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, SavedQuery } from '../lib/api'

const LIMIT = 20

function relativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

export default function SparqlGallery() {
  const navigate = useNavigate()
  const [queries, setQueries] = useState<SavedQuery[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [pageOffset, setPageOffset] = useState(0)
  const [searchInput, setSearchInput] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [ontologyFilter, setOntologyFilter] = useState('')
  const [authorFilter, setAuthorFilter] = useState<{ id: string; name: string } | null>(null)
  const [ontologyOptions, setOntologyOptions] = useState<string[]>([])
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    api.ontologies.list(0, 200)
      .then(r => setOntologyOptions(r.ontologies.map(o => o.shortname).filter(Boolean) as string[]))
      .catch(() => {})
  }, [])

  const fetchQueries = useCallback(async (
    q: string,
    ontology: string,
    userId: string | undefined,
    newOffset: number,
    append: boolean,
  ) => {
    setLoading(true)
    try {
      const r = await api.savedQueries.listPublic({
        q: q || undefined,
        ontology: ontology || undefined,
        user_id: userId,
        limit: LIMIT,
        offset: newOffset,
      })
      setQueries(prev => append ? [...prev, ...r.queries] : r.queries)
      setTotal(r.total)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setPageOffset(0)
    fetchQueries(searchQ, ontologyFilter, authorFilter?.id, 0, false)
  }, [searchQ, ontologyFilter, authorFilter, fetchQueries])

  function handleSearchChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value
    setSearchInput(v)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setSearchQ(v), 300)
  }

  function loadMore() {
    const next = pageOffset + LIMIT
    setPageOffset(next)
    fetchQueries(searchQ, ontologyFilter, authorFilter?.id, next, true)
  }

  // Build unique author list from current result set
  const authorMap = new Map<string, string>()
  queries.forEach(q => {
    if (q.user_display_name) authorMap.set(q.user_id, q.user_display_name)
  })
  const authors = Array.from(authorMap.entries()).map(([id, name]) => ({ id, name }))

  return (
    <div style={{ minHeight: 'calc(100vh - var(--nav-height))', background: 'var(--bg)' }}>
      {/* Header */}
      <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
          <h1 style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text)', margin: 0 }}>Query Gallery</h1>
          <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            {total} public {total === 1 ? 'query' : 'queries'}
          </span>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <input
            type="text"
            placeholder="🔍 Search by name, description, or tag…"
            value={searchInput}
            onChange={handleSearchChange}
            style={{ flex: 1, minWidth: 200, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '0.4rem 0.75rem', color: 'var(--text)', fontSize: 'var(--font-size-sm)', outline: 'none' }}
          />
          <select
            value={ontologyFilter}
            onChange={e => setOntologyFilter(e.target.value)}
            style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '0.4rem 0.75rem', color: ontologyFilter ? 'var(--text)' : 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
          >
            <option value="">Ontology ▾</option>
            {ontologyOptions.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
          <select
            value={authorFilter?.id ?? ''}
            onChange={e => {
              const found = authors.find(a => a.id === e.target.value) ?? null
              setAuthorFilter(found)
            }}
            style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '0.4rem 0.75rem', color: authorFilter ? 'var(--text)' : 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
          >
            <option value="">Author ▾</option>
            {authors.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
      </div>

      {/* Grid */}
      <div style={{ padding: '1rem 1.5rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.75rem' }}>
        {queries.map(q => (
          <div
            key={q.id}
            style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <span style={{ color: 'var(--text)', fontWeight: 600, fontSize: 'var(--font-size-sm)', flex: 1, marginRight: '0.5rem' }}>
                {q.name}
              </span>
              <span
                onClick={() => navigate(`/sparql?q=${q.id}`)}
                style={{ color: 'var(--accent-blue)', fontSize: '0.7rem', cursor: 'pointer', flexShrink: 0 }}
              >Open ↗</span>
            </div>
            {q.description && (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                {q.description}
              </div>
            )}
            {q.tags.length > 0 && (
              <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                {q.tags.map(t => (
                  <span key={t} style={{ background: 'rgba(103,232,249,0.08)', border: '1px solid rgba(103,232,249,0.2)', color: 'var(--accent-blue)', borderRadius: 3, padding: '1px 5px', fontSize: '0.65rem' }}>
                    {t}
                  </span>
                ))}
              </div>
            )}
            <div style={{ color: 'var(--text-dim)', fontSize: '0.65rem' }}>
              {q.user_display_name ?? 'Unknown'} · {relativeDate(q.updated_at)}
            </div>
          </div>
        ))}
        {queries.length === 0 && !loading && (
          <div style={{ gridColumn: '1 / -1', textAlign: 'center', color: 'var(--text-dim)', padding: '3rem 0' }}>
            No public queries found.
          </div>
        )}
      </div>

      {queries.length < total && (
        <div style={{ padding: '1rem 1.5rem', textAlign: 'center' }}>
          <button
            onClick={loadMore}
            disabled={loading}
            style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 4, padding: '0.5rem 1.5rem', fontSize: 'var(--font-size-sm)', cursor: 'pointer' }}
          >{loading ? 'Loading…' : 'Load more'}</button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Register route in App.tsx**

In `frontend/src/App.tsx`, add import after the `Sparql` import:

```typescript
import SparqlGallery from './pages/SparqlGallery'
```

Add route after `<Route path="/sparql" ...>`:

```tsx
<Route path="/sparql/gallery" element={<Shell><SparqlGallery /></Shell>} />
```

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit
```

Expected: No errors

- [ ] **Step 4: Run full test suite**

```bash
cd /home/micheldumontier/code/ontoexplorer
uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All existing tests pass; saved_queries tests pass (7 total new tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SparqlGallery.tsx frontend/src/App.tsx
git commit -m "feat(saved-queries): add SparqlGallery page and register routes"
```

---

## Self-Review

**Spec coverage:**
- ✅ Authenticated save/load/share — Tasks 2, 4, 5
- ✅ Private by default; public toggle — SavedQueryCreate.is_public default False
- ✅ Public gallery at /sparql/gallery — Task 6
- ✅ Searchable by text, filterable by ontology + author — GET /public params
- ✅ Shareable URL /sparql?q=<id> — Task 5 (?q= handling)
- ✅ Unauthenticated: browse gallery + open in editor — gallery no-auth, /sparql?q= no-auth for public
- ✅ Unauthenticated sidebar: "Sign in" placeholder — QuerySidebar !user branch
- ✅ 404 for private queries (not 403) — get_saved_query endpoint
- ✅ Tag combo input with ontology shortname suggestions — QuerySidebar tag section
- ✅ Alembic migration — Task 1

**No placeholders:** All steps contain complete code.

**Type consistency:** `SavedQuery` interface in api.ts matches `_serialize()` dict keys in Python router. `yasguiRef` type `React.RefObject<InstanceType<typeof Yasgui> | null>` matches between Sparql.tsx and QuerySidebar props.
