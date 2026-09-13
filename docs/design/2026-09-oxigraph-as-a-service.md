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
