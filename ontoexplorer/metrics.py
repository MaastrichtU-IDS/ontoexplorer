"""Custom Prometheus metrics for OntoExplorer."""

from prometheus_client import Counter, Gauge, Histogram

# ── Ingestion ──────────────────────────────────────────────────────────────────

ontologies_ingested_total = Counter(
    "ontoexplorer_ontologies_ingested_total",
    "Total ontologies successfully ingested",
    ["format", "duplicate"],
)

ingestion_duration_seconds = Histogram(
    "ontoexplorer_ingestion_duration_seconds",
    "Wall-clock time for the full ingestion pipeline",
    ["format"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
)

ingestion_triples = Histogram(
    "ontoexplorer_ingestion_triples",
    "Number of triples in ingested ontology",
    buckets=[100, 1_000, 10_000, 100_000, 500_000, 1_000_000, 5_000_000],
)

ingestion_errors_total = Counter(
    "ontoexplorer_ingestion_errors_total",
    "Total ingestion pipeline errors",
    ["step"],
)

# ── Reasoning ─────────────────────────────────────────────────────────────────

reasoning_jobs_total = Counter(
    "ontoexplorer_reasoning_jobs_total",
    "Total reasoning jobs by outcome",
    ["status"],
)

reasoning_duration_seconds = Histogram(
    "ontoexplorer_reasoning_duration_seconds",
    "Time taken by ELK reasoning jobs",
    buckets=[5, 30, 60, 300, 600, 1800, 3600],
)

# ── SPARQL ────────────────────────────────────────────────────────────────────

sparql_requests_total = Counter(
    "ontoexplorer_sparql_requests_total",
    "Total SPARQL requests proxied",
    ["endpoint", "method"],
)

sparql_latency_seconds = Histogram(
    "ontoexplorer_sparql_latency_seconds",
    "SPARQL proxy round-trip latency",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10],
)

sparql_errors_total = Counter(
    "ontoexplorer_sparql_errors_total",
    "Total SPARQL proxy errors",
    ["endpoint"],
)

# ── Webhook delivery ──────────────────────────────────────────────────────────

webhook_deliveries_total = Counter(
    "ontoexplorer_webhook_deliveries_total",
    "Total webhook delivery attempts",
    ["status"],
)

# ── API key usage ─────────────────────────────────────────────────────────────

api_key_requests_total = Counter(
    "ontoexplorer_api_key_requests_total",
    "Total requests authenticated with API keys",
)

# ── Celery queue depth (updated by worker heartbeat) ─────────────────────────

celery_queue_depth = Gauge(
    "ontoexplorer_celery_queue_depth",
    "Approximate number of tasks waiting in Celery queue",
    ["queue"],
)
