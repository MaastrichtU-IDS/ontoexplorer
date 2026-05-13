# OntoExplorer

A next-generation FAIR ontology repository — ingest, browse, query, and reason over ontologies with full provenance tracking, semantic search, and standards-compliant APIs.

## What it does

- **Ingest** ontologies by IRI, URL, or file upload (OWL/XML, Turtle, RDF/XML, OBO, JSON-LD)
- **Browse** class and property hierarchies with asserted and OWL-EL inferred views
- **Search** terms by label, synonym, or CURIE with fast prefix-search backed by Redis
- **Reason** using ELK (OWL-EL) — superclasses, subclasses, consistency, justifications
- **Inspect** ontology document metadata (dcterms, pav, vann, schema.org, etc.) and VoID statistics
- **Query** via SPARQL 1.1 endpoints over both metadata (Fuseki) and content (Oxigraph)
- **Authenticate** via ORCID, GitHub, or Google OAuth 2.0
- **Track** ingestion jobs, register webhooks, and manage API keys

## Architecture

```
┌─────────────┐   REST/JSON    ┌─────────────────┐
│  React SPA  │ ─────────────▶ │   FastAPI API    │
│  (Vite/TS)  │                │   (port 8000)    │
└─────────────┘                └────────┬─────────┘
                                        │
              ┌─────────────────────────┼──────────────────────────┐
              ▼                         ▼                          ▼
      ┌──────────────┐        ┌──────────────────┐       ┌──────────────┐
      │   Postgres   │        │    Oxigraph      │       │    Redis     │
      │  (port 5432) │        │  (embedded RDF   │       │  (port 6379) │
      │  jobs, users │        │   triplestore)   │       │  cache/queue │
      └──────────────┘        └──────────────────┘       └──────────────┘
              ▼                         ▼                          ▼
      ┌──────────────┐        ┌──────────────────┐       ┌──────────────┐
      │    MinIO     │        │     Fuseki       │       │ Celery Worker│
      │  (port 9000) │        │  (port 7001)     │       │  (ingestion, │
      │  OWL files   │        │  FAIR metadata   │       │   reasoning) │
      └──────────────┘        └──────────────────┘       └──────────────┘
                                                                   │
                                                          ┌────────▼────────┐
                                                          │   ELK Service   │
                                                          │   (port 8001)   │
                                                          │  OWL-EL reasoner│
                                                          └─────────────────┘
```

**Storage split:**
| Store | Purpose |
|---|---|
| MinIO | Raw ontology files and cached `owl:imports` |
| Oxigraph (embedded) | Asserted + inferred RDF triples, SPARQL content queries |
| Fuseki | DCAT/VoID/PROV-O metadata, federation-ready SPARQL endpoint |
| Postgres | Users, versions, jobs, webhooks, API keys |
| Redis | Celery broker, search index, stats cache, ELK classification cache |

## Quickstart

### Prerequisites

- Docker + Docker Compose v2
- [uv](https://docs.astral.sh/uv/) >= 0.5 (Python deps)
- Node.js >= 20 + npm (frontend dev server)

### 1. Clone and configure

```bash
git clone <repo-url>
cd ontoexplorer
cp .env.example .env
# Edit .env — set OAuth credentials (ORCID/GitHub/Google) and JWT_SECRET_KEY
```

### 2. Start the backend stack

```bash
docker compose up -d
```

### 3. Run database migrations

```bash
docker compose exec api uv run alembic upgrade head
```

Backend services:

| Service       | URL                        | Purpose                      |
|---------------|----------------------------|------------------------------|
| API           | http://localhost:8000      | FastAPI backend              |
| API Docs      | http://localhost:8000/api/docs | Swagger UI               |
| MinIO Console | http://localhost:9001      | Object storage (admin/admin) |
| Fuseki        | http://localhost:7001      | SPARQL metadata endpoint     |
| Prometheus    | http://localhost:9090      | Metrics                      |
| Grafana       | http://localhost:3000      | Dashboards                   |
| Loki          | http://localhost:3100      | Log aggregation              |

### 4. Start the frontend dev server

The React SPA is not served by Docker — run it locally with Vite:

```bash
cd frontend
npm install   # first time only
npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api`, `/auth`, and `/sparql` to the FastAPI backend at `localhost:8000`, so no CORS configuration is needed.

### 5. Run tests

```bash
uv run pytest
```

## Ingesting an Ontology

**By IRI** (content-negotiated fetch):
```bash
curl -X POST http://localhost:8000/api/v1/ontologies \
  -H "Content-Type: application/json" \
  -d '{"iri": "http://purl.obolibrary.org/obo/go.owl"}'
```

**By direct URL:**
```bash
curl -X POST http://localhost:8000/api/v1/ontologies \
  -H "Content-Type: application/json" \
  -d '{"url": "https://raw.githubusercontent.com/.../ontology.ttl"}'
```

**File upload:**
```bash
curl -X POST http://localhost:8000/api/v1/ontologies \
  -F "file=@ontology.owl"
```

Check job status:
```bash
curl http://localhost:8000/api/v1/jobs/<task_id>
```

## API Reference

Base path: `/api/v1/`

```
# Ontologies
POST   /ontologies                               Submit (IRI, URL, or file)
GET    /ontologies                               List (paginated, filterable)
GET    /ontologies/{id}                          Ontology metadata
GET    /ontologies/{id}/versions                 All versions
GET    /ontologies/{id}/{vid}                    Version metadata
GET    /ontologies/{id}/{vid}/download           Download original file
GET    /ontologies/{id}/{vid}/ontology-metadata  Metadata from owl:Ontology block
GET    /ontologies/{id}/{vid}/stats              VoID statistics (cached)
GET    /ontologies/{id}/{vid}/terms              Browse terms (classes/properties)
GET    /ontologies/{id}/{vid}/terms/{iri}        Term detail with inferred relations
GET    /ontologies/{id}/{vid}/search             Full-text search
GET    /ontologies/{id}/{vid}/autocomplete       Label autocomplete
GET    /ontologies/{id}/{vid}/inferred-children  Inferred class hierarchy (ELK)
GET    /ontologies/{id}/{vid}/ancestors          Ancestor chain for tree navigation
GET    /ontologies/{id}/{vid}/consistency        OWL consistency check
POST   /ontologies/{id}/{vid}/justification      Request justification (async)
GET    /ontologies/{id}/{vid}/justification/{jid} Retrieve justification result
DELETE /ontologies/{id}                          Delete ontology and all versions
DELETE /ontologies/{id}/{vid}                    Deprecate version

# SPARQL
GET/POST /sparql                                 SPARQL over Fuseki (FAIR metadata)
GET/POST /sparql/content                         SPARQL over Oxigraph (asserted triples)

# Search
GET    /search                                   Cross-ontology entity search

# Jobs / webhooks / API keys
GET    /jobs                                     List jobs
GET    /jobs/{id}                                Job status
POST   /webhooks                                 Register webhook
GET    /webhooks                                 List webhooks
DELETE /webhooks/{id}                            Unregister
POST   /api-keys                                 Create API key
DELETE /api-keys/{id}                            Revoke key

# Auth
GET    /auth/{provider}/login                    OAuth redirect (orcid/github/google)
GET    /auth/{provider}/callback                 OAuth callback
POST   /auth/refresh                             Refresh JWT
GET    /auth/me                                  Current user

# Health
GET    /health                                   Liveness
GET    /ready                                    Readiness (checks all backends)
GET    /metrics                                  Prometheus metrics
```

## Project Layout

```
ontoexplorer/                    Python package
  api/                           FastAPI routers
    ontologies.py                Ontology, version, term, reasoning endpoints
    auth.py                      OAuth + JWT endpoints
    search.py                    Per-ontology search + autocomplete
    global_search.py             Cross-ontology search
    jobs.py                      Job tracking
    webhooks.py                  Webhook management
    api_keys.py                  API key management
    stats.py                     Usage statistics
    sparql.py                    SPARQL proxy endpoints
  modules/
    ingestion/                   OWL/RDF parsing pipeline (pyhornedowl + rdflib)
    metadata/                    DCAT/VoID/PROV-O generators, Fuseki writer
    storage/                     MinIO client
    content/                     Oxigraph named-graph management
    auth/                        OAuth providers, JWT sessions, FastAPI deps
    jobs/                        Celery tasks (ingest, index, reason, justify)
    search/                      Redis entity index (build_index, entity_lookup)
    webhooks/                    HMAC-signed outbound delivery
  clients/
    oxigraph.py                  pyoxigraph Store wrapper
    reasoning.py                 ELK service HTTP client (202-Accepted + poll)
  models/
    db.py                        SQLAlchemy ORM (Ontology, OntologyVersion, User, …)
    api.py                       Pydantic request/response schemas
  config.py                      pydantic-settings, all env vars

frontend/                        React + TypeScript SPA (Vite)
  src/
    pages/                       OntologyPage, TermPage, Search, Dashboard, …
    components/                  ClassTree, TermPanel, NavBar, ResizeHandle, …
    hooks/                       useClassTree, useInferredTree, useTerm, …
    lib/
      api.ts                     Typed fetch client with JWT refresh
      auth.ts                    OAuth redirect, token management

docker/
  elk-service/                   OWL-EL reasoning microservice (FastAPI + py4j + ELK)
  prometheus/                    Scrape config
  grafana/                       Dashboard provisioning
  promtail/                      Log shipping to Loki

tests/
  integration/                   End-to-end ingestion, auth, SPARQL tests
```

## Key Design Decisions

| Concern | Decision | Rationale |
|---|---|---|
| Content triplestore | pyoxigraph (embedded) | Rust-backed, SPARQL 1.1, no extra container; extract when concurrency demands it |
| Metadata store | Fuseki (Jena) | SPARQL 1.1 + update, DCAT/VoID native, federation-ready |
| OWL parsing | pyhornedowl + rdflib | pyhornedowl scales to SNOMED; rdflib handles Turtle/N-Triples/JSON-LD |
| Reasoning | ELK in separate Docker service | OWL-EL complete, scales to GO (67k classes); isolated from API process |
| ELK protocol | 202-Accepted + poll | Classification takes >10 min for large ontologies (GO ~7.5 min) |
| Oxigraph in FastAPI | `asyncio.to_thread` + `asyncio.gather` | `Store.query()` is synchronous; blocks event loop if called directly |
| Stats caching | Redis, pre-populated at index time | COUNT(*) over millions of triples is slow; 30-day TTL, invalidated on deprecation |
| Search index | Redis sorted set (lexicographic) | Sub-millisecond prefix search over 100k+ terms |
| Mobile layout | Single-pane, tree ↔ detail toggle | Two-pane layout unusable below 768px |

## Configuration

All settings are read from environment variables (or `.env`). Key variables:

```bash
DATABASE_URL=postgresql+asyncpg://ontoexplorer:ontoexplorer@postgres:5432/ontoexplorer
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=minio:9000
OXIGRAPH_DATA_PATH=/data/oxigraph
OXIGRAPH_READ_ONLY=true          # set in API container; worker keeps write access
ELK_SERVICE_URL=http://elk-service:8001
ELK_SERVICE_TIMEOUT=3600         # seconds — GO classification takes ~7.5 min
JWT_SECRET_KEY=change-me-in-production

# OAuth providers (fill in at least one to enable login)
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
ORCID_CLIENT_ID=...
ORCID_CLIENT_SECRET=...

# URL settings — must match your deployment
APP_URL=http://localhost:8000    # API base URL, used to build OAuth callback URIs
FRONTEND_URL=http://localhost:5173  # SPA base URL, used for post-OAuth redirects

# Development only — skips OAuth, creates a dev@localhost user automatically
AUTH_BYPASS=false
```

See `.env.example` for the full list.

## OAuth Setup

### GitHub (quickest for local dev)

1. Go to **GitHub → Settings → Developer settings → OAuth Apps → New OAuth App**
2. Set:
   - **Homepage URL**: `http://localhost:5173`
   - **Authorization callback URL**: `http://localhost:8000/auth/github/callback`
3. Copy the **Client ID** and generate a **Client Secret**
4. Add to `.env`:
   ```bash
   GITHUB_CLIENT_ID=<your-client-id>
   GITHUB_CLIENT_SECRET=<your-client-secret>
   AUTH_BYPASS=false
   ```
5. Restart the API: `docker compose up -d api`

> **SSH port forwarding**: if accessing the app over SSH, forward both ports — the browser must reach port 8000 directly for the OAuth callback to work:
> ```bash
> ssh -L 5173:localhost:5173 -L 8000:localhost:8000 user@host
> ```

### ORCID

1. Register at https://orcid.org/developer-tools (or https://sandbox.orcid.org for testing)
2. Set **Redirect URI** to `http://localhost:8000/auth/orcid/callback`
3. Add `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET` (and `ORCID_SANDBOX=true` for sandbox) to `.env`

### Google

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → Create OAuth Client ID
2. Add `http://localhost:8000/auth/google/callback` as an **Authorized redirect URI**
3. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to `.env`

### Development bypass

Set `AUTH_BYPASS=true` to skip OAuth entirely. The API will create a `dev@localhost` user and treat every request as authenticated. **Never use this in production.**

## License

MIT
