# Reasoning at scale — design sketch

> **Status: forward-looking design, not current state.** Today OntoExplorer runs
> the reasoner service as a single worker with async, cache-first justification.
> That is fine for current load — **do not build the machinery below yet.** This
> records the target pattern for when "many users × many ontologies" makes the
> single-worker reasoner the bottleneck. See
> [`ingestion-storage-reasoning.md`](ingestion-storage-reasoning.md) for how the
> system works today.

## The design axis

At scale the question stops being "make one `justify` faster" and becomes "serve
many tenants over many ontologies with bounded, scalable resources." The guiding
principle:

> Reasoning results are pure functions of `(version, query, reasoner)`. So the
> read path should be **cache-first and precompute-heavy**, heavy reasoning
> should run in a **horizontally-scalable worker pool**, and in-memory state
> should exist **only** where statefulness is intrinsic — incremental sessions,
> and warm handles for the largest ontologies — behind **ontology-affinity
> routing**.

## Three tiers

### 1. Web / API tier — stateless, cache-only
Everything a user sees (is `A ⊑ B`, inferred super/subclasses, a cached
justification) is served from Redis / the search index. Never blocks on a
reasoner. Scales by adding replicas. (Already mostly true: 0.3.56 made
justification non-blocking and cached.)

### 2. Reasoning workers — horizontally scaled, sharded by ontology
Instead of one in-process cache in a single reasoner-service worker, run N
workers and route every job for a `version_id` to the **same** worker via
consistent hashing (`hash(version_id)` over a hash ring / routing key).

- Each worker **owns a subset** of ontologies and keeps a **bounded LRU of warm
  prepared handles / km sessions** for just its shard. Memory stays bounded — you
  are not holding every ontology on every worker.
- Affinity means the same process/thread reuses a handle, which satisfies the
  `unsendable` / thread-locked constraint of rustdl handles *for free* (single
  owner), and captures the warm-reuse win (warm parse + warm classification).
- Scaling out is adding shards + rebalancing the ring — a knob, not a rewrite.

### 3. Durable artifacts + cache
Per version: the `.ofn` (already cached), the full classification closure, and
justification results → Redis (hot) + MinIO (durable). A cold worker that
receives a shard on rebalance reloads a version from `.ofn` fast instead of
re-converting from N-Triples.

## Precompute vs on-demand

- **Classify once at ingest**, materialize the full sub/super hierarchy into the
  store/cache. Subsumption and hierarchy queries then become *lookups*, not
  reasoner calls — the reasoner leaves the hot path entirely.
- **Justification** cannot be precomputed for all pairs, so it stays
  **first-touch + cached** (background job → cache). At scale the large majority
  of justify requests are repeats and hit cache.

## How this resolves today's constraints

| Today | At scale |
|---|---|
| reasoner-service pinned to **1 uvicorn worker** (km sessions held in-process) | N sharded workers; each session lives on its owning shard, requests sticky-routed by `session_id` |
| rustdl handles are `unsendable` (RcStr, thread-locked) | each shard is the single owner of its handles — no cross-thread access |
| memory per large ontology | bounded LRU **per shard**, only that shard's ontologies |
| km incremental = in-process subprocess, forces single worker | session-affinity routing (`session_id → owning worker`); still a subprocess, now one shard among many |
| `PreparedOntology` reuse win (~20%) unused ([rustdl #58](https://github.com/MaastrichtU-IDS/rustdl/pull/58)) | captured via affinity as a side effect; the bigger payoff is avoiding re-parse/re-classify of huge ontologies on warm shards |

## Fairness & isolation (multi-tenant)

Heavy reasoning × many users needs:
- per-job **timeouts + memory caps**,
- a **bounded queue**,
- **per-tenant quotas / priority** so one user's giant ontology cannot starve
  others (e.g. a priority queue keyed by tenant; at most one in-flight heavy
  classify per tenant).

## Evolution path (incremental — do not build ahead of need)

1. **Now:** async + cache + single reasoner worker. Adequate. Do *not* add
   sharding.
2. **First pressure point — the single-worker ceiling.** Put km incremental
   sessions behind a **session-affinity router** so the reasoner-service can run
   multiple workers, each owning its sessions. Highest-value first step; removes
   the current scaling ceiling with the least machinery.
3. **Real scale.** Consistent-hash **shard reasoning by version**, add a
   warm-handle LRU per shard, precompute classification at ingest, and add tenant
   fairness.

## Honest caveat — keep 90% simple

For **classify / justify specifically**, results are cached, so a **stateless**
cache-first worker pool may be all that is ever needed — affinity/warm-handle
sharding only earns its complexity when (a) ontologies are large enough that
*re-loading* dominates even on a cache miss, or (b) for the intrinsically
stateful **incremental sessions**.

So the recommended split is:

- **Stateless pool** for `classify` / `justify` — simple, scales on cache.
- **Affinity-routed stateful shards** *only* for incremental sessions (and, if
  needed, warm handles for the few giant ontologies).

That confines the hard stateful/affinity machinery to the ~10% of the workload
that genuinely needs it, and keeps the rest boring.
