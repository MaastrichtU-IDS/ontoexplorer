# Monitoring

OntoExplorer runs a self-contained observability stack alongside the
application: **Prometheus** for metrics, **Loki** for logs, and
**Grafana** as the unified UI. All three are defined in
[docker-compose.yml](../docker-compose.yml) and come up automatically
with `docker compose up`.

## Components

### Prometheus — metrics
[http://localhost:9090](http://localhost:9090)

Time-series database. Pulls `/metrics` endpoints on a 15-second
schedule and keeps history (default ~15 days). Queried with PromQL.

- Config: [docker/prometheus/prometheus.yml](../docker/prometheus/prometheus.yml)
- Scrapes today: `prometheus` (itself) and `ontoexplorer-api` at
  `http://api:8000/metrics`.
- Target status: **Status → Targets** in the Prometheus UI, or
  `curl -s localhost:9090/api/v1/targets`.

### Loki — logs
[http://localhost:3100](http://localhost:3100) (API only; query through
Grafana)

Log database, similar shape to Prometheus but for log lines. Indexes
labels (container, stream) rather than line contents. Queried with
LogQL through Grafana.

### Promtail — log shipper
No exposed port.

Runs alongside Loki. Discovers Docker containers via
`/var/run/docker.sock` and ships their stdout/stderr to Loki, tagged
with the container name and stream.

- Config: [docker/promtail/config.yml](../docker/promtail/config.yml)
- Labels every log line with `container=<name>` and `stream=stdout|stderr`.

### Grafana — UI
[http://localhost:3000](http://localhost:3000)

Dashboards and ad-hoc queries against both Prometheus and Loki.
Anonymous read-only access is enabled
(`GF_AUTH_ANONYMOUS_ENABLED=true`); the admin login is `admin / admin`
on first use.

- Data sources auto-provisioned: [docker/grafana/provisioning/datasources/datasources.yml](../docker/grafana/provisioning/datasources/datasources.yml)
- Pre-built dashboard: **OntoExplorer** at
  [/d/ontoexplorer-main/ontoexplorer](http://localhost:3000/d/ontoexplorer-main/ontoexplorer),
  source at [docker/grafana/dashboards/ontoexplorer.json](../docker/grafana/dashboards/ontoexplorer.json).

## Metrics exposed by the API

Defined in [ontoexplorer/metrics.py](../ontoexplorer/metrics.py):

| Metric | Type | Labels | Notes |
|---|---|---|---|
| `ontoexplorer_ontologies_ingested_total` | Counter | format, duplicate | one per successful ingestion |
| `ontoexplorer_ingestion_duration_seconds` | Histogram | format | wall-clock for the full pipeline |
| `ontoexplorer_ingestion_triples` | Histogram | — | triple count per ingest |
| `ontoexplorer_ingestion_errors_total` | Counter | step | per pipeline step |
| `ontoexplorer_reasoning_jobs_total` | Counter | status | done / failed |
| `ontoexplorer_reasoning_duration_seconds` | Histogram | — | ELK classification time |
| `ontoexplorer_sparql_requests_total` | Counter | endpoint, method | endpoint is `fuseki` or `content` |
| `ontoexplorer_sparql_latency_seconds` | Histogram | endpoint | proxy round-trip |
| `ontoexplorer_sparql_errors_total` | Counter | endpoint | |
| `ontoexplorer_webhook_deliveries_total` | Counter | status | |
| `ontoexplorer_api_key_requests_total` | Counter | — | API-key authenticated requests |
| `ontoexplorer_celery_queue_depth` | Gauge | queue | currently **not written** — see Gaps |

Labelled metrics do not appear in `/metrics` output until they have
been incremented at least once with that label set. An idle metric
looks invisible — fire one request through to verify.

## Common queries

### Prometheus / PromQL

```promql
# SPARQL request rate per endpoint, last 5 min
rate(ontoexplorer_sparql_requests_total[5m])

# p95 SPARQL latency
histogram_quantile(0.95, rate(ontoexplorer_sparql_latency_seconds_bucket[5m]))

# Ingestion duration p90 by format
histogram_quantile(0.90, sum by (le, format) (rate(ontoexplorer_ingestion_duration_seconds_bucket[15m])))

# Scrape targets up (1) or down (0)
up
```

### Loki / LogQL

```logql
# Tail API logs
{container="ontoexplorer-api-1"}

# Errors only
{container="ontoexplorer-api-1"} |= "ERROR"

# Errors across the whole stack
{compose_project="ontoexplorer"} |~ "ERROR|Traceback"

# Worker logs filtered to a specific task
{container="ontoexplorer-worker-1"} |~ "ontoexplorer.index_ontology"
```

## Relationship to the admin Service Health row

The admin page's **Service Health** row (`/admin`) is point-in-time
liveness — *"is this thing answering right now?"*. Prometheus and Loki
answer the complementary questions:

- **Trends** — "is SPARQL p95 latency drifting up over the last week?",
  "did the queue depth spike around the worker restart?"
- **Forensics** — "what did the API log when that ingestion job failed
  at 14:32 yesterday?"

Service Health does not replace dashboards; dashboards do not replace
Service Health.

## Gaps

- **`ontoexplorer_celery_queue_depth` is defined but never written.**
  The admin overview reads the depth ad-hoc from Redis (`LLEN celery`).
  To track it over time in Prometheus, add a periodic Celery Beat task
  that calls `metrics.celery_queue_depth.labels(queue="celery").set(...)`
  on the API process — or expose a `/metrics` endpoint from the worker
  and add a second scrape target.
- **Worker, beat, Fuseki, ELK, Postgres, Redis are not scraped.** Only
  the API exports Prometheus metrics. Container-level CPU and memory
  would need `cadvisor`; Postgres and Redis have their own exporter
  sidecars (`postgres_exporter`, `redis_exporter`) that can be added to
  Compose if needed.
- **Loki has no retention policy configured** — it defaults to keeping
  logs indefinitely on the host filesystem. Fine for development;
  consider a retention period for any deployed instance.

## Troubleshooting

```bash
# Are scrape targets healthy?
curl -s localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health}'

# Is the API actually exposing metrics?
curl -s localhost:8000/metrics | grep -c "^ontoexplorer_"

# Is Loki ready? (transient 503s are normal during ingester join)
curl -s localhost:3100/ready

# Which containers is Promtail discovering?
curl -s 'localhost:3100/loki/api/v1/label/container/values'

# Is Grafana up and seeing its datasources?
curl -s localhost:3000/api/health
curl -s localhost:3000/api/datasources | jq '.[].name'
```
