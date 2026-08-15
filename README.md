# OntoExplorer

A next-generation FAIR ontology repository — ingest, browse, query, and reason over ontologies with full provenance tracking, semantic search, and standards-compliant APIs.

## What it does

- **Ingest** ontologies by IRI, URL, or file upload (OWL/XML, RDF/XML, Turtle, N-Triples, N-Quads, TriG, JSON-LD, OBO, Manchester, OWL Functional)
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
- **Integrate** via an OLS4-compatible read-only API (`/ols/api/...`) so existing OLS4 clients (Python `ols-client`, R `rols`, etc.) work against OntoExplorer with no code changes — see [OLS4-Compatible API](#ols4-compatible-api) below

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
                                                          ┌────────▼───────────┐
                                                          │  Reasoner service  │
                                                          │    (port 8001)     │
                                                          │ rustdl·konclude·km │
                                                          └────────────────────┘
```

**Storage split:**
| Store | Purpose |
|---|---|
| MinIO | Raw ontology files and cached `owl:imports` |
| Oxigraph (embedded) | Asserted + inferred RDF triples, SPARQL content queries (RDF-family uploads stream in as-is; Manchester/OBO/OWL-Functional are converted to Turtle first) |
| Fuseki | DCAT/VoID/PROV-O metadata, federation-ready SPARQL endpoint |
| Postgres (pgvector) | Users, versions, jobs, webhooks, API keys, annotation profiles, **term embeddings** |
| Redis | Celery broker, search/label index, stats cache, reasoner-service cache (input axioms as N-Triples, classification/justification results, per-version `.ofn`) |

Reasoning is handled by the reasoner service (rustdl / konclude / km — the legacy
rdflib and whelk reasoners have been retired). For the full format-and-storage
data flow — what is sent to Oxigraph, what is cached in Redis, and how uploads
are converted — see [`docs/ingestion-storage-reasoning.md`](docs/ingestion-storage-reasoning.md).

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

This brings up the backend services **and** a production-style nginx build of
the frontend (see step 4) — on first run it builds the frontend image, so it may
take a minute.

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
| Frontend      | http://localhost:3001      | React SPA (nginx, production build) |
| API           | http://localhost:8000      | FastAPI backend              |
| API Docs      | http://localhost:8000/api/docs | Swagger UI               |
| MinIO Console | http://localhost:9001      | Object storage (minioadmin/minioadmin) |
| Fuseki        | http://localhost:7001      | SPARQL metadata endpoint     |
| Prometheus    | http://localhost:9090      | Metrics                      |
| Grafana       | http://localhost:3000      | Dashboards                   |
| Loki          | http://localhost:3100      | Log aggregation              |

### 4. Frontend: two modes

The frontend runs in one of two forms depending on what you're doing.

**Production-style nginx build (default — started by step 2).** `docker compose
up -d` builds the SPA and serves it via **nginx at http://localhost:3001**,
identical to production. nginx also reverse-proxies `/api`, `/auth`, and `/ols`
to the API, so nothing else is needed. Use this to run the app, or to test the
real production frontend locally.

**Vite dev server (hot reload — for active frontend work).** When editing the
SPA, run Vite natively for instant hot-module reload:

```bash
cd frontend
npm install   # first time only
npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api` and `/auth`
to the API at `localhost:8000`, so no CORS configuration is needed. The nginx
frontend on 3001 can keep running alongside it, or stop it with
`docker compose stop frontend`.

> The two modes mirror the dev/prod split: **dev** = Vite dev server (live
> reload, bind-mounted source); **prod** = the nginx-built image. For a real
> production deployment (GHCR images, TLS, auto-migrations), see
> [Deploying a Tagged Release](#deploying-a-tagged-release).

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

Accepted formats: RDF/XML, OWL/XML, Turtle, N-Triples, N-Quads, TriG, JSON-LD
(parsed directly), plus OBO, Manchester, and OWL Functional (converted to Turtle
via `horned-convert` at ingest). See
[`docs/ingestion-storage-reasoning.md`](docs/ingestion-storage-reasoning.md) for
the full format/data flow.

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

The Ontologies page lists every registered ontology with its description, statistics, and group membership. A tab strip at the top switches between four fleet views:

| Tab | URL | Purpose |
|-----|-----|---------|
| **List** | `/ontologies` | The default catalog table with filtering, sorting, and OWL profile / language badges per row |
| **Coverage** | `/ontologies?tab=coverage` | Fleet-wide label / definition / multilingual coverage rollup |
| **OWL Profile** | `/ontologies?tab=profiles` | Per-ontology OWL 2 EL/RL/QL/DL conformance |
| **Compare** | `/ontologies?tab=compare` | Side-by-side diff of any two ontologies in the repository |

The legacy URLs `/coverage`, `/owl-profile`, and `/compare` redirect to the matching tab (query parameters on `/compare` are preserved, so old `?from=…&to=…` deep-links still work).

**Group filter chips** across the top of the **List** tab narrow the list to a specific collection:

| Chip | Catalog group tag | Content |
|------|-------------------|---------|
| Upper Ontology | `upper` | Foundational upper-level ontologies (BFO, CCO, DUL) |
| OBO Foundry | `obo` | OBO Foundry member ontologies (GO, CL, RO, HP, MP, DOID, UBERON, CHEBI) |
| SULO Family | `sulo_family` | Ontologies built on the SULO upper ontology (reserved; no catalog entries yet) |

Ontologies tagged `fair` (dcterms, DCAT, PROV-O, PAV, schema.org, SKOS, VoID) and `biomedical` (NCIt, ORDO, Mondo, OBI) appear in the full list but do not yet have dedicated filter chips in the browser. Colored badges on each row show all group memberships at a glance.

**OWL Profile filter chips** (a second chip row labelled `OWL Profile:`) narrow the list to ontologies that conform to a specific OWL 2 profile — EL, RL, QL, or DL. Chips are tinted in the same colour palette as the per-row badges so an active filter is unambiguous. Combine with group / language chips and free-text search for layered filtering.

**Per-row OWL Profile badges** appear to the right of each row's IRI chip — one small coloured pill per profile the ontology currently conforms to (EL/RL/QL/DL). Rows with no conforming profile show no profile badges.

**Search** (the filter bar below the chips) matches against name, IRI, and description with ranked results — exact name/IRI matches appear first, followed by partial name/IRI matches, then label matches, then description matches. Chip filter and text search compose: select chip(s) first, then type to narrow within that group.

Each row shows: name, IRI chip, group badges, OWL profile badges, language badges, description, then stats (`<n> cls · <n> obj · … · modified <date>`) on the line below. The "modified" date reflects the latest ingested version, not the original creation date. Long descriptions are clamped to three lines; click **more…** to expand.

### Coverage tab

The Coverage tab reports how well-populated each ontology is in terms of **labels**, **definitions**, and **multilingual labels**, broken out by entity type. Three summary cards show fleet-wide class coverage; below them, a sortable table lists every ontology with per-metric percentages. Clicking a row opens that ontology's detail page on a new **Coverage** tab that shows five scorecards (classes / object props / data props / annotation props / individuals) and a class-label language distribution bar.

Coverage is computed at index time using the auto-detected `label_props` / `definition_props` from each ontology's annotation profile — no extra SPARQL at request time. Zero-total cells render as `—`. Ontologies whose coverage cache hasn't been populated yet (e.g., recently submitted, not yet reindexed) are silently skipped in the rollup.

### OWL 2 profile tab

Every indexed ontology is automatically classified against the four W3C OWL 2 profiles (EL, RL, QL, DL). Detection runs in-process via SPARQL against the existing Oxigraph store at indexing time; results are cached in Redis with a 30-day TTL. The fleet view at `/ontologies?tab=profiles` shows conformance across all loaded ontologies with summary cards and a sortable table. Each ontology page has an **OWL Profile** tab listing violations grouped by axiom type, with sample violations shown for each violation category. Use the `?profile=el|rl|ql|dl` query parameter on the ontologies list endpoint to filter to ontologies conforming to a specific profile — useful for selecting ontologies suitable for a particular reasoner or query rewriter.

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

# OWL 2 profiles
GET    /owl-profile/public                       Fleet rollup: per-ontology OWL 2 profile (EL/RL/QL/DL) conformance — no auth
GET    /ontologies/{id}/{vid}/owl-profile        Per-version OWL 2 profile classification with violation details

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

## OLS4-Compatible API

OntoExplorer ships a read-only OLS4-compatible API layer mounted at `/ols/api/...` that mirrors the [EMBL-EBI Ontology Lookup Service v4](https://www.ebi.ac.uk/ols4) protocol. Existing OLS4 clients (the [`ols-client`](https://pypi.org/project/ols-client/) Python library, EBI's [`rols`](https://github.com/EBISPOT/rols) R package, custom HTTP clients) work against OntoExplorer with no code changes — just point them at `http://localhost:8000/ols/api`.

### Ontology identifier convention

All endpoints accept either the ontology's **shortname** (the canonical, OLS4-style identifier, e.g. `pets`, `go`, `mondo`) or its internal UUID in the URL path:

```bash
curl http://localhost:8000/ols/api/ontologies/pets        # shortname (preferred)
curl http://localhost:8000/ols/api/ontologies/ca02490d-…  # UUID (also works)
```

Responses always use the shortname for `ontologyId`, `preferredPrefix` (upper-cased shortname), and `_links/self`. Shortnames are auto-derived from the ontology IRI on ingest and guaranteed unique; admin can rename via `PATCH /ontologies/{id}`.

### Endpoint families (78 routes total — see Swagger UI for full reference)

```
# v1 HAL (mimics EBI OLS4 protocol, paginated HAL+JSON envelopes)
GET    /ols/api/ontologies                                           Paged ontology list
GET    /ols/api/ontologies/{ont}                                     Ontology detail
GET    /ols/api/ontologies/{ont}/terms                               Paged term list (classes)
GET    /ols/api/ontologies/{ont}/terms/{double-encoded-iri}          Term detail (IRI is %25-double-encoded)
GET    /ols/api/ontologies/{ont}/terms/roots                         Root classes (no asserted parents)
GET    /ols/api/ontologies/{ont}/terms/{iri}/parents                 Asserted parents
GET    /ols/api/ontologies/{ont}/terms/{iri}/children                Asserted children
GET    /ols/api/ontologies/{ont}/terms/{iri}/ancestors               Transitive ancestors
GET    /ols/api/ontologies/{ont}/terms/{iri}/descendants             Transitive descendants
GET    /ols/api/ontologies/{ont}/terms/{iri}/hierarchicalParents     Inferred parents (ELK)
GET    /ols/api/ontologies/{ont}/terms/{iri}/hierarchicalAncestors   Inferred transitive ancestors
GET    /ols/api/ontologies/{ont}/terms/{iri}/hierarchicalDescendants Inferred transitive descendants
GET    /ols/api/ontologies/{ont}/properties[/...]                    Object/data/annotation properties (same hierarchy shape)
GET    /ols/api/ontologies/{ont}/individuals[/...]                   Named individuals
GET    /ols/api/ontologies/{ont}/download                            301 redirect to native download URL
GET    /ols/api/terms?iri=...                                        Global term lookup across ontologies
GET    /ols/api/terms/findByIdAndIsDefiningOntology?iri=...          Only hits where ontology is the defining source
GET    /ols/api/properties[?iri=...|/findByIdAndIsDefiningOntology…] (same shape as terms)

# Solr-style search
GET    /ols/api/search?q=…&ontology=…&rows=…       Faceted Solr response (numFound + docs[])
GET    /ols/api/select?q=…                         Lightweight type-ahead variant
GET    /ols/api/suggest?q=…                        Single-field suggester

# v2 flat surface (denormalized — no HAL envelopes)
GET    /ols/api/v2/ontologies                      Flat paged list
GET    /ols/api/v2/ontologies/{ont}                Flat detail
GET    /ols/api/v2/classes | /properties | /individuals | /entities  Cross-ontology entity views
GET    /ols/api/v2/ontologies/{ont}/classes | /properties | /individuals | /entities
GET    /ols/api/v2/ontologies/{ont}/{type}/{iri}    Per-entity detail (no HAL _links)

# LLM endpoints (semantic search powered by pgvector embeddings)
GET    /ols/api/v2/llm_models                      List embedding models in use
GET    /ols/api/v2/llm_search?q=…                  Vector similarity over all classes
GET    /ols/api/v2/ontologies/{ont}/classes/llm_search?q=…   Restricted to one ontology
GET    /ols/api/v2/ontologies/{ont}/classes/llm_similar?iri=…  Find similar terms

# Tier-2 widgets (used by EBI's OLS UI)
GET    /ols/api/ontologies/{ont}/terms/{iri}/jstree                  Tree-node JSON for jsTree UI
GET    /ols/api/ontologies/{ont}/terms/{iri}/graph                   Graph fragment for D3 widgets

# Tier-3 (intentionally not implemented — EBI features that require infrastructure we don't have)
GET    /ols/api/ontologies/{ont}/terms/preferredRoots                501 Not Implemented
GET    /ols/api/v2/ontologies/{ont}/classes/llm_embedding            501 Not Implemented
(several others — all return a structured 501 with `feature_not_implemented` detail)
```

### Quick examples

```bash
# Paginated list of ontologies (HAL v1)
curl 'http://localhost:8000/ols/api/ontologies?page=0&size=10'

# Detail for one ontology by shortname
curl http://localhost:8000/ols/api/ontologies/pets

# Term detail — IRI must be %25-DOUBLE-encoded in the path
# http://example.org/pets/Dog → http%3A%2F%2Fexample.org%2Fpets%2FDog (single)
#                              → http%253A%252F%252Fexample.org%252Fpets%252FDog (double)
curl 'http://localhost:8000/ols/api/ontologies/pets/terms/http%253A%252F%252Fexample.org%252Fpets%252FDog'

# Solr-style search across all ontologies, restricted to pets
curl 'http://localhost:8000/ols/api/search?q=dog&ontology=pets&rows=5'

# Vector semantic search
curl 'http://localhost:8000/ols/api/v2/llm_search?q=feathered+animal&size=5'
```

### Programmatic access

```python
# pip install ols-client
from ols_client import OLSClient
ols = OLSClient(base_url='http://localhost:8000/ols/api')
print([o['ontologyId'] for o in ols.list_ontologies()])
print(ols.get_term('pets', 'http://example.org/pets/Dog'))
```

### Full API reference

The complete OpenAPI 3.1 spec — every endpoint, parameter, response schema — is auto-generated and available at:

- **Swagger UI:** [http://localhost:8000/api/docs](http://localhost:8000/api/docs) (filter the sidebar by tags starting with `ols-`)
- **ReDoc:** [http://localhost:8000/api/redoc](http://localhost:8000/api/redoc)
- **Raw spec:** [http://localhost:8000/api/openapi.json](http://localhost:8000/api/openapi.json)

For the upstream OLS4 protocol reference (the spec our endpoints mimic), see EBI's live docs at [https://www.ebi.ac.uk/ols4/api/v2/swagger-ui/index.html](https://www.ebi.ac.uk/ols4/api/v2/swagger-ui/index.html).

### Compliance audit vs EBI

A small contract test in `tests/integration/ols/test_ebi_compliance.py` validates our response shapes against snapshots of real EBI OLS4 responses (cached in `tests/fixtures/ols4_ebi_samples/`). For each fixture it walks every key EBI returns and asserts our response has the same key — extra fields are fine, missing fields count as a gap. A `KNOWN_GAPS` dict at the top of the test documents the current gap count per fixture; the test fails if the count changes in either direction (regression or — better — a closed gap that just needs the count updated).

**Current baseline:** 37 gaps across 7 fixtures (down from an initial 110). Two endpoints (`ontology_detail_v1`, `search`) are fully shape-compliant; one (`ontologies_list_v1`) has a single `_links.next` gap that only appears under multi-page tests. The remaining 30 gaps are concentrated in the v2 flat surface — partly populated in production via the Oxigraph document-metadata pass-through (blank in the local test env), partly the `linkedEntities` sub-dict which requires enumerating every predicate referenced in the ontology's terms (deferred — not blocking client integration since v1 is the primary client surface).

Run on demand:

```bash
uv run pytest tests/integration/ols/test_ebi_compliance.py -v
```

When EBI evolves the protocol, refresh the fixtures and re-calibrate:

```bash
bash scripts/refresh_ebi_ols_fixtures.sh
uv run pytest tests/integration/ols/test_ebi_compliance.py -v   # adjust KNOWN_GAPS to match
```

### Coverage tiers

The implementation is organized in three tiers per the design spec at [docs/superpowers/specs/2026-05-18-ols4-compat-design.md](docs/superpowers/specs/2026-05-18-ols4-compat-design.md):

- **Tier 1 — Core OLS4 protocol:** ontologies, terms (including hierarchy), properties, individuals, search/select/suggest, v2 flat surface. **Implemented.**
- **Tier 2 — Widgets needed by EBI's OLS UI:** `jstree`, `graph`. **Implemented.**
- **Tier 3 — EBI-specific features that depend on infrastructure we don't have** (e.g. preferred-roots curation, persistent LLM embedding endpoint shape). Return a structured `501 Not Implemented` with `feature_not_implemented` detail so clients can distinguish "missing in this server" from a generic error.

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
    owl_profile.py               Per-version + fleet OWL 2 profile (EL/RL/QL/DL) classification endpoints
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
    owl_profile/                 OWL 2 profile detection (SPARQL-based EL/RL/QL patterns + DL structural checks), registry, cache
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

Set `AUTH_BYPASS=true` to skip OAuth entirely. The API will create a `dev@localhost` user and treat every request as authenticated. **Never use this in production.** (`ENVIRONMENT=production` refuses to boot when this is set — see `Settings.validate_production` in [ontoexplorer/config.py](ontoexplorer/config.py).)

## Deploying a Tagged Release

Push a semver tag on `main` (`0.2.0`, `v0.2.1`, etc.) and the `release.yml` workflow builds + publishes two images to GHCR:

- `ghcr.io/maastrichtu-ids/ontoexplorer-api:<tag>` — used by `api`, `worker`, `beat`.
- `ghcr.io/maastrichtu-ids/ontoexplorer-elk-service:<tag>` — the EL reasoner sidecar.

Each release publishes three tags per image: the exact version (`:0.2.0`), the floating minor (`:0.2`), and `:latest`.

### On the target machine

The target host needs docker + docker compose v2, plus a way to fetch the compose files at the release tag. The image runtimes are self-contained — no Python toolchain or source tree needed at runtime.

Because the repo is private, the compose files (and the GHCR images) both require GitHub authentication on the target. The two-step setup is:

```bash
# 1. One-time: log docker into GHCR with a PAT that has `read:packages`
echo "$GHCR_PAT" | docker login ghcr.io -u <your-gh-username> --password-stdin

# 2. Shallow-clone the repo at the release tag (only docker-compose*.yml and
#    .env.example are read at runtime; everything else is for development)
git clone --depth 1 --branch 0.2.1 git@github.com:MaastrichtU-IDS/ontoexplorer.git
cd ontoexplorer

# Populate .env from the checked-in example. Set ENVIRONMENT=production,
# a real JWT_SECRET_KEY (any long random string), and real OAuth client IDs.
cp .env.example .env && $EDITOR .env

# Pull the images and bring the stack up
IMAGE_TAG=0.2.1 docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
IMAGE_TAG=0.2.1 docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Apply database migrations
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api uv run alembic upgrade head
```

If you make the GHCR packages public (Org → Packages → package settings → Change visibility) you can skip the `docker login ghcr.io` step.

The prod overlay sets `pull_policy: always` and drops the dev-only source-tree bind mounts and `--reload` flag.

### Upgrading

```bash
# Pull the new release tag's compose files (in case docker-compose.{,prod}.yml changed)
git fetch --tags && git checkout 0.3.0

IMAGE_TAG=0.3.0 docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
IMAGE_TAG=0.3.0 docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api uv run alembic upgrade head
```

To roll back, set `IMAGE_TAG=` to the previous version and rerun `pull && up -d`. Note that alembic downgrades are not routinely tested — backward-incompatible schema changes are flagged in release notes.

### One-time GHCR setup

The first release of a package requires that the GitHub repo's "Package settings" allow `GITHUB_TOKEN` to write to GHCR. This is on by default for new repos, but for existing repos: **Settings → Actions → General → Workflow permissions → Read and write permissions**.

## License

MIT
