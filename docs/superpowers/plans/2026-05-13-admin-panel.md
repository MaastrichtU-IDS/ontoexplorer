# Admin Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/admin` page with live service-health cards, per-ontology pipeline status table, and recent-jobs table, auto-refreshing every 10 seconds, protected by an `ADMIN_EMAILS` env-var allowlist.

**Architecture:** New `GET /api/v1/admin/overview` endpoint aggregates Postgres, Redis, MinIO, ELK health + Celery queue depth + per-ontology pipeline state + last 50 jobs in one call. Frontend `AdminPage` uses a `useAdminOverview` React Query hook with `refetchInterval: 10_000`. Access guard: email checked against `ADMIN_EMAILS` on the backend; `is_admin: bool` returned by `/auth/me` to drive the conditional nav link.

**Tech Stack:** FastAPI, SQLAlchemy async, Redis (DB 0 + DB 2), httpx, React, React Query (`@tanstack/react-query`), React Router, TypeScript.

---

## File Map

| File | Action |
|---|---|
| `ontoexplorer/config.py` | Add `admin_emails: str = ""` |
| `ontoexplorer/api/auth.py` | Add `is_admin` to `/auth/me` response |
| `ontoexplorer/api/admin.py` | **New** — `GET /api/v1/admin/overview` |
| `ontoexplorer/main.py` | Register admin router |
| `.env.example` | Add `ADMIN_EMAILS=` entry |
| `tests/integration/test_admin.py` | **New** — access control + response shape tests |
| `frontend/src/lib/api.ts` | Add `UserProfile.is_admin`, `AdminOverview` type, `api.admin.overview()` |
| `frontend/src/hooks/useAdminOverview.ts` | **New** — React Query hook |
| `frontend/src/pages/AdminPage.tsx` | **New** — admin UI (3 sections) |
| `frontend/src/App.tsx` | Add `/admin` route inside `AuthGuard` |
| `frontend/src/components/NavBar.tsx` | Add conditional Admin link |

---

## Task 1: Config + `is_admin` helper + `/auth/me`

**Files:**
- Modify: `ontoexplorer/config.py`
- Modify: `ontoexplorer/api/auth.py`

- [ ] **Step 1: Add `admin_emails` to Settings**

In `ontoexplorer/config.py`, add after the `github_webhook_secret` line:

```python
    # Admin access — comma-separated list of email addresses granted /admin access
    admin_emails: str = ""
```

- [ ] **Step 2: Add `is_admin` helper**

At the bottom of `ontoexplorer/config.py`, before `_settings`:

```python
def is_admin(user) -> bool:
    """Return True if user.email is in the ADMIN_EMAILS allowlist."""
    emails = {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}
    return bool(user.email and user.email.lower() in emails)
```

- [ ] **Step 3: Add `is_admin` to `/auth/me` response**

In `ontoexplorer/api/auth.py`, add the import at the top of the file:

```python
from ontoexplorer.config import get_settings, is_admin
```

Replace the existing `me` endpoint return:

```python
@router.get("/me", summary="Current user profile")
async def me(user: User = Depends(require_auth)):
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat(),
        "is_admin": is_admin(user),
    }
```

- [ ] **Step 4: Add `ADMIN_EMAILS` to `.env.example`**

Append to `.env.example`:

```
# ── Admin panel ───────────────────────────────────────────────────────────────
# Comma-separated email addresses that can access /admin
ADMIN_EMAILS=
```

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/config.py ontoexplorer/api/auth.py .env.example
git commit -m "feat(admin): add admin_emails config + is_admin helper + /auth/me field"
```

---

## Task 2: `GET /api/v1/admin/overview` endpoint

**Files:**
- Create: `ontoexplorer/api/admin.py`
- Modify: `ontoexplorer/main.py`

- [ ] **Step 1: Create `ontoexplorer/api/admin.py`**

```python
"""Admin overview endpoint — aggregates service health, pipeline state, and recent jobs."""
from __future__ import annotations

import asyncio

import httpx
import redis as redis_sync
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings, is_admin
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Job, Ontology, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import require_auth

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _require_admin(user: User = Depends(require_auth)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Service health checks ─────────────────────────────────────────────────────

async def _check_postgres(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def _check_redis() -> str:
    try:
        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        r.ping()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def _check_minio() -> str:
    s = get_settings()
    scheme = "https" if s.minio_secure else "http"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{scheme}://{s.minio_endpoint}/minio/health/live")
        return "ok" if resp.status_code == 200 else f"error: HTTP {resp.status_code}"
    except Exception as exc:
        return f"error: {exc}"


async def _check_elk() -> str:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{get_settings().elk_service_url}/health")
        return "ok" if resp.status_code == 200 else f"error: HTTP {resp.status_code}"
    except Exception as exc:
        return f"error: {exc}"


def _celery_queue_depth() -> int:
    try:
        r = redis_sync.from_url(get_settings().redis_url, decode_responses=True)
        return r.llen("celery")
    except Exception:
        return -1


# ── Ontology pipeline status ──────────────────────────────────────────────────

def _elk_redis() -> redis_sync.Redis:
    """Connect to Redis DB 2 where ELK stores classification results."""
    base = get_settings().redis_url.rsplit("/", 1)[0]
    return redis_sync.from_url(f"{base}/2", decode_responses=True)


def _search_redis() -> redis_sync.Redis:
    return redis_sync.from_url(get_settings().redis_url, decode_responses=True)


async def _reasoning_status(version_id: str) -> str:
    """Return 'ready', 'running', or 'not_started' for a version."""
    # Fast path: check ELK Redis cache (DB 2)
    try:
        elk_r = _elk_redis()
        if elk_r.exists(f"classification:{version_id}"):
            return "ready"
    except Exception:
        pass

    # Slow path: call ELK service for non-ready versions
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{get_settings().elk_service_url}/classify/{version_id}"
            )
        if resp.status_code == 200:
            return "ready"
        if resp.status_code == 409:
            body = resp.text
            return "running" if "in progress" in body.lower() else "not_started"
    except Exception:
        pass
    return "not_started"


# ── Main endpoint ─────────────────────────────────────────────────────────────

@router.get("/overview", summary="Admin system overview")
async def admin_overview(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    # 1. Service health (concurrent)
    postgres_status, redis_status, minio_status, elk_status = await asyncio.gather(
        _check_postgres(db),
        asyncio.to_thread(_check_redis),
        _check_minio(),
        _check_elk(),
    )
    queue_depth = await asyncio.to_thread(_celery_queue_depth)

    # 2. Ontology pipeline — latest version per ontology
    rows = (await db.execute(
        text("""
            SELECT o.id, o.iri, o.shortname,
                   v.id AS version_id, v.triple_count, v.status AS ingestion_status,
                   v.created_at AS version_created_at
            FROM ontologies o
            JOIN versions v ON v.id = (
                SELECT id FROM versions WHERE ontology_id = o.id
                ORDER BY created_at DESC LIMIT 1
            )
            ORDER BY o.shortname NULLS LAST, o.iri
        """)
    )).mappings().all()

    search_r = await asyncio.to_thread(_search_redis)

    async def _onto_entry(row) -> dict:
        vid = row["version_id"]
        indexed = await asyncio.to_thread(
            lambda: bool(search_r.exists(f"search:meta:{vid}"))
        )
        reasoning = await _reasoning_status(vid)
        created = row["version_created_at"]
        return {
            "id": row["id"],
            "iri": row["iri"],
            "shortname": row["shortname"],
            "version_id": vid,
            "triple_count": row["triple_count"],
            "ingestion_status": row["ingestion_status"],
            "indexed": indexed,
            "reasoning_status": reasoning,
            "version_created_at": created.isoformat() if created else None,
        }

    ontologies = await asyncio.gather(*[_onto_entry(r) for r in rows])

    # 3. Recent jobs (last 50, with ontology shortname via join)
    job_rows = (await db.execute(
        text("""
            SELECT j.id, j.type, j.version_id, j.status,
                   j.started_at, j.finished_at, j.error, j.created_at,
                   o.shortname AS ontology_shortname
            FROM jobs j
            JOIN versions v ON v.id = j.version_id
            JOIN ontologies o ON o.id = v.ontology_id
            ORDER BY j.created_at DESC
            LIMIT 50
        """)
    )).mappings().all()

    def _fmt(dt) -> str | None:
        return dt.isoformat() if dt else None

    jobs = [
        {
            "id": r["id"],
            "type": r["type"],
            "version_id": r["version_id"],
            "ontology_shortname": r["ontology_shortname"],
            "status": r["status"],
            "started_at": _fmt(r["started_at"]),
            "finished_at": _fmt(r["finished_at"]),
            "error": r["error"],
        }
        for r in job_rows
    ]

    return {
        "services": {
            "postgres": postgres_status,
            "redis": redis_status,
            "minio": minio_status,
            "elk": elk_status,
            "celery_queue_depth": queue_depth,
        },
        "ontologies": list(ontologies),
        "jobs": jobs,
    }
```

- [ ] **Step 2: Register admin router in `ontoexplorer/main.py`**

Add import after the existing router imports:

```python
from ontoexplorer.api.admin import router as admin_router
```

Add `include_router` call after the `stats_router` line:

```python
    app.include_router(admin_router)
```

- [ ] **Step 3: Verify the app starts**

```bash
docker compose logs api --tail 20
```

Expected: no import errors, `OntoExplorer API ready` in logs.

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/api/admin.py ontoexplorer/main.py
git commit -m "feat(admin): GET /api/v1/admin/overview endpoint"
```

---

## Task 3: Backend tests

**Files:**
- Create: `tests/integration/test_admin.py`

- [ ] **Step 1: Write the tests**

```python
"""Tests for the admin overview endpoint."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.anyio
async def test_admin_overview_requires_auth(client):
    """Unauthenticated request returns 401."""
    resp = await client.get("/api/v1/admin/overview")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_admin_overview_requires_admin_email(client, user_and_key):
    """Authenticated non-admin user returns 403."""
    _, raw_key = user_and_key
    resp = await client.get(
        "/api/v1/admin/overview",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_overview_returns_shape(client, user_and_key, monkeypatch):
    """Admin user gets a response with services/ontologies/jobs keys."""
    user, raw_key = user_and_key

    # Make the user an admin by patching is_admin
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)

    # Patch all external I/O
    with (
        patch("ontoexplorer.api.admin._check_postgres", new=AsyncMock(return_value="ok")),
        patch("ontoexplorer.api.admin._check_redis", return_value="ok"),
        patch("ontoexplorer.api.admin._check_minio", new=AsyncMock(return_value="ok")),
        patch("ontoexplorer.api.admin._check_elk", new=AsyncMock(return_value="ok")),
        patch("ontoexplorer.api.admin._celery_queue_depth", return_value=0),
        patch("ontoexplorer.api.admin._search_redis", return_value=MagicMock(exists=lambda k: False)),
        patch("ontoexplorer.api.admin._elk_redis", return_value=MagicMock(exists=lambda k: False)),
        patch("ontoexplorer.api.admin._reasoning_status", new=AsyncMock(return_value="not_started")),
    ):
        resp = await client.get(
            "/api/v1/admin/overview",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "services" in body
    assert "ontologies" in body
    assert "jobs" in body
    assert "postgres" in body["services"]
    assert "celery_queue_depth" in body["services"]


@pytest.mark.anyio
async def test_is_admin_helper_empty_config():
    """is_admin returns False when ADMIN_EMAILS is empty."""
    from ontoexplorer.config import is_admin
    from unittest.mock import MagicMock

    user = MagicMock()
    user.email = "anyone@example.com"

    with patch("ontoexplorer.config.get_settings") as mock_settings:
        mock_settings.return_value.admin_emails = ""
        assert is_admin(user) is False


@pytest.mark.anyio
async def test_is_admin_helper_matching_email():
    """is_admin returns True when user email is in ADMIN_EMAILS."""
    from ontoexplorer.config import is_admin
    from unittest.mock import MagicMock

    user = MagicMock()
    user.email = "michel@maastrichtuniversity.nl"

    with patch("ontoexplorer.config.get_settings") as mock_settings:
        mock_settings.return_value.admin_emails = "michel@maastrichtuniversity.nl,other@example.com"
        assert is_admin(user) is True


@pytest.mark.anyio
async def test_auth_me_includes_is_admin(client, user_and_key):
    """GET /auth/me returns is_admin field."""
    _, raw_key = user_and_key
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    assert "is_admin" in resp.json()
    assert isinstance(resp.json()["is_admin"], bool)
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/integration/test_admin.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_admin.py
git commit -m "test(admin): access control and response shape tests"
```

---

## Task 4: Frontend types + API client + hook

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/hooks/useAdminOverview.ts`

- [ ] **Step 1: Add `is_admin` to `UserProfile` and add `AdminOverview` types in `api.ts`**

In `frontend/src/lib/api.ts`, update the `UserProfile` interface (currently around line 72):

```typescript
export interface UserProfile {
  id: string
  email: string | null
  display_name: string | null
  created_at: string
  is_admin: boolean
}
```

Add these new types after the existing type definitions (before the `api` object):

```typescript
export interface AdminServiceStatus {
  postgres: string
  redis: string
  minio: string
  elk: string
  celery_queue_depth: number
}

export interface AdminOntologyEntry {
  id: string
  iri: string
  shortname: string | null
  version_id: string
  triple_count: number | null
  ingestion_status: string
  indexed: boolean
  reasoning_status: 'ready' | 'running' | 'not_started'
  version_created_at: string | null
}

export interface AdminJobEntry {
  id: string
  type: string
  version_id: string
  ontology_shortname: string | null
  status: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface AdminOverview {
  services: AdminServiceStatus
  ontologies: AdminOntologyEntry[]
  jobs: AdminJobEntry[]
}
```

- [ ] **Step 2: Add `api.admin.overview()` to the `api` object in `api.ts`**

Add after the `stats` block in the `api` object:

```typescript
  admin: {
    overview: () => request<AdminOverview>('/admin/overview'),
  },
```

- [ ] **Step 3: Create `frontend/src/hooks/useAdminOverview.ts`**

```typescript
import { useQuery } from '@tanstack/react-query'
import { api, AdminOverview } from '../lib/api'

export function useAdminOverview() {
  return useQuery<AdminOverview>({
    queryKey: ['admin', 'overview'],
    queryFn: api.admin.overview,
    refetchInterval: 10_000,
    staleTime: 0,
  })
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/hooks/useAdminOverview.ts
git commit -m "feat(admin): AdminOverview types, api.admin.overview(), useAdminOverview hook"
```

---

## Task 5: `AdminPage` component

**Files:**
- Create: `frontend/src/pages/AdminPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/AdminPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useAdminOverview } from '../hooks/useAdminOverview'
import { AdminOntologyEntry, AdminJobEntry } from '../lib/api'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTriples(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

function fmtAge(iso: string | null): string {
  if (!iso) return '—'
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function fmtDuration(started: string | null, finished: string | null): string {
  if (!started) return '—'
  const end = finished ? new Date(finished).getTime() : Date.now()
  const secs = Math.floor((end - new Date(started).getTime()) / 1000)
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`
}

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusDot({ status, label }: { status: string; label?: string }) {
  const text = label ?? status
  if (status === 'ok' || status === 'ingested' || status === 'done' || status === 'ready') {
    return <span style={{ color: 'var(--accent-green, #3fb950)', fontSize: 11 }}>● {text}</span>
  }
  if (status === 'running') {
    return <span style={{ color: 'var(--accent-blue, #58a6ff)', fontSize: 11 }}>⟳ {text}</span>
  }
  if (status === 'not_started' || status === 'queued' || status === 'pending') {
    return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>— {text}</span>
  }
  if (status === 'failed' || status.startsWith('error')) {
    return <span style={{ color: '#f85149', fontSize: 11 }}>✕ {text}</span>
  }
  return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{text}</span>
}

// ── Section heading ───────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase',
      letterSpacing: '.8px', marginBottom: 6,
    }}>
      {children}
    </div>
  )
}

// ── Service Health ────────────────────────────────────────────────────────────

function ServiceCard({ name, status }: { name: string; status: string | number }) {
  const isOk = status === 'ok'
  const isNum = typeof status === 'number'
  const color = isNum
    ? (status > 0 ? '#f0883e' : 'var(--accent-green, #3fb950)')
    : (isOk ? 'var(--accent-green, #3fb950)' : '#f85149')
  return (
    <div style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 6, padding: '10px 12px', textAlign: 'center', minWidth: 90,
    }}>
      <div style={{ color, fontSize: 11, marginBottom: 3, fontWeight: 500 }}>
        {isNum ? `▶ ${status} queued` : (isOk ? '● ok' : `✕ error`)}
      </div>
      <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
        {name}
      </div>
    </div>
  )
}

// ── Ontology Pipeline ─────────────────────────────────────────────────────────

const REASONING_ORDER: Record<string, number> = { not_started: 0, running: 1, ready: 2 }

function OntologyTable({ rows }: { rows: AdminOntologyEntry[] }) {
  const sorted = [...rows].sort((a, b) =>
    (REASONING_ORDER[a.reasoning_status] ?? 0) - (REASONING_ORDER[b.reasoning_status] ?? 0)
  )
  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
            {['Ontology', 'Triples', 'Ingestion', 'Indexed', 'Reasoning', 'Updated'].map(h => (
              <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Ontology' ? 'left' : 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(row => (
            <tr key={row.version_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                {row.shortname ?? row.iri.split(/[/#]/).pop()}
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
                {fmtTriples(row.triple_count)}
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                <StatusDot status={row.ingestion_status} />
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                <StatusDot status={row.indexed ? 'done' : 'not_started'} label={row.indexed ? 'yes' : 'no'} />
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                <StatusDot status={row.reasoning_status} label={row.reasoning_status.replace('_', ' ')} />
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                {fmtAge(row.version_created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Recent Jobs ───────────────────────────────────────────────────────────────

const JOB_TYPE_COLOR: Record<string, string> = {
  ingest: '#d2a8ff',
  ingestion: '#d2a8ff',
  index: '#79c0ff',
  indexing: '#79c0ff',
  reason: '#56d364',
  reasoning: '#56d364',
}

function JobsTable({ jobs }: { jobs: AdminJobEntry[] }) {
  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
            {['Type', 'Ontology', 'Status', 'Duration', 'Started'].map(h => (
              <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Type' || h === 'Ontology' ? 'left' : 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {jobs.map(job => (
            <tr key={job.id} style={{
              borderBottom: '1px solid rgba(255,255,255,0.04)',
              background: job.status === 'failed' ? 'rgba(248,81,73,0.06)' : undefined,
            }}>
              <td style={{ padding: '6px 10px', color: JOB_TYPE_COLOR[job.type] ?? 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', fontWeight: 600 }}>
                {job.type}
              </td>
              <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                {job.ontology_shortname ?? '—'}
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                <StatusDot status={job.status} />
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
                {fmtDuration(job.started_at, job.finished_at)}
                {job.status === 'running' && <span style={{ color: 'var(--text-dim)' }}>…</span>}
              </td>
              <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                {fmtAge(job.started_at ?? job.started_at)}
              </td>
            </tr>
          ))}
          {jobs.length === 0 && (
            <tr>
              <td colSpan={5} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)' }}>
                No jobs yet
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const navigate = useNavigate()
  const { user, isLoading: authLoading } = useAuth()
  const { data, isLoading, dataUpdatedAt } = useAdminOverview()
  const [secondsAgo, setSecondsAgo] = useState(0)

  // Redirect non-admins after auth resolves
  useEffect(() => {
    if (!authLoading && user && !user.is_admin) {
      navigate('/')
    }
  }, [authLoading, user, navigate])

  // "Last updated Ns ago" counter
  useEffect(() => {
    if (!dataUpdatedAt) return
    const tick = () => setSecondsAgo(Math.floor((Date.now() - dataUpdatedAt) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [dataUpdatedAt])

  if (authLoading || isLoading) {
    return <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>Loading…</div>
  }
  if (!user?.is_admin) return null

  const s = data!.services

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '1.5rem 2rem' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <span style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)' }}>System Admin</span>
        <span style={{
          color: '#3fb950', fontSize: 11,
          background: 'rgba(63,185,80,.1)', border: '1px solid rgba(63,185,80,.25)',
          padding: '1px 8px', borderRadius: 10,
        }}>
          ● live · refreshes every 10s
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
          Last updated {secondsAgo}s ago
        </span>
      </div>

      {/* Service health */}
      <SectionLabel>Service Health</SectionLabel>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 }}>
        <ServiceCard name="Postgres" status={s.postgres} />
        <ServiceCard name="Redis" status={s.redis} />
        <ServiceCard name="MinIO" status={s.minio} />
        <ServiceCard name="ELK" status={s.elk} />
        <ServiceCard name="Queue" status={s.celery_queue_depth} />
      </div>

      {/* Ontology pipeline */}
      <SectionLabel>Ontology Pipeline ({data!.ontologies.length})</SectionLabel>
      <div style={{ marginBottom: 24 }}>
        <OntologyTable rows={data!.ontologies} />
      </div>

      {/* Recent jobs */}
      <SectionLabel>Recent Jobs</SectionLabel>
      <JobsTable jobs={data!.jobs} />

    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/AdminPage.tsx
git commit -m "feat(admin): AdminPage component — health, pipeline, jobs"
```

---

## Task 6: Route + NavBar wiring

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavBar.tsx`

- [ ] **Step 1: Add `/admin` route to `App.tsx`**

In `frontend/src/App.tsx`, add the import:

```typescript
import AdminPage from './pages/AdminPage'
```

Inside the `<Route element={<Shell><AuthGuard /></Shell>}>` block, add after the dashboard routes:

```tsx
<Route path="/admin" element={<AdminPage />} />
```

The full `AuthGuard` block becomes:

```tsx
<Route element={<Shell><AuthGuard /></Shell>}>
  <Route element={<DashboardLayout />}>
    <Route path="/dashboard" element={<Dashboard />} />
    <Route path="/dashboard/keys" element={<ApiKeys />} />
    <Route path="/dashboard/webhooks" element={<Webhooks />} />
    <Route path="/dashboard/stats" element={<Stats />} />
  </Route>
  <Route path="/admin" element={<AdminPage />} />
</Route>
```

- [ ] **Step 2: Add conditional Admin link to `NavBar.tsx`**

In `frontend/src/components/NavBar.tsx`, add the Admin link inside the `isAuthenticated` block, before the user display name. Replace the authenticated section:

```tsx
{isAuthenticated ? (
  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
    {user?.is_admin && (
      <NavLink
        to="/admin"
        style={({ isActive }) => ({
          color: isActive ? '#f0883e' : 'var(--text-dim)',
          fontSize: 'var(--font-size-sm)',
          border: '1px solid',
          borderColor: isActive ? '#f0883e' : 'var(--border)',
          borderRadius: 4,
          padding: '2px 8px',
        })}
      >
        Admin
      </NavLink>
    )}
    <span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
      {user?.display_name}
    </span>
    <button
      onClick={() => logout()}
      style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
    >
      Sign out
    </button>
  </div>
) : (
  <Link to="/login" style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
    Sign in
  </Link>
)}
```

- [ ] **Step 3: Set `ADMIN_EMAILS` in `.env` and test in browser**

Add to `.env`:

```
ADMIN_EMAILS=michel.dumontier@maastrichtuniversity.nl
```

Restart the API container to pick up the new env var:

```bash
docker compose restart api
```

Open `http://localhost:5173/admin` in the browser. Verify:
- Service health cards appear
- Ontology pipeline table shows all 21 ontologies
- Recent jobs table shows the last 50 jobs
- Page auto-refreshes every 10s (watch "Last updated Ns ago" counter reset)
- A non-admin user (or unauthenticated) is redirected to `/`
- The "Admin" link appears in the navbar for the admin user

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest tests/ -v --timeout=60
```

Expected: all tests pass, including the 6 new admin tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/NavBar.tsx
git commit -m "feat(admin): wire /admin route and conditional NavBar link"
```
