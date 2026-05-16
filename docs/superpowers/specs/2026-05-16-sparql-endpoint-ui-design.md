# SPARQL Endpoint & UI Editor — Design Spec

**Date:** 2026-05-16  
**Status:** Approved

---

## Overview

Add a public SPARQL 1.1 query interface to OntoExplorer, backed by a process-isolated Oxigraph server and exposed through a YASGUI editor in the frontend. The endpoint runs in a dedicated read-only container so runaway user queries cannot affect the main API process.

---

## Goals

- Let researchers run ad-hoc SPARQL queries against all loaded ontology triples
- Provide a familiar, researcher-grade editor (YASGUI) with syntax highlighting, prefix autocomplete, and formatted result rendering
- Protect the main API from performance and memory impacts of arbitrary user queries
- Keep the endpoint publicly accessible (no auth required), consistent with FAIR SPARQL endpoint conventions

---

## Architecture

```
Browser
  └─ /sparql page (YASGUI widget)
       └─ POST /api/v1/sparql/content   (FastAPI proxy)
            └─ http://oxigraph-sparql:7878/query   (oxigraph-server container, read-only)
                   └─ /data/oxigraph   (shared Docker volume, same data as main store)
```

The main API process no longer executes SPARQL in-process. The `oxigraph-sparql` container is on the internal Docker network only — not exposed to the host.

---

## Backend

### 1. New Docker service: `oxigraph-sparql`

Add to `docker-compose.yml`:

```yaml
oxigraph-sparql:
  image: oxigraph/oxigraph
  command: serve --location /data --bind 0.0.0.0:7878 --read-only
  restart: unless-stopped
  volumes:
    - oxigraph-data:/data
```

- Mounts `oxigraph-data` at `/data` (no `:ro` filesystem flag — RocksDB secondary instances write tracking files and will error if the mount is OS-level read-only)
- `--read-only` application flag is the enforced protection: no SPARQL Update permitted, RocksDB opens as a secondary instance
- Not exposed to the host (no `ports:` mapping)
- `restart: unless-stopped`: oxigraph-server will fail if the store directory does not yet exist (no ontologies loaded); the container restarts until the API or worker has initialised the RocksDB path

### 2. Config: `ontoexplorer/config.py`

Add two new settings:

```python
oxigraph_sparql_url: str = "http://oxigraph-sparql:7878"
sparql_query_timeout_seconds: int = 30
```

Local dev default for `oxigraph_sparql_url` can be `http://localhost:7878` when running oxigraph-server manually.

### 3. Rewrite `ontoexplorer/api/sparql.py`

**Current problem:** `_oxigraph_query` calls pyoxigraph synchronously in an `async` FastAPI handler, blocking the event loop. The new design removes all in-process pyoxigraph execution from this module.

**New behaviour for `/sparql/content`:**

1. Extract query string and Accept header (existing `_extract_query_and_accept` helper, unchanged)
2. Run query guard — reject any query matching Update keywords (see below)
3. Forward via `httpx.AsyncClient` to `{oxigraph_sparql_url}/query` with the configured timeout
4. Stream the response body and content-type back to the caller unchanged

**Query guard** — returns HTTP 400 before forwarding if the query (after stripping comments and leading whitespace) matches:

```
INSERT|DELETE|DROP|CLEAR|LOAD|CREATE|COPY|MOVE|ADD
```

Case-insensitive. This is defence-in-depth; the server's `--read-only` flag is the primary enforcement.

**Timeout** — `httpx.AsyncClient` is configured with `timeout=settings.sparql_query_timeout_seconds`. A timeout returns HTTP 504 to the caller with a JSON body `{"detail": "Query timed out"}`.

**`/sparql` (QLever/Fuseki metadata endpoint)** — unchanged; continues to proxy to Fuseki as before.

**`_oxigraph_query` helper** — deleted; no longer needed.

---

## Frontend

### 1. New dependency: YASGUI

```
@triplydb/yasgui
```

YASGUI bundles:
- **YASQE** — CodeMirror-based SPARQL editor with keyword/prefix autocomplete and syntax highlighting
- **YASR** — result renderer for SELECT (table), CONSTRUCT/DESCRIBE (Turtle), ASK (boolean badge)
- Default prefix autocomplete via prefix.cc

### 2. New page: `frontend/src/pages/Sparql.tsx`

A React component that:

- Mounts a YASGUI instance in a `useEffect`, destroyed on unmount
- Configures the YASGUI endpoint to `/api/v1/sparql/content`
- Sets request method to `POST` with `Content-Type: application/sparql-query`
- Seeds the editor with a default example query (list all ontology classes):

```sparql
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class ?label WHERE {
  ?class a owl:Class .
  OPTIONAL { ?class rdfs:label ?label }
}
LIMIT 100
```

- Takes full viewport height below the NavBar (no inner scroll; YASGUI manages its own layout)
- Wraps the YASGUI container `div` in a styled wrapper that inherits the app's background colour

**YASGUI configuration options set:**

| Option | Value |
|---|---|
| `endpointCatalogueOptions.getData` | returns single entry: `{ endpoint: '/api/v1/sparql/content', title: 'OntoExplorer — Ontology Content' }` |
| `requestConfig.method` | `POST` |
| `requestConfig.acceptHeaderSelect` | `application/sparql-results+json` |
| `requestConfig.acceptHeaderGraph` | `text/turtle` |
| `yasqe.value` | default query above |

No custom entity autocomplete in this iteration — YASGUI's built-in prefix/keyword autocomplete is sufficient for v1.

### 3. Route: `frontend/src/App.tsx`

Add:
```tsx
import Sparql from './pages/Sparql'
// ...
<Route path="/sparql" element={<Shell><Sparql /></Shell>} />
```

### 4. NavBar link

Add a "SPARQL" link to the NavBar alongside the existing "Search" link. No auth guard — the page is public.

---

## Error handling

| Condition | Backend response | YASGUI display |
|---|---|---|
| Empty query | 422 (existing) | YASGUI prevents submission |
| Update keyword detected | 400 `{"detail": "SPARQL Update not permitted"}` | YASR error panel |
| Query timeout (30 s) | 504 `{"detail": "Query timed out"}` | YASR error panel |
| oxigraph-sparql container down | 502 (httpx connection error → FastAPI 500) | YASR error panel |
| Valid query, empty results | 200, empty bindings | YASR "No results" |

---

## What this does NOT include (defer to later)

- Entity/IRI autocomplete from the actual ontology data (requires a completions endpoint)
- Rate limiting (add slowapi if abuse is observed)
- Query history persistence
- Named graph selector (queries run against the full store; users can filter with `FROM NAMED` or `GRAPH` clauses)
- QLever metadata endpoint exposed in the UI (only the Oxigraph content endpoint for now)
