# Design: Oxigraph as a network service (make the API horizontally scalable)

Status: proposal / scoping. Author: perf investigation follow-up, Sept 2026.

## Problem

The API cannot scale horizontally. It reads RDF content by opening the embedded
Oxigraph RocksDB store as a **read-only secondary** off the `oxigraph-data`
volume (`clients/oxigraph.py: Store.read_only(path)`), and the sole writer
(`worker-heavy`) opens it read-write off the **same RWO volume**. Because a
ReadWriteOnce volume attaches to one node, api + worker-heavy (+ worker-light)
are pinned together on one node (nodeSelector on dev, podAffinity on the retired
perf overlay). Consequences measured this quarter:

- **`replicas: 1` for api** — the whole read path is one pod. Phase-1 load tests:
  ~120 rps on one uvicorn worker; ~365 rps peak with `--workers 4`, but it
  collapses past ~conc 20 without a CPU reservation, because more workers just
  oversubscribe the one node.
- **RWO co-location fragility** — the 0.3.77 rollout stalled on multi-attach when
  pods spread across three nodes; the fix was pinning, which forecloses scale-out.
- The in-process **metadata store** (0.4.3) now has the same shape — a second RWO
  store the api opens read-only.

The API layer (HTTP, auth, serialisation, business logic) is otherwise stateless
and would scale to N replicas across nodes — the embedded RocksDB mount is the
only thing pinning it.

## Proposal

Run Oxigraph as a standalone **network SPARQL server** (the Rust `oxigraph`
binary, `oxigraph serve`) that owns the RWO volume, and have the API and workers
talk to it over HTTP instead of opening RocksDB in-process.

```
            RWO oxigraph-data ──▶ [ oxigraph-server ]  (replicas:1, owns the volume)
                                      ▲   ▲
                     SPARQL query ────┘   └──── SPARQL UPDATE / bulk load
                     (api ×N, any node)        (worker-heavy)
```

- **API becomes stateless**: drop the volume mount and the read-only-secondary
  logic; `clients/oxigraph.py` issues SPARQL query over HTTP. No node pin →
  `replicas: N` across nodes, behind the existing Service.
- **Writers** load/update via the server's HTTP API (SPARQL UPDATE for graph
  drops; the `/store?graph=…` bulk endpoint for triple loads). The `-Q write
  --concurrency=1` constraint — which exists only because RocksDB allows one
  read-write opener — can relax; the server serialises writes itself.
- **Same on-disk format**: `oxigraph serve` reads the exact RocksDB directory
  pyoxigraph writes, so the existing volume is served as-is — **no data
  migration**, and rollback is re-mounting it embedded.
- **Metadata store**: same treatment, or leave embedded (it's tiny and only the
  api reads it) — decide during the spike.

## Why this is the right lever (from the perf data)

The read ceiling today is "one api pod's embedded reads." Moving reads to a
purpose-built Rust SPARQL server (no GIL, optimised query engine) and making the
api a horizontally-scalable stateless tier moves the ceiling to "one oxigraph
server's query throughput + N api pods for HTTP/serialisation/business logic."
For read-heavy load that is a large step up, and it removes the RWO pinning that
caused real incidents.

## Costs / risks

- **A network hop per SPARQL query** — adds latency vs in-process (RocksDB reads
  are ~µs). Mitigated by co-locating the server, HTTP keep-alive, and that most
  API endpoints don't hit Oxigraph at all (search=Redis, detail=Postgres).
- **The server is still `replicas:1`** (single RWO writer/owner) — it's a new
  single point for content queries. But one optimised Rust server should out-serve
  N python embedded readers, and it can be given real CPU/memory without pinning
  the api to it.
- **Rewrite surface**: `clients/oxigraph.py` (query + every write op → HTTP),
  `clients/metadata_store.py` (if migrated), services manifests (new Deployment,
  drop mounts + nodeSelector/affinity), worker write paths. Reasoner-service is
  unaffected (talks Redis only).
- **Write throughput is already serial** (~2.4 jobs/min, reasoning-bound), so the
  server's single-writer nature costs nothing there.

## Phased plan

1. **Spike** on a throwaway perf namespace (like the metadata migration): stand up
   `oxigraph serve` on a copy of the volume, point a branch's `clients/oxigraph.py`
   at it, run the read-capacity harness with api `replicas: 3` across nodes.
   Compare rps/latency vs today's single-pod embedded numbers.
2. If it wins: migrate content reads, then writes, then (optionally) the metadata
   store; drop the RWO mounts + node pinning from the api.
3. Roll perf → dev with the same gated release/backfill discipline used for the
   Fuseki removal.

## Decision needed

Green-light the **spike** (step 1) — it's the only way to get real
horizontal-scale numbers, and it's reversible (the volume format is unchanged).
Everything past the spike is contingent on its results.

## Spike step 0 — format/protocol compatibility (validated 2026-09-13)

Before standing up any namespace, the critical assumption was tested locally:
does `oxigraph serve` read the exact RocksDB directory `pyoxigraph` writes?

- Wrote a store with **pyoxigraph 0.5.8** (a named graph `urn:ontology:o1:v1`),
  `flush()`, closed it.
- Ran **`ghcr.io/oxigraph/oxigraph:0.5.8 serve --location <that dir>`**.
- **Named-graph SPARQL query over HTTP returned the data** — the server reads the
  binding's on-disk format directly. **No migration; rollback is re-mounting the
  dir embedded.**
- **SPARQL UPDATE over HTTP** (`INSERT DATA { GRAPH … }`) returned 204 and the
  triple was queryable — writers can use the HTTP update endpoint.

So the two load-bearing assumptions (shared on-disk format, HTTP query+update)
hold. Pin the server image to the pyoxigraph minor version in the manifests.

Remaining spike work (in-cluster): a perf overlay with an `oxigraph-server`
Deployment owning the volume; a branch pointing `clients/oxigraph.py` at it over
HTTP for query + writes; api `replicas: 3` with no volume mount / node pin; run
the read-capacity harness across nodes and compare to single-pod embedded.

## Refactor inventory — scoped to the API process (2026-09-13)

Grepping the embedded-Oxigraph surface found ~113 call sites, but the key insight
is that **only the API process must become stateless** to scale to `replicas:N`.
The workers (`worker-heavy` RW, `worker-light` RO) are single-per-node by design
and can keep the embedded mount — they don't need to scale out. So the refactor
surface is just the API-process read paths, not the whole codebase.

**API process → must route to the HTTP server (the actual work):**
- `api/sparql.py` — `/sparql/content` (and `/sparql`): simplest — proxy the query
  straight to the server's `/query` and return its bytes (like the old Fuseki
  passthrough), no in-process serialisation.
- `api/ols/*` (classes_v2, individuals, ontologies, properties, terms) — the OLS
  v2 read API; `get_store().query(...)`.
- `api/ontologies.py` — `/inferred` (now `quads_for_pattern`), term/hierarchy reads.
- `api/mod.py` — MOD-API reads.
- `api/admin/health.py` — swap the store-open check for an HTTP ping.
- `modules/search/{autocomplete,evaluator}.py` — reached from the API search routes.
- `modules/{profile,meta_profile}/detector.py` — **audit each**: the `/detect`
  routes may run inline in the API (→ HTTP) or be queued to a worker (→ embedded).

**Workers → keep embedded (no change):**
- `modules/ingestion/pipeline.py`, `modules/jobs/tasks.py` — ingest/reason/purge
  (writes; the sole RW opener stays embedded, or writes via the server's HTTP
  update/load — decide in the spike).
- `modules/ingestion/import_resolver.py`, `modules/metadata/{dcat,void}.py`,
  `modules/diff/*` — all run inside worker tasks.
- `modules/search/indexer.py` — index build (worker).

**The abstraction:** replace `get_store().query(q, default_graph=…, named_graphs=…)`
and `sparql_query(q)` in the API paths with a `content_query(...)` that routes
embedded (workers) vs HTTP (API) by config (`OXIGRAPH_HTTP_ENDPOINT`); rewrite the
API's few `quads_for_pattern` scans as equivalent SPARQL so they route too. Ship
behind the flag (empty = embedded, current behaviour) so it's non-breaking and the
same image works both ways — the spike just sets the env var on the perf API.

Step 0 (above) already proved the server reads the volume and answers query+update
over HTTP, so this refactor is the remaining risk, and it's bounded to the list above.

## Update (2026-09-13): read surface done; write path must also go HTTP

**Shipped:** the whole API **read** surface now routes to an HTTP server behind
flags, with zero call-site churn:
- `clients/oxigraph.py` `_HttpStoreProxy` (returned by `get_store()` when
  `OXIGRAPH_HTTP_ENDPOINT` is set) covers `.query()`, `.quads_for_pattern()` (native
  Quads), `__len__` — the ~34+24 read sites. (#133 content SPARQL passthrough, #134 proxy.)
- `clients/metadata_store.py` `_HttpMetadataProxy` for `/sparql`. (#135.)
- All validated live against `ghcr.io/oxigraph/oxigraph:0.5.8`; embedded mode unchanged.

**Constraint found:** `oxigraph serve-read-only` documents that *"opening as
read-only while another process writes the database is undefined behavior."* So
the tempting Option B — worker keeps the embedded RW store, a `serve-read-only`
server answers the API's reads off the same volume — is **unsafe**. (The current
embedded model's API RO-secondary-alongside-writer is the same shape and works in
practice, but building a new architecture on documented UB is wrong.)

**Therefore the server must be the sole opener (RW `serve`), and the write path
must also go through HTTP** — the piece deferred until now:
- Route the *centralised* write functions in `clients/oxigraph.py` — `load_graph`,
  `bulk_load_bytes`, `append_bytes_to_graph`, `delete_graph` — to the server:
  bulk RDF load via `POST {endpoint}/store?graph=<g>`, drops via `POST /update`
  (`DROP GRAPH`). Because writes are centralised in these functions, this is
  bounded (a handful of functions), not per-call-site — provided pipeline/tasks
  don't call `store.add()/load()` directly (to audit).
- In server mode `get_store()` for workers returns the read proxy (for their
  `.query()` reads); their writes go through the routed write functions. The
  `-Q write --concurrency=1` constraint can relax (the server serialises).

**Revised remaining bricks:** (1) write path → HTTP [bounded, next]; (2) perf
namespace with a single RW `oxigraph serve` (content) + one for metadata, api
`replicas:3` with no mounts/pin, workers pointed at the servers; (3) measure read
scaling vs the ~630 rps single-pod baseline.

### Update (2026-09-13): write path done

Brick (1) is implemented and validated live against `oxigraph:0.5.8`. Both stores'
write paths now route over HTTP when their endpoint is set, flag-gated and
non-breaking (empty endpoint = embedded, unchanged):

- Content (`clients/oxigraph.py`): `load_graph`, `bulk_load_bytes`,
  `append_bytes_to_graph`, `delete_graph` branch to `_http_load_graph`
  (`POST /store?graph=<g>` for bulk load, `POST /update` `DROP SILENT GRAPH` for
  replace/delete). `get_store()` now returns the read proxy for **every** process
  when the endpoint is set — workers included — so nobody opens the embedded
  RocksDB the server owns. The two direct write sites outside the centralised
  functions were converted too: `pipeline._move_named_graph` (IRI reconcile →
  one `INSERT{…}WHERE{…}; DROP` update) and `tasks._reason_and_persist` (inferred
  graph replace → `_http_load_graph(replace=True)`).
- Metadata (`clients/metadata_store.py`): `sparql_update`, `insert_turtle`,
  `delete_graph` route to `POST /update` / `POST /store`; `flush()` is a no-op in
  server mode (the server is the sole process — nothing to make visible to a
  now-absent read-only secondary); `get_metadata_store()` returns the proxy for
  all processes when its endpoint is set.

Live checks (docker `oxigraph serve`): replace/append/bulk-load/count/delete,
graph rename, and the metadata insert/delete-where/drop cycle all return the
expected triple counts. All in-cluster clients use `trust_env=False` (never via
egress-proxy). CI covers the wiring with a mocked httpx. Next: brick (2), the
perf namespace.

### Update (2026-09-13): perf-namespace results — ceiling lifted, then moved

Validated the full stateless stack in an ephemeral `ontoexplorer-perf` namespace:
content + metadata each a single `oxigraph serve` (sole volume owner), `api`
stateless (no store mounts, no nodeSelector) spread across all 3 nodes via a
hostname `topologySpreadConstraint`, worker-heavy writing over HTTP. In-cluster
write path confirmed on 0.4.7 (bulk-load 60k triples, append, delete,
graph-rename — all correct counts).

Read throughput, query `SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 5` over a
60k-triple graph (4 parallel load-gen pods to beat a single asyncio client's
~600 rps ceiling):

| config | conc-1 latency | aggregate rps (4×conc24) |
|---|---|---|
| 0.4.7 api, per-request httpx client, r3 | 23 ms | ~345, **collapses** at conc≥32 |
| 0.4.8 api, pooled client, r1 (single pod) | 5.5 ms | **1125** |
| 0.4.8 api, pooled client, r3 | 5.5 ms | **1256** |
| oxigraph server direct (bypass api), 2 cores | — | **1508** |

Findings:
1. **The RWO single-pod ceiling is gone.** api runs `replicas:3` across three
   nodes with no store volume and no node-pin — impossible before (the embedded
   RocksDB RWO claim pinned api to one node at `replicas:1`).
2. **Connection pooling was the api-side bottleneck** (shipped in 0.4.8): a fresh
   httpx client per request cost ~18 ms of handshake (23 → 5.5 ms conc-1) and
   *collapsed* throughput under concurrency. Pooling removed both.
3. **The read ceiling has moved to the shared oxigraph server** (~1.5k rps at the
   server, ~1.26k through the api). r1 ≈ r3 because every api pod funnels to the
   one content server — SPARQL read throughput is now gated by the store, not the
   api. Even a *single* api pod (1125 rps) beats the old embedded single-pod
   baseline (~630 rps, phase-1), on a harder query.
4. **Horizontal api scaling still pays** for everything that isn't a single shared
   store read — request handling, the many Redis/Postgres-backed endpoints, TLS,
   serialisation — and for HA (3 pods survive a node loss). Scaling SPARQL reads
   further is now a *store* lever (more server CPU, or read replicas), decoupled
   from the api. That decoupling is the point of the refactor.

The perf namespace was torn down after measurement (ephemeral, not GitOps-managed).
