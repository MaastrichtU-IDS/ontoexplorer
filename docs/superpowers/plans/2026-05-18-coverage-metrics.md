# Coverage Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute per-version coverage metrics (label / definition / multilingual %, broken out by entity type) during indexing, expose them via two read-only endpoints reading from Redis, and surface them in the UI as a fleet `/coverage` page and a per-ontology section on `OntologyPage`.

**Architecture:** A pure function `compute_coverage(entities, deprecated_iris, labels_by_iri, defs_by_iri)` lives in a new `ontoexplorer/modules/search/coverage.py`. It is called from the existing `build_index` flow (where those dicts are already in memory) and its output is written to a Redis key `coverage:{version_id}` with the same TTL as the stats cache. A new FastAPI router `ontoexplorer/api/coverage.py` exposes two routes that read the cache only. The frontend gets a `Coverage.tsx` fleet page (nav-linked) and a `CoverageSection.tsx` mounted on `OntologyPage`.

**Tech Stack:** FastAPI, Redis (via the existing `_get_redis` helper), SQLAlchemy (for the fleet query), pytest with `fakeredis`, React + TanStack Query, Vitest + React Testing Library.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ontoexplorer/modules/search/coverage.py` | new | `coverage_cache_key()` + pure `compute_coverage()` |
| `ontoexplorer/modules/search/indexer.py` | modify | Call `compute_coverage` + write Redis cache inside `build_index` |
| `ontoexplorer/api/coverage.py` | new | Two GET endpoints reading the Redis cache |
| `ontoexplorer/main.py` | modify | Register the new router |
| `tests/unit/search/test_coverage.py` | new | Unit tests for `compute_coverage` |
| `tests/integration/test_coverage_api.py` | new | Integration tests for both endpoints (uses `fakeredis`) |
| `frontend/src/lib/api.ts` | modify | TS interfaces + `api.coverage.*` |
| `frontend/src/pages/Coverage.tsx` | new | Fleet page with summary cards + sortable table |
| `frontend/src/pages/Coverage.test.tsx` | new | Sort + zero-total `—` rendering tests |
| `frontend/src/components/CoverageSection.tsx` | new | Per-version scorecards + language bar |
| `frontend/src/pages/OntologyPage.tsx` | modify | Mount `<CoverageSection>` |
| `frontend/src/App.tsx` | modify | Add `/coverage` route |
| `frontend/src/components/NavBar.tsx` | modify | Add `Coverage` nav link |

---

## Task 1: `compute_coverage` pure function (TDD)

**Files:**
- Create: `ontoexplorer/modules/search/coverage.py`
- Test: `tests/unit/search/test_coverage.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/search/test_coverage.py`:

```python
"""Unit tests for the pure coverage-computation helper."""
from ontoexplorer.modules.search.coverage import compute_coverage, ENTITY_TYPES


def _empty_by_type():
    return {t: {"total": 0, "with_label": 0, "with_definition": 0, "multilingual": 0, "by_lang": {}}
            for t in ENTITY_TYPES}


def test_empty_input_returns_zeroed_buckets_for_all_types():
    result = compute_coverage(entities={}, deprecated_iris=set(), labels_by_iri={}, defs_by_iri={})
    assert result["by_type"] == _empty_by_type()


def test_label_and_definition_counts_per_entity_type():
    entities = {"C1": "class", "C2": "class", "P1": "object_property"}
    labels = {
        "C1": [{"value": "Foo", "lang": "en"}],
        "C2": [],
        "P1": [{"value": "hasPart", "lang": ""}],
    }
    defs = {"C1": [{"value": "...", "lang": "en"}]}
    result = compute_coverage(entities, set(), labels, defs)

    cls = result["by_type"]["class"]
    assert cls["total"] == 2
    assert cls["with_label"] == 1
    assert cls["with_definition"] == 1

    op = result["by_type"]["object_property"]
    assert op["total"] == 1
    assert op["with_label"] == 1
    assert op["with_definition"] == 0


def test_multilingual_counts_distinct_lang_tags_including_empty():
    entities = {"C1": "class", "C2": "class", "C3": "class"}
    labels = {
        "C1": [{"value": "Foo", "lang": "en"}, {"value": "Voo", "lang": "fr"}],
        "C2": [{"value": "Bar", "lang": "en"}, {"value": "Baz", "lang": "en"}],
        "C3": [{"value": "Untagged", "lang": ""}, {"value": "Tagged", "lang": "en"}],
    }
    result = compute_coverage(entities, set(), labels, {})
    cls = result["by_type"]["class"]
    # C1 (en+fr) and C3 (""+en) are multilingual; C2 is not
    assert cls["multilingual"] == 2


def test_by_lang_counts_entities_not_labels():
    entities = {"C1": "class", "C2": "class"}
    labels = {
        "C1": [{"value": "Foo", "lang": "en"}, {"value": "Foo2", "lang": "en"}],
        "C2": [{"value": "Bar", "lang": "en"}, {"value": "Bär", "lang": "de"}],
    }
    result = compute_coverage(entities, set(), labels, {})
    by_lang = result["by_type"]["class"]["by_lang"]
    # Each entity contributes at most 1 per language even with multiple labels in that lang
    assert by_lang == {"en": 2, "de": 1}


def test_deprecated_entities_excluded_from_all_counts():
    entities = {"C1": "class", "C2": "class"}
    deprecated = {"C2"}
    labels = {
        "C1": [{"value": "Foo", "lang": "en"}],
        "C2": [{"value": "OldFoo", "lang": "en"}, {"value": "Vieux", "lang": "fr"}],
    }
    defs = {"C2": [{"value": "deprecated def", "lang": "en"}]}
    result = compute_coverage(entities, deprecated, labels, defs)
    cls = result["by_type"]["class"]
    assert cls["total"] == 1
    assert cls["with_label"] == 1
    assert cls["with_definition"] == 0
    assert cls["multilingual"] == 0
    assert cls["by_lang"] == {"en": 1}


def test_unknown_entity_type_is_ignored():
    # If for some reason `entities` contains a type not in ENTITY_TYPES, it's silently dropped
    entities = {"C1": "class", "X1": "weird_type"}
    result = compute_coverage(entities, set(), {"C1": [{"value": "C", "lang": "en"}]}, {})
    assert result["by_type"]["class"]["total"] == 1
    assert "weird_type" not in result["by_type"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/search/test_coverage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ontoexplorer.modules.search.coverage'`

- [ ] **Step 3: Implement `compute_coverage`**

Create `ontoexplorer/modules/search/coverage.py`:

```python
"""Per-version coverage computation: pure function operating on indexer dicts."""
from __future__ import annotations

from typing import Iterable

ENTITY_TYPES: tuple[str, ...] = (
    "class",
    "object_property",
    "data_property",
    "annotation_property",
    "individual",
)


def coverage_cache_key(version_id: str) -> str:
    return f"coverage:{version_id}"


def _empty_bucket() -> dict:
    return {"total": 0, "with_label": 0, "with_definition": 0, "multilingual": 0, "by_lang": {}}


def compute_coverage(
    entities: dict[str, str],
    deprecated_iris: set[str],
    labels_by_iri: dict[str, list[dict]],
    defs_by_iri: dict[str, list[dict]],
) -> dict:
    """Compute per-entity-type coverage from the indexer's in-memory dicts.

    Returns a dict shaped as:
        {"by_type": {<entity_type>: {"total", "with_label", "with_definition",
                                     "multilingual", "by_lang": {<lang>: int}}}}
    Empty lang tag ("") is preserved as its own bucket.
    """
    by_type: dict[str, dict] = {t: _empty_bucket() for t in ENTITY_TYPES}

    for iri, entity_type in entities.items():
        if iri in deprecated_iris or entity_type not in by_type:
            continue

        bucket = by_type[entity_type]
        bucket["total"] += 1

        labels: Iterable[dict] = labels_by_iri.get(iri, [])
        lang_tags = {entry.get("lang", "") for entry in labels}
        if labels:
            bucket["with_label"] += 1
        if len(lang_tags) >= 2:
            bucket["multilingual"] += 1
        for tag in lang_tags:
            bucket["by_lang"][tag] = bucket["by_lang"].get(tag, 0) + 1

        if defs_by_iri.get(iri):
            bucket["with_definition"] += 1

    return {"by_type": by_type}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/search/test_coverage.py -v`
Expected: PASS — all 6 tests green.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/coverage.py tests/unit/search/test_coverage.py
git commit -m "feat(coverage): pure compute_coverage helper"
```

---

## Task 2: Wire `compute_coverage` into the indexer

**Files:**
- Modify: `ontoexplorer/modules/search/indexer.py` (insert call after `_populate_stats_cache`)
- Test: `tests/unit/search/test_coverage_indexer_integration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/search/test_coverage_indexer_integration.py`:

```python
"""Test that build_index writes a coverage record to Redis under the expected key."""
import json
from unittest.mock import patch

import fakeredis

from ontoexplorer.modules.search.coverage import coverage_cache_key
from ontoexplorer.modules.search.indexer import build_index


def _patch_query(rows):
    """Return a function that yields the given rows for any SPARQL call."""
    def _fake(_q):
        return iter(rows)
    return _fake


def test_build_index_writes_coverage_cache(monkeypatch):
    """Stub out SPARQL so build_index runs and emits a coverage cache key."""
    r = fakeredis.FakeRedis(decode_responses=True)

    # Minimal SPARQL stub: empty result for every query — produces an empty ontology
    # but exercises the post-indexing cache writes.
    monkeypatch.setattr(
        "ontoexplorer.modules.search.indexer.sparql_query",
        _patch_query([]),
    )
    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        build_index(version_id="v-test", ontology_id="o-test")

    raw = r.get(coverage_cache_key("v-test"))
    assert raw is not None, "coverage cache key was not written"
    payload = json.loads(raw)
    assert "by_type" in payload
    assert "indexed_at" in payload
    assert set(payload["by_type"].keys()) == {
        "class", "object_property", "data_property", "annotation_property", "individual"
    }
    # Empty ontology → all totals zero
    for t, bucket in payload["by_type"].items():
        assert bucket["total"] == 0
        assert bucket["by_lang"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/search/test_coverage_indexer_integration.py -v`
Expected: FAIL — `assert raw is not None` because the cache key isn't written yet.

- [ ] **Step 3: Wire the call into `build_index`**

In `ontoexplorer/modules/search/indexer.py`, find the line near 481:

```python
    _build_tree_cache(version_id, ontology_id, entities, labels_by_iri, r)
    _populate_stats_cache(version_id, ontology_id, entities, r)
```

Replace those two lines with:

```python
    _build_tree_cache(version_id, ontology_id, entities, labels_by_iri, r)
    _populate_stats_cache(version_id, ontology_id, entities, r)
    _populate_coverage_cache(
        version_id, entities, deprecated_iris, labels_by_iri, defs_by_iri, r
    )
```

Then add the new helper near the existing `_populate_stats_cache` definition (just below it, around line 748). Insert:

```python
def _populate_coverage_cache(
    version_id: str,
    entities: dict[str, str],
    deprecated_iris: set[str],
    labels_by_iri: dict[str, list[dict]],
    defs_by_iri: dict[str, list[dict]],
    r: redis.Redis,
) -> None:
    """Compute per-version coverage and write to Redis with the same TTL as stats."""
    from datetime import datetime, timezone
    from ontoexplorer.modules.search.coverage import compute_coverage, coverage_cache_key

    payload = compute_coverage(entities, deprecated_iris, labels_by_iri, defs_by_iri)
    payload["version_id"] = version_id
    payload["indexed_at"] = datetime.now(timezone.utc).isoformat()
    r.setex(coverage_cache_key(version_id), _SEARCH_TTL, json.dumps(payload))
```

- [ ] **Step 4: Add cache invalidation**

In `ontoexplorer/modules/search/indexer.py`, find `invalidate_index` (around line 751) and add the coverage key to `to_delete`. Locate the block that builds `to_delete` and add a line after the existing `_stats_cache_key` line:

```python
    to_delete.append(_stats_cache_key(version_id))
```

becomes:

```python
    to_delete.append(_stats_cache_key(version_id))
    from ontoexplorer.modules.search.coverage import coverage_cache_key
    to_delete.append(coverage_cache_key(version_id))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/search/test_coverage_indexer_integration.py -v`
Expected: PASS.

Then re-run the broader indexer suite to make sure nothing else broke:

Run: `pytest tests/unit/search/test_indexer.py -v`
Expected: PASS — same number of tests as before, all green.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/modules/search/indexer.py tests/unit/search/test_coverage_indexer_integration.py
git commit -m "feat(coverage): write coverage cache during indexing"
```

---

## Task 3: Coverage API router

**Files:**
- Create: `ontoexplorer/api/coverage.py`
- Modify: `ontoexplorer/main.py`
- Test: `tests/integration/test_coverage_api.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_coverage_api.py`:

```python
"""Integration tests for the coverage endpoints."""
import json
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.coverage import coverage_cache_key


def _sample_payload(version_id: str) -> dict:
    return {
        "version_id": version_id,
        "indexed_at": "2026-05-18T00:00:00+00:00",
        "by_type": {
            "class":               {"total": 100, "with_label": 90, "with_definition": 50, "multilingual": 10, "by_lang": {"en": 90, "de": 10}},
            "object_property":     {"total": 20,  "with_label": 18, "with_definition": 5,  "multilingual": 0,  "by_lang": {"en": 18}},
            "data_property":       {"total": 5,   "with_label": 5,  "with_definition": 0,  "multilingual": 0,  "by_lang": {"en": 5}},
            "annotation_property": {"total": 3,   "with_label": 3,  "with_definition": 0,  "multilingual": 0,  "by_lang": {"en": 3}},
            "individual":          {"total": 0,   "with_label": 0,  "with_definition": 0,  "multilingual": 0,  "by_lang": {}},
        },
    }


@pytest.mark.anyio
async def test_version_coverage_returns_cached_payload(client, db_session):
    ont = Ontology(iri="http://example.org/cov-test.owl", shortname="cov", title="Cov Test")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="cov/test.ttl",
        sha256="cov_test_001",
        format="turtle",
        status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(coverage_cache_key(ver.id), json.dumps(_sample_payload(ver.id)))

    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/coverage")

    assert resp.status_code == 200
    body = resp.json()
    assert body["version_id"] == ver.id
    assert body["by_type"]["class"]["total"] == 100
    assert body["by_type"]["class"]["by_lang"]["de"] == 10


@pytest.mark.anyio
async def test_version_coverage_returns_404_when_cache_missing(client, db_session):
    ont = Ontology(iri="http://example.org/cov-missing.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="cov/missing.ttl",
        sha256="cov_missing_001",
        format="turtle",
        status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/coverage")

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_fleet_coverage_aggregates_and_omits_by_lang(client, db_session):
    # Two ontologies, each with one ready version, both with cache entries
    ont_a = Ontology(iri="http://example.org/a.owl", shortname="a", title="A")
    ont_b = Ontology(iri="http://example.org/b.owl", shortname="b", title="B")
    db_session.add_all([ont_a, ont_b])
    await db_session.flush()
    ver_a = OntologyVersion(ontology_id=ont_a.id, minio_key="a.ttl", sha256="a001", format="turtle", status="ready")
    ver_b = OntologyVersion(ontology_id=ont_b.id, minio_key="b.ttl", sha256="b001", format="turtle", status="ready")
    db_session.add_all([ver_a, ver_b])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(coverage_cache_key(ver_a.id), json.dumps(_sample_payload(ver_a.id)))
    r.set(coverage_cache_key(ver_b.id), json.dumps(_sample_payload(ver_b.id)))

    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get("/api/v1/coverage/public")

    assert resp.status_code == 200
    body = resp.json()
    # Two ontologies, totals doubled
    assert body["totals"]["class"]["total"] == 200
    assert body["totals"]["class"]["with_label"] == 180
    assert len(body["by_ontology"]) == 2
    # by_lang must be stripped from the fleet payload
    for entry in body["by_ontology"]:
        for bucket in entry["by_type"].values():
            assert "by_lang" not in bucket


@pytest.mark.anyio
async def test_fleet_coverage_skips_versions_without_cache(client, db_session):
    ont = Ontology(iri="http://example.org/skip.owl", shortname="skip", title="Skip")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(ontology_id=ont.id, minio_key="skip.ttl", sha256="skip001", format="turtle", status="ready")
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)  # empty — no coverage keys
    with patch("ontoexplorer.api.coverage._get_redis", return_value=r):
        resp = await client.get("/api/v1/coverage/public")

    assert resp.status_code == 200
    body = resp.json()
    assert body["by_ontology"] == []
    for bucket in body["totals"].values():
        assert bucket == {"total": 0, "with_label": 0, "with_definition": 0, "multilingual": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_coverage_api.py -v`
Expected: FAIL — `404` for every test because the route doesn't exist (FastAPI returns 404 for unknown paths).

- [ ] **Step 3: Implement the router**

Create `ontoexplorer/api/coverage.py`:

```python
"""Coverage endpoints — read-only views over the Redis coverage cache."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.search.coverage import ENTITY_TYPES, coverage_cache_key
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["coverage"])

_AGGREGATE_FIELDS: tuple[str, ...] = ("total", "with_label", "with_definition", "multilingual")


def _empty_totals() -> dict:
    return {t: {f: 0 for f in _AGGREGATE_FIELDS} for t in ENTITY_TYPES}


@router.get("/ontologies/{ontology_id}/{version_id}/coverage", summary="Per-version coverage metrics")
async def get_version_coverage(ontology_id: str, version_id: str):
    r = _get_redis()
    raw = r.get(coverage_cache_key(version_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Coverage not computed — reindex pending")
    return json.loads(raw)


@router.get("/coverage/public", summary="Fleet coverage rollup (no auth)")
async def get_fleet_coverage(db: AsyncSession = Depends(get_db)):
    # Pick the latest ready version per ontology — same shape as /stats/public
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    rows = (await db.execute(
        select(OntologyVersion.id, OntologyVersion.ontology_id, Ontology.shortname, Ontology.title)
        .join(subq,
              (OntologyVersion.ontology_id == subq.c.ontology_id)
              & (OntologyVersion.created_at == subq.c.max_created))
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
    )).all()

    r = _get_redis()
    keys = [coverage_cache_key(row.id) for row in rows]
    raws = r.mget(keys) if keys else []

    totals = _empty_totals()
    by_ontology: list[dict] = []
    for row, raw in zip(rows, raws):
        if raw is None:
            continue
        payload = json.loads(raw)
        # Strip by_lang from fleet payload for compactness
        stripped: dict[str, dict] = {}
        for t in ENTITY_TYPES:
            bucket = payload["by_type"].get(t, {})
            stripped[t] = {f: int(bucket.get(f, 0)) for f in _AGGREGATE_FIELDS}
            for f in _AGGREGATE_FIELDS:
                totals[t][f] += stripped[t][f]
        by_ontology.append({
            "ontology_id": row.ontology_id,
            "version_id":  row.id,
            "shortname":   row.shortname,
            "title":       row.title,
            "indexed_at":  payload.get("indexed_at"),
            "by_type":     stripped,
        })

    return {"totals": totals, "by_ontology": by_ontology}
```

- [ ] **Step 4: Register the router**

In `ontoexplorer/main.py`, add the import alongside the others (around line 23):

```python
from ontoexplorer.api.coverage import router as coverage_router
```

And register it alongside the other routers (around line 77, near `stats_router`):

```python
    app.include_router(coverage_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/integration/test_coverage_api.py -v`
Expected: PASS — all 4 tests green.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/coverage.py ontoexplorer/main.py tests/integration/test_coverage_api.py
git commit -m "feat(coverage): API endpoints for per-version + fleet coverage"
```

---

## Task 4: Frontend API client types and functions

**Files:**
- Modify: `frontend/src/lib/api.ts` (add types after the existing `OntologyMetaProfile` interface; add the `coverage` namespace inside the `api` const)

- [ ] **Step 1: Add TypeScript interfaces**

In `frontend/src/lib/api.ts`, find the existing `OntologyMetaProfile` interface (near line 495) and add the following interfaces *after* its closing brace:

```typescript
// ── Coverage types ────────────────────────────────────────────────────────────

export type CoverageEntityType =
  | 'class'
  | 'object_property'
  | 'data_property'
  | 'annotation_property'
  | 'individual'

export interface CoverageBucket {
  total: number
  with_label: number
  with_definition: number
  multilingual: number
  by_lang: Record<string, number>
}

export interface CoverageBucketCompact {
  total: number
  with_label: number
  with_definition: number
  multilingual: number
}

export interface CoverageRecord {
  version_id: string
  indexed_at: string
  by_type: Record<CoverageEntityType, CoverageBucket>
}

export interface CoverageFleetEntry {
  ontology_id: string
  version_id: string
  shortname: string | null
  title: string | null
  indexed_at: string
  by_type: Record<CoverageEntityType, CoverageBucketCompact>
}

export interface CoverageFleet {
  totals: Record<CoverageEntityType, CoverageBucketCompact>
  by_ontology: CoverageFleetEntry[]
}
```

- [ ] **Step 2: Add the `coverage` namespace to `api`**

In `frontend/src/lib/api.ts`, find the existing `stats: {` block (around line 974) and insert a new `coverage` namespace just *before* it:

```typescript
  coverage: {
    fleet: () => request<CoverageFleet>('/coverage/public'),
    version: (ontologyId: string, versionId: string) =>
      request<CoverageRecord>(`/ontologies/${ontologyId}/${versionId}/coverage`),
  },

```

- [ ] **Step 3: Verify the type-checker passes**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "(error|coverage)" | head -20`
Expected: No errors mentioning `coverage`. (Pre-existing unrelated errors in other files are OK.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(coverage): frontend API client types"
```

---

## Task 5: Fleet Coverage page + route + nav link

**Files:**
- Create: `frontend/src/pages/Coverage.tsx`
- Create: `frontend/src/pages/Coverage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavBar.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/Coverage.test.tsx`:

```tsx
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import Coverage from './Coverage'

const FLEET = {
  totals: {
    class:               { total: 1000, with_label: 950, with_definition: 500, multilingual: 100 },
    object_property:     { total:   50, with_label:  48, with_definition:  10, multilingual:   0 },
    data_property:       { total:   10, with_label:  10, with_definition:   0, multilingual:   0 },
    annotation_property: { total:    5, with_label:   5, with_definition:   0, multilingual:   0 },
    individual:          { total:    0, with_label:   0, with_definition:   0, multilingual:   0 },
  },
  by_ontology: [
    { ontology_id: 'o1', version_id: 'v1', shortname: 'go',  title: 'Gene Ontology', indexed_at: '2026-05-18T00:00:00Z',
      by_type: {
        class:               { total: 800, with_label: 800, with_definition: 400, multilingual: 80 },
        object_property:     { total:  40, with_label:  40, with_definition:  10, multilingual:  0 },
        data_property:       { total:   5, with_label:   5, with_definition:   0, multilingual:  0 },
        annotation_property: { total:   3, with_label:   3, with_definition:   0, multilingual:  0 },
        individual:          { total:   0, with_label:   0, with_definition:   0, multilingual:  0 },
      } },
    { ontology_id: 'o2', version_id: 'v2', shortname: 'sulo', title: 'SULO', indexed_at: '2026-05-18T00:00:00Z',
      by_type: {
        class:               { total: 200, with_label: 150, with_definition: 100, multilingual: 20 },
        object_property:     { total:  10, with_label:   8, with_definition:   0, multilingual:  0 },
        data_property:       { total:   5, with_label:   5, with_definition:   0, multilingual:  0 },
        annotation_property: { total:   2, with_label:   2, with_definition:   0, multilingual:  0 },
        individual:          { total:   0, with_label:   0, with_definition:   0, multilingual:  0 },
      } },
  ],
}

vi.mock('../lib/api', () => ({
  api: { coverage: { fleet: () => Promise.resolve(FLEET) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders fleet summary cards and per-ontology rows', async () => {
  wrap(<Coverage />)
  expect(await screen.findByText('Gene Ontology')).toBeInTheDocument()
  expect(screen.getByText('SULO')).toBeInTheDocument()
  // 950 / 1000 class labels = 95%
  expect(screen.getByText('95%')).toBeInTheDocument()
})

test('sort by class label % toggles ascending and descending', async () => {
  const user = userEvent.setup()
  wrap(<Coverage />)
  await screen.findByText('Gene Ontology')

  const labelHeader = screen.getByRole('button', { name: /class label %/i })
  await user.click(labelHeader) // ascending
  let rows = screen.getAllByTestId('coverage-row').map(r => within(r).getByTestId('ontology-name').textContent)
  expect(rows).toEqual(['SULO', 'Gene Ontology'])  // SULO 75% < GO 100%

  await user.click(labelHeader) // descending
  rows = screen.getAllByTestId('coverage-row').map(r => within(r).getByTestId('ontology-name').textContent)
  expect(rows).toEqual(['Gene Ontology', 'SULO'])
})

test('renders em-dash for zero-total cells', async () => {
  wrap(<Coverage />)
  await screen.findByText('Gene Ontology')
  // Individuals column for GO has total=0 → should render "—" not "NaN%"
  const goRow = screen.getAllByTestId('coverage-row')[0]
  expect(within(goRow).getByTestId('individuals-label-pct').textContent).toBe('—')
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Coverage.test.tsx`
Expected: FAIL — module `./Coverage` not found.

- [ ] **Step 3: Implement the Coverage page**

Create `frontend/src/pages/Coverage.tsx`:

```tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, slugFromIri, CoverageFleet, CoverageFleetEntry, CoverageEntityType } from '../lib/api'

type SortKey =
  | 'name' | 'class_total' | 'class_label' | 'class_def' | 'class_multi'
  | 'props_label' | 'props_def' | 'ind_label'

function pct(num: number, denom: number): string {
  if (denom <= 0) return '—'
  return `${Math.round((num / denom) * 100)}%`
}

function pctValue(num: number, denom: number): number {
  if (denom <= 0) return -1  // sorts zero-total rows to the bottom of ascending order
  return num / denom
}

function propsAgg(entry: CoverageFleetEntry, field: 'total' | 'with_label' | 'with_definition'): number {
  const types: CoverageEntityType[] = ['object_property', 'data_property', 'annotation_property']
  return types.reduce((acc, t) => acc + (entry.by_type[t]?.[field] ?? 0), 0)
}

export default function Coverage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['coverage', 'fleet'],
    queryFn: () => api.coverage.fleet(),
  })
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  if (isLoading) return <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
  if (error || !data) return <p style={{ color: 'var(--text-dim)' }}>Failed to load coverage.</p>

  const fleet = data as CoverageFleet
  const rows = [...fleet.by_ontology].sort((a, b) => {
    const valA = sortValue(a, sortKey)
    const valB = sortValue(b, sortKey)
    if (valA < valB) return sortDir === 'asc' ? -1 : 1
    if (valA > valB) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  function toggleSort(key: SortKey) {
    if (key === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('asc') }
  }

  const classTotals = fleet.totals.class

  return (
    <div>
      <h1 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '1rem' }}>Coverage</h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginBottom: '1.25rem' }}>
        <SummaryCard label="Class label coverage"      pct={pct(classTotals.with_label, classTotals.total)} />
        <SummaryCard label="Class definition coverage" pct={pct(classTotals.with_definition, classTotals.total)} />
        <SummaryCard label="Class multilingual"        pct={pct(classTotals.multilingual, classTotals.total)} />
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            <Th onClick={() => toggleSort('name')}        active={sortKey === 'name'}        dir={sortDir}>Ontology</Th>
            <Th onClick={() => toggleSort('class_total')} active={sortKey === 'class_total'} dir={sortDir}>Classes</Th>
            <Th onClick={() => toggleSort('class_label')} active={sortKey === 'class_label'} dir={sortDir}>Class label %</Th>
            <Th onClick={() => toggleSort('class_def')}   active={sortKey === 'class_def'}   dir={sortDir}>Class def %</Th>
            <Th onClick={() => toggleSort('class_multi')} active={sortKey === 'class_multi'} dir={sortDir}>Class multilingual %</Th>
            <Th onClick={() => toggleSort('props_label')} active={sortKey === 'props_label'} dir={sortDir}>Props label %</Th>
            <Th onClick={() => toggleSort('props_def')}   active={sortKey === 'props_def'}   dir={sortDir}>Props def %</Th>
            <Th onClick={() => toggleSort('ind_label')}   active={sortKey === 'ind_label'}   dir={sortDir}>Indivs label %</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map(entry => (
            <CoverageRow key={entry.version_id} entry={entry} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function sortValue(entry: CoverageFleetEntry, key: SortKey): number | string {
  const cls = entry.by_type.class
  const ind = entry.by_type.individual
  switch (key) {
    case 'name':        return (entry.title || entry.shortname || entry.ontology_id).toLowerCase()
    case 'class_total': return cls.total
    case 'class_label': return pctValue(cls.with_label, cls.total)
    case 'class_def':   return pctValue(cls.with_definition, cls.total)
    case 'class_multi': return pctValue(cls.multilingual, cls.total)
    case 'props_label': return pctValue(propsAgg(entry, 'with_label'), propsAgg(entry, 'total'))
    case 'props_def':   return pctValue(propsAgg(entry, 'with_definition'), propsAgg(entry, 'total'))
    case 'ind_label':   return pctValue(ind.with_label, ind.total)
  }
}

function CoverageRow({ entry }: { entry: CoverageFleetEntry }) {
  const cls = entry.by_type.class
  const ind = entry.by_type.individual
  const slug = entry.shortname || slugFromIri(entry.ontology_id)
  const name = entry.title || entry.shortname || entry.ontology_id

  return (
    <tr data-testid="coverage-row" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
      <td style={{ padding: '5px 8px' }}>
        <Link to={`/ontologies/${slug}#coverage`} data-testid="ontology-name" style={{ color: 'var(--accent-blue)' }}>
          {name}
        </Link>
      </td>
      <td style={{ padding: '5px 8px' }}>{cls.total.toLocaleString()}</td>
      <td style={{ padding: '5px 8px' }}>{pct(cls.with_label, cls.total)}</td>
      <td style={{ padding: '5px 8px' }}>{pct(cls.with_definition, cls.total)}</td>
      <td style={{ padding: '5px 8px' }}>{pct(cls.multilingual, cls.total)}</td>
      <td style={{ padding: '5px 8px' }}>{pct(propsAgg(entry, 'with_label'), propsAgg(entry, 'total'))}</td>
      <td style={{ padding: '5px 8px' }}>{pct(propsAgg(entry, 'with_definition'), propsAgg(entry, 'total'))}</td>
      <td style={{ padding: '5px 8px' }} data-testid="individuals-label-pct">{pct(ind.with_label, ind.total)}</td>
    </tr>
  )
}

function Th({ children, onClick, active, dir }: {
  children: React.ReactNode; onClick: () => void; active: boolean; dir: 'asc' | 'desc'
}) {
  return (
    <th style={{ padding: '4px 8px', textAlign: 'left' }}>
      <button onClick={onClick} style={{
        background: 'none', border: 'none', color: active ? 'var(--text)' : 'var(--text-dim)',
        fontSize: 10, textTransform: 'uppercase', fontWeight: 500, cursor: 'pointer', padding: 0,
      }}>
        {children}{active ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
      </button>
    </th>
  )
}

function SummaryCard({ label, pct }: { label: string; pct: string }) {
  return (
    <div style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '1rem',
    }}>
      <p style={{
        fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: '0.25rem',
        textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600,
      }}>{label}</p>
      <p style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--text)' }}>{pct}</p>
    </div>
  )
}
```

- [ ] **Step 4: Add the route**

In `frontend/src/App.tsx`, add the import (alongside other page imports):

```tsx
import Coverage from './pages/Coverage'
```

Add the route inside the public `<Routes>` block (sibling of `<Route path="/search" …>`):

```tsx
      <Route path="/coverage" element={<Shell><Coverage /></Shell>} />
```

- [ ] **Step 5: Add the nav link**

In `frontend/src/components/NavBar.tsx`, find the `navLinks` array (line 8) and add Coverage:

```tsx
const navLinks = [
  { to: '/ontologies', label: 'Ontologies' },
  { to: '/coverage',   label: 'Coverage' },
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/Coverage.test.tsx`
Expected: PASS — all 3 tests green.

Also run the NavBar test, which asserts on visible nav links:

Run: `cd frontend && npx vitest run src/components/NavBar.test.tsx`
Expected: PASS. If a test asserts on a hardcoded list of link labels, update the assertion to include `'Coverage'` (the current `NavBar.test.tsx` only asserts on `'Browse'`, `'Search'`, `'Dashboard'`, which come from elsewhere in NavBar — so no change should be needed; but verify).

- [ ] **Step 7: Manually smoke-test the page**

Run: `cd frontend && npm run dev` (or rely on the running dev server)
Open `http://localhost:5173/coverage` in a browser. Verify:
- Summary cards render (or show `—` if no coverage caches exist yet)
- Table renders one row per ontology with a populated coverage cache
- Clicking a column header toggles sort indicator (▲ / ▼)
- Clicking an ontology name navigates to `/ontologies/<slug>#coverage`

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/Coverage.tsx frontend/src/pages/Coverage.test.tsx frontend/src/App.tsx frontend/src/components/NavBar.tsx
git commit -m "feat(coverage): fleet /coverage page with sortable table"
```

---

## Task 6: Per-version Coverage section on `OntologyPage`

**Files:**
- Create: `frontend/src/components/CoverageSection.tsx`
- Modify: `frontend/src/pages/OntologyPage.tsx` (mount the new section)

- [ ] **Step 1: Implement `CoverageSection`**

Create `frontend/src/components/CoverageSection.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'
import { api, CoverageEntityType, CoverageRecord } from '../lib/api'

const TYPE_LABELS: Record<CoverageEntityType, string> = {
  class:               'Classes',
  object_property:     'Object properties',
  data_property:       'Data properties',
  annotation_property: 'Annotation properties',
  individual:          'Individuals',
}

const TYPE_ORDER: CoverageEntityType[] = [
  'class', 'object_property', 'data_property', 'annotation_property', 'individual',
]

function pct(num: number, denom: number): string {
  if (denom <= 0) return '—'
  return `${Math.round((num / denom) * 100)}%`
}

export default function CoverageSection({ ontologyId, versionId }: {
  ontologyId: string; versionId: string
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['coverage', 'version', versionId],
    queryFn: () => api.coverage.version(ontologyId, versionId),
    retry: false,
  })

  if (isLoading) return null
  if (error || !data) {
    return (
      <section id="coverage" style={{ padding: '1rem 0' }}>
        <h2 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.5rem' }}>Coverage</h2>
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Coverage not yet computed — will be available after the next reindex.
        </p>
      </section>
    )
  }

  const record = data as CoverageRecord
  const classByLang = record.by_type.class.by_lang
  const classTotal = record.by_type.class.total

  return (
    <section id="coverage" style={{ padding: '1rem 0' }}>
      <h2 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.5rem' }}>Coverage</h2>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '0.5rem', marginBottom: '1rem' }}>
        {TYPE_ORDER.map(t => {
          const b = record.by_type[t]
          return (
            <div key={t} data-testid={`coverage-card-${t}`} style={{
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius)', padding: '0.6rem 0.75rem',
            }}>
              <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
                {TYPE_LABELS[t]} ({b.total.toLocaleString()})
              </div>
              <Metric label="Label"    pct={pct(b.with_label, b.total)}      count={b.with_label} />
              <Metric label="Def"      pct={pct(b.with_definition, b.total)} count={b.with_definition} />
              <Metric label="Multilang" pct={pct(b.multilingual, b.total)}    count={b.multilingual} />
            </div>
          )
        })}
      </div>

      {classTotal > 0 && Object.keys(classByLang).length > 0 && (
        <div data-testid="lang-bar">
          <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
            Class label languages
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {Object.entries(classByLang)
              .sort((a, b) => b[1] - a[1])
              .map(([tag, n]) => (
                <span key={tag} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 3,
                  background: 'rgba(80,160,255,0.12)', color: 'var(--accent-blue)',
                }}>
                  {tag || '(no lang)'}: {n.toLocaleString()} ({pct(n, classTotal)})
                </span>
              ))}
          </div>
        </div>
      )}

      <p style={{ marginTop: '0.75rem', color: 'var(--text-muted)', fontSize: 11 }}>
        Last computed: {new Date(record.indexed_at).toLocaleString()}
      </p>
    </section>
  )
}

function Metric({ label, pct, count }: { label: string; pct: string; count: number }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginTop: 2 }}>
      <span style={{ color: 'var(--text-dim)' }}>{label}</span>
      <span style={{ color: 'var(--text)' }}>{pct} <span style={{ color: 'var(--text-muted)' }}>({count.toLocaleString()})</span></span>
    </div>
  )
}
```

- [ ] **Step 2: Mount `CoverageSection` in `OntologyPage`**

In `frontend/src/pages/OntologyPage.tsx`, add the import alongside the other component imports near the top (after `HistoryTab`):

```tsx
import CoverageSection from '../components/CoverageSection'
```

Find the JSX block that renders the ontology body — search for `<HistoryTab` to locate it. Immediately after the `<HistoryTab …/>` element (or alongside it in the same parent container — pick the spot consistent with neighbouring sections), insert:

```tsx
        {ontologyId && versionId && (
          <CoverageSection ontologyId={ontologyId} versionId={versionId} />
        )}
```

(Variable names `ontologyId` and `versionId` are the ones already in scope on this page; use whatever the existing code calls them — verify with a quick `grep -n 'ontologyId\|versionId\|version.id' frontend/src/pages/OntologyPage.tsx | head -10` and use those exact names.)

- [ ] **Step 3: Write the failing test**

Create `frontend/src/components/CoverageSection.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CoverageSection from './CoverageSection'

const RECORD = {
  version_id: 'v1',
  indexed_at: '2026-05-18T12:00:00Z',
  by_type: {
    class: {
      total: 1000, with_label: 950, with_definition: 500, multilingual: 100,
      by_lang: { en: 950, de: 80, fr: 20, '': 5 },
    },
    object_property:     { total: 0, with_label: 0, with_definition: 0, multilingual: 0, by_lang: {} },
    data_property:       { total: 0, with_label: 0, with_definition: 0, multilingual: 0, by_lang: {} },
    annotation_property: { total: 0, with_label: 0, with_definition: 0, multilingual: 0, by_lang: {} },
    individual:          { total: 0, with_label: 0, with_definition: 0, multilingual: 0, by_lang: {} },
  },
}

vi.mock('../lib/api', () => ({
  api: { coverage: { version: () => Promise.resolve(RECORD) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

test('renders cards for each entity type with em-dash on zero totals', async () => {
  wrap(<CoverageSection ontologyId="o1" versionId="v1" />)
  expect(await screen.findByTestId('coverage-card-class')).toBeInTheDocument()
  // Classes with_label = 950/1000 = 95%
  expect(screen.getByTestId('coverage-card-class').textContent).toMatch(/95%/)
  // Object properties total=0 → "—"
  expect(screen.getByTestId('coverage-card-object_property').textContent).toMatch(/—/)
})

test('renders language bar segments sorted by count desc, with (no lang) for empty tag', async () => {
  wrap(<CoverageSection ontologyId="o1" versionId="v1" />)
  const bar = await screen.findByTestId('lang-bar')
  // Sorted desc: en(950), de(80), fr(20), ""(5)
  const text = bar.textContent || ''
  const enIdx = text.indexOf('en:')
  const deIdx = text.indexOf('de:')
  const noIdx = text.indexOf('(no lang)')
  expect(enIdx).toBeGreaterThan(-1)
  expect(deIdx).toBeGreaterThan(enIdx)
  expect(noIdx).toBeGreaterThan(deIdx)
})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/CoverageSection.test.tsx`
Expected: PASS — both tests green.

- [ ] **Step 5: Manually smoke-test**

Open an ontology detail page in the running dev server. Scroll to the new Coverage section. Verify:
- 5 cards render (one per entity type)
- Zero-total cards show `—` instead of `NaN%`
- Language bar shows segments for `class` labels, sorted by count desc
- `(no lang)` appears for untagged labels (if any)
- "Last computed:" timestamp renders
- Anchor `#coverage` works (clicking a row from `/coverage` page scrolls here)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/CoverageSection.tsx frontend/src/components/CoverageSection.test.tsx frontend/src/pages/OntologyPage.tsx
git commit -m "feat(coverage): per-version Coverage section on OntologyPage"
```

---

## Final verification

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest tests/ -q`
Expected: All tests pass. No regressions in indexer, stats, or other API tests.

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: All tests pass. No regressions in NavBar or OntologyPage tests.

- [ ] **Step 3: Manual end-to-end check**

1. Restart the API: `docker compose restart api`
2. Trigger a reindex on at least one ontology so its coverage cache is populated. (Or check Redis for an existing `coverage:*` key.)
3. Visit `/coverage` — fleet table renders.
4. Click an ontology — navigates to its detail page; the new Coverage section appears.
5. If no coverage cache exists for a version, the section shows the "not yet computed" placeholder.
