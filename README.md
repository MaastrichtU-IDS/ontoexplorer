# OntoExplorer

A next-generation FAIR ontology repository — ingest, browse, query, and reason over ontologies with full provenance tracking, semantic search, and standards-compliant APIs.

## What it does

- **Ingest** ontologies by IRI, URL, or file upload (OWL/XML, Turtle, RDF/XML, OBO, JSON-LD)
- **Browse** class and property hierarchies with asserted and OWL-EL inferred views; keyboard-navigable (↑↓→←→, Enter)
- **Search** across all ontologies from the home page — keyword prefix search, structured MOS expression query, and **vector semantic search** (type ≥ 3 characters to get semantically similar results alongside prefix matches); a "Searching…" indicator replaces "No results" while queries are in flight
- **Semantic search** — nomic-ai/nomic-embed-text-v1.5 embeddings stored in pgvector; cosine-similarity search over term labels, definitions, synonyms, and ontological context (superclasses/subclasses)
- **Reason** using ELK (OWL-EL) — superclasses, subclasses, consistency, justifications
- **Inspect** ontology document metadata (dcterms, pav, vann, schema.org, etc.) and VoID statistics
- **Query** via SPARQL 1.1 endpoints over both metadata (Fuseki) and content (Oxigraph)
- **Authenticate** via ORCID, GitHub, or Google OAuth 2.0
- **Profile** annotation properties per version — auto-detect which IRIs carry labels, definitions, synonyms, deprecated flags, and examples; the **Profile tab** shows every detected annotation property as a row (with its `rdfs:label` from the RDF data as the display name), lets you assign or reassign roles, and rebuilds the search index on save
- **Standardize metadata** — auto-detect which vocabulary expresses each ontology's title, description, version, license, homepage, creators, and 29 total roles (including MOD-API properties such as `mod:competencyQuestion`, `mod:reliesOn`, `mod:similar`) from the `owl:Ontology` block; confirm or override via the same **Profile tab**
- **Browse in your language** — pick a language from the global navbar picker (sourced live from indexed ontologies); class, property, and individual trees show labels in the preferred language; term detail panels filter definitions, synonyms, and annotations to that language; each tree node carries a small language badge so you always know which label variant is shown
- **Sync** ontologies automatically — hourly polling and GitHub push webhooks trigger re-ingestion when content changes
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
| Postgres (pgvector) | Users, versions, jobs, webhooks, API keys, annotation profiles, **term embeddings** |
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
docker compose exec api alembic upgrade head
```

> **WSL2 note:** New migration files created in the WSL2 filesystem are not automatically visible inside already-running Docker containers that use bind mounts. If `alembic upgrade head` reports an older revision as head, copy the missing file in first:
> ```bash
> docker compose cp alembic/versions/<revision>_<name>.py api:/app/alembic/versions/
> docker compose exec api alembic upgrade head
> ```

> **Note:** The stack uses `pgvector/pgvector:pg16` (not `postgres:16`) so the `vector` extension is available for semantic search embeddings.

Backend services:

| Service       | URL                        | Purpose                      |
|---------------|----------------------------|------------------------------|
| API           | http://localhost:8000      | FastAPI backend              |
| API Docs      | http://localhost:8000/api/docs | Swagger UI               |
| MinIO Console | http://localhost:9001      | Object storage (minioadmin/minioadmin) |
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
  -d '{"iri": "http://purl.obolibrary.org/obo/go.owl", "groups": ["obo"]}'
```

**By direct URL:**
```bash
curl -X POST http://localhost:8000/api/v1/ontologies \
  -H "Content-Type: application/json" \
  -d '{"url": "https://raw.githubusercontent.com/.../ontology.ttl", "groups": ["upper"]}'
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

## Auto-Sync

Ontologies submitted via URL can be kept in sync automatically. There are two complementary mechanisms.

### Hourly polling

Enable `auto_sync` on any ontology and Celery Beat will re-fetch its `source_url` every hour. If the SHA-256 of the fetched content differs from the stored hash a fresh ingestion is queued; if it matches, nothing happens.

```bash
# Enable auto-sync on an ontology (requires authentication)
curl -X PATCH http://localhost:8000/api/v1/ontologies/<id> \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"auto_sync": true}'
```

The `beat` Docker Compose service runs Celery Beat. It starts automatically with `docker compose up -d`.

### GitHub push webhook

For immediate sync on every push, register OntoExplorer as a webhook receiver in your GitHub repository:

1. Go to **GitHub repository → Settings → Webhooks → Add webhook**
2. Set:
   - **Payload URL**: `https://your-domain/api/v1/inbound/github`
   - **Content type**: `application/json`
   - **Secret**: a random string, e.g. `openssl rand -hex 32`
   - **Events**: _Just the push event_
3. Add the secret to `.env`:
   ```bash
   GITHUB_WEBHOOK_SECRET=<your-secret>
   ```
4. Restart the API: `docker compose up -d api`

When a push arrives, the endpoint:
1. Verifies the `X-Hub-Signature-256` HMAC header
2. Extracts all added/modified file paths from the payload
3. Reconstructs raw GitHub URLs (`https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}`)
4. Looks up any registered `OntologyVersion.source_url` that matches one of those URLs
5. Queues `ingest_ontology` for each match

Only ontologies whose `source_url` was recorded at ingestion time (i.e., submitted by URL) are eligible for webhook-triggered sync.

## Seeding a Catalog

A curated list of 22 well-known ontologies is in [`seeds/catalog.yaml`](seeds/catalog.yaml), covering upper ontologies (BFO, CCO, DUL), FAIR vocabulary (DCAT, PROV-O, schema.org, SKOS, …), OBO Foundry core (GO, CHEBI, HP, DOID, …), and biomedical/clinical ontologies (NCIt, ORDO, Mondo, OBI). Each entry carries a `group:` tag (`upper`, `obo`, `fair`, `biomedical`) that is forwarded to the API at submission time so ontologies appear in the correct filter group immediately after ingestion.

Bulk-submit them with the seed script:

```bash
# Dry run — see what would be submitted
uv run scripts/seed_ontologies.py --dry-run

# Submit all groups
uv run scripts/seed_ontologies.py --api-key oe_...

# Submit only FAIR vocabulary and upper ontologies (lighter, good starting point)
uv run scripts/seed_ontologies.py --api-key oe_... --group fair --group upper
```

The script prints `✓ queued`, `~ already registered`, or `✗ error` per entry and exits non-zero if any submission failed. Large ontologies (CHEBI, NCIt, GO) will take several minutes to ingest and are noted in the catalog. The API key must have write scope — create one via `POST /api/v1/api-keys` or `scripts/create_dev_user.py`.

## Using the Browser

### Home page (`/`)

The home page is the primary entry point for searching across all ontologies. It shows live aggregate stats and two search modes toggled via a tab bar:

**Aggregate statistics** — a row of cards shows the total count per entity type across all ready ontologies (Ontologies, Classes, Object Properties, Data Properties, Annotation Properties, Individuals, Axioms). Each card for entity types also shows a **unique** count beneath the total — the number of distinct IRIs present across all ontologies combined (computed via Redis `SUNION` over the per-version entity-type sets). Cards with a zero count are hidden.

**Keyword Search** — prefix-matches term labels, CURIEs, and IRIs against the Redis search index for every ontology that has been indexed. Results are globally re-ranked (exact label → prefix match → substring) and each hit shows the term label, its short IRI, and the source ontology name or shortname as a right-pinned pill. Semantically similar terms (vector search, when embeddings are available) appear below a divider with cosine-similarity scores.

**Structured Query** — accepts a Manchester OWL Syntax (MOS) expression such as `'cell death'`, `BFO:0000040`, or `'part of' some GO:0005623`. Results are fanned out across all ontologies in parallel and merged with global re-ranking. An ontology picker filters the search to a specific subset.

The navbar exposes an **API** link (opens `/api/docs` in a new tab) for quick access to the interactive Swagger UI.

### Browsing the catalog (`/ontologies`)

The Ontologies page lists every registered ontology with its description, statistics, and group membership.

**Group filter chips** across the top narrow the list to a specific collection:

| Chip | Catalog group tag | Content |
|------|-------------------|---------|
| Upper Ontology | `upper` | Foundational upper-level ontologies (BFO, CCO, DUL) |
| OBO Foundry | `obo` | OBO Foundry member ontologies (GO, CL, RO, HP, MP, DOID, UBERON, CHEBI) |
| SULO Family | `sulo_family` | Ontologies built on the SULO upper ontology (reserved; no catalog entries yet) |

Ontologies tagged `fair` (dcterms, DCAT, PROV-O, PAV, schema.org, SKOS, VoID) and `biomedical` (NCIt, ORDO, Mondo, OBI) appear in the full list but do not yet have dedicated filter chips in the browser. Colored badges on each row show all group memberships at a glance.

**Search** (the filter bar below the chips) matches against name, IRI, and description with ranked results — exact name/IRI matches appear first, followed by partial name/IRI matches, then label matches, then description matches. Chip filter and text search compose: select a chip first, then type to narrow within that group.

Long descriptions are clamped to three lines; click **more…** to expand.

### Coverage (`/coverage`)

The Coverage page reports how well-populated each ontology is in terms of **labels**, **definitions**, and **multilingual labels**, broken out by entity type. Three summary cards show fleet-wide class coverage; below them, a sortable table lists every ontology with per-metric percentages. Clicking a row opens that ontology's detail page on a new **Coverage** tab that shows five scorecards (classes / object props / data props / annotation props / individuals) and a class-label language distribution bar.

Coverage is computed at index time using the auto-detected `label_props` / `definition_props` from each ontology's annotation profile — no extra SPARQL at request time. Zero-total cells render as `—`. Ontologies whose coverage cache hasn't been populated yet (e.g., recently submitted, not yet reindexed) are silently skipped in the rollup.

### Navigating hierarchies

Open an ontology page (`/ontologies/<name>`) to see the class and property trees in the left panel. Click any node to load its details in the right panel.

**Left panel controls** — just below the search bar, a shared controls row contains the **Show Obsolete / Hide Obsolete** toggle (applies to all sections). Each collapsible section header (Classes, Object Properties, Data Properties) has its own **Expand / Collapse** button inline. The Classes section additionally has an **Asserted / Inferred** toggle and Object Properties has a **Show Inverses / Hide Inverses** toggle.

**Keyboard navigation** — click anywhere in a tree to give it focus, then use:

| Key | Action |
|-----|--------|
| ↓ / ↑ | Move the cursor to the next / previous visible node |
| → | Expand the focused node (no-op if already expanded or leaf) |
| ← | Collapse the focused node (no-op if already collapsed or leaf) |
| Enter | Load the focused node's details in the right panel |

The keyboard cursor (accent outline) is independent from the selected node shown in the right panel — you can arrow around freely and press Enter only when you want to navigate. Each tree section (Classes, Object Properties, Data Properties, Annotation Properties) has its own independent focus; Tab moves between them.

### Multilingual support

OntoExplorer surfaces the language-tagged literals that are already present in each ontology — it does not translate anything.

**Global language picker** — in the top-right of the navbar, click the language chip to open a dropdown that lists every language tag found across all indexed ontologies, sorted alphabetically and searchable by name or ISO code. Selecting a language stores it in `sessionStorage` and reloads the page so the preference applies immediately to every component.

**Per-tree filtering** — the selected language propagates to every tree query. If a term has a label in the preferred language, that label is shown with a small monospace badge displaying the ISO tag (e.g., `fr`). When no preferred-language label exists, the tree falls back to untagged labels, then English, then any other language.

**Term detail panel** — definitions, synonyms, and annotation values in the right panel are filtered by the same preference (preferred lang → untagged → English → all). Duplicate values that appear across multiple predicates (e.g., both `IAO:0000115` and `skos:definition` carry the same text) are collapsed to a single entry.

**Ontology statistics** — the stats panel at the top of each ontology page includes a **Languages** count showing how many distinct language tags are present in that version's search index.

**Language preference scope** — the preference is session-scoped (cleared when the browser tab closes). It does not affect API queries made outside the browser. Set a per-ontology default by editing the ontology's `preferred_lang` field via PATCH.

### Semantic Search

After indexing, each ontology version is embedded with `nomic-ai/nomic-embed-text-v1.5` (768-dimensional ONNX model, run by the Celery worker). The embedding text for each entity combines its primary label, first definition, up to 10 synonyms, and up to 5 superclass and 10 subclass labels for ontological context.

Embeddings are stored in Postgres via **pgvector** with an HNSW cosine-similarity index. At query time, the API embeds the search string and issues a vector nearest-neighbour query. Results appear in a "Semantically similar" section below prefix matches, with cosine-similarity scores (0–1).

- Semantic results are only returned when the search string is ≥ 3 characters and `semantic=true` is passed (the frontend sets this automatically).
- If embedding is still in progress for an ontology, semantic results are silently empty (prefix search is unaffected).
- The worker respects `OMP_NUM_THREADS=2` / `ONNXRUNTIME_NUM_THREADS=2` and a 3 GiB memory cap to avoid saturating the host.
- **RDFS-only vocabularies** (e.g. Schema.org, which uses `rdfs:Class` / `rdf:Property` instead of OWL types) are fully indexed and embedded. OWL-typed entities take precedence; RDFS types fill the gap for non-OWL vocabularies.

**Backfilling existing ontologies:**

```bash
# Queue embed_ontology for all ready versions that have no embeddings yet
docker compose exec api python - << 'EOF'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from ontoexplorer.modules.jobs.tasks import embed_ontology
from ontoexplorer.config import Settings

async def dispatch():
    engine = create_async_engine(Settings().database_url)
    async with AsyncSession(engine) as db:
        rows = (await db.execute(text("""
            SELECT v.id, v.ontology_id FROM versions v
            WHERE v.status = 'ready'
              AND NOT EXISTS (SELECT 1 FROM term_embeddings te WHERE te.version_id = v.id)
        """))).all()
        for v in rows:
            embed_ontology.delay(v.id, ontology_id=v.ontology_id)
        print(f"Queued {len(rows)} versions")

asyncio.run(dispatch())
EOF
```

### Searching within an ontology

Use the search bar at the top of the left panel to find classes and properties by label or CURIE. Arrow keys and Enter work in the search dropdown too. Semantic results appear below prefix matches when embeddings are available for that version.

### Asserted vs. inferred views

The Classes section header has an **Asserted / Inferred** toggle. The inferred view requires ELK reasoning to have completed for that ontology version (status shown on the ontology page). Language-filtered labels are applied to the inferred tree the same way as the asserted tree.

## Annotation Profiles

Different ontologies use different annotation properties to express the same concepts — one uses `rdfs:label`, another `skos:prefLabel`; one uses `IAO:0000115` for definitions, another `rdfs:comment`. Without knowing which properties an ontology actually uses, search indexing, rendering, and synonym lookup will silently miss data.

After each ingest, a `detect_profile` Celery task scans the ontology's named graph in Oxigraph to count how many entities carry each annotation property from a curated registry. The best-matching properties are written to an `ontology_profiles` row and passed to the search indexer — no hardcoded predicate list.

### What's detected

| Role | Curated candidates |
|------|--------------------|
| Labels | `rdfs:label`, `skos:prefLabel`, `dcterms:title`, `dc:title`, `schema:name` |
| Definitions | `IAO:0000115`, `skos:definition`, `rdfs:comment`, `dcterms:description` |
| Synonyms | `skos:altLabel`, `oboInOwl:hasExactSynonym`, `hasRelatedSynonym`, `hasBroadSynonym`, `hasNarrowSynonym` |
| Deprecated | `owl:deprecated` |
| Examples | `skos:example` |

If the ontology header declares `mod:prefLabelProperty` or `mod:definitionProperty`, those IRIs are promoted to first position. Properties used on > 5 % of classes that aren't in the registry are surfaced as **unknown** for manual role assignment.

### Reviewing and editing

Once detection completes, open the **Profile** tab on the ontology page. The editor lists every detected annotation property as a row. The primary display name for each row is the property's `rdfs:label` from the ontology's own RDF data (falling back to a short CURIE when no label is declared). A term-usage count and a role dropdown appear on each row.

Status badges:

- **Blue** — profile auto-detected.
- **Green** — user-confirmed.

Change any role assignment and click **Save and re-index** to write the updated profile and rebuild the search index.

### Pipeline

```
ingest → detect_profile → index_ontology → embed_ontology → (reason)
                ↑
   PATCH /profile → re-index → embed_ontology
```

`detect_profile` always enqueues `index_ontology` — even if detection fails, indexing proceeds using the curated registry defaults. `index_ontology` enqueues `embed_ontology` once the search index is ready.

Each step can also be triggered individually from the **Admin panel** using the per-row action buttons (↑ ingest, ↺ index, ⬡ embed, ⚙ reason), or from the API — see [Admin endpoints](#api-reference).

## Ontology Metadata Profile

Ontologies express document-level metadata using many different vocabularies — one uses `dcterms:title` for the ontology title, another `rdfs:label`; one uses `owl:versionInfo` for the version string, another `pav:version`. Without knowing which predicates are actually used, the platform cannot reliably surface a consistent title, description, or license for every ontology.

After each ingest, a `detect_meta_profile` Celery task scans the `owl:Ontology` block (or `rdfs:Class`/`rdf:Property` subject in RDFS-only vocabularies) in Oxigraph and scores candidate values for each metadata role against a curated registry. The best candidates are written to an `ontology_meta_profiles` row and used in list views, the admin panel, and ontology detail pages.

### What's detected

29 roles are detected in total (see `ontoexplorer/modules/meta_profile/registry.py`). Key roles:

| Role group | Roles |
|------------|-------|
| Identification | Title, Shortname, NS Prefix, NS URI, Version Info, Version IRI |
| Provenance | Creator, Contributor, Publisher, Created, Modified |
| Content | Description, Language, Citation |
| Access | License, Homepage |
| Relationships (MOD-API) | See Also, Is Defined By, Competency Question, Endorsed By, Relies On, Similar, Generalizes, Specializes, Known Usage, Used In Project |

For each role, a curated list of candidate IRIs is scored against the `owl:Ontology` block. All detected property IRIs are looked up via `rdfs:label` from the ontology's own RDF data and displayed by human-readable name in the editor.

### Reviewing and confirming

Auto-detected values appear on the ontology detail page under the **Profile** tab (the same tab used for annotation profiles). The metadata section shows every detected property as a row — its label, current value, and an editable role assignment. Click **Save and re-index** to persist changes and trigger re-indexing.

The bulk endpoint `GET /meta?ids=...` returns resolved metadata for multiple versions in one request and is used by the admin panel and list views.

### Pipeline

```
ingest → detect_meta_profile → (ready for display)
                ↑
   PATCH /meta → re-index
```

## API Reference

### OLS4-compatible API (/ols/api)

Mounts an OLS4-compatible read-only API at `/ols/api/...` so clients already speaking the EMBL-EBI Ontology Lookup Service v4 protocol (Zooma, `ols-client`, OxO, OLS web widgets, custom annotation pipelines) work as drop-in replacements. Base URL pattern: `https://<your-host>/ols/api/ontologies` mirrors `https://www.ebi.ac.uk/ols4/api/ontologies`.

**Four classes of differences clients should know about:**

1. **Versioning:** OntoExplorer has a multi-version model but the OLS layer exposes only the latest ready version of each ontology — a single "current" string in metadata. There is no version-switching API.
2. **IRIs in URL paths:** Double-URL-encoded per OLS4 convention (e.g. `http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FGO_0008150`). Query-param `?iri=` is single-encoded.
3. **Tier-3 stubs:** 9 endpoints return `501 Not Implemented` with `{"error": "not_implemented", "message": "...", "ols_path": "..."}`: `tag_text`, `curation_sources`, `ontologies/by-tag`, `ontologies/by-domain`, `terms/preferredRoots`, raw `llm_embedding` read (GET) and write (POST), pairwise `llm_similarity`.
4. **No auth:** all endpoints are public, matching OLS.

**Endpoints:**

- **V1 HAL (~25 routes):** `/ontologies` (list/detail), `/ontologies/{id}/download`, `/ontologies/{id}/terms` (list/detail/roots/parents/children/ancestors/descendants/hierarchicalParents/hierarchicalAncestors/hierarchicalDescendants), `/ontologies/{id}/terms/{iri}/jstree`, `/ontologies/{id}/terms/{iri}/graph`; same family for `/properties` and `/individuals`; global `/terms`, `/properties`, `/individuals` with `findByIdAndIsDefiningOntology` variants.
- **V2 flat (~23 routes):** `/v2/classes`, `/v2/properties`, `/v2/individuals`, `/v2/entities`, `/v2/ontologies/{id}/...` with hierarchy variants, `/v2/stats`, `/v2/defined-fields`.
- **Solr-style search (3 routes):** `/search`, `/select`, `/suggest` — same Solr-shaped `responseHeader/response` envelope as EBI OLS.
- **LLM endpoints (4 routes):** `/v2/llm_models`, `/v2/classes/llm_search` (global + per-ontology), `/v2/classes/{iri}/llm_similar` — backed by the existing `semantic_search` + `term_embeddings` pgvector store.

**Worked example:**

```bash
curl -s https://api.example.org/ols/api/ontologies | jq '._embedded.ontologies[0].ontologyId'
curl -s "https://api.example.org/ols/api/search?q=diabetes&rows=3" | jq '.response.numFound'
curl -s https://api.example.org/ols/api/v2/stats | jq
```

### Native REST API

Base path: `/api/v1/`

```
# Ontologies
POST   /ontologies                               Submit (IRI, URL, or file)
GET    /ontologies                               List (paginated; ?q= ranked text search; ?group= filter)
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
PATCH  /ontologies/{id}                          Update ontology (shortname, auto_sync, groups)
DELETE /ontologies/{id}                          Delete ontology and all versions
DELETE /ontologies/{id}/{vid}                    Deprecate version

# Annotation profiles
GET    /ontologies/{id}/{vid}/profile            Get annotation property profile
PATCH  /ontologies/{id}/{vid}/profile            Update profile (triggers re-index)
POST   /ontologies/{id}/{vid}/profile/detect     Re-run auto-detection
GET    /ontologies/{id}/{vid}/profile/candidates All annotation properties with usage counts

# Ontology-level metadata profile (document-level, not annotation roles)
GET    /ontologies/{id}/{vid}/meta               Resolved metadata profile (title, description, …)
PATCH  /ontologies/{id}/{vid}/meta               Update metadata profile
POST   /ontologies/{id}/{vid}/meta/detect        Re-run metadata auto-detection
GET    /ontologies/{id}/{vid}/meta/candidates    All candidate metadata values
GET    /meta                                     Bulk metadata for all versions

# Languages
GET    /languages                                All language tags present across indexed ontologies (with label counts)

# Stats
GET    /stats/public                             Aggregate counts (ontologies, classes, properties, individuals) — no auth
GET    /stats                                    Usage statistics for the authenticated user

# Coverage
GET    /coverage/public                          Fleet rollup: per-ontology label/definition/multilingual coverage — no auth
GET    /ontologies/{id}/{vid}/coverage           Per-version coverage scorecard (by entity type, with by_lang breakdown)

# Admin
GET    /admin/overview                           System overview (requires admin role)
POST   /admin/ontologies/{id}/ingest             Queue re-ingestion for one ontology (requires admin role)
POST   /admin/ontologies/{id}/index              Queue search re-index for one ontology (requires admin role)
POST   /admin/ontologies/{id}/embed              Queue embedding generation for one ontology (requires admin role)
POST   /admin/ontologies/{id}/reason             Queue OWL-EL reasoning for one ontology (requires admin role)
POST   /admin/reindex                            Queue re-index for all ingested versions (requires admin role)

# SPARQL
GET/POST /sparql                                 SPARQL over Fuseki (FAIR metadata)
GET/POST /sparql/content                         SPARQL over Oxigraph (asserted triples)

# Search
GET    /search                                   Cross-ontology entity or MOS expression search (all indexed versions)
GET    /ontologies/{id}/search                   Search within an ontology (latest indexed version)
GET    /ontologies/{id}/autocomplete             Autocomplete within an ontology (latest indexed version)

# Jobs / webhooks / API keys
GET    /jobs                                     List jobs
GET    /jobs/{id}                                Job status
POST   /webhooks                                 Register webhook
GET    /webhooks                                 List webhooks
DELETE /webhooks/{id}                            Unregister
POST   /api-keys                                 Create API key
DELETE /api-keys/{id}                            Revoke key

# Inbound
POST   /inbound/github                           GitHub push event receiver (HMAC-verified)

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
    profile.py                   Annotation profile CRUD + detection endpoints
    meta_profile.py              Ontology document metadata profile endpoints
    auth.py                      OAuth + JWT endpoints
    search.py                    Per-ontology search + autocomplete
    global_search.py             Cross-ontology search and ontology-level convenience endpoints
    jobs.py                      Job tracking
    webhooks.py                  Webhook management
    api_keys.py                  API key management
    stats.py                     Aggregate and per-user usage statistics
    coverage.py                  Per-version + fleet coverage of labels / definitions / multilingual labels
    admin.py                     Admin overview, per-ontology pipeline actions (ingest/index/embed/reason), and bulk re-index endpoints
    sparql.py                    SPARQL proxy endpoints
    inbound.py                   Inbound webhook receivers (GitHub push events)
    ols/                         OLS4-compatible read-only shim at /ols/api/... (v1 HAL + v2 flat + Solr search + LLM)
  modules/
    ingestion/                   OWL/RDF parsing pipeline (pyhornedowl + rdflib)
    metadata/                    DCAT/VoID/PROV-O generators, Fuseki writer
    storage/                     MinIO client
    content/                     Oxigraph named-graph management
    auth/                        OAuth providers, JWT sessions, FastAPI deps
    jobs/                        Celery tasks (ingest, detect_profile, index, reason, justify, poll)
    profile/                     Annotation property registry + SPARQL-based detector
    meta_profile/                Ontology document metadata registry + auto-detector
    search/                      Redis entity index (build_index, entity_lookup), fastembed embedder, pgvector semantic search; coverage.py — pure compute_coverage helper used at index time
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
| Auto-sync dedup | SHA-256 comparison before re-queue | Polling fetches the full file; comparing hash avoids spurious ingestion when nothing changed |
| GitHub sync | HMAC-SHA256 on `X-Hub-Signature-256` | Standard GitHub webhook verification; 401 on mismatch prevents replay attacks |
| Annotation profiles | SPARQL COUNT per curated IRI, stored in `ontology_profiles` table; 5 roles (label, definition, synonym, deprecated, example) | Different ontologies use different predicates for labels/definitions; auto-detection + user override avoids hardcoding; property `rdfs:label` from the RDF data shown as the display name in the editor |
| Metadata profiles | Scored candidate extraction from `owl:Ontology` block, stored in `ontology_meta_profiles`; 29 roles including MOD-API properties | Unifies title/description/license/relationships across dcterms, pav, schema.org, SKOS, MOD without hardcoding per-ontology mappings; both profile types share a single **Profile** tab |
| Language filtering | Preferred lang → untagged → English → all; dedup by value | Ontologies mix predicates (IAO:0000115, skos:definition, rdfs:comment) carrying the same text — dedup prevents repeated entries; fallback chain ensures something always renders even if the term has no label in the session language |
| Language index | Redis hash `search:entities:{vid}:langs` (lang → count) per version | Aggregated at index time; `GET /languages` sums across all versions in O(versions) without a SPARQL scan |
| Search index | Redis sorted set (lexicographic) | Sub-millisecond prefix search over 100k+ terms |
| Semantic search | fastembed + nomic-embed-text-v1.5 → pgvector HNSW cosine index | ONNX-optimised 768-dim model; no GPU required; HNSW gives sub-10ms ANN at scale; model cached on shared Docker volume so API and worker share one copy |
| Embedding text | label + definition + synonyms + superclass/subclass labels | Ontological context improves cosine similarity for domain-specific synonymy ("auntie" → Aunt) beyond pure label matching |
| Embedding resource limits | `OMP_NUM_THREADS=2`, `ONNXRUNTIME_NUM_THREADS=2`, `mem_limit=3g` | Default ONNX Runtime uses all cores (measured 800% CPU on 8-core host); limits prevent system starvation during backfill |
| RDFS entity collection | `rdfs:Class` + `rdf:Property` checked after OWL types | Enables indexing of non-OWL vocabularies (Schema.org, SKOS, etc.); OWL types take precedence so standard ontologies are unaffected |
| Inferred tree performance | Reverse `children_of` index built once per request; Redis pipeline for batch label lookups; in-process LRU cache for ELK classifications (10-min TTL, per-version lock) | GO has 67k+ classes — O(N²) child detection and per-request ELK fetches caused multi-minute loads; reverse index + cache reduces this to sub-second |
| Admin pipeline actions | Per-row buttons (ingest / index / embed / reason) inline in status cells | Avoids extra columns; action buttons are contextually co-located with the status they affect |
| Mobile layout | Single-pane, tree ↔ detail toggle | Two-pane layout unusable below 768px |

## Configuration

All settings are read from environment variables (or `.env`). Key variables:

```bash
DATABASE_URL=postgresql+asyncpg://ontoexplorer:ontoexplorer@postgres:5432/ontoexplorer
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=minio:9000
OXIGRAPH_DATA_PATH=/data/oxigraph
OXIGRAPH_READ_ONLY=true          # set in API container; worker keeps write access
FASTEMBED_CACHE_PATH=/root/.cache/fastembed  # shared volume between API and worker
ELK_SERVICE_URL=http://elk-service:8001
ELK_SERVICE_TIMEOUT=3600         # seconds — GO classification takes ~7.5 min
JWT_SECRET_KEY=change-me-in-production

# Inbound GitHub push webhook (optional — for immediate sync on push)
GITHUB_WEBHOOK_SECRET=<random-secret>

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
