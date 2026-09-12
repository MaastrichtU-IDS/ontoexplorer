# Performance harnesses

Load-test tools for an OntoExplorer instance, plus the findings from the first
runs. Point them at an **isolated perf instance** (see the `ontoexplorer-perf`
overlay in the services repo) for anything write-heavy; the read probe is safe to
run gently against a live instance.

## Tools

| script | what it does |
|---|---|
| `read_capacity.py ramp` | mixed weighted read scenario, ramps concurrency, auto-aborts at the knee |
| `read_capacity.py isolate` | ramps each read endpoint alone (search/autocomplete/sparql) to find which backend caps first |
| `write_throughput.py` | submits a batch of **distinct** ontologies at once; reports per-job latency, serial throughput, and failures |
| `fleet_perf_minio.py` | in-worker classify/justify bench per ontology (see `docs/perf/`) |

All take `--base <url>`. `read_capacity.py` uses only side-effect-free, id-free
endpoints (no downloads/views — those mutate usage counters). `write_throughput.py`
needs upload rights (AUTH_BYPASS or `--token`) and mutates data.

```
python scripts/perf/read_capacity.py ramp    --base https://<instance>
python scripts/perf/read_capacity.py isolate --base https://<instance>
python scripts/perf/write_throughput.py      --base https://<instance>
```

## Findings (first run, perf instance @ 0.4.2, api `--workers 4` + cpu request 2)

**Read path**
- Light endpoints are excellent unloaded (<20 ms) and size-independent.
- **SPARQL-over-Fuseki is the read bottleneck: ~90 rps, flat across concurrency**
  (single JVM pod) — ~5× lower than the Redis-backed endpoints. SPARQL-heavy read
  load is Fuseki-bound; scaling it means scaling Fuseki, not the api.
- Redis-backed search/autocomplete peak ~400–490 rps at conc ~10, then decline —
  api-side worker saturation, not the backend.
- `--workers 4` + a CPU reservation removed the hard *collapse* a single worker
  showed (graceful degradation, no errors to conc 150), but throughput still does
  not climb past the ~conc-20 knee for a mixed load.
- `/inferred` was a >59 s spike on a 404k-triple graph (full-graph `ORDER BY`);
  fixed in 0.4.1 to an index scan — now ~0.3 s, offset-independent.

**Write path**
- Strictly **serial** by design: the sole RW Oxigraph opener is `celery -Q write
  --concurrency=1`. A burst of concurrent submits queues; wall-clock ≈ the sum of
  per-ontology costs. Serial throughput on a distinct-ontology burst was
  ~2.4 jobs/min, dominated by per-ontology reasoning time (seconds to minutes).
- Submitting the **same** ontology twice concurrently races on version creation
  (one job fails). Distinct submissions do not. Candidate for a defensive
  dedup-on-submit.

**Structural ceiling**
- The api opens Oxigraph as a read-only RocksDB secondary off the RWO volume, so
  it cannot scale horizontally (replicas pin to one node). Extra uvicorn workers
  in the one pod are the only in-place read lever; running Oxigraph as a network
  service would make the api stateless and horizontally scalable (bigger change).

## Note

Client-side latency only — the server Prometheus `/metrics` histogram is not
routed through the ingress, so these measure user-perceived latency (which is the
right signal for a capacity knee). Correlate with SigNoz traces for server-side
attribution.
