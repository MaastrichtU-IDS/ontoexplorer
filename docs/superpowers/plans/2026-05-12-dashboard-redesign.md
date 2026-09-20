# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the `/dashboard` family of pages with a left sidebar layout, a toggleable inline "Add Ontology" form, rich table rows showing version/status/triple-count, and a delete action.

**Architecture:** A new `DashboardLayout` component provides the sidebar and wraps all four `/dashboard/*` routes via React Router's nested `<Outlet />`. The `Dashboard` page is rewritten to use dark-theme CSS variables, fetch version data per row with React Query, and toggle an inline add-form. A new `DELETE /api/v1/ontologies/{id}` backend endpoint hard-deletes an ontology and cascades to its versions.

**Tech Stack:** React 18, React Router v6, @tanstack/react-query v5, FastAPI, SQLAlchemy async, pytest-anyio, @testing-library/react + vitest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `ontoexplorer/api/ontologies.py` | Add `DELETE /{ontology_id}` endpoint; add `triple_count` to `_version_dict` |
| Modify | `tests/integration/test_ontologies.py` | Test for delete endpoint |
| Modify | `frontend/src/lib/api.ts` | Add `api.ontologies.delete(id)`; add `triple_count` to `OntologyVersion` type |
| Create | `frontend/src/components/DashboardLayout.tsx` | Sidebar nav + `<Outlet />` |
| Modify | `frontend/src/App.tsx` | Nest all dashboard routes inside `DashboardLayout` |
| Modify | `frontend/src/pages/Dashboard.tsx` | Full rewrite: dark theme, toggle form, rich rows with versions query + delete |

---

## Task 1: Backend — expose triple_count and add delete endpoint

**Files:**
- Modify: `ontoexplorer/api/ontologies.py` (lines ~1461–1475 for `_version_dict`; add new route after line ~1454)
- Modify: `tests/integration/test_ontologies.py`

- [ ] **Step 1: Write the failing backend test**

Add to `tests/integration/test_ontologies.py`:

```python
@pytest.mark.anyio
async def test_delete_ontology(client, user_and_key, db_session):
    """DELETE /api/v1/ontologies/{id} removes the ontology and returns 204."""
    from ontoexplorer.models.db import Ontology
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    # Create an ontology directly in the DB
    ont = Ontology(iri="http://example.org/to-delete.owl")
    db_session.add(ont)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/ontologies/{ont.id}", headers=auth)
    assert resp.status_code == 204

    # Confirm it's gone
    resp2 = await client.get(f"/api/v1/ontologies/{ont.id}", headers=auth)
    assert resp2.status_code == 404


@pytest.mark.anyio
async def test_delete_ontology_not_found(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    resp = await client.delete("/api/v1/ontologies/does-not-exist", headers=auth)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_versions_include_triple_count(client, user_and_key, db_session):
    """GET /api/v1/ontologies/{id}/versions includes triple_count field."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    ont = Ontology(iri="http://example.org/triple-count.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key.ttl",
        sha256="abc123",
        format="turtle",
        status="ready",
        triple_count=42000,
    )
    db_session.add(ver)
    await db_session.commit()

    resp = await client.get(f"/api/v1/ontologies/{ont.id}/versions", headers=auth)
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    assert versions[0]["triple_count"] == 42000
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /path/to/ontoexplorer
docker compose exec api pytest tests/integration/test_ontologies.py::test_delete_ontology tests/integration/test_ontologies.py::test_delete_ontology_not_found tests/integration/test_ontologies.py::test_versions_include_triple_count -v
```

Expected: 3 FAILures (endpoints don't exist yet, `triple_count` not in response).

- [ ] **Step 3: Add `triple_count` to `_version_dict` and the new delete route**

In `ontoexplorer/api/ontologies.py`, update `_version_dict` at line ~1465:

```python
def _version_dict(v: OntologyVersion) -> dict:
    return {
        "id": v.id,
        "ontology_id": v.ontology_id,
        "version_iri": v.version_iri,
        "format": v.format,
        "status": v.status,
        "sha256": v.sha256,
        "triple_count": v.triple_count,
        "download_url": f"/api/v1/ontologies/{v.ontology_id}/{v.id}/download",
        "created_at": v.created_at.isoformat(),
    }
```

Then add the delete route after the existing `@router.delete("/{ontology_id}/{version_id}", ...)` block (around line ~1454). Add before `_ontology_dict`:

```python
@router.delete("/{ontology_id}", summary="Delete an ontology and all its versions")
async def delete_ontology(
    ontology_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    ontology = await _get_ontology_or_404(db, ontology_id)
    await db.delete(ontology)
    await db.commit()
    return Response(status_code=204)
```

> **Note:** FastAPI matches routes in order. The `/{ontology_id}/{version_id}` DELETE route is defined first, so there is no ambiguity. The new `/{ontology_id}` DELETE route only fires when there is no second path segment.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
docker compose exec api pytest tests/integration/test_ontologies.py::test_delete_ontology tests/integration/test_ontologies.py::test_delete_ontology_not_found tests/integration/test_ontologies.py::test_versions_include_triple_count -v
```

Expected: 3 PASSes.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/ontologies.py tests/integration/test_ontologies.py
git commit -m "feat(api): add DELETE /ontologies/{id} and expose triple_count in versions"
```

---

## Task 2: Frontend — api client additions

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add `triple_count` to the `OntologyVersion` interface**

In `frontend/src/lib/api.ts`, update the `OntologyVersion` interface (around line 85):

```typescript
export interface OntologyVersion {
  id: string
  ontology_id: string
  version_iri: string | null
  format: string
  status: string
  sha256: string
  triple_count: number | null
  download_url: string
  created_at: string
}
```

- [ ] **Step 2: Add `api.ontologies.delete`**

In the `ontologies` block of `api` (after `submitFile`, around line 421):

```typescript
    delete: (id: string) =>
      request<void>(`/ontologies/${id}`, { method: 'DELETE' }),
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /path/to/ontoexplorer/frontend
npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): add ontologies.delete and triple_count to OntologyVersion type"
```

---

## Task 3: DashboardLayout component

**Files:**
- Create: `frontend/src/components/DashboardLayout.tsx`

- [ ] **Step 1: Write a test for DashboardLayout**

Create `frontend/src/components/DashboardLayout.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DashboardLayout from './DashboardLayout'

function wrap(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<DashboardLayout />}>
            <Route path="/dashboard" element={<div>Ontologies page</div>} />
            <Route path="/dashboard/keys" element={<div>Keys page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders sidebar nav links', () => {
  wrap('/dashboard')
  expect(screen.getByText('Ontologies')).toBeInTheDocument()
  expect(screen.getByText('API Keys')).toBeInTheDocument()
  expect(screen.getByText('Webhooks')).toBeInTheDocument()
  expect(screen.getByText('Stats')).toBeInTheDocument()
})

test('renders child route via Outlet', () => {
  wrap('/dashboard')
  expect(screen.getByText('Ontologies page')).toBeInTheDocument()
})

test('renders correct child on /dashboard/keys', () => {
  wrap('/dashboard/keys')
  expect(screen.getByText('Keys page')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /path/to/ontoexplorer/frontend
npx vitest run src/components/DashboardLayout.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create DashboardLayout**

Create `frontend/src/components/DashboardLayout.tsx`:

```typescript
import { NavLink, Outlet } from 'react-router-dom'

const sidebarLinks = [
  { to: '/dashboard', label: 'Ontologies', end: true },
  { to: '/dashboard/keys', label: 'API Keys', end: false },
  { to: '/dashboard/webhooks', label: 'Webhooks', end: false },
  { to: '/dashboard/stats', label: 'Stats', end: false },
]

export default function DashboardLayout() {
  return (
    <div style={{ display: 'flex', minHeight: 'calc(100vh - var(--nav-height))' }}>
      <aside style={{
        width: 140,
        borderRight: '1px solid var(--border)',
        padding: '1.5rem 0',
        flexShrink: 0,
      }}>
        <p style={{
          padding: '0 1rem',
          marginBottom: '0.75rem',
          fontSize: 'var(--font-size-sm)',
          color: 'var(--text-dim)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}>
          Dashboard
        </p>
        <nav style={{ display: 'flex', flexDirection: 'column' }}>
          {sidebarLinks.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              style={({ isActive }) => ({
                padding: '0.4rem 1rem',
                fontSize: 'var(--font-size-base)',
                color: isActive ? 'var(--accent)' : 'var(--text-muted)',
                background: isActive ? 'var(--bg-secondary)' : 'transparent',
                textDecoration: 'none',
                borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              })}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main style={{ flex: 1, padding: '1.5rem 2rem', minWidth: 0 }}>
        <Outlet />
      </main>
    </div>
  )
}
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
npx vitest run src/components/DashboardLayout.test.tsx
```

Expected: 3 PASSes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DashboardLayout.tsx frontend/src/components/DashboardLayout.test.tsx
git commit -m "feat(ui): add DashboardLayout sidebar component"
```

---

## Task 4: Wire DashboardLayout into App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update App.tsx**

Replace the dashboard routes block in `frontend/src/App.tsx`. The full file becomes:

```typescript
import { Route, Routes } from 'react-router-dom'
import NavBar from './components/NavBar'
import AuthGuard from './components/AuthGuard'
import DashboardLayout from './components/DashboardLayout'
import Home from './pages/Home'
import Search from './pages/Search'
import Ontologies from './pages/Ontologies'
import Dashboard from './pages/Dashboard'
import ApiKeys from './pages/ApiKeys'
import Webhooks from './pages/Webhooks'
import Stats from './pages/Stats'
import OntologyPage from './pages/OntologyPage'
import Login from './pages/Login'
import AuthCallback from './pages/AuthCallback'

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ paddingTop: 'var(--nav-height)', minHeight: '100vh' }}>
      <NavBar />
      {children}
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Shell><Home /></Shell>} />
      <Route path="/ontologies" element={<Shell><Ontologies /></Shell>} />
      <Route path="/ontologies/:slug" element={<Shell><OntologyPage /></Shell>} />
      <Route path="/ontologies/:slug/:version" element={<Shell><OntologyPage /></Shell>} />
      <Route path="/search" element={<Shell><Search /></Shell>} />
      <Route path="/login" element={<Shell><Login /></Shell>} />
      <Route path="/auth/:provider/callback" element={<AuthCallback />} />
      <Route element={<Shell><AuthGuard /></Shell>}>
        <Route element={<DashboardLayout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/dashboard/keys" element={<ApiKeys />} />
          <Route path="/dashboard/webhooks" element={<Webhooks />} />
          <Route path="/dashboard/stats" element={<Stats />} />
        </Route>
      </Route>
    </Routes>
  )
}
```

- [ ] **Step 2: Verify the dev server still starts**

```bash
cd /path/to/ontoexplorer/frontend
npm run build 2>&1 | tail -10
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(ui): nest dashboard routes inside DashboardLayout"
```

---

## Task 5: Rewrite Dashboard.tsx

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

This is the main visual task. The page fetches the ontology list, then fetches versions per row (using React Query's per-item queries), and renders rich rows with an inline delete confirmation.

- [ ] **Step 1: Write the test**

Create `frontend/src/pages/Dashboard.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Dashboard from './Dashboard'

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      list: vi.fn().mockResolvedValue({
        ontologies: [
          { id: 'ont1', iri: 'http://example.org/go.owl', created_at: '2026-05-10T00:00:00Z' },
          { id: 'ont2', iri: 'http://example.org/chebi.owl', created_at: '2026-05-08T00:00:00Z' },
        ],
        offset: 0,
        limit: 50,
      }),
      versions: vi.fn().mockResolvedValue({
        versions: [
          { id: 'v1', ontology_id: 'ont1', version_iri: 'http://example.org/go/2024', format: 'owl',
            status: 'ready', sha256: 'abc', triple_count: 1200000, download_url: '/dl', created_at: '2026-05-10T00:00:00Z' },
        ],
      }),
      submitByIri: vi.fn(),
      submitByUrl: vi.fn(),
      delete: vi.fn().mockResolvedValue(undefined),
    },
  },
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders heading', () => {
  wrap()
  expect(screen.getByText('My Ontologies')).toBeInTheDocument()
})

test('shows add form when button is clicked', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  expect(screen.getByPlaceholderText(/purl.obolibrary/)).toBeInTheDocument()
})

test('hides add form when cancel is clicked', async () => {
  wrap()
  fireEvent.click(screen.getByText('+ Add Ontology'))
  fireEvent.click(screen.getByText('× Cancel'))
  expect(screen.queryByPlaceholderText(/purl.obolibrary/)).not.toBeInTheDocument()
})

test('renders ontology rows', async () => {
  wrap()
  await waitFor(() => expect(screen.getByText('http://example.org/go.owl')).toBeInTheDocument())
  expect(screen.getByText('http://example.org/chebi.owl')).toBeInTheDocument()
})

test('shows confirm delete UI on delete button click', async () => {
  wrap()
  await waitFor(() => screen.getByText('http://example.org/go.owl'))
  const deleteButtons = screen.getAllByText('delete')
  fireEvent.click(deleteButtons[0])
  expect(screen.getByText('confirm?')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd /path/to/ontoexplorer/frontend
npx vitest run src/pages/Dashboard.test.tsx
```

Expected: multiple FAILures.

- [ ] **Step 3: Rewrite Dashboard.tsx**

Replace `frontend/src/pages/Dashboard.tsx` entirely:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Ontology, type OntologyVersion } from '../lib/api'

// ── Status dot ────────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  ready:      'var(--accent)',
  ingested:   'var(--text-muted)',
  reasoning:  'var(--accent-purple)',
  indexing:   'var(--accent-purple)',
  deprecated: 'var(--text-dim)',
  failed:     '#f87171',
}

function StatusDot({ status }: { status: string }) {
  return (
    <span style={{ color: STATUS_COLOR[status] ?? 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
      ● {status}
    </span>
  )
}

// ── Format triple count ───────────────────────────────────────────────────────

function fmtCount(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
  return String(n)
}

// ── Single ontology row ───────────────────────────────────────────────────────

function OntologyRow({ ontology, onDeleted }: { ontology: Ontology; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const qc = useQueryClient()

  const { data: versionsData } = useQuery({
    queryKey: ['versions', ontology.id],
    queryFn: () => api.ontologies.versions(ontology.id),
  })

  const latest: OntologyVersion | undefined = versionsData?.versions[0]

  const del = useMutation({
    mutationFn: () => api.ontologies.delete(ontology.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ontologies'] })
      onDeleted()
    },
  })

  const shortVersion = latest?.version_iri
    ? latest.version_iri.replace(/.*[/#]/, '')
    : '—'

  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      {/* IRI + date */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top' }}>
        <Link
          to={`/ontologies/${ontology.id}`}
          style={{ color: 'var(--accent-blue)', fontSize: 'var(--font-size-base)', display: 'block' }}
        >
          {ontology.iri}
        </Link>
        <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          added {new Date(ontology.created_at).toLocaleDateString()}
          {latest?.triple_count != null && ` · ${fmtCount(latest.triple_count)} triples`}
        </span>
      </td>

      {/* Version */}
      <td style={{ padding: '0.6rem 1rem', color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
        {shortVersion}
      </td>

      {/* Status */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
        {latest ? <StatusDot status={latest.status} /> : <span style={{ color: 'var(--text-dim)' }}>—</span>}
      </td>

      {/* Actions */}
      <td style={{ padding: '0.6rem 1rem', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
        <Link
          to={`/ontologies/${ontology.id}`}
          style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginRight: '0.75rem' }}
        >
          view
        </Link>
        {confirming ? (
          <span style={{ fontSize: 'var(--font-size-sm)' }}>
            <span style={{ color: 'var(--text-muted)', marginRight: '0.25rem' }}>confirm?</span>
            <button
              onClick={() => del.mutate()}
              disabled={del.isPending}
              style={{ color: '#f87171', marginRight: '0.35rem', fontSize: 'var(--font-size-sm)' }}
            >
              yes
            </button>
            <button
              onClick={() => setConfirming(false)}
              style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
            >
              no
            </button>
          </span>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
          >
            delete
          </button>
        )}
      </td>
    </tr>
  )
}

// ── Add-ontology inline form ──────────────────────────────────────────────────

type AddTab = 'iri' | 'url' | 'paste'

function AddOntologyForm({ onSuccess }: { onSuccess: () => void }) {
  const [tab, setTab] = useState<AddTab>('iri')
  const [value, setValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      const result = tab === 'iri'
        ? await api.ontologies.submitByIri(value)
        : await api.ontologies.submitByUrl(value)
      setMessage(`Queued — task ID: ${result.task_id}`)
      setValue('')
      setTimeout(onSuccess, 2000)
    } catch (err: unknown) {
      setMessage(`Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const tabs: { key: AddTab; label: string }[] = [
    { key: 'iri', label: 'By IRI' },
    { key: 'url', label: 'By URL' },
    { key: 'paste', label: 'Upload / Paste' },
  ]

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      padding: '1rem',
      marginBottom: '1.25rem',
    }}>
      {/* Tabs */}
      <div style={{ display: 'flex', gap: '0.375rem', marginBottom: '0.75rem' }}>
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{
              padding: '0.25rem 0.6rem',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border)',
              background: tab === key ? 'var(--accent)' : 'transparent',
              color: tab === key ? '#0f172a' : 'var(--text-muted)',
              fontWeight: tab === key ? 700 : 400,
              fontSize: 'var(--font-size-sm)',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'paste' ? (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          File upload is available via the REST API: <code>POST /api/v1/ontologies</code> with multipart form data.
        </p>
      ) : (
        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder={tab === 'iri' ? 'https://purl.obolibrary.org/obo/go.owl' : 'https://example.com/ontology.ttl'}
            style={{ flex: 1 }}
            required
          />
          <button
            type="submit"
            disabled={submitting}
            style={{
              padding: '0.4rem 0.9rem',
              background: 'var(--accent)',
              color: '#0f172a',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 700,
              fontSize: 'var(--font-size-sm)',
            }}
          >
            {submitting ? 'Adding…' : 'Add'}
          </button>
        </form>
      )}

      {message && (
        <p style={{
          marginTop: '0.5rem',
          fontSize: 'var(--font-size-sm)',
          color: message.startsWith('Error') ? '#f87171' : 'var(--accent)',
        }}>
          {message}
        </p>
      )}
    </div>
  )
}

// ── Dashboard page ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [showForm, setShowForm] = useState(false)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['ontologies'],
    queryFn: () => api.ontologies.list(),
  })

  function handleAdded() {
    qc.invalidateQueries({ queryKey: ['ontologies'] })
    setShowForm(false)
  }

  const ontologies = data?.ontologies ?? []

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>My Ontologies</h1>
        <button
          onClick={() => setShowForm(v => !v)}
          style={{
            padding: '0.35rem 0.8rem',
            background: showForm ? 'var(--bg-secondary)' : 'var(--accent)',
            color: showForm ? 'var(--text-muted)' : '#0f172a',
            border: showForm ? '1px solid var(--border)' : 'none',
            borderRadius: 'var(--radius-sm)',
            fontWeight: 600,
            fontSize: 'var(--font-size-sm)',
          }}
        >
          {showForm ? '× Cancel' : '+ Add Ontology'}
        </button>
      </div>

      {/* Inline add form */}
      {showForm && <AddOntologyForm onSuccess={handleAdded} />}

      {/* Table */}
      {isLoading ? (
        <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
          <thead>
            <tr style={{ background: 'var(--bg-secondary)' }}>
              {['Ontology', 'Version', 'Status', ''].map(h => (
                <th
                  key={h}
                  style={{
                    padding: '0.5rem 1rem',
                    textAlign: 'left',
                    fontSize: 'var(--font-size-sm)',
                    fontWeight: 600,
                    color: 'var(--text-dim)',
                    borderBottom: '1px solid var(--border)',
                    letterSpacing: '0.05em',
                    textTransform: 'uppercase',
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ontologies.map(o => (
              <OntologyRow key={o.id} ontology={o} onDeleted={() => {}} />
            ))}
            {ontologies.length === 0 && (
              <tr>
                <td
                  colSpan={4}
                  style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
                >
                  No ontologies yet. Use "+ Add Ontology" above to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run the tests**

```bash
cd /path/to/ontoexplorer/frontend
npx vitest run src/pages/Dashboard.test.tsx
```

Expected: all PASSes.

- [ ] **Step 5: Run the full frontend test suite**

```bash
npx vitest run
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Dashboard.test.tsx
git commit -m "feat(ui): redesign dashboard — sidebar layout, rich table rows, inline add/delete"
```

---

## Task 6: Visual verification

- [ ] **Step 1: Start the frontend dev server if not running**

```bash
cd /path/to/ontoexplorer/frontend
npm run dev
```

Open `http://localhost:5173/dashboard` in a browser.

- [ ] **Step 2: Verify sidebar appears**

Confirm the left sidebar shows "DASHBOARD" label with Ontologies, API Keys, Webhooks, Stats links. Active link is green with a left border accent.

- [ ] **Step 3: Verify "+ Add Ontology" toggle**

Click "+ Add Ontology" — inline form should slide in with By IRI / By URL / Upload tabs. Click "× Cancel" — form disappears.

- [ ] **Step 4: Verify table rows**

Confirm rows show: IRI as a cyan link + "added {date}" secondary text; version label; status dot; view link and delete button. Delete click shows "confirm? yes no" inline.

- [ ] **Step 5: Verify sidebar navigation**

Click "API Keys", "Webhooks", "Stats" in the sidebar — confirm they navigate to the correct sub-pages and the sidebar stays visible.
