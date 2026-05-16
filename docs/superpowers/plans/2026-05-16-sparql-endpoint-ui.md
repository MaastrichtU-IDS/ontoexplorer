# SPARQL Endpoint & UI Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a process-isolated SPARQL endpoint backed by `oxigraph-server` and expose it through a YASGUI editor at `/sparql`.

**Architecture:** A new `oxigraph-sparql` Docker container runs `oxigraph/oxigraph` in `--read-only` mode against the shared `oxigraph-data` volume. The existing FastAPI `/api/v1/sparql/content` endpoint is rewritten to proxy requests to this container via `httpx` (with a 30-second timeout and a query guard that blocks SPARQL Update keywords). The frontend gains a new `/sparql` page embedding a YASGUI widget pre-configured to POST to that endpoint.

**Tech Stack:** `oxigraph/oxigraph` Docker image, `httpx` (already in deps), `@triplydb/yasgui` (new npm dep), React 18 + Vite, pytest + `unittest.mock`.

---

## File Map

| File | Action |
|---|---|
| `docker-compose.yml` | Add `oxigraph-sparql` service |
| `ontoexplorer/config.py` | Add `oxigraph_sparql_url` and `sparql_query_timeout_seconds` |
| `ontoexplorer/api/sparql.py` | Rewrite `sparql_content` handler; add `_is_update_query`; delete `_oxigraph_query` |
| `tests/unit/test_sparql_guard.py` | New — unit tests for `_is_update_query` |
| `tests/integration/test_sparql.py` | New — integration tests for endpoint guard and timeout |
| `frontend/vite.config.ts` | Add `optimizeDeps.include` for YASGUI |
| `frontend/src/pages/Sparql.tsx` | New — YASGUI page component |
| `frontend/src/App.tsx` | Add `/sparql` route |
| `frontend/src/components/NavBar.tsx` | Add SPARQL nav link |

---

## Task 1: Add `oxigraph-sparql` Docker service

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the service**

Open `docker-compose.yml` and add the following block after the `worker` service (before `minio`):

```yaml
  oxigraph-sparql:
    image: oxigraph/oxigraph
    command: serve --location /data --bind 0.0.0.0:7878 --read-only
    restart: unless-stopped
    volumes:
      - oxigraph-data:/data
```

Do **not** add a `ports:` mapping — the container is internal only. Do **not** use `:ro` on the volume mount; RocksDB secondary instances write tracking files and will fail if the filesystem is read-only.

`restart: unless-stopped` handles the cold-start case: if no ontologies have been loaded yet the RocksDB directory may not exist, causing oxigraph-server to exit. It will retry once the worker initialises the store.

- [ ] **Step 2: Verify the compose file parses**

```bash
docker compose config --quiet && echo "OK"
```

Expected: `OK` with no errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(infra): add oxigraph-sparql read-only container"
```

---

## Task 2: Add config settings

**Files:**
- Modify: `ontoexplorer/config.py`

- [ ] **Step 1: Add the two new settings**

In `ontoexplorer/config.py`, add after the `oxigraph_read_only` line:

```python
    oxigraph_sparql_url: str = "http://oxigraph-sparql:7878"
    sparql_query_timeout_seconds: int = 30
```

The default URL works in Docker Compose. For local dev without Docker, set `OXIGRAPH_SPARQL_URL=http://localhost:7878` in `.env`.

- [ ] **Step 2: Verify settings load**

```bash
python -c "from ontoexplorer.config import get_settings; s = get_settings(); print(s.oxigraph_sparql_url, s.sparql_query_timeout_seconds)"
```

Expected output:
```
http://oxigraph-sparql:7878 30
```

- [ ] **Step 3: Commit**

```bash
git add ontoexplorer/config.py
git commit -m "feat(config): add oxigraph_sparql_url and sparql_query_timeout_seconds"
```

---

## Task 3: Query guard — TDD

**Files:**
- Create: `tests/unit/test_sparql_guard.py`
- Modify: `ontoexplorer/api/sparql.py`

The guard is a pure function `_is_update_query(query: str) -> bool`. Write the tests first, watch them fail, then implement.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sparql_guard.py`:

```python
"""Unit tests for the SPARQL Update query guard."""

import pytest

from ontoexplorer.api.sparql import _is_update_query


def test_select_is_allowed():
    assert _is_update_query("SELECT * WHERE { ?s ?p ?o }") is False


def test_ask_is_allowed():
    assert _is_update_query("ASK { <http://ex.org/> ?p ?o }") is False


def test_construct_is_allowed():
    assert _is_update_query("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }") is False


def test_insert_data_is_blocked():
    assert _is_update_query("INSERT DATA { <http://ex.org/s> <http://ex.org/p> <http://ex.org/o> }") is True


def test_delete_is_blocked():
    assert _is_update_query("DELETE WHERE { ?s ?p ?o }") is True


def test_drop_graph_is_blocked():
    assert _is_update_query("DROP GRAPH <http://ex.org/g>") is True


def test_clear_is_blocked():
    assert _is_update_query("CLEAR ALL") is True


def test_load_is_blocked():
    assert _is_update_query("LOAD <http://ex.org/data>") is True


def test_create_graph_is_blocked():
    assert _is_update_query("CREATE GRAPH <http://ex.org/g>") is True


def test_case_insensitive():
    assert _is_update_query("insert data { <http://ex.org/s> <http://ex.org/p> <http://ex.org/o> }") is True


def test_commented_out_insert_is_allowed():
    query = "# INSERT DATA { <http://ex.org/s> <http://ex.org/p> <http://ex.org/o> }\nSELECT * WHERE { ?s ?p ?o }"
    assert _is_update_query(query) is False


def test_insert_in_iri_is_allowed():
    # The word INSERT appears only inside a URI, not as a keyword
    query = "SELECT * WHERE { ?s <http://ex.org/hasInsertTime> ?o }"
    assert _is_update_query(query) is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/unit/test_sparql_guard.py -v 2>&1 | head -20
```

Expected: `ImportError` or `AttributeError` — `_is_update_query` does not exist yet.

- [ ] **Step 3: Implement `_is_update_query` in `sparql.py`**

Add these imports at the top of `ontoexplorer/api/sparql.py` (after the existing imports):

```python
import re
```

Add the constant and function before the router definition:

```python
_UPDATE_RE = re.compile(
    r'\b(INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD)\b',
    re.IGNORECASE,
)


def _is_update_query(query: str) -> bool:
    stripped = re.sub(r'#[^\n]*', '', query)
    return bool(_UPDATE_RE.search(stripped))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/unit/test_sparql_guard.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_sparql_guard.py ontoexplorer/api/sparql.py
git commit -m "feat(sparql): add _is_update_query guard with unit tests"
```

---

## Task 4: Rewrite `sparql_content` to proxy via httpx

**Files:**
- Modify: `ontoexplorer/api/sparql.py`
- Create: `tests/integration/test_sparql.py`

Write the integration tests first (they will fail because the handler still uses the old in-process pyoxigraph), then replace the handler.

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_sparql.py`:

```python
"""Integration tests for the SPARQL proxy endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.anyio
async def test_sparql_content_blocks_insert(client):
    resp = await client.post(
        "/api/v1/sparql/content",
        content=b"INSERT DATA { <http://ex.org/s> <http://ex.org/p> <http://ex.org/o> }",
        headers={"content-type": "application/sparql-query"},
    )
    assert resp.status_code == 400
    assert "not permitted" in resp.json()["detail"]


@pytest.mark.anyio
async def test_sparql_content_blocks_delete(client):
    resp = await client.post(
        "/api/v1/sparql/content",
        content=b"DELETE WHERE { ?s ?p ?o }",
        headers={"content-type": "application/sparql-query"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_sparql_content_proxies_select(client):
    fake_body = b'{"results":{"bindings":[]}}'
    fake_response = MagicMock()
    fake_response.content = fake_body
    fake_response.headers = {"content-type": "application/sparql-results+json"}

    mock_post = AsyncMock(return_value=fake_response)
    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_client_instance):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=b"SELECT * WHERE { ?s ?p ?o } LIMIT 1",
            headers={
                "content-type": "application/sparql-query",
                "accept": "application/sparql-results+json",
            },
        )

    assert resp.status_code == 200
    assert resp.content == fake_body


@pytest.mark.anyio
async def test_sparql_content_returns_504_on_timeout(client):
    import httpx as _httpx

    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_client_instance):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=b"SELECT * WHERE { ?s ?p ?o }",
            headers={"content-type": "application/sparql-query"},
        )

    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()
```

- [ ] **Step 2: Run tests to see current failures**

```bash
python -m pytest tests/integration/test_sparql.py -v 2>&1 | head -30
```

Expected: `test_sparql_content_blocks_insert` and `test_sparql_content_blocks_delete` fail (guard not wired into the handler yet); the proxy tests may error differently.

- [ ] **Step 3: Rewrite `ontoexplorer/api/sparql.py`**

Replace the entire file with:

```python
"""SPARQL 1.1 proxy endpoints.

GET/POST /sparql         → Fuseki (FAIR metadata)
GET/POST /sparql/content → oxigraph-sparql container (asserted ontology triples)
"""

import re
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ontoexplorer.clients import qlever as qlever_client
from ontoexplorer import metrics
from ontoexplorer.config import get_settings

router = APIRouter(tags=["sparql"])

_DEFAULT_ACCEPT = "application/sparql-results+json"

_UPDATE_RE = re.compile(
    r'\b(INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD)\b',
    re.IGNORECASE,
)


def _is_update_query(query: str) -> bool:
    stripped = re.sub(r'#[^\n]*', '', query)
    return bool(_UPDATE_RE.search(stripped))


@router.get("/sparql", summary="SPARQL 1.1 over Fuseki metadata store")
@router.post("/sparql")
async def sparql_metadata(request: Request):
    query, accept = await _extract_query_and_accept(request)
    metrics.sparql_requests_total.labels(endpoint="qlever", method=request.method).inc()
    t0 = time.monotonic()
    try:
        body, content_type = await qlever_client.query_passthrough(query, accept)
    except Exception:
        metrics.sparql_errors_total.labels(endpoint="qlever").inc()
        raise
    finally:
        metrics.sparql_latency_seconds.labels(endpoint="qlever").observe(time.monotonic() - t0)
    return Response(content=body, media_type=content_type)


@router.get("/sparql/content", summary="SPARQL 1.1 over Oxigraph content store (asserted triples)")
@router.post("/sparql/content")
async def sparql_content(request: Request):
    query, accept = await _extract_query_and_accept(request)

    if _is_update_query(query):
        return JSONResponse(
            status_code=400,
            content={"detail": "SPARQL Update not permitted on this endpoint"},
        )

    settings = get_settings()
    metrics.sparql_requests_total.labels(endpoint="oxigraph", method=request.method).inc()
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.sparql_query_timeout_seconds) as client:
            r = await client.post(
                f"{settings.oxigraph_sparql_url}/query",
                content=query.encode(),
                headers={
                    "Content-Type": "application/sparql-query",
                    "Accept": accept,
                },
            )
        return Response(content=r.content, media_type=r.headers.get("content-type", accept))
    except httpx.TimeoutException:
        metrics.sparql_errors_total.labels(endpoint="oxigraph").inc()
        return JSONResponse(status_code=504, content={"detail": "Query timed out"})
    except Exception:
        metrics.sparql_errors_total.labels(endpoint="oxigraph").inc()
        raise
    finally:
        metrics.sparql_latency_seconds.labels(endpoint="oxigraph").observe(time.monotonic() - t0)


async def _extract_query_and_accept(request: Request) -> tuple[str, str]:
    accept = request.headers.get("accept", _DEFAULT_ACCEPT)

    if request.method == "GET":
        query = request.query_params.get("query", "")
    else:
        content_type = request.headers.get("content-type", "")
        if "application/sparql-query" in content_type:
            query = (await request.body()).decode()
        else:
            form = await request.form()
            query = form.get("query", "")  # type: ignore[arg-type]

    if not query:
        raise ValueError("Missing 'query' parameter")
    return query, accept
```

- [ ] **Step 4: Run all SPARQL tests**

```bash
python -m pytest tests/unit/test_sparql_guard.py tests/integration/test_sparql.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/sparql.py tests/integration/test_sparql.py
git commit -m "feat(sparql): proxy /sparql/content to oxigraph-server via httpx"
```

---

## Task 5: Install YASGUI and configure Vite

**Files:**
- Modify: `frontend/vite.config.ts`

- [ ] **Step 1: Install the package**

```bash
cd frontend && npm install @triplydb/yasgui
```

- [ ] **Step 2: Update `vite.config.ts` for CJS compatibility**

`@triplydb/yasgui` is a CommonJS bundle. Vite needs it listed in `optimizeDeps.include` so it is pre-bundled into ESM.

Replace the contents of `frontend/vite.config.ts` with:

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
  optimizeDeps: {
    include: ['@triplydb/yasgui'],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
```

- [ ] **Step 3: Verify the dev server starts without errors**

```bash
cd frontend && npm run dev 2>&1 | head -20
```

Expected: Vite starts on port 5173 with no import errors.

Stop with Ctrl+C.

- [ ] **Step 4: Commit**

```bash
cd frontend && git add package.json package-lock.json vite.config.ts
git commit -m "feat(frontend): install @triplydb/yasgui, configure Vite optimizeDeps"
```

---

## Task 6: Create the SPARQL page

**Files:**
- Create: `frontend/src/pages/Sparql.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/pages/Sparql.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import Yasgui from '@triplydb/yasgui'
import '@triplydb/yasgui/build/yasgui.min.css'

const DEFAULT_QUERY = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class ?label WHERE {
  ?class a owl:Class .
  OPTIONAL { ?class rdfs:label ?label }
}
LIMIT 100`

export default function Sparql() {
  const containerRef = useRef<HTMLDivElement>(null)
  const yasguiRef = useRef<Yasgui | null>(null)

  useEffect(() => {
    if (!containerRef.current || yasguiRef.current) return

    yasguiRef.current = new Yasgui(containerRef.current, {
      requestConfig: {
        endpoint: '/api/v1/sparql/content',
        method: 'POST',
        acceptHeaderSelect: 'application/sparql-results+json',
        acceptHeaderGraph: 'text/turtle',
      },
      yasqe: {
        value: DEFAULT_QUERY,
      },
    })

    return () => {
      yasguiRef.current = null
      if (containerRef.current) containerRef.current.innerHTML = ''
    }
  }, [])

  return (
    <div
      ref={containerRef}
      style={{ height: 'calc(100vh - var(--nav-height))' }}
    />
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1
```

Expected: no errors. If `@triplydb/yasgui` types are missing, add `// @ts-ignore` above the import line and re-run.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Sparql.tsx
git commit -m "feat(frontend): add Sparql page with YASGUI editor"
```

---

## Task 7: Wire routing and NavBar

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavBar.tsx`

- [ ] **Step 1: Add the route to `App.tsx`**

In `frontend/src/App.tsx`, add the import after the existing page imports:

```tsx
import Sparql from './pages/Sparql'
```

Then add the route inside `<Routes>`, after the `/search` route:

```tsx
<Route path="/sparql" element={<Shell><Sparql /></Shell>} />
```

- [ ] **Step 2: Add the NavBar link**

In `frontend/src/components/NavBar.tsx`, update the `navLinks` array:

```typescript
const navLinks = [
  { to: '/ontologies', label: 'Ontologies' },
  { to: '/sparql', label: 'SPARQL' },
]
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1
```

Expected: no errors.

- [ ] **Step 4: Smoke test in the browser**

Start the dev server:

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173/sparql`. Verify:
- The NavBar shows an "SPARQL" link
- Clicking it loads the YASGUI editor
- The default query is pre-populated
- Clicking "Run" (or pressing Ctrl+Enter) sends a request (it will fail with a network error in local dev unless the backend is running — that's expected)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/NavBar.tsx
git commit -m "feat(frontend): wire /sparql route and NavBar link"
```

---

## End-to-End Smoke Test (with full stack)

Once all tasks are complete, verify the full stack works:

- [ ] Start the stack: `docker compose up -d`
- [ ] Load at least one ontology via the admin page or API so the Oxigraph store is initialised
- [ ] Check that `oxigraph-sparql` is healthy: `docker compose logs oxigraph-sparql | tail -10` — should show `Listening for requests at http://0.0.0.0:7878`
- [ ] Open `http://localhost:5173/sparql`
- [ ] Run the default query — results table should appear
- [ ] Try `INSERT DATA { <http://ex.org/s> <http://ex.org/p> <http://ex.org/o> }` — should show an error panel with "not permitted"
