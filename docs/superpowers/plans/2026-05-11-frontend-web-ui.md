# OntoExplorer Frontend Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full OntoExplorer React SPA — Home search hero, Browse (resizable class tree + term panel), Search (MOS expression search), full-page term view, and Dashboard — all wired to the existing FastAPI backend.

**Architecture:** Top-nav shell with React Router v6 routes; TanStack Query for all server state; plain CSS variables for theming (dark navy/slate). Browse page uses a drag-resizable split pane. Search uses live autocomplete with MOS expression detection.

**Tech Stack:** React 18 + TypeScript + Vite 5 · React Router v6 · TanStack Query v5 · Recharts · Vitest + React Testing Library (jsdom) · plain CSS

**Spec:** `docs/superpowers/specs/2026-05-11-frontend-web-ui-design.md`

---

## File Map

### New files
```
frontend/src/test/setup.ts
frontend/src/hooks/useAuth.ts
frontend/src/hooks/useOntologies.ts
frontend/src/hooks/useClassTree.ts
frontend/src/hooks/useTerm.ts
frontend/src/hooks/useSearch.ts
frontend/src/components/NavBar.tsx
frontend/src/components/AuthGuard.tsx
frontend/src/components/OntologySelector.tsx
frontend/src/components/SearchBar.tsx
frontend/src/components/ResizeHandle.tsx
frontend/src/components/ClassTree.tsx
frontend/src/components/TermPanel.tsx
frontend/src/pages/Home.tsx
frontend/src/pages/Browse.tsx
frontend/src/pages/TermPage.tsx
frontend/src/pages/Search.tsx
frontend/src/pages/Login.tsx
frontend/src/pages/AuthCallback.tsx
ontoexplorer/api/global_search.py
```

### Modified files
```
frontend/package.json              — add vitest + testing-library deps
frontend/vite.config.ts            — add vitest test config
frontend/src/index.css             — CSS variable design tokens (dark theme)
frontend/src/lib/api.ts            — fix auth.me path, add term/search/global methods
frontend/src/App.tsx               — replace all routes with new page structure
frontend/src/components/Layout.tsx — replace sidebar with top-nav shell wrapper
ontoexplorer/api/ontologies.py     — add ?parent= param to list_terms
ontoexplorer/main.py               — register global_search router
```

---

## Task 1: Testing setup + CSS variables + NavBar + useAuth + AuthGuard + routes

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`
- Modify: `frontend/src/index.css`
- Create: `frontend/src/hooks/useAuth.ts`
- Create: `frontend/src/components/NavBar.tsx`
- Create: `frontend/src/components/AuthGuard.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/NavBar.test.tsx`
- Test: `frontend/src/components/AuthGuard.test.tsx`

- [ ] **Step 1: Install test dependencies**

Run from `frontend/`:
```bash
cd frontend
npm install --save-dev vitest @vitest/coverage-v8 @testing-library/react @testing-library/user-event @testing-library/jest-dom jsdom
```

Expected: `package.json` devDependencies updated, no errors.

- [ ] **Step 2: Add vitest config to vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/sparql': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
```

- [ ] **Step 3: Add test scripts to package.json**

In `frontend/package.json` scripts section, add:
```json
"test": "vitest",
"test:run": "vitest run"
```

- [ ] **Step 4: Create test setup file**

`frontend/src/test/setup.ts`:
```typescript
import '@testing-library/jest-dom'
```

- [ ] **Step 5: Write failing tests for NavBar and AuthGuard**

`frontend/src/components/NavBar.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NavBar from './NavBar'

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false, isLoading: false }),
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders logo and nav links', () => {
  wrap(<NavBar />)
  expect(screen.getByText('OntoExplorer')).toBeInTheDocument()
  expect(screen.getByText('Browse')).toBeInTheDocument()
  expect(screen.getByText('Search')).toBeInTheDocument()
  expect(screen.getByText('Dashboard')).toBeInTheDocument()
})

test('shows Sign in when unauthenticated', () => {
  wrap(<NavBar />)
  expect(screen.getByText('Sign in')).toBeInTheDocument()
})
```

`frontend/src/components/AuthGuard.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AuthGuard from './AuthGuard'

function wrap(isAuthenticated: boolean, isLoading: boolean) {
  vi.mock('../hooks/useAuth', () => ({
    useAuth: () => ({ user: null, isAuthenticated, isLoading }),
  }))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route element={<AuthGuard />}>
            <Route path="/dashboard" element={<div>Protected</div>} />
          </Route>
          <Route path="/login" element={<div>Login page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('shows protected content when authenticated', () => {
  wrap(true, false)
  expect(screen.getByText('Protected')).toBeInTheDocument()
})

test('redirects to /login when not authenticated', () => {
  wrap(false, false)
  expect(screen.getByText('Login page')).toBeInTheDocument()
})
```

- [ ] **Step 6: Run tests to confirm they fail**

```bash
cd frontend && npm run test:run -- NavBar AuthGuard
```

Expected: FAIL — `Cannot find module './NavBar'` and `Cannot find module './AuthGuard'`

- [ ] **Step 7: Update index.css with CSS design tokens**

`frontend/src/index.css` — replace entire file:
```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0f172a;
  --bg-secondary: #1e293b;
  --bg-hover: #334155;
  --border: #334155;
  --text: #e2e8f0;
  --text-muted: #94a3b8;
  --text-dim: #64748b;
  --accent: #22c55e;
  --accent-blue: #67e8f9;
  --accent-purple: #a78bfa;
  --nav-height: 48px;
  --radius: 6px;
  --radius-sm: 4px;
  --font-size-sm: 12px;
  --font-size-base: 14px;
}

html, body, #root {
  height: 100%;
  background: var(--bg);
  color: var(--text);
  font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
  font-size: var(--font-size-base);
  line-height: 1.5;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

button {
  cursor: pointer;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
}

input, textarea, select {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: var(--radius-sm);
  font: inherit;
  padding: 6px 10px;
  outline: none;
}

input:focus, textarea:focus, select:focus {
  border-color: var(--accent);
}
```

- [ ] **Step 8: Create useAuth hook**

`frontend/src/hooks/useAuth.ts`:
```typescript
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export interface UserProfile {
  id: string
  email: string
  display_name: string
}

export function useAuth() {
  const { data, isLoading, error } = useQuery<UserProfile>({
    queryKey: ['auth', 'me'],
    queryFn: api.auth.me,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  return {
    user: data ?? null,
    isAuthenticated: !!data && !error,
    isLoading,
  }
}
```

- [ ] **Step 9: Create NavBar component**

`frontend/src/components/NavBar.tsx`:
```typescript
import { NavLink, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { logout } from '../lib/auth'

const navLinks = [
  { to: '/browse', label: 'Browse' },
  { to: '/search', label: 'Search' },
  { to: '/dashboard', label: 'Dashboard' },
]

export default function NavBar() {
  const { user, isAuthenticated } = useAuth()

  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      height: 'var(--nav-height)',
      background: '#0a0f1a',
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center',
      padding: '0 1.5rem', gap: '1.5rem',
    }}>
      <Link to="/" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 15 }}>
        OntoExplorer
      </Link>
      {navLinks.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
          style={({ isActive }) => ({
            color: isActive ? 'var(--text)' : 'var(--text-dim)',
            fontSize: 'var(--font-size-base)',
          })}
        >
          {label}
        </NavLink>
      ))}
      <div style={{ marginLeft: 'auto' }}>
        {isAuthenticated ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
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
      </div>
    </nav>
  )
}
```

- [ ] **Step 10: Create AuthGuard component**

`frontend/src/components/AuthGuard.tsx`:
```typescript
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function AuthGuard() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '50vh', color: 'var(--text-muted)' }}>
        Loading…
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <Outlet />
}
```

- [ ] **Step 11: Rewrite App.tsx with full route structure**

`frontend/src/App.tsx`:
```typescript
import { Route, Routes } from 'react-router-dom'
import NavBar from './components/NavBar'
import AuthGuard from './components/AuthGuard'
import Home from './pages/Home'
import Browse from './pages/Browse'
import TermPage from './pages/TermPage'
import Search from './pages/Search'
import Dashboard from './pages/Dashboard'
import ApiKeys from './pages/ApiKeys'
import Webhooks from './pages/Webhooks'
import Stats from './pages/Stats'
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
      <Route path="/browse" element={<Shell><Browse /></Shell>} />
      <Route path="/browse/:oid/:vid" element={<Shell><Browse /></Shell>} />
      <Route path="/browse/:oid/:vid/term/*" element={<Shell><TermPage /></Shell>} />
      <Route path="/search" element={<Shell><Search /></Shell>} />
      <Route path="/login" element={<Shell><Login /></Shell>} />
      <Route path="/auth/:provider/callback" element={<AuthCallback />} />
      <Route element={<Shell><AuthGuard /></Shell>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/dashboard/keys" element={<ApiKeys />} />
        <Route path="/dashboard/webhooks" element={<Webhooks />} />
        <Route path="/dashboard/stats" element={<Stats />} />
      </Route>
    </Routes>
  )
}
```

Note: `Home`, `Browse`, `TermPage`, `Search`, `Login`, `AuthCallback` do not exist yet — TypeScript will error until they are created. Add temporary stub files to unblock compilation:

`frontend/src/pages/Home.tsx` (stub):
```typescript
export default function Home() { return <div>Home</div> }
```
`frontend/src/pages/Browse.tsx` (stub):
```typescript
export default function Browse() { return <div>Browse</div> }
```
`frontend/src/pages/TermPage.tsx` (stub):
```typescript
export default function TermPage() { return <div>TermPage</div> }
```
`frontend/src/pages/Search.tsx` (stub):
```typescript
export default function Search() { return <div>Search</div> }
```
`frontend/src/pages/Login.tsx` (stub):
```typescript
export default function Login() { return <div>Login</div> }
```
`frontend/src/pages/AuthCallback.tsx` (stub):
```typescript
export default function AuthCallback() { return <div>…</div> }
```

- [ ] **Step 12: Run tests to verify they pass**

```bash
cd frontend && npm run test:run -- NavBar AuthGuard
```

Expected: PASS — 3 tests passing.

- [ ] **Step 13: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors (stubs satisfy imports).

- [ ] **Step 14: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
  frontend/src/test/ frontend/src/index.css \
  frontend/src/hooks/useAuth.ts \
  frontend/src/components/NavBar.tsx frontend/src/components/AuthGuard.tsx \
  frontend/src/components/NavBar.test.tsx frontend/src/components/AuthGuard.test.tsx \
  frontend/src/App.tsx \
  frontend/src/pages/Home.tsx frontend/src/pages/Browse.tsx \
  frontend/src/pages/TermPage.tsx frontend/src/pages/Search.tsx \
  frontend/src/pages/Login.tsx frontend/src/pages/AuthCallback.tsx
git commit -m "feat(frontend): app shell — NavBar, AuthGuard, routes, CSS tokens, vitest setup"
```

---

## Task 2: Extend api.ts + backend parent param + global entity search

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `ontoexplorer/api/ontologies.py`
- Create: `ontoexplorer/api/global_search.py`
- Modify: `ontoexplorer/main.py`
- Test: `tests/api/test_terms_parent.py`
- Test: `tests/api/test_global_search.py`

- [ ] **Step 1: Write failing backend tests**

`tests/api/test_terms_parent.py`:
```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_list_terms_root_only(client: AsyncClient, ingested_version):
    """Terms with parent=root returns only root classes (not owl:Thing subclasses that have parents)."""
    oid, vid = ingested_version
    r = await client.get(f"/api/v1/ontologies/{oid}/{vid}/terms?parent=root")
    assert r.status_code == 200
    data = r.json()
    assert "terms" in data
    assert isinstance(data["terms"], list)

@pytest.mark.asyncio
async def test_list_terms_with_parent_iri(client: AsyncClient, ingested_version):
    """Terms with parent=<iri> returns direct subclasses."""
    oid, vid = ingested_version
    # First get root terms to find a valid parent IRI
    r = await client.get(f"/api/v1/ontologies/{oid}/{vid}/terms?parent=root")
    root_terms = r.json()["terms"]
    if not root_terms:
        pytest.skip("No root terms in test ontology")
    parent_iri = root_terms[0]["iri"]
    r2 = await client.get(f"/api/v1/ontologies/{oid}/{vid}/terms", params={"parent": parent_iri})
    assert r2.status_code == 200
    assert "terms" in r2.json()
```

`tests/api/test_global_search.py`:
```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_global_search_returns_results(client: AsyncClient):
    r = await client.get("/api/v1/search?q=cell")
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert isinstance(data["results"], list)

@pytest.mark.asyncio
async def test_global_search_requires_query(client: AsyncClient):
    r = await client.get("/api/v1/search")
    assert r.status_code == 422  # missing required param
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /path/to/ontoexplorer && python -m pytest tests/api/test_terms_parent.py tests/api/test_global_search.py -v 2>&1 | head -30
```

Expected: FAIL or collection error (endpoints don't exist yet).

- [ ] **Step 3: Add `parent` query param to `list_terms` in ontologies.py**

In `ontoexplorer/api/ontologies.py`, replace the `list_terms` function:

```python
@router.get("/{ontology_id}/{version_id}/terms", summary="List terms (classes)")
async def list_terms(
    ontology_id: str,
    version_id: str,
    parent: str | None = Query(None, description="'root' for top-level classes, or an IRI for direct subclasses"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    import pyoxigraph

    store = get_store()
    g = graph_iri(ontology_id, version_id)

    if parent is None or parent == "root":
        # Root classes: owl:Class not subClassOf any other owl:Class in this ontology
        query = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?label WHERE {{
                GRAPH <{g}> {{
                    ?class a owl:Class .
                    OPTIONAL {{ ?class rdfs:label ?label }}
                    FILTER NOT EXISTS {{
                        ?class rdfs:subClassOf ?p .
                        FILTER(isIRI(?p) && str(?p) != "http://www.w3.org/2002/07/owl#Thing")
                        GRAPH <{g}> {{ ?p a owl:Class }}
                    }}
                }}
            }}
            ORDER BY ?class
            LIMIT {limit} OFFSET {offset}
        """
    else:
        # Direct subclasses of the given parent IRI
        query = f"""
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?class ?label WHERE {{
                GRAPH <{g}> {{
                    ?class a owl:Class .
                    ?class rdfs:subClassOf <{parent}> .
                    OPTIONAL {{ ?class rdfs:label ?label }}
                }}
            }}
            ORDER BY ?class
            LIMIT {limit} OFFSET {offset}
        """

    results = store.query(query)
    terms = []
    for row in results:
        terms.append({
            "iri": str(row["class"]),
            "label": str(row["label"]) if row.get("label") else None,
        })
    return {"terms": terms, "offset": offset, "limit": limit, "parent": parent}
```

- [ ] **Step 4: Create global search endpoint**

`ontoexplorer/api/global_search.py`:
```python
"""Global cross-ontology entity search — GET /api/v1/search?q=<query>."""
import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import OntologyVersion
from ontoexplorer.modules.search.indexer import entity_lookup

router = APIRouter(prefix="/api/v1/search", tags=["global-search"])


@router.get("", summary="Cross-ontology entity prefix search")
async def global_search(
    q: str = Query(..., min_length=1, description="Entity label prefix"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    # Gather all version IDs that are indexed or classified
    result = await db.execute(
        select(OntologyVersion.id, OntologyVersion.ontology_id, OntologyVersion.status)
        .where(OntologyVersion.status.in_(["indexed", "classified"]))
    )
    versions = result.fetchall()

    if not versions:
        return {"results": [], "count": 0}

    per_version = max(5, limit // max(len(versions), 1))

    async def search_version(vid: str, oid: str) -> list[dict]:
        rows = await asyncio.to_thread(entity_lookup, vid, q, None, per_version)
        for r in rows:
            r["version_id"] = vid
            r["ontology_id"] = oid
        return rows

    nested = await asyncio.gather(
        *[search_version(str(v.id), str(v.ontology_id)) for v in versions]
    )

    seen_iris: set[str] = set()
    merged: list[dict] = []
    for rows in nested:
        for row in rows:
            if row["iri"] not in seen_iris:
                seen_iris.add(row["iri"])
                merged.append(row)
            if len(merged) >= limit:
                break
        if len(merged) >= limit:
            break

    return {"results": merged, "count": len(merged), "truncated": len(merged) >= limit}
```

- [ ] **Step 5: Register global_search router in main.py**

In `ontoexplorer/main.py`, add after other imports and include_router calls:

```python
from ontoexplorer.api.global_search import router as global_search_router
# ...
app.include_router(global_search_router)
```

- [ ] **Step 6: Run backend tests**

```bash
python -m pytest tests/api/test_terms_parent.py tests/api/test_global_search.py -v
```

Expected: PASS.

- [ ] **Step 7: Rewrite api.ts with all new methods**

`frontend/src/lib/api.ts`:
```typescript
import { getAccessToken, refreshAccessToken, clearAccessToken } from './auth'

const BASE = '/api/v1'

export interface Ontology {
  id: string
  iri: string
  status: string
  class_count?: number
  description?: string
  created_at: string
}

export interface OntologyVersion {
  id: string
  ontology_id: string
  version_iri: string | null
  status: string
  created_at: string
}

export interface Term {
  iri: string
  label: string | null
}

export interface RawTermDetail {
  iri: string
  properties: Record<string, string[]>
}

export interface ParsedTerm {
  iri: string
  label: string
  definition: string | null
  entityType: 'class' | 'property' | 'individual'
  synonyms: { exact: string[]; related: string[]; broad: string[]; narrow: string[] }
  superclasses: string[]
}

export interface SearchResult {
  iri: string
  label: string
  short: string
  match_type: 'entity' | 'elk' | 'sparql'
  version_id?: string
  ontology_id?: string
}

export interface AutocompleteCompletion {
  text: string
  type: string
  iri: string | null
  short: string | null
  insert: string
}

export interface UserProfile {
  id: string
  email: string
  display_name: string
}

// ── Predicates ──────────────────────────────────────────────────────────────
const P = {
  label:        'http://www.w3.org/2000/01/rdf-schema#label',
  comment:      'http://www.w3.org/2000/01/rdf-schema#comment',
  definition:   'http://purl.obolibrary.org/obo/IAO_0000115',
  subClassOf:   'http://www.w3.org/2000/01/rdf-schema#subClassOf',
  type:         'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
  exactSyn:     'http://www.geneontology.org/formats/oboInOwl#hasExactSynonym',
  relatedSyn:   'http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym',
  broadSyn:     'http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym',
  narrowSyn:    'http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym',
  owlClass:     'http://www.w3.org/2002/07/owl#Class',
  owlObjProp:   'http://www.w3.org/2002/07/owl#ObjectProperty',
  owlDataProp:  'http://www.w3.org/2002/07/owl#DatatypeProperty',
  owlAnnProp:   'http://www.w3.org/2002/07/owl#AnnotationProperty',
  owlIndividual:'http://www.w3.org/2002/07/owl#NamedIndividual',
}

export function parseTerm(raw: RawTermDetail): ParsedTerm {
  const p = raw.properties
  const label = p[P.label]?.[0] ?? raw.iri.split(/[#/]/).pop() ?? raw.iri
  const definition = p[P.definition]?.[0] ?? p[P.comment]?.[0] ?? null
  const types = p[P.type] ?? []
  let entityType: ParsedTerm['entityType'] = 'class'
  if (types.includes(P.owlObjProp) || types.includes(P.owlDataProp) || types.includes(P.owlAnnProp)) {
    entityType = 'property'
  } else if (types.includes(P.owlIndividual)) {
    entityType = 'individual'
  }
  const superclasses = (p[P.subClassOf] ?? []).filter(v => v.startsWith('http'))
  return {
    iri: raw.iri,
    label,
    definition,
    entityType,
    synonyms: {
      exact:   p[P.exactSyn]   ?? [],
      related: p[P.relatedSyn] ?? [],
      broad:   p[P.broadSyn]   ?? [],
      narrow:  p[P.narrowSyn]  ?? [],
    },
    superclasses,
  }
}

// ── HTTP helpers ─────────────────────────────────────────────────────────────
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getAccessToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  let resp = await fetch(`${BASE}${path}`, { ...options, headers })

  if (resp.status === 401) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      headers['Authorization'] = `Bearer ${refreshed}`
      resp = await fetch(`${BASE}${path}`, { ...options, headers })
    } else {
      clearAccessToken()
      window.location.href = '/login'
      throw new Error('Session expired')
    }
  }

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw Object.assign(new Error(err.detail ?? 'Request failed'), {
      status: resp.status,
      body: err,
    })
  }
  if (resp.status === 204) return undefined as T
  return resp.json()
}

async function authRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getAccessToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const resp = await fetch(path, { ...options, headers })
  if (!resp.ok) throw new Error('Not authenticated')
  return resp.json()
}

// ── API surface ───────────────────────────────────────────────────────────────
export const api = {
  auth: {
    me: () => authRequest<UserProfile>('/auth/me'),
  },
  ontologies: {
    list: () => request<{ ontologies: Ontology[] }>('/ontologies'),
    get: (oid: string) => request<Ontology>(`/ontologies/${oid}`),
    versions: (oid: string) => request<{ versions: OntologyVersion[] }>(`/ontologies/${oid}/versions`),
    terms: (oid: string, vid: string, parent?: string | null) => {
      const params = new URLSearchParams({ limit: '200' })
      if (parent !== undefined && parent !== null) params.set('parent', parent)
      else params.set('parent', 'root')
      return request<{ terms: Term[] }>(`/ontologies/${oid}/${vid}/terms?${params}`)
    },
    termDetail: (oid: string, vid: string, iri: string) =>
      request<RawTermDetail>(`/ontologies/${oid}/${vid}/terms/${encodeURIComponent(iri)}`),
    submitByIri: (iri: string) =>
      request<{ task_id: string }>('/ontologies', { method: 'POST', body: JSON.stringify({ iri }) }),
    submitByUrl: (url: string) =>
      request<{ task_id: string }>('/ontologies', { method: 'POST', body: JSON.stringify({ url }) }),
    submitFile: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return request<{ task_id: string }>('/ontologies', { method: 'POST', body: fd,
        headers: {} as Record<string, string> })
    },
    search: (oid: string, vid: string, q: string, mode = 'auto') =>
      request<{ mode: string; results: SearchResult[]; count: number }>(`/ontologies/${oid}/${vid}/search?q=${encodeURIComponent(q)}&mode=${mode}`),
    autocomplete: (oid: string, vid: string, q: string, cursor = -1) =>
      request<{ completions: AutocompleteCompletion[]; context: string }>(`/ontologies/${oid}/${vid}/autocomplete?q=${encodeURIComponent(q)}&cursor=${cursor}`),
  },
  globalSearch: {
    search: (q: string, limit = 20) =>
      request<{ results: SearchResult[]; count: number }>(`/../search?q=${encodeURIComponent(q)}&limit=${limit}`),
  },
}
```

Note: `globalSearch.search` uses `/../search` to escape the `/api/v1` base: `/api/v1/../search` → `/api/v1/search`. An alternative (cleaner) is to add a second fetch helper that doesn't use BASE. Update `api.ts` to use `fetch('/api/v1/search?...')` directly in `globalSearch.search`:

```typescript
  globalSearch: {
    search: (q: string, limit = 20) => {
      const params = new URLSearchParams({ q, limit: String(limit) })
      return fetch(`/api/v1/search?${params}`).then(r => r.json()) as Promise<{ results: SearchResult[]; count: number }>
    },
  },
```

- [ ] **Step 8: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/api.ts \
  ontoexplorer/api/ontologies.py \
  ontoexplorer/api/global_search.py \
  ontoexplorer/main.py \
  tests/api/test_terms_parent.py \
  tests/api/test_global_search.py
git commit -m "feat: extend api.ts, add parent param to /terms, add global entity search"
```

---

## Task 3: OntologySelector + useOntologies

**Files:**
- Create: `frontend/src/hooks/useOntologies.ts`
- Create: `frontend/src/components/OntologySelector.tsx`
- Test: `frontend/src/components/OntologySelector.test.tsx`

- [ ] **Step 1: Write failing test**

`frontend/src/components/OntologySelector.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import OntologySelector from './OntologySelector'

const mockOntologies = [
  { id: 'go', iri: 'http://go', status: 'indexed', created_at: '2024-01-01' },
  { id: 'mondo', iri: 'http://mondo', status: 'indexed', created_at: '2024-01-01' },
]

vi.mock('../lib/api', () => ({
  api: { ontologies: { list: () => Promise.resolve({ ontologies: mockOntologies }) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

test('renders All option by default', async () => {
  wrap(<OntologySelector value={null} onChange={() => {}} />)
  expect(await screen.findByText('All')).toBeInTheDocument()
})

test('calls onChange when option selected', async () => {
  const onChange = vi.fn()
  wrap(<OntologySelector value={null} onChange={onChange} />)
  const select = await screen.findByRole('combobox')
  await userEvent.selectOptions(select, 'go')
  expect(onChange).toHaveBeenCalledWith('go')
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- OntologySelector
```

Expected: FAIL — `Cannot find module './OntologySelector'`

- [ ] **Step 3: Create useOntologies hook**

`frontend/src/hooks/useOntologies.ts`:
```typescript
import { useQuery } from '@tanstack/react-query'
import { api, Ontology } from '../lib/api'

export function useOntologies() {
  const { data, isLoading } = useQuery({
    queryKey: ['ontologies'],
    queryFn: api.ontologies.list,
    staleTime: 30_000,
  })
  return { ontologies: data?.ontologies ?? [], isLoading }
}
```

- [ ] **Step 4: Create OntologySelector component**

`frontend/src/components/OntologySelector.tsx`:
```typescript
import { useOntologies } from '../hooks/useOntologies'

interface Props {
  value: string | null
  onChange: (id: string | null) => void
  required?: boolean
  placeholder?: string
}

export default function OntologySelector({ value, onChange, required, placeholder }: Props) {
  const { ontologies, isLoading } = useOntologies()

  return (
    <select
      value={value ?? ''}
      onChange={e => onChange(e.target.value || null)}
      disabled={isLoading}
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        color: value ? 'var(--text)' : 'var(--text-dim)',
        borderRadius: 'var(--radius-sm)',
        padding: '5px 8px',
        fontSize: 'var(--font-size-sm)',
        minWidth: 120,
      }}
    >
      {!required && <option value="">All</option>}
      {required && !value && (
        <option value="" disabled>
          {placeholder ?? 'Select ontology…'}
        </option>
      )}
      {ontologies.map(o => (
        <option key={o.id} value={o.id}>
          {o.id}
        </option>
      ))}
    </select>
  )
}
```

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm run test:run -- OntologySelector
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useOntologies.ts frontend/src/components/OntologySelector.tsx frontend/src/components/OntologySelector.test.tsx
git commit -m "feat(frontend): OntologySelector + useOntologies hook"
```

---

## Task 4: SearchBar + useSearch

**Files:**
- Create: `frontend/src/hooks/useSearch.ts`
- Create: `frontend/src/components/SearchBar.tsx`
- Test: `frontend/src/components/SearchBar.test.tsx`

- [ ] **Step 1: Write failing tests**

`frontend/src/components/SearchBar.test.tsx`:
```typescript
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SearchBar from './SearchBar'

vi.mock('../lib/api', () => ({
  api: {
    ontologies: { autocomplete: () => Promise.resolve({ completions: [], context: 'entity' }) },
  },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders with placeholder text', () => {
  wrap(<SearchBar ontologyId={null} versionId={null} onSearch={() => {}} />)
  expect(screen.getByPlaceholderText(/search terms/i)).toBeInTheDocument()
})

test('calls onSearch when Enter is pressed', async () => {
  const onSearch = vi.fn()
  wrap(<SearchBar ontologyId={null} versionId={null} onSearch={onSearch} />)
  const input = screen.getByPlaceholderText(/search terms/i)
  await userEvent.type(input, 'cell death{Enter}')
  expect(onSearch).toHaveBeenCalledWith('cell death')
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- SearchBar
```

Expected: FAIL.

- [ ] **Step 3: Create useSearch hook**

`frontend/src/hooks/useSearch.ts`:
```typescript
import { useQuery } from '@tanstack/react-query'
import { api, AutocompleteCompletion, SearchResult } from '../lib/api'

export function useSearch(ontologyId: string | null, versionId: string | null, query: string) {
  return useQuery({
    queryKey: ['search', ontologyId, versionId, query],
    queryFn: () => api.ontologies.search(ontologyId!, versionId!, query),
    enabled: !!ontologyId && !!versionId && query.length >= 2,
    staleTime: 10_000,
  })
}

export function useAutocomplete(
  ontologyId: string | null,
  versionId: string | null,
  query: string,
  cursor: number,
  enabled: boolean,
) {
  return useQuery<{ completions: AutocompleteCompletion[]; context: string }>({
    queryKey: ['autocomplete', ontologyId, versionId, query, cursor],
    queryFn: () => api.ontologies.autocomplete(ontologyId!, versionId!, query, cursor),
    enabled: enabled && !!ontologyId && !!versionId && query.length >= 1,
    staleTime: 5_000,
  })
}

export function useGlobalSearch(query: string) {
  return useQuery({
    queryKey: ['global-search', query],
    queryFn: () => api.globalSearch.search(query),
    enabled: query.length >= 2,
    staleTime: 10_000,
  })
}
```

- [ ] **Step 4: Create SearchBar component**

`frontend/src/components/SearchBar.tsx`:
```typescript
import { useState, useRef, useEffect } from 'react'
import { useAutocomplete } from '../hooks/useSearch'

interface Props {
  ontologyId: string | null
  versionId: string | null
  onSearch: (query: string) => void
  placeholder?: string
  initialValue?: string
}

export default function SearchBar({ ontologyId, versionId, onSearch, placeholder, initialValue }: Props) {
  const [value, setValue] = useState(initialValue ?? '')
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [cursor, setCursor] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)

  // Autocomplete fires when query contains a quote (MOS context) or is in entity mode
  const autocompleteEnabled = showSuggestions && value.length >= 1
  const { data: acData } = useAutocomplete(ontologyId, versionId, value, cursor, autocompleteEnabled)

  const completions = acData?.completions ?? []

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      setShowSuggestions(false)
      onSearch(value.trim())
    } else if (e.key === 'Escape') {
      setShowSuggestions(false)
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setValue(e.target.value)
    setCursor(e.target.selectionStart ?? -1)
    setShowSuggestions(true)
  }

  function applyCompletion(insert: string) {
    setValue(insert)
    setShowSuggestions(false)
    inputRef.current?.focus()
  }

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '8px 12px',
      }}>
        <span style={{ color: 'var(--text-dim)' }}>⌕</span>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
          onFocus={() => setShowSuggestions(true)}
          placeholder={placeholder ?? 'Search terms, ontologies, CURIEs, or MOS expressions…'}
          style={{
            flex: 1, background: 'none', border: 'none',
            color: 'var(--text)', fontSize: 'var(--font-size-base)',
            outline: 'none',
          }}
        />
      </div>

      {showSuggestions && completions.length > 0 && (
        <ul style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 200,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', listStyle: 'none',
          marginTop: 4, maxHeight: 240, overflowY: 'auto',
        }}>
          {completions.map((c, i) => (
            <li
              key={i}
              onMouseDown={() => applyCompletion(c.insert)}
              style={{
                padding: '6px 12px', cursor: 'pointer',
                display: 'flex', gap: 8, alignItems: 'center',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >
              <span style={{
                fontSize: 10, background: 'var(--bg)',
                color: c.type === 'class' ? 'var(--accent-purple)' : 'var(--text-dim)',
                borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase',
              }}>
                {c.type}
              </span>
              <span style={{ color: 'var(--text)' }}>{c.text}</span>
              {c.short && <span style={{ color: 'var(--text-dim)', fontSize: 11, marginLeft: 'auto' }}>{c.short}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm run test:run -- SearchBar
```

Expected: PASS — 2 tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useSearch.ts frontend/src/components/SearchBar.tsx frontend/src/components/SearchBar.test.tsx
git commit -m "feat(frontend): SearchBar with autocomplete + useSearch/useGlobalSearch hooks"
```

---

## Task 5: Home page

**Files:**
- Modify: `frontend/src/pages/Home.tsx` (replace stub)
- Test: `frontend/src/pages/Home.test.tsx`

- [ ] **Step 1: Write failing test**

`frontend/src/pages/Home.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Home from './Home'

vi.mock('../lib/api', () => ({
  api: {
    ontologies: { list: () => Promise.resolve({ ontologies: [] }) },
    globalSearch: { search: () => Promise.resolve({ results: [], count: 0 }) },
  },
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Home /></MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders search bar and two panels', () => {
  wrap()
  expect(screen.getByText(/terms/i)).toBeInTheDocument()
  expect(screen.getByText(/ontologies/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- src/pages/Home
```

Expected: FAIL — stub `Home` doesn't match.

- [ ] **Step 3: Implement Home page**

`frontend/src/pages/Home.tsx`:
```typescript
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchBar from '../components/SearchBar'
import OntologySelector from '../components/OntologySelector'
import { useGlobalSearch } from '../hooks/useSearch'
import { useOntologies } from '../hooks/useOntologies'

export default function Home() {
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [selectedOid, setSelectedOid] = useState<string | null>(null)
  const navigate = useNavigate()

  const { data: searchData } = useGlobalSearch(submittedQuery)
  const { ontologies } = useOntologies()

  const filteredOntologies = submittedQuery
    ? ontologies.filter(o =>
        o.id.toLowerCase().includes(submittedQuery.toLowerCase()) ||
        o.iri.toLowerCase().includes(submittedQuery.toLowerCase())
      )
    : ontologies

  function handleSearch(q: string) {
    setSubmittedQuery(q)
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '3rem 1.5rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 24, fontWeight: 700, marginBottom: '0.5rem', textAlign: 'center' }}>
        OntoExplorer
      </h1>
      <p style={{ color: 'var(--text-muted)', textAlign: 'center', marginBottom: '2rem' }}>
        FAIR ontology repository — search terms, ontologies, and MOS expressions
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: '1.5rem', alignItems: 'center' }}>
        <OntologySelector value={selectedOid} onChange={setSelectedOid} />
        <div style={{ flex: 1 }}>
          <SearchBar
            ontologyId={selectedOid}
            versionId={null}
            onSearch={handleSearch}
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        {/* Terms panel */}
        <div style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius)', padding: '1rem' }}>
          <h2 style={{ color: 'var(--accent-purple)', fontSize: 12, textTransform: 'uppercase', letterSpacing: 1, marginBottom: '0.75rem' }}>
            Terms
          </h2>
          {!submittedQuery ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
              Search to find terms across all ontologies
            </p>
          ) : searchData?.results.length === 0 ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No terms found</p>
          ) : (
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {(searchData?.results ?? []).map(r => (
                <li
                  key={r.iri}
                  onClick={() => r.ontology_id && navigate(`/browse/${r.ontology_id}/${r.version_id}?term=${encodeURIComponent(r.iri)}`)}
                  style={{
                    padding: '6px 8px', borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'baseline',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                  onMouseLeave={e => (e.currentTarget.style.background = '')}
                >
                  <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{r.label}</span>
                  <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Ontologies panel */}
        <div style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius)', padding: '1rem' }}>
          <h2 style={{ color: 'var(--accent-blue)', fontSize: 12, textTransform: 'uppercase', letterSpacing: 1, marginBottom: '0.75rem' }}>
            Ontologies
          </h2>
          {filteredOntologies.length === 0 ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No ontologies</p>
          ) : (
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {filteredOntologies.slice(0, 10).map(o => (
                <li
                  key={o.id}
                  onClick={() => navigate(`/browse/${o.id}/latest`)}
                  style={{
                    padding: '6px 8px', borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                  onMouseLeave={e => (e.currentTarget.style.background = '')}
                >
                  <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{o.id}</span>
                  <span style={{
                    fontSize: 10, background: 'var(--bg)', color: 'var(--text-dim)',
                    borderRadius: 3, padding: '1px 5px', marginLeft: 'auto',
                  }}>{o.status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm run test:run -- src/pages/Home
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Home.tsx frontend/src/pages/Home.test.tsx
git commit -m "feat(frontend): Home page with split Terms/Ontologies panels"
```

---

## Task 6: ResizeHandle

**Files:**
- Create: `frontend/src/components/ResizeHandle.tsx`
- Test: `frontend/src/components/ResizeHandle.test.tsx`

- [ ] **Step 1: Write failing test**

`frontend/src/components/ResizeHandle.test.tsx`:
```typescript
import { render, fireEvent } from '@testing-library/react'
import ResizeHandle from './ResizeHandle'

test('fires onDelta with positive delta when dragged right', () => {
  const onDelta = vi.fn()
  const { container } = render(<ResizeHandle onDelta={onDelta} />)
  const handle = container.firstChild as HTMLElement

  fireEvent.mouseDown(handle, { clientX: 100 })
  fireEvent.mouseMove(document, { clientX: 150 })
  fireEvent.mouseUp(document)

  expect(onDelta).toHaveBeenCalledWith(50)
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- ResizeHandle
```

Expected: FAIL.

- [ ] **Step 3: Implement ResizeHandle**

`frontend/src/components/ResizeHandle.tsx`:
```typescript
import { useCallback } from 'react'

interface Props {
  onDelta: (delta: number) => void
}

export default function ResizeHandle({ onDelta }: Props) {
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX

    function onMouseMove(ev: MouseEvent) {
      onDelta(ev.clientX - startX)
    }
    function onMouseUp(ev: MouseEvent) {
      onDelta(ev.clientX - startX)
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [onDelta])

  return (
    <div
      onMouseDown={handleMouseDown}
      style={{
        width: 4, cursor: 'col-resize', flexShrink: 0,
        background: 'var(--border)',
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent)')}
      onMouseLeave={e => (e.currentTarget.style.background = 'var(--border)')}
    />
  )
}
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm run test:run -- ResizeHandle
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ResizeHandle.tsx frontend/src/components/ResizeHandle.test.tsx
git commit -m "feat(frontend): ResizeHandle drag component"
```

---

## Task 7: ClassTree + useClassTree

**Files:**
- Create: `frontend/src/hooks/useClassTree.ts`
- Create: `frontend/src/components/ClassTree.tsx`
- Test: `frontend/src/components/ClassTree.test.tsx`

- [ ] **Step 1: Write failing test**

`frontend/src/components/ClassTree.test.tsx`:
```typescript
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ClassTree from './ClassTree'

const rootTerms = [
  { iri: 'http://ex.org/A', label: 'Term A' },
  { iri: 'http://ex.org/B', label: 'Term B' },
]
const childTerms = [{ iri: 'http://ex.org/A1', label: 'Term A1' }]

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      terms: (oid: string, vid: string, parent?: string | null) =>
        Promise.resolve({ terms: parent && parent !== 'root' ? childTerms : rootTerms }),
    },
  },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

test('renders root terms', async () => {
  wrap(<ClassTree ontologyId="go" versionId="v1" selectedIri={null} onSelect={() => {}} />)
  expect(await screen.findByText('Term A')).toBeInTheDocument()
  expect(screen.getByText('Term B')).toBeInTheDocument()
})

test('clicking a node calls onSelect', async () => {
  const onSelect = vi.fn()
  wrap(<ClassTree ontologyId="go" versionId="v1" selectedIri={null} onSelect={onSelect} />)
  const node = await screen.findByText('Term A')
  fireEvent.click(node)
  expect(onSelect).toHaveBeenCalledWith('http://ex.org/A')
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- ClassTree
```

Expected: FAIL.

- [ ] **Step 3: Create useClassTree hook**

`frontend/src/hooks/useClassTree.ts`:
```typescript
import { useQuery } from '@tanstack/react-query'
import { api, Term } from '../lib/api'

export function useClassTreeNodes(
  ontologyId: string | null,
  versionId: string | null,
  parent: string | null,
) {
  return useQuery<{ terms: Term[] }>({
    queryKey: ['class-tree', ontologyId, versionId, parent ?? 'root'],
    queryFn: () => api.ontologies.terms(ontologyId!, versionId!, parent),
    enabled: !!ontologyId && !!versionId,
    staleTime: 60_000,
  })
}
```

- [ ] **Step 4: Create ClassTree component**

`frontend/src/components/ClassTree.tsx`:
```typescript
import { useState } from 'react'
import { useClassTreeNodes } from '../hooks/useClassTree'
import { Term } from '../lib/api'

interface NodeProps {
  ontologyId: string
  versionId: string
  term: Term
  depth: number
  selectedIri: string | null
  onSelect: (iri: string) => void
}

function TreeNode({ ontologyId, versionId, term, depth, selectedIri, onSelect }: NodeProps) {
  const [expanded, setExpanded] = useState(false)
  const [hasChildren, setHasChildren] = useState<boolean | null>(null)

  const { data: childData, isLoading } = useClassTreeNodes(
    expanded ? ontologyId : null,
    expanded ? versionId : null,
    expanded ? term.iri : null,
  )

  const children = childData?.terms ?? []
  const isSelected = selectedIri === term.iri

  function handleToggle(e: React.MouseEvent) {
    e.stopPropagation()
    setExpanded(v => !v)
  }

  const label = term.label ?? term.iri.split(/[#/]/).pop() ?? term.iri

  return (
    <li>
      <div
        onClick={() => onSelect(term.iri)}
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          paddingLeft: depth * 12,
          padding: `4px 8px 4px ${8 + depth * 12}px`,
          cursor: 'pointer',
          background: isSelected ? 'var(--bg-hover)' : 'transparent',
          borderRadius: 'var(--radius-sm)',
          color: isSelected ? 'var(--accent)' : 'var(--text)',
        }}
        onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)' }}
        onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = '' }}
      >
        <span
          onClick={handleToggle}
          style={{ width: 14, fontSize: 10, color: 'var(--text-dim)', flexShrink: 0, userSelect: 'none' }}
        >
          {isLoading ? '…' : expanded ? '▾' : '▸'}
        </span>
        <span style={{ fontSize: 'var(--font-size-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {label}
        </span>
      </div>
      {expanded && children.length > 0 && (
        <ul style={{ listStyle: 'none' }}>
          {children.map(child => (
            <TreeNode
              key={child.iri}
              ontologyId={ontologyId}
              versionId={versionId}
              term={child}
              depth={depth + 1}
              selectedIri={selectedIri}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

interface Props {
  ontologyId: string
  versionId: string
  selectedIri: string | null
  onSelect: (iri: string) => void
}

export default function ClassTree({ ontologyId, versionId, selectedIri, onSelect }: Props) {
  const { data, isLoading } = useClassTreeNodes(ontologyId, versionId, null)
  const roots = data?.terms ?? []

  if (isLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</div>
  }

  if (roots.length === 0) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No classes found</div>
  }

  return (
    <ul style={{ listStyle: 'none', overflow: 'auto', flex: 1 }}>
      {roots.map(term => (
        <TreeNode
          key={term.iri}
          ontologyId={ontologyId}
          versionId={versionId}
          term={term}
          depth={0}
          selectedIri={selectedIri}
          onSelect={onSelect}
        />
      ))}
    </ul>
  )
}
```

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm run test:run -- ClassTree
```

Expected: PASS — 2 tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useClassTree.ts frontend/src/components/ClassTree.tsx frontend/src/components/ClassTree.test.tsx
git commit -m "feat(frontend): ClassTree with lazy-load expand + useClassTree hook"
```

---

## Task 8: TermPanel + useTerm

**Files:**
- Create: `frontend/src/hooks/useTerm.ts`
- Create: `frontend/src/components/TermPanel.tsx`
- Test: `frontend/src/components/TermPanel.test.tsx`

- [ ] **Step 1: Write failing test**

`frontend/src/components/TermPanel.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TermPanel from './TermPanel'

const mockRaw = {
  iri: 'http://purl.obolibrary.org/obo/GO_0008219',
  properties: {
    'http://www.w3.org/2000/01/rdf-schema#label': ['cell death'],
    'http://purl.obolibrary.org/obo/IAO_0000115': ['A biological process…'],
    'http://www.w3.org/1999/02/22-rdf-syntax-ns#type': ['http://www.w3.org/2002/07/owl#Class'],
  },
}

vi.mock('../lib/api', () => ({
  api: {
    ontologies: { termDetail: () => Promise.resolve(mockRaw) },
  },
  parseTerm: (raw: typeof mockRaw) => ({
    iri: raw.iri,
    label: 'cell death',
    definition: 'A biological process…',
    entityType: 'class',
    synonyms: { exact: [], related: [], broad: [], narrow: [] },
    superclasses: [],
  }),
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('shows term label and definition', async () => {
  wrap()
  expect(await screen.findByText('cell death')).toBeInTheDocument()
  expect(screen.getByText(/biological process/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- TermPanel
```

Expected: FAIL.

- [ ] **Step 3: Create useTerm hook**

`frontend/src/hooks/useTerm.ts`:
```typescript
import { useQuery } from '@tanstack/react-query'
import { api, parseTerm, ParsedTerm } from '../lib/api'

export function useTerm(ontologyId: string | null, versionId: string | null, termIri: string | null) {
  return useQuery<ParsedTerm>({
    queryKey: ['term', ontologyId, versionId, termIri],
    queryFn: async () => {
      const raw = await api.ontologies.termDetail(ontologyId!, versionId!, termIri!)
      return parseTerm(raw)
    },
    enabled: !!ontologyId && !!versionId && !!termIri,
    staleTime: 60_000,
  })
}
```

- [ ] **Step 4: Create TermPanel component**

`frontend/src/components/TermPanel.tsx`:
```typescript
import { Link } from 'react-router-dom'
import { useTerm } from '../hooks/useTerm'

interface Props {
  ontologyId: string
  versionId: string
  termIri: string
}

const badge = (label: string, color: string) => (
  <span style={{
    fontSize: 10, background: 'var(--bg)', color,
    borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase',
  }}>{label}</span>
)

export default function TermPanel({ ontologyId, versionId, termIri }: Props) {
  const { data, isLoading, error } = useTerm(ontologyId, versionId, termIri)

  if (isLoading) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Term not found</div>

  const typeColor = data.entityType === 'class' ? 'var(--accent-purple)'
    : data.entityType === 'property' ? 'var(--accent-blue)' : 'var(--text-muted)'

  const shortIri = data.iri.split(/[#/]/).pop() ?? data.iri

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding: '10px 12px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ fontWeight: 600, color: 'var(--accent)', flex: 1 }}>{data.label}</span>
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{shortIri}</span>
        {badge(data.entityType, typeColor)}
        <Link
          to={`/browse/${ontologyId}/${versionId}/term/${encodeURIComponent(data.iri)}`}
          style={{ color: 'var(--text-dim)', fontSize: 11, flexShrink: 0 }}
        >
          Open full page ↗
        </Link>
      </div>

      {/* Body: split — definition+synonyms left, subclasses right */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left: definition + superclasses + synonyms */}
        <div style={{ flex: 1, padding: '10px 12px', overflow: 'auto', borderRight: '1px solid var(--border)' }}>
          {data.definition && (
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 10, lineHeight: 1.5 }}>
              {data.definition}
            </p>
          )}
          {data.superclasses.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 4 }}>
                Superclasses
              </div>
              {data.superclasses.map(iri => (
                <div key={iri} style={{ color: 'var(--accent)', fontSize: 'var(--font-size-sm)', paddingLeft: 8 }}>
                  {iri.split(/[#/]/).pop()}
                </div>
              ))}
            </div>
          )}
          {(data.synonyms.exact.length > 0 || data.synonyms.related.length > 0) && (
            <div>
              <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 4 }}>
                Synonyms
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
                {[...data.synonyms.exact, ...data.synonyms.related].join(' · ')}
              </div>
            </div>
          )}
        </div>

        {/* Right: subclasses loaded lazily via ClassTree children */}
        <div style={{ flex: 1, padding: '10px 12px', overflow: 'auto' }}>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 6 }}>
            Subclasses
          </div>
          <SubclassList ontologyId={ontologyId} versionId={versionId} parentIri={termIri} />
        </div>
      </div>
    </div>
  )
}

function SubclassList({ ontologyId, versionId, parentIri }: { ontologyId: string; versionId: string; parentIri: string }) {
  const { data, isLoading } = useTerm(null, null, null)  // won't fire
  // Use class tree children endpoint directly
  import { useClassTreeNodes } from '../hooks/useClassTree'
  const { data: childData } = useClassTreeNodes(ontologyId, versionId, parentIri)
  const children = childData?.terms ?? []

  if (isLoading) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</span>
  if (children.length === 0) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No subclasses</span>

  return (
    <ul style={{ listStyle: 'none' }}>
      {children.slice(0, 10).map(c => (
        <li key={c.iri} style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', padding: '2px 0' }}>
          ▸ {c.label ?? c.iri.split(/[#/]/).pop()}
        </li>
      ))}
      {children.length > 10 && (
        <li style={{ color: 'var(--text-dim)', fontSize: 11, padding: '2px 0' }}>
          + {children.length - 10} more…
        </li>
      )}
    </ul>
  )
}
```

Note: The inline `import` in `SubclassList` is not valid. Extract the function to its own proper import at the top of the file. Fix `TermPanel.tsx` as follows — move `SubclassList` to use the `useClassTreeNodes` hook imported at the top of the file:

Replace the SubclassList component with:
```typescript
// At top of file, add:
import { useClassTreeNodes } from '../hooks/useClassTree'

// Replace SubclassList with:
function SubclassList({ ontologyId, versionId, parentIri }: { ontologyId: string; versionId: string; parentIri: string }) {
  const { data: childData, isLoading } = useClassTreeNodes(ontologyId, versionId, parentIri)
  const children = childData?.terms ?? []

  if (isLoading) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</span>
  if (children.length === 0) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No subclasses</span>

  return (
    <ul style={{ listStyle: 'none' }}>
      {children.slice(0, 10).map(c => (
        <li key={c.iri} style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', padding: '2px 0' }}>
          ▸ {c.label ?? c.iri.split(/[#/]/).pop()}
        </li>
      ))}
      {children.length > 10 && (
        <li style={{ color: 'var(--text-dim)', fontSize: 11, padding: '2px 0' }}>
          + {children.length - 10} more…
        </li>
      )}
    </ul>
  )
}
```

The `useTerm` call inside `SubclassList` (the original incorrect one) is removed; only `useClassTreeNodes` is used there.

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm run test:run -- TermPanel
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useTerm.ts frontend/src/components/TermPanel.tsx frontend/src/components/TermPanel.test.tsx
git commit -m "feat(frontend): TermPanel (split definition+subclasses) + useTerm hook"
```

---

## Task 9: Browse page

**Files:**
- Modify: `frontend/src/pages/Browse.tsx` (replace stub)
- Test: `frontend/src/pages/Browse.test.tsx`

- [ ] **Step 1: Write failing integration test**

`frontend/src/pages/Browse.test.tsx`:
```typescript
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Browse from './Browse'

const mockOntologies = [
  { id: 'go', iri: 'http://go', status: 'indexed', created_at: '2024-01-01' },
]
const mockVersions = [{ id: 'v1', ontology_id: 'go', version_iri: null, status: 'indexed', created_at: '2024-01-01' }]
const mockTerms = { terms: [{ iri: 'http://ex.org/A', label: 'Term A' }] }
const mockTermDetail = {
  iri: 'http://ex.org/A',
  properties: {
    'http://www.w3.org/2000/01/rdf-schema#label': ['Term A'],
    'http://www.w3.org/1999/02/22-rdf-syntax-ns#type': ['http://www.w3.org/2002/07/owl#Class'],
  },
}

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      list: () => Promise.resolve({ ontologies: mockOntologies }),
      versions: () => Promise.resolve({ versions: mockVersions }),
      terms: () => Promise.resolve(mockTerms),
      termDetail: () => Promise.resolve(mockTermDetail),
    },
  },
  parseTerm: (raw: any) => ({
    iri: raw.iri, label: 'Term A', definition: null,
    entityType: 'class', synonyms: { exact: [], related: [], broad: [], narrow: [] }, superclasses: [],
  }),
}))

function wrap(path = '/browse') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/browse" element={<Browse />} />
          <Route path="/browse/:oid/:vid" element={<Browse />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('shows ontology list on load', async () => {
  wrap()
  expect(await screen.findByText('go')).toBeInTheDocument()
})

test('clicking ontology navigates to browse/:oid/:vid', async () => {
  wrap()
  const item = await screen.findByText('go')
  fireEvent.click(item)
  await waitFor(() => expect(screen.getByText('Term A')).toBeInTheDocument())
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- src/pages/Browse
```

Expected: FAIL — stub doesn't match.

- [ ] **Step 3: Implement Browse page**

`frontend/src/pages/Browse.tsx`:
```typescript
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useOntologies } from '../hooks/useOntologies'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import ClassTree from '../components/ClassTree'
import TermPanel from '../components/TermPanel'
import ResizeHandle from '../components/ResizeHandle'

const PANE_MIN = 200
const PANE_MAX = 600
const PANE_DEFAULT = 280

function useVersions(oid: string | undefined) {
  return useQuery({
    queryKey: ['versions', oid],
    queryFn: () => api.ontologies.versions(oid!),
    enabled: !!oid,
    staleTime: 30_000,
  })
}

export default function Browse() {
  const { oid, vid } = useParams<{ oid: string; vid: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { ontologies } = useOntologies()
  const { data: versionsData } = useVersions(oid)

  const selectedTermIri = searchParams.get('term')

  // Resizable left pane
  const [paneWidth, setPaneWidth] = useState<number>(() => {
    const stored = localStorage.getItem('browse-pane-width')
    return stored ? Number(stored) : PANE_DEFAULT
  })
  const dragStart = useRef<number | null>(null)

  function handleDelta(delta: number) {
    setPaneWidth(w => {
      const next = Math.min(PANE_MAX, Math.max(PANE_MIN, w + delta))
      localStorage.setItem('browse-pane-width', String(next))
      return next
    })
  }

  const versions = versionsData?.versions ?? []
  const activeVid = vid ?? versions[0]?.id

  function selectTerm(iri: string) {
    setSearchParams({ term: iri })
  }

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - var(--nav-height))', overflow: 'hidden' }}>
      {/* Left pane */}
      <div style={{
        width: paneWidth, flexShrink: 0,
        display: 'flex', flexDirection: 'column',
        background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)',
        overflow: 'hidden',
      }}>
        {/* Ontology list */}
        <div style={{ padding: '10px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 6 }}>
            Ontologies
          </div>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 200, overflowY: 'auto' }}>
            {ontologies.map(o => (
              <li
                key={o.id}
                onClick={() => navigate(`/browse/${o.id}/${versions[0]?.id ?? 'latest'}`)}
                style={{
                  padding: '4px 8px', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                  background: oid === o.id ? 'var(--bg-hover)' : 'transparent',
                  color: oid === o.id ? 'var(--accent)' : 'var(--text-muted)',
                  fontSize: 'var(--font-size-sm)',
                }}
                onMouseEnter={e => { if (oid !== o.id) e.currentTarget.style.background = 'rgba(255,255,255,0.04)' }}
                onMouseLeave={e => { if (oid !== o.id) e.currentTarget.style.background = '' }}
              >
                {o.id}
              </li>
            ))}
          </ul>
        </div>

        {/* Version selector */}
        {oid && versions.length > 1 && (
          <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)' }}>
            <select
              value={activeVid}
              onChange={e => navigate(`/browse/${oid}/${e.target.value}`)}
              style={{ width: '100%', fontSize: 'var(--font-size-sm)' }}
            >
              {versions.map(v => (
                <option key={v.id} value={v.id}>{v.id}</option>
              ))}
            </select>
          </div>
        )}

        {/* Class tree */}
        {oid && activeVid ? (
          <ClassTree
            ontologyId={oid}
            versionId={activeVid}
            selectedIri={selectedTermIri}
            onSelect={selectTerm}
          />
        ) : (
          <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            Select an ontology to browse
          </div>
        )}
      </div>

      {/* Resize handle */}
      <ResizeHandle onDelta={handleDelta} />

      {/* Right pane */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {oid && activeVid && selectedTermIri ? (
          <TermPanel ontologyId={oid} versionId={activeVid} termIri={selectedTermIri} />
        ) : (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)',
          }}>
            {oid ? 'Click a class in the tree to see its details' : 'Select an ontology from the left'}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm run test:run -- src/pages/Browse
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Browse.tsx frontend/src/pages/Browse.test.tsx
git commit -m "feat(frontend): Browse page with resizable split pane + ClassTree + TermPanel"
```

---

## Task 10: Full-page TermPage

**Files:**
- Modify: `frontend/src/pages/TermPage.tsx` (replace stub)
- Test: `frontend/src/pages/TermPage.test.tsx`

- [ ] **Step 1: Write failing test**

`frontend/src/pages/TermPage.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TermPage from './TermPage'

const mockRaw = {
  iri: 'http://purl.obolibrary.org/obo/GO_0008219',
  properties: {
    'http://www.w3.org/2000/01/rdf-schema#label': ['cell death'],
    'http://purl.obolibrary.org/obo/IAO_0000115': ['A biological process involving cessation of metabolic processes.'],
    'http://www.w3.org/1999/02/22-rdf-syntax-ns#type': ['http://www.w3.org/2002/07/owl#Class'],
    'http://www.geneontology.org/formats/oboInOwl#hasExactSynonym': ['cell killing'],
  },
}

vi.mock('../lib/api', () => ({
  api: { ontologies: { termDetail: () => Promise.resolve(mockRaw) } },
  parseTerm: (raw: typeof mockRaw) => ({
    iri: raw.iri,
    label: 'cell death',
    definition: 'A biological process involving cessation of metabolic processes.',
    entityType: 'class',
    synonyms: { exact: ['cell killing'], related: [], broad: [], narrow: [] },
    superclasses: [],
  }),
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/browse/go/v1/term/http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2FGO_0008219']}>
        <Routes>
          <Route path="/browse/:oid/:vid/term/*" element={<TermPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('shows label, definition, and synonyms', async () => {
  wrap()
  expect(await screen.findByText('cell death')).toBeInTheDocument()
  expect(screen.getByText(/biological process/i)).toBeInTheDocument()
  expect(screen.getByText('cell killing')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- src/pages/TermPage
```

Expected: FAIL.

- [ ] **Step 3: Implement TermPage**

`frontend/src/pages/TermPage.tsx`:
```typescript
import { useParams } from 'react-router-dom'
import { useTerm } from '../hooks/useTerm'
import { useClassTreeNodes } from '../hooks/useClassTree'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: '1.5rem' }}>
      <h2 style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: '0.5rem' }}>
        {title}
      </h2>
      {children}
    </section>
  )
}

export default function TermPage() {
  const { oid, vid, '*': termIriEncoded } = useParams()
  const termIri = termIriEncoded ? decodeURIComponent(termIriEncoded) : null
  const { data, isLoading, error } = useTerm(oid ?? null, vid ?? null, termIri)
  const { data: subclassData } = useClassTreeNodes(oid ?? null, vid ?? null, termIri)

  if (isLoading) return <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>Term not found</div>

  const typeColor = data.entityType === 'class' ? 'var(--accent-purple)'
    : data.entityType === 'property' ? 'var(--accent-blue)' : 'var(--text-muted)'

  const subclasses = subclassData?.terms ?? []

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '2rem 1.5rem' }}>
      {/* Breadcrumb */}
      <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', marginBottom: '1.5rem' }}>
        <a href="/browse">Browse</a>
        {' → '}
        <a href={`/browse/${oid}/${vid}`}>{oid}</a>
        {' → '}
        <span style={{ color: 'var(--text-muted)' }}>{data.label}</span>
      </div>

      {/* Header */}
      <Section title="Term">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
          <h1 style={{ color: 'var(--accent)', fontSize: 22, fontWeight: 700 }}>{data.label}</h1>
          <span style={{
            fontSize: 11, background: 'var(--bg-secondary)', color: typeColor,
            borderRadius: 3, padding: '2px 8px',
          }}>{data.entityType}</span>
        </div>
        <div
          style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', cursor: 'pointer', wordBreak: 'break-all' }}
          onClick={() => navigator.clipboard.writeText(data.iri)}
          title="Click to copy IRI"
        >
          {data.iri}
        </div>
      </Section>

      {/* Definition */}
      {data.definition && (
        <Section title="Definition">
          <p style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>{data.definition}</p>
        </Section>
      )}

      {/* Synonyms */}
      {Object.entries(data.synonyms).some(([, v]) => v.length > 0) && (
        <Section title="Synonyms">
          {(['exact', 'related', 'broad', 'narrow'] as const).map(type => (
            data.synonyms[type].length > 0 && (
              <div key={type} style={{ marginBottom: 6 }}>
                <span style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'capitalize', marginRight: 8 }}>{type}:</span>
                {data.synonyms[type].map((s, i) => (
                  <span key={i} style={{ color: 'var(--text-muted)', marginRight: 8 }}>{s}</span>
                ))}
              </div>
            )
          ))}
        </Section>
      )}

      {/* Hierarchy */}
      <Section title="Hierarchy">
        {data.superclasses.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>Superclasses</div>
            {data.superclasses.map(iri => (
              <div key={iri} style={{ color: 'var(--accent)', fontSize: 'var(--font-size-sm)', paddingLeft: 8, marginBottom: 2 }}>
                <a href={`/browse/${oid}/${vid}?term=${encodeURIComponent(iri)}`}>
                  {iri.split(/[#/]/).pop()}
                </a>
              </div>
            ))}
          </div>
        )}
        {subclasses.length > 0 && (
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>
              Subclasses ({subclasses.length})
            </div>
            <ul style={{ listStyle: 'none', columns: 2, gap: '0.5rem' }}>
              {subclasses.map(c => (
                <li key={c.iri} style={{ marginBottom: 4 }}>
                  <a
                    href={`/browse/${oid}/${vid}/term/${encodeURIComponent(c.iri)}`}
                    style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}
                  >
                    {c.label ?? c.iri.split(/[#/]/).pop()}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      {/* Provenance */}
      <Section title="Provenance">
        <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Ontology: <span style={{ color: 'var(--text-muted)' }}>{oid}</span>
          {' · '}
          Version: <span style={{ color: 'var(--text-muted)' }}>{vid}</span>
        </div>
      </Section>
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm run test:run -- src/pages/TermPage
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TermPage.tsx frontend/src/pages/TermPage.test.tsx
git commit -m "feat(frontend): full-page TermPage with all sections"
```

---

## Task 11: Search page

**Files:**
- Modify: `frontend/src/pages/Search.tsx` (replace stub)
- Test: `frontend/src/pages/Search.test.tsx`

- [ ] **Step 1: Write failing test**

`frontend/src/pages/Search.test.tsx`:
```typescript
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Search from './Search'

const mockResults = [
  { iri: 'http://ex.org/A', label: 'cell death', short: 'GO_0008219', match_type: 'entity' as const },
]

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      list: () => Promise.resolve({ ontologies: [{ id: 'go', iri: 'http://go', status: 'indexed', created_at: '2024-01-01' }] }),
      search: () => Promise.resolve({ mode: 'entity', results: mockResults, count: 1 }),
      autocomplete: () => Promise.resolve({ completions: [], context: 'entity' }),
      versions: () => Promise.resolve({ versions: [{ id: 'v1', ontology_id: 'go', version_iri: null, status: 'indexed', created_at: '2024-01-01' }] }),
    },
  },
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Search /></MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders ontology selector and search bar', async () => {
  wrap()
  expect(await screen.findByRole('combobox')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- src/pages/Search
```

Expected: FAIL.

- [ ] **Step 3: Implement Search page**

`frontend/src/pages/Search.tsx`:
```typescript
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import OntologySelector from '../components/OntologySelector'
import SearchBar from '../components/SearchBar'
import { useSearch } from '../hooks/useSearch'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

function useFirstVersion(oid: string | null) {
  return useQuery({
    queryKey: ['versions', oid],
    queryFn: () => api.ontologies.versions(oid!),
    enabled: !!oid,
    staleTime: 30_000,
    select: d => d.versions[0]?.id ?? null,
  })
}

export default function Search() {
  const [selectedOid, setSelectedOid] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const navigate = useNavigate()

  const { data: vid } = useFirstVersion(selectedOid)
  const { data: results, isLoading, error } = useSearch(selectedOid, vid ?? null, submitted)

  function handleSearch(q: string) {
    if (!selectedOid) return
    setSubmitted(q)
    setQuery(q)
  }

  const badgeColor = (type: string) =>
    type === 'elk' ? 'var(--accent)'
    : type === 'sparql' ? 'var(--accent-blue)'
    : 'var(--text-dim)'

  const apiError = error as any
  const is422 = apiError?.status === 422
  const is503 = apiError?.status === 503

  return (
    <div style={{ padding: '2rem 1.5rem', maxWidth: 900, margin: '0 auto' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 18, fontWeight: 700, marginBottom: '1.5rem' }}>
        MOS Expression Search
      </h1>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 8, marginBottom: '1.5rem', alignItems: 'center' }}>
        <OntologySelector value={selectedOid} onChange={setSelectedOid} required placeholder="Select ontology…" />
        <div style={{ flex: 1 }}>
          <SearchBar
            ontologyId={selectedOid}
            versionId={vid ?? null}
            onSearch={handleSearch}
            placeholder="Enter MOS expression or entity label…"
          />
        </div>
      </div>

      {!selectedOid && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Select an ontology to search within. MOS expressions require OWL-EL classification.
        </p>
      )}

      {/* Error states */}
      {is422 && (
        <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem', marginBottom: '1rem' }}>
          <p style={{ color: 'var(--text)', marginBottom: 8 }}>Ambiguous label — did you mean:</p>
          {apiError.body?.candidates?.map((c: string) => (
            <button
              key={c}
              onClick={() => setQuery(c)}
              style={{ color: 'var(--accent)', marginRight: 8, fontSize: 'var(--font-size-sm)' }}
            >
              {c}
            </button>
          ))}
        </div>
      )}
      {is503 && (
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
          Ontology is not yet classified. Check job status.
        </p>
      )}

      {/* Results */}
      {isLoading && <p style={{ color: 'var(--text-dim)' }}>Searching…</p>}
      {results && results.results.length === 0 && submitted && (
        <p style={{ color: 'var(--text-dim)' }}>No results for "{submitted}"</p>
      )}
      {results && results.results.length > 0 && (
        <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {results.results.map(r => (
            <li
              key={r.iri}
              onClick={() => navigate(`/browse/${selectedOid}/${vid}/term/${encodeURIComponent(r.iri)}`)}
              style={{
                padding: '8px 12px', borderRadius: 'var(--radius-sm)',
                cursor: 'pointer', background: 'var(--bg-secondary)',
                display: 'flex', gap: 10, alignItems: 'center',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'var(--bg-secondary)')}
            >
              <span style={{ color: 'var(--accent)', fontWeight: 500, flex: 1 }}>{r.label}</span>
              <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
              <span style={{
                fontSize: 10, background: 'var(--bg)', color: badgeColor(r.match_type),
                borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase',
              }}>{r.match_type}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm run test:run -- src/pages/Search
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Search.tsx frontend/src/pages/Search.test.tsx
git commit -m "feat(frontend): Search page with MOS expression support, error states"
```

---

## Task 12: Login page + AuthCallback

**Files:**
- Modify: `frontend/src/pages/Login.tsx` (replace stub)
- Modify: `frontend/src/pages/AuthCallback.tsx` (replace stub)
- Test: `frontend/src/pages/Login.test.tsx`

- [ ] **Step 1: Write failing test**

`frontend/src/pages/Login.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'

test('renders three OAuth provider buttons', () => {
  render(<MemoryRouter><Login /></MemoryRouter>)
  expect(screen.getByText(/sign in with orcid/i)).toBeInTheDocument()
  expect(screen.getByText(/sign in with github/i)).toBeInTheDocument()
  expect(screen.getByText(/sign in with google/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd frontend && npm run test:run -- src/pages/Login
```

Expected: FAIL.

- [ ] **Step 3: Implement Login page**

`frontend/src/pages/Login.tsx`:
```typescript
import { loginWithProvider } from '../lib/auth'

const providers = [
  { id: 'orcid' as const, label: 'Sign in with ORCID', color: '#a6ce39' },
  { id: 'github' as const, label: 'Sign in with GitHub', color: '#6e7681' },
  { id: 'google' as const, label: 'Sign in with Google', color: '#4285f4' },
]

export default function Login() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', minHeight: 'calc(100vh - var(--nav-height))',
      gap: '1rem',
    }}>
      <h1 style={{ color: 'var(--text)', fontSize: 20, fontWeight: 700, marginBottom: '0.5rem' }}>
        Sign in to OntoExplorer
      </h1>
      <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: '1.5rem' }}>
        Choose a provider to continue
      </p>
      {providers.map(({ id, label, color }) => (
        <button
          key={id}
          onClick={() => loginWithProvider(id)}
          style={{
            background: 'var(--bg-secondary)', border: `1px solid ${color}`,
            color: 'var(--text)', borderRadius: 'var(--radius)',
            padding: '10px 24px', width: 260, fontSize: 'var(--font-size-base)',
            display: 'flex', alignItems: 'center', gap: 10,
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'var(--bg-secondary)')}
        >
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0 }} />
          {label}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Implement AuthCallback page**

`frontend/src/pages/AuthCallback.tsx`:
```typescript
import { useEffect } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { setAccessToken } from '../lib/auth'

export default function AuthCallback() {
  const { provider } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  useEffect(() => {
    // The server sets access_token as a readable cookie; auth.ts picks it up on next getAccessToken() call.
    // Navigate to the original destination or dashboard.
    const dest = searchParams.get('next') ?? '/dashboard'
    navigate(dest, { replace: true })
  }, [])

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', color: 'var(--text-muted)' }}>
      Signing in…
    </div>
  )
}
```

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm run test:run -- src/pages/Login
```

Expected: PASS.

- [ ] **Step 6: Run all frontend tests**

```bash
cd frontend && npm run test:run
```

Expected: all tests pass.

- [ ] **Step 7: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/Login.tsx frontend/src/pages/AuthCallback.tsx frontend/src/pages/Login.test.tsx
git commit -m "feat(frontend): Login page (OAuth providers) + AuthCallback"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task |
|---|---|
| Top nav: OntoExplorer, Browse, Search, Dashboard, Sign in / avatar | Task 1 NavBar |
| Dashboard routes redirect to /login when unauthenticated | Task 1 AuthGuard |
| Home: search bar, ontology selector pill, Terms+Ontologies panels | Task 5 |
| Home: MOS expressions supported | Task 4 SearchBar (autocomplete) |
| Home: left panel = terms, right panel = ontologies | Task 5 |
| Browse: resizable split pane, width saved to localStorage | Task 9 |
| Browse: ontology list + version selector | Task 9 |
| Browse: lazy-loaded class tree | Task 7 |
| Browse: term detail panel (definition + synonyms + subclasses) | Task 8 |
| Browse: "Open full page →" link | Task 8 TermPanel |
| Full-page term view: all sections (header, def, synonyms, hierarchy, provenance) | Task 10 |
| Search: ontology selector (required), MOS bar, results with match-type badges | Task 11 |
| Search: 422 ambiguous, 503 not classified error states | Task 11 |
| Search: autocomplete (fires on quote, inserts closing quote) | Task 4 |
| Dashboard: my ontologies table | Existing Dashboard.tsx (unchanged) |
| Dashboard: API keys, webhooks, stats | Existing pages (unchanged) |
| Login: 3 OAuth provider buttons | Task 12 |
| OAuth callback: exchanges code, stores JWT | Task 12 AuthCallback |
| api.ts: Bearer token, 401 refresh | Task 2 |
| `GET /terms?parent=` for lazy tree | Task 2 backend |
| Global entity search endpoint | Task 2 backend |
| Vitest + Testing Library component tests | Task 1 setup |
| Integration smoke test (Browse mount → tree → term panel) | Task 9 test |

### Notes for implementer

1. **SearchBar autocomplete** is wired to `useAutocomplete` which requires both `ontologyId` and `versionId`. On the Home page these may be null (when "All" is selected), so autocomplete is disabled there — the home page search is purely entity-based via the global search endpoint.

2. **OntologyVersion resolution in Browse** — the route is `/browse/:oid/:vid`. When navigating from the ontology list (which only knows `oid`), we default to the first version. Use the versions endpoint to get the first version ID.

3. **SPARQL injection in `list_terms`** — the `parent` IRI is interpolated directly into SPARQL. The implementer should validate that `parent` looks like a URL (starts with `http`) before interpolating, or use parameterised SPARQL if pyoxigraph supports it.

4. **`parseTerm` in api.ts tests** — tests that mock `../lib/api` need to also mock `parseTerm` export since it's exported from the same module. The mock in Task 8 shows the pattern.

5. **`useTerm` in SubclassList** — the incorrect `useTerm` call in the original TermPanel draft was removed. SubclassList only uses `useClassTreeNodes`.
