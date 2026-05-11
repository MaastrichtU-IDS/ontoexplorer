# OntoExplorer

A next-generation FAIR ontology repository — discover, browse, query, and reuse ontologies with full provenance tracking, semantic search, and standards-compliant APIs.

## Features

- OWL 2 ontology ingestion (via `pyhornedowl`) and RDF parsing (`rdflib`)
- Embedded SPARQL via `pyoxigraph`; scalable SPARQL via QLever
- Async REST API built with FastAPI + SQLAlchemy 2 (asyncpg)
- Background processing with Celery + Redis
- Object storage (MinIO) for ontology artefacts
- OAuth 2.0 / OIDC authentication (`authlib` + `python-jose`)
- Observability: Prometheus metrics, Grafana dashboards, Loki log aggregation

## Quickstart (local dev)

### Prerequisites

- [uv](https://docs.astral.sh/uv/) >= 0.5
- Docker + Docker Compose v2

### 1. Clone and configure

```bash
git clone <repo-url>
cd ontoexplorer
cp .env.example .env
# Edit .env as needed
```

### 2. Install Python dependencies

```bash
uv sync
```

### 3. Start the full dev stack

```bash
docker compose up -d
```

Services started:

| Service     | URL                          | Purpose                    |
|-------------|------------------------------|----------------------------|
| API         | http://localhost:8000        | FastAPI backend             |
| Docs        | http://localhost:8000/docs   | Swagger UI                  |
| MinIO UI    | http://localhost:9001        | Object storage console      |
| QLever      | http://localhost:7001        | SPARQL triplestore          |
| Prometheus  | http://localhost:9090        | Metrics                     |
| Grafana     | http://localhost:3000        | Dashboards (admin/admin)    |
| Loki        | http://localhost:3100        | Log aggregation             |

### 4. Run tests

```bash
uv run pytest
```

### 5. Run the API locally (without Docker)

```bash
uv run uvicorn ontoexplorer.api.main:app --reload
```

## Project Layout

```
ontoexplorer/           Python package
  api/                  FastAPI routers and app factory
  modules/
    ingestion/          OWL/RDF parsing pipeline
    metadata/           Ontology metadata management
    storage/            MinIO object storage client
    content/            Full-text and semantic search
    auth/               OAuth 2.0 / OIDC integration
    jobs/               Celery tasks
    webhooks/           Outbound webhook dispatcher
  clients/              External service clients
  models/               SQLAlchemy ORM models + Pydantic schemas
frontend/               React SPA (Phase 3+)
docker/
  elk-service/          ELK entity linking service (Phase 6 placeholder)
  prometheus/           Prometheus configuration
  promtail/             Promtail log shipping configuration
tests/
  integration/          Integration tests
```

## License

MIT
