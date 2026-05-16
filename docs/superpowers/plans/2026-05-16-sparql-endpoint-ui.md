# SPARQL Endpoint & UI Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public SPARQL 1.1 query interface backed by an isolated `oxigraph-server` container and a YASGUI editor page in the React frontend.

**Architecture:** A new `oxigraph-sparql` Docker service runs `oxigraph/oxigraph` in `--read-only` mode, mounting the same `oxigraph-data` volume as the API/worker. The FastAPI `/sparql/content` endpoint is rewritten to proxy queries via `httpx` (fixing the existing sync-in-async bug) with a query guard that blocks SPARQL Update keywords. The frontend gains a `/sparql` page that mounts a YASGUI widget pointed at the proxy endpoint.

**Tech Stack:** Python / FastAPI / httpx (backend), `oxigraph/oxigraph` Docker image (triplestore), `@triplydb/yasgui` (frontend editor), React + Vite + TypeScript (frontend)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `ontoexplorer/config.py` | Add `oxigraph_sparql_url` + `sparql_query_timeout_seconds` |
| Modify | `ontoexplorer/api/sparql.py` | Replace in-process pyoxigraph with httpx proxy + query guard |
| Create | `tests/integration/test_sparql.py` | Integration tests for the SPARQL proxy endpoint |
| Modify | `docker-compose.yml` | Add `oxigraph-sparql` service |
| Create | `frontend/src/pages/Sparql.tsx` | YASGUI page component |
| Modify | `frontend/src/App.tsx` | Add `/sparql` route |
| Modify | `frontend/src/components/NavBar.tsx` | Add SPARQL nav link |

---

## Task 1: Add config settings

**Files:**
- Modify: `ontoexplorer/config.py`

- [ ] **Step 1: Add two settings after the existing `oxigraph_read_only` line**

In `ontoexplorer/config.py`, add after `oxigraph_read_only: bool = False`:

```python
    # Oxigraph SPARQL server (isolated read-only container)
    oxigraph_sparql_url: str = "http://oxigraph-sparql:7878"
    sparql_query_timeout_seconds: int = 30
```

- [ ] **Step 2: Verify the settings load without error**

```bash
cd /home/micheldumontier/code/ontoexplorer
python -c "from ontoexplorer.config import get_settings; s = get_settings(); print(s.oxigraph_sparql_url, s.sparql_query_timeout_seconds)"
```

Expected output:
```
http://oxigraph-sparql:7878 30
```

- [ ] **Step 3: Commit**

```bash
git add ontoexplorer/config.py
git commit -m "feat(sparql): add oxigraph_sparql_url and sparql_query_timeout_seconds config"
```

---

## Task 2: Rewrite sparql.py — query guard + httpx proxy

**Files:**
- Modify: `ontoexplorer/api/sparql.py`
- Create: `tests/integration/test_sparql.py`

The current `/sparql/content` handler calls pyoxigraph synchronously inside an `async` FastAPI route, blocking the event loop. This task replaces that with an `httpx.AsyncClient` proxy and adds a query guard that rejects SPARQL Update keywords.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_sparql.py`:

```python
"""Integration tests for SPARQL proxy endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.anyio
async def test_sparql_content_blocks_insert(client):
    resp = await client.post(
        "/api/v1/sparql/content",
        content=b"INSERT DATA { <http://example.org/s> <http://example.org/p> <http://example.org/o> }",
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
async def test_sparql_content_blocks_drop(client):
    resp = await client.post(
        "/api/v1/sparql/content",
        content=b"DROP ALL",
        headers={"content-type": "application/sparql-query"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_sparql_content_proxies_select(client):
    fake = MagicMock()
    fake.status_code = 200
    fake.content = b'{"results":{"bindings":[]}}'
    fake.headers = {"content-type": "application/sparql-results+json"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(return_value=fake)

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=b"SELECT * WHERE { ?s ?p ?o } LIMIT 1",
            headers={"content-type": "application/sparql-query"},
        )

    assert resp.status_code == 200
    mock_http.post.assert_called_once()
    call_args = mock_http.post.call_args
    assert "/query" in call_args.args[0]


@pytest.mark.anyio
async def test_sparql_content_timeout_returns_504(client):
    import httpx

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=b"SELECT * WHERE { ?s ?p ?o }",
            headers={"content-type": "application/sparql-query"},
        )

    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_sparql_content_get_proxies_query_param(client):
    fake = MagicMock()
    fake.status_code = 200
    fake.content = b'{"results":{"bindings":[]}}'
    fake.headers = {"content-type": "application/sparql-results+json"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(return_value=fake)

    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.get(
            "/api/v1/sparql/content",
            params={"query": "SELECT * WHERE { ?s ?p ?o } LIMIT 1"},
        )

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_sparql_comment_does_not_trigger_guard(client):
    """A SPARQL comment containing 'INSERT' must not be blocked."""
    fake = MagicMock()
    fake.status_code = 200
    fake.content = b'{"results":{"bindings":[]}}'
    fake.headers = {"content-type": "application/sparql-results+json"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.post = AsyncMock(return_value=fake)

    query = b"# INSERT is mentioned in this comment\nSELECT * WHERE { ?s ?p ?o } LIMIT 1"
    with patch("ontoexplorer.api.sparql.httpx.AsyncClient", return_value=mock_http):
        resp = await client.post(
            "/api/v1/sparql/content",
            content=query,
            headers={"content-type": "application/sparql-query"},
        )

    assert resp.status_code == 200
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd /home/micheldumontier/code/ontoexplorer
uv run pytest tests/integration/test_sparql.py -v 2>&1 | head -40
```

Expected: tests FAIL (no httpx proxy exists yet).

- [ ] **Step 3: Rewrite ontoexplorer/api/sparql.py**

Replace the entire file with:

```python
"""SPARQL 1.1 proxy endpoints.

GET/POST /sparql         → QLever/Fuseki (FAIR metadata)
GET/POST /sparql/content → oxigraph-sparql container (asserted ontology triples)
"""

import re
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ontoexplorer import metrics
from ontoexplorer.config import get_settings

router = APIRouter(tags=["sparql"])

_DEFAULT_ACCEPT = "application/sparql-results+json"

_UPDATE_RE = re.compile(
    r"\b(INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD)\b",
    re.IGNORECASE,
)


def _check_query_guard(query: str) -> None:
    """Raise ValueError if query contains SPARQL Update keywords."""
    stripped = re.sub(r"#[^\n]*", "", query)
    if _UPDATE_RE.search(stripped):
        raise ValueError("SPARQL Update not permitted")


@router.get("/sparql", summary="SPARQL 1.1 over QLever metadata store")
@router.post("/sparql")
async def sparql_metadata(request: Request):
    query, accept = await _extract_query_and_accept(request)
    metrics.sparql_requests_total.labels(endpoint="qlever", method=request.method).inc()
    t0 = time.monotonic()
    try:
        from ontoexplorer.clients import qlever as qlever_client
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

    try:
        _check_query_guard(query)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    settings = get_settings()
    metrics.sparql_requests_total.labels(endpoint="oxigraph", method=request.method).inc()
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.sparql_query_timeout_seconds) as http:
            resp = await http.post(
                f"{settings.oxigraph_sparql_url}/query",
                content=query.encode(),
                headers={"Content-Type": "application/sparql-query", "Accept": accept},
            )
        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", accept),
        )
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

- [ ] **Step 4: Run tests and confirm they pass**

```bash
cd /home/micheldumontier/code/ontoexplorer
uv run pytest tests/integration/test_sparql.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
cd /home/micheldumontier/code/ontoexplorer
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: no previously-passing tests now fail.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/sparql.py tests/integration/test_sparql.py
git commit -m "feat(sparql): proxy /sparql/content via httpx with query guard and timeout"
```

---

## Task 3: Add oxigraph-sparql Docker service

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the new service after the `qlever` service block**

In `docker-compose.yml`, insert after the `qlever:` service block (before `postgres:`):

```yaml
  oxigraph-sparql:
    image: oxigraph/oxigraph
    command: serve --location /data --bind 0.0.0.0:7878 --read-only
    restart: unless-stopped
    volumes:
      - oxigraph-data:/data
```

No `ports:` mapping — the service is internal only, reachable at `http://oxigraph-sparql:7878` from the `api` container. The `restart: unless-stopped` policy handles the case where the service starts before the RocksDB directory is initialised by the API or worker.

- [ ] **Step 2: Verify the compose file is valid**

```bash
cd /home/micheldumontier/code/ontoexplorer
docker compose config --quiet && echo "compose OK"
```

Expected output: `compose OK`

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(sparql): add oxigraph-sparql read-only Docker service"
```

---

## Task 4: Install YASGUI

**Files:**
- Modify: `frontend/package.json` (via npm install)

- [ ] **Step 1: Install the package**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npm install @triplydb/yasgui
```

Expected: `@triplydb/yasgui` appears in `package.json` dependencies.

- [ ] **Step 2: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(sparql): add @triplydb/yasgui dependency"
```

---

## Task 5: Create Sparql.tsx page

**Files:**
- Create: `frontend/src/pages/Sparql.tsx`

YASGUI is a vanilla JS library. Mount it in a React `useEffect` on a `div` ref; destroy it on unmount. `persistenceId: null` disables YASGUI's localStorage tab-persistence so the page always opens with the default query.

- [ ] **Step 1: Create the component**

Create `frontend/src/pages/Sparql.tsx`:

```tsx
import { useEffect, useRef } from 'react'
// @ts-expect-error — @triplydb/yasgui ships no bundled types in all versions
import Yasgui from '@triplydb/yasgui'
import '@triplydb/yasgui/dist/yasgui.min.css'

const DEFAULT_QUERY = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class ?label WHERE {
  ?class a owl:Class .
  OPTIONAL { ?class rdfs:label ?label }
}
LIMIT 100`

export default function Sparql() {
  const containerRef = useRef<HTMLDivElement>(null)
  const yasguiRef = useRef<InstanceType<typeof Yasgui> | null>(null)

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
      yasqe: { value: DEFAULT_QUERY },
    })

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
  }, [])

  return (
    <div style={{
      height: 'calc(100vh - var(--nav-height))',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0 }} />
    </div>
  )
}
```

- [ ] **Step 2: Check for TypeScript errors**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx tsc --noEmit 2>&1 | grep -i "sparql\|yasgui" || echo "no TS errors for Sparql/Yasgui"
```

If `Cannot find module '@triplydb/yasgui'` errors appear, create `frontend/src/declarations.d.ts`:

```ts
declare module '@triplydb/yasgui'
declare module '@triplydb/yasgui/dist/yasgui.min.css'
```

Re-run `npx tsc --noEmit` and confirm those errors are gone.

- [ ] **Step 3: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/Sparql.tsx
git add frontend/src/declarations.d.ts 2>/dev/null; true
git commit -m "feat(sparql): YASGUI-based Sparql page component"
```

---

## Task 6: Wire route and NavBar link

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavBar.tsx`

- [ ] **Step 1: Add import and route in App.tsx**

Add the import after the existing page imports in `frontend/src/App.tsx`:

```tsx
import Sparql from './pages/Sparql'
```

Add the route after the `/search` route:

```tsx
<Route path="/sparql" element={<Shell><Sparql /></Shell>} />
```

- [ ] **Step 2: Add SPARQL link in NavBar.tsx**

In `frontend/src/components/NavBar.tsx`, update the `navLinks` array:

```tsx
const navLinks = [
  { to: '/ontologies', label: 'Ontologies' },
  { to: '/sparql', label: 'SPARQL' },
]
```

- [ ] **Step 3: Type-check**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Run existing frontend tests**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npm run test:run
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/App.tsx frontend/src/components/NavBar.tsx
git commit -m "feat(sparql): add /sparql route and NavBar link"
```

---

## Verification checklist

After all tasks complete, confirm each of the following:

- [ ] `uv run pytest tests/integration/test_sparql.py -v` — all 7 tests pass
- [ ] `uv run pytest tests/ -v --tb=short` — no regressions in the full suite
- [ ] `docker compose config --quiet` — compose file is valid
- [ ] `npx tsc --noEmit` (run in `frontend/`) — zero TypeScript errors
- [ ] `npm run test:run` (run in `frontend/`) — all tests pass
- [ ] NavBar shows "SPARQL" link; it is active on `/sparql`
- [ ] YASGUI editor renders with the default SELECT query and endpoint `/api/v1/sparql/content`
- [ ] End-to-end with `docker compose up` + a loaded ontology: running the default SELECT query in YASGUI returns results in the table
