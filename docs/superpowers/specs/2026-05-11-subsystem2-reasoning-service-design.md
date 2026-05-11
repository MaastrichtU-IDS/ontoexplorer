# Subsystem 2: OWL-EL Reasoning Service

**Date:** 2026-05-11  
**Status:** Approved  
**Builds on:** Subsystem 1 (FAIR Repository Core)

---

## Overview

Subsystem 2 upgrades the Phase 6 ELK reasoning stub into a fully capable, independently scalable OWL-EL reasoning service. It adds a Redis-backed classification cache, complete CR-rule coverage, superclass/subclass hierarchy queries, consistency checking, and async justification computation with support for multiple independent minimal justifications.

---

## Architecture

The ELK service (`docker/elk-service/`) becomes a stateful reasoning server backed by the existing Redis container. The main OntoExplorer API (`ontoexplorer/api/ontologies.py`) exposes proxy endpoints so consumers never talk to ELK directly.

```
Client
  └─► OntoExplorer API  ──proxy──►  ELK Service  ──store/read──►  Redis
            │                             │
            │ Celery task                 │ synchronous compute
            ▼                             ▼
        Postgres (jobs)              Classification index
                                     Justification results
```

The `reason_ontology` Celery task calls `POST /classify` (replacing the old `POST /reason`). Justification requests use a new `compute_justification` Celery task that calls `POST /classify/{version_id}/justification` and persists the result.

---

## ELK Service API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness + Redis connectivity |
| `POST` | `/classify` | Run full OWL-EL classification; store in Redis |
| `GET` | `/classify/{version_id}` | Full classification result |
| `GET` | `/classify/{version_id}/superclasses?class=<IRI>&direct=false` | All inferred ancestors (or direct only) |
| `GET` | `/classify/{version_id}/subclasses?class=<IRI>&direct=false` | All inferred descendants (or direct only) |
| `GET` | `/classify/{version_id}/consistency` | Pass/fail + list of unsatisfiable classes |
| `POST` | `/classify/{version_id}/justification` | Synchronously compute justification(s); store in Redis |
| `GET` | `/classify/{version_id}/justification/{justification_id}` | Retrieve stored justification result |

### `POST /classify` request

```json
{
  "ntriples": "...",
  "version_id": "uuid"
}
```

### `POST /classify/{version_id}/justification` request

```json
{
  "sub": "http://example.org/A",
  "sup": "http://example.org/C",
  "max_justifications": 3
}
```

- `max_justifications`: number of independent minimal justification sets to find. Default `1`. `0` means compute all (bounded by Celery `time_limit`).
- For unsatisfiability: omit `sup` and set `"type": "unsatisfiable"`.

### Justification response

```json
{
  "sub": "ex:A",
  "sup": "ex:C",
  "justifications_requested": 3,
  "justifications_found": 2,
  "minimal": true,
  "justifications": [
    ["ex:A rdfs:subClassOf ex:B .", "ex:B rdfs:subClassOf ex:C ."],
    ["ex:A owl:equivalentClass ex:X .", "ex:X rdfs:subClassOf ex:C ."]
  ],
  "proof_traces": [
    [{"rule": "CR2", "premises": ["ex:A ⊑ ex:B", "ex:B ⊑ ex:C"], "conclusion": "ex:A ⊑ ex:C"}],
    [{"rule": "equiv", "premises": ["ex:A ≡ ex:X"], "conclusion": "ex:A ⊑ ex:X"},
     {"rule": "CR2", "premises": ["ex:A ⊑ ex:X", "ex:X ⊑ ex:C"], "conclusion": "ex:A ⊑ ex:C"}]
  ],
  "duration_ms": 220.4
}
```

---

## OWL-EL Classifier Enhancements

The classifier is extended to implement the full OWL-EL normalisation + completion rules:

| Rule | Description |
|---|---|
| CR1 | Every class is subclass of `owl:Thing` |
| CR2 | Transitivity: `A ⊑ B`, `B ⊑ C` → `A ⊑ C` |
| CR3 | Conjunction left: `A ⊑ B ⊓ C` → `A ⊑ B`, `A ⊑ C` (full `owl:intersectionOf` traversal) |
| CR4 | Existential propagation: if `A ⊑ ∃r.B` and `B ⊑ C`, propagate to classes with `∃r.C` superclass expressions |
| CR5 | Role hierarchy: `r ⊑ s` means `∃r.A ⊑ ∃s.A` |
| CR6 | Unsatisfiability: derive `A ⊑ owl:Nothing` when contradictory constraints are present |

**Proof trace recording:** During the fixed-point computation, every derived fact records `(rule, premises)`. This trace is stored alongside the classification result and used for justification backtracking.

**Classification result stored in Redis** (`classification:{version_id}`, gzip-compressed JSON, 30-day TTL):

```json
{
  "version_id": "...",
  "classified_at": "2026-05-11T...",
  "class_count": 1200,
  "superclasses": {"ex:A": ["ex:B", "ex:C", "owl:Thing"]},
  "subclasses":   {"ex:B": ["ex:A", "ex:D"]},
  "direct_superclasses": {"ex:A": ["ex:B"]},
  "direct_subclasses":   {"ex:B": ["ex:A"]},
  "unsatisfiable": ["ex:EmptyClass"],
  "proof_traces": {"ex:A|ex:C": [{"rule": "CR2", ...}]},
  "duration_ms": 340.5
}
```

---

## Main OntoExplorer API — New Endpoints

Added to `ontoexplorer/api/ontologies.py`:

```
GET  /api/v1/ontologies/{id}/{version}/superclasses?class=<IRI>&direct=false
GET  /api/v1/ontologies/{id}/{version}/subclasses?class=<IRI>&direct=false
GET  /api/v1/ontologies/{id}/{version}/consistency
POST /api/v1/ontologies/{id}/{version}/justification
GET  /api/v1/ontologies/{id}/{version}/justification/{job_id}
```

`direct=true` returns only immediately asserted superclass/subclass relationships (one hop), served from the `direct_superclasses`/`direct_subclasses` index in the Redis cache.

---

## Async Justification Flow

```
POST /ontologies/{id}/{version}/justification
  → creates Postgres job (type="justification")
  → enqueues compute_justification Celery task
  → returns {"job_id": "...", "status": "queued"}

[Celery worker]
  compute_justification(version_id, sub, sup, max_justifications)
    → POST /classify/{version_id}/justification to ELK service
    → ELK computes, stores result in Redis:
        key: justification:{version_id}:{sha256(sub+sup+max)}
        TTL: 7 days
    → marks job done in Postgres
    → fires justification.completed webhook

GET /ontologies/{id}/{version}/justification/{job_id}
  → if job done: proxy to ELK GET /classify/{version_id}/justification/{id}
  → if running:  202 Accepted + job status
  → if failed:   500 + error detail
```

---

## Redis Storage Schema

| Key | Content | TTL |
|---|---|---|
| `classification:{version_id}` | Gzip-compressed JSON classification result | 30 days |
| `justification:{version_id}:{sha256(sub+sup+max)}` | Justification result JSON | 7 days |

Keys for a version are invalidated when `version.deprecated` fires (the webhook handler deletes `classification:{version_id}` and all `justification:{version_id}:*`).

---

## Webhook Events

Added to the existing event registry:

| Event | Fired when |
|---|---|
| `justification.completed` | Justification job finished successfully |
| `justification.failed` | Justification job failed or timed out |

(The existing `reasoning.completed` / `reasoning.failed` events cover `/classify`.)

---

## Error Handling

| Situation | Response |
|---|---|
| ELK service unreachable | `503` `{"detail": "reasoning service unavailable"}` |
| Version not yet classified | `409` `{"detail": "reasoning not yet completed"}` |
| Unknown class IRI | `404` `{"detail": "class not found in classification index"}` |
| Justification job still running | `202` + job status body |
| `max_justifications=0` hits time limit | Returns partial results with `"minimal": false, "timed_out": true` |

---

## Docker Compose Changes

The ELK service gains a Redis dependency and two new environment variables:

```yaml
elk-service:
  environment:
    REDIS_URL: redis://redis:6379/2      # database 2 (separate from Celery)
    JUSTIFICATION_TIME_LIMIT_SECONDS: 300
  depends_on:
    - redis
```

---

## New Python Dependencies

Added to `docker/elk-service/Dockerfile`:

```
redis>=5.0          # Redis client
```

No new dependencies in the main `pyproject.toml` — the main API proxies to ELK via httpx (already present).

---

## Module Structure

```
docker/elk-service/
  main.py              # FastAPI app (expanded)
  classifier.py        # OWL-EL CR rules + proof trace recording
  cache.py             # Redis read/write helpers
  justification.py     # Justification/proof-trace backtracking

ontoexplorer/
  api/ontologies.py    # New proxy endpoints (superclasses, subclasses, consistency, justification)
  clients/reasoning.py # New methods: superclasses(), subclasses(), consistency(), justify()
  modules/jobs/tasks.py  # compute_justification Celery task
  modules/webhooks/registry.py  # justification.completed / justification.failed events
```

---

## Verification Plan

1. **Unit tests** — `docker/elk-service/` (pytest, no Docker needed):
   - CR3 conjunction: `A ⊑ B ⊓ C` → infer `A ⊑ B` and `A ⊑ C`
   - CR4 existential propagation
   - CR5 role hierarchy
   - CR6 unsatisfiability detection
   - Proof trace completeness: every inferred fact has a recorded derivation
   - Justification minimality: removing any axiom from a justification breaks the inference
   - Multiple justifications: two independent minimal sets returned when they exist

2. **Integration tests** — `tests/integration/test_reasoning_service.py`:
   - `/classify` endpoint populates Redis
   - `/superclasses` and `/subclasses` return correct results from cache
   - `/consistency` correctly identifies unsatisfiable class
   - `POST /justification` queues a Celery job
   - `GET /justification/{job_id}` returns result after job completes
   - Cache invalidation on `version.deprecated`
   - Proxy endpoints on main API return same data as direct ELK calls

3. **Scale test** — SNOMED CT (400k classes):
   - Full classification completes within 5 minutes
   - Superclass query for a leaf class responds in under 50ms (served from Redis)
   - Single justification for a 3-hop chain computes in under 500ms
