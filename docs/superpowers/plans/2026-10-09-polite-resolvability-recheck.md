# Polite Resolvability Re-check — Implementation Plan

> **For agentic workers:** implement task-by-task, TDD, committing per task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Recover ontologies whose resolvability check failed *transiently* (HTTP 429/5xx, timeouts) by re-checking them **politely** — a polite User-Agent, per-host request spacing, honoring `Retry-After`, and a small capped batch per beat run — so we never again rate-limit ourselves against shared hosts (`w3id.org`, `purl.obolibrary.org`, `purl.org`).

**Architecture:** The initial backfill fired ~1,900 checks at once; many ontologies share a host, so those hosts 429'd us (94 observed) and some timed out. This adds a `recheck_resolvability` Celery beat task that re-checks only the *retryable* failures, a capped batch at a time, spacing requests to the same host and skipping any host still inside its `Retry-After` cooldown. Over a few runs the throttled ontologies flip to their true state.

**Tech Stack:** Python / Celery (beat) / SQLAlchemy (async) / `httpx` via `ontoexplorer.clients.fetch_guard.guarded_transport`. Builds on `ontoexplorer/modules/resolve/conneg.py` and the `check_ontology_resolvable` task (PR #304/#305).

**Spec:** `docs/superpowers/specs/2026-10-09-ontology-ownership-proof-design.md` (resolvability is the dereference signal; this plan is its operational re-check loop).

## Global Constraints

- **Politeness is the point:** never burst a host. A single worker runs these serially; the task additionally enforces a **per-host minimum interval** and skips hosts in a `Retry-After` cooldown.
- SSRF: keep the existing `guarded_transport`; do not add a new fetch path.
- **Only retryable failures are re-checked** — `resolvable=false` with HTTP 429/5xx or a fetch error (timeout/DNS/reset). Never re-check permanent states: 404/403/401/400/406, `200-but-not-RDF`, or `resolvable=true`.
- Capped per run so a beat tick is bounded in time and host load; idempotent and safe to re-run.
- Postgres + sqlite compatible (unit tests run on sqlite); `resolve_detail` JSON reads use the dialect-agnostic accessors already in the model.

## Review Focus

- **`Retry-After` as HTTP-date** (not delta-seconds): must parse both forms, and a malformed value must not crash the check — Task 1 `test_parse_retry_after_date_and_seconds`.
- **A host in cooldown** (`next_check_after` in the future) must be **skipped**, not re-hit — Task 2 `test_retryable_skips_cooldown`.
- **Permanent failures excluded**: a 404 / `200-not-RDF` ontology is never selected for re-check — Task 2 `test_retryable_excludes_permanent`.
- **Per-host spacing**: two ontologies on the same host in one batch must be spaced by ≥ the min interval — Task 3 `test_recheck_spaces_same_host`.
- **An empty retryable set** is a no-op (no sleeps, no dispatch) — Task 3 `test_recheck_noop_when_none`.

---

### Task 1: Polite User-Agent + capture `Retry-After`

**Files:**
- Modify: `ontoexplorer/modules/resolve/conneg.py`
- Test: `tests/unit/resolve/test_retry_after.py`

**Interfaces:**
- Produces: `parse_retry_after(value: str | None, *, now: datetime | None = None) -> datetime | None` (absolute "retry not before" time); `check_resolvable` now sends a polite `User-Agent` and records `retry_after` (ISO string or None) in `ResolveResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_retry_after.py
from datetime import datetime, timezone
from ontoexplorer.modules.resolve.conneg import parse_retry_after


def _now():
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_retry_after_date_and_seconds():
    # delta-seconds
    assert parse_retry_after("120", now=_now()) == datetime(2026, 1, 1, 12, 2, 0, tzinfo=timezone.utc)
    # HTTP-date
    got = parse_retry_after("Wed, 01 Jan 2026 12:05:00 GMT", now=_now())
    assert got == datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    # junk / missing → None (never raises)
    assert parse_retry_after("soon", now=_now()) is None
    assert parse_retry_after(None, now=_now()) is None
```

- [ ] **Step 2: Run → fail** (`ImportError: parse_retry_after`): `uv run pytest tests/unit/resolve/test_retry_after.py -v`

- [ ] **Step 3: Implement** — in `conneg.py`:

```python
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

POLITE_UA = "OntoExplorer-ResolvabilityBot/1.0 (+https://ontoexplorer.dev; dereference check)"


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> datetime | None:
    """Absolute 'do not retry before' time from a Retry-After header, or None.
    Accepts delta-seconds or an HTTP-date; never raises."""
    if not value:
        return None
    now = now or datetime.now(timezone.utc)
    value = value.strip()
    if value.isdigit():
        return now + timedelta(seconds=int(value))
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None
```

Add `retry_after: str | None = None` to `ResolveResult`. In `check_resolvable`, send the UA and, on a non-2xx response, capture Retry-After:

```python
            with client.stream("GET", iri, headers={"Accept": RDF_ACCEPT, "User-Agent": POLITE_UA}) as resp:
                ...
                if not 200 <= status < 300:
                    ra = parse_retry_after(resp.headers.get("retry-after"))
                    return ResolveResult(False, final_url=final, http_status=status,
                                         content_type=ctype, retry_after=ra.isoformat() if ra else None)
```

- [ ] **Step 4: Run → pass.** Also run the existing `tests/unit/resolve/test_check_resolvable.py` to confirm the added header/field didn't break it.

- [ ] **Step 5: Commit** — `feat(resolve): polite User-Agent + parse Retry-After`

---

### Task 2: Select retryable failures (respecting cooldown)

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`
- Test: `tests/unit/resolve/test_recheck_select.py`

**Interfaces:**
- Produces: `async def _retryable_resolvability_ids(db, *, limit: int, now=None) -> list[str]` — ontology ids whose last check was a transient failure (429/5xx or fetch error) and whose `resolve_detail.retry_after` is absent or already elapsed; oldest-checked first.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_recheck_select.py
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from ontoexplorer.models.db import Ontology
from ontoexplorer.modules.jobs.tasks import _retryable_resolvability_ids


async def _o(db, *, resolvable, detail, checked_minutes_ago=10):
    o = Ontology(id=uuid.uuid4().hex, iri=f"http://x/{uuid.uuid4().hex}", shortname=uuid.uuid4().hex[:8],
                 title="O", resolvable=resolvable, resolve_detail=detail,
                 resolve_checked_at=datetime.now(timezone.utc) - timedelta(minutes=checked_minutes_ago))
    db.add(o); await db.commit(); return o


@pytest.mark.anyio
async def test_retryable_selects_transient_failures(db_session):
    rate = await _o(db_session, resolvable=False, detail={"http_status": "429"})
    err = await _o(db_session, resolvable=False, detail={"http_status": None, "error": "timeout"})
    ids = await _retryable_resolvability_ids(db_session, limit=100)
    assert rate.id in ids and err.id in ids


@pytest.mark.anyio
async def test_retryable_excludes_permanent(db_session):
    dead = await _o(db_session, resolvable=False, detail={"http_status": "404"})
    html = await _o(db_session, resolvable=False, detail={"http_status": "200"})
    ok = await _o(db_session, resolvable=True, detail={"http_status": "200"})
    ids = await _retryable_resolvability_ids(db_session, limit=100)
    assert dead.id not in ids and html.id not in ids and ok.id not in ids


@pytest.mark.anyio
async def test_retryable_skips_cooldown(db_session):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    cooling = await _o(db_session, resolvable=False, detail={"http_status": "503", "retry_after": future})
    ids = await _retryable_resolvability_ids(db_session, limit=100)
    assert cooling.id not in ids
```

- [ ] **Step 2: Run → fail** (`ImportError`).

- [ ] **Step 3: Implement** in `tasks.py`:

```python
_RETRYABLE_STATUSES = ("429", "500", "502", "503", "504", "520", "522", "524")


async def _retryable_resolvability_ids(db, *, limit: int, now=None) -> list[str]:
    """Ontology ids whose last resolvability check was a TRANSIENT failure
    (429/5xx, or a fetch error with no HTTP status) and that are not inside a
    Retry-After cooldown. Oldest-checked first so the backlog rotates fairly."""
    from datetime import datetime, timezone
    from sqlalchemy import text
    now = now or datetime.now(timezone.utc)
    rows = (await db.execute(text("""
        SELECT id FROM ontologies
        WHERE resolvable IS FALSE
          AND (
            resolve_detail->>'http_status' IN :statuses
            OR (resolve_detail->>'http_status' IS NULL AND resolve_detail->>'error' IS NOT NULL)
          )
          AND (resolve_detail->>'retry_after' IS NULL
               OR (resolve_detail->>'retry_after')::timestamptz <= :now)
        ORDER BY resolve_checked_at ASC NULLS FIRST
        LIMIT :lim
    """).bindparams(statuses=tuple(_RETRYABLE_STATUSES)), {"now": now, "lim": limit})).all()
    return [str(r.id) for r in rows]
```

> Note: `IN :statuses` needs an expanding bindparam. If the raw `IN :tuple` form is awkward on both dialects, build the query with `sqlalchemy.bindparam("statuses", expanding=True)` and pass `list(_RETRYABLE_STATUSES)`; the `(... )::timestamptz` cast is Postgres-only, so for the sqlite test use `datetime(...)`-comparable ISO strings — the test seeds ISO strings and sqlite compares them lexically, which is correct for UTC ISO. Verify the test passes on sqlite; if the `::timestamptz` cast breaks sqlite, gate it like `_q_sql` (compare as text on sqlite, timestamptz on PG).

- [ ] **Step 4: Run → pass** (3 tests).

- [ ] **Step 5: Commit** — `feat(resolve): select transient-failure ontologies for re-check`

---

### Task 3: `recheck_resolvability` task with per-host spacing

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`
- Test: `tests/unit/resolve/test_recheck_task.py`

**Interfaces:**
- Consumes: `_retryable_resolvability_ids` (Task 2), `_apply_resolvability` (PR #304).
- Produces: `async def _recheck_batch(db, *, limit, min_host_interval_s, sleep, apply) -> int` — re-checks the selected ids, sleeping to keep same-host requests ≥ `min_host_interval_s` apart; `sleep`/`apply` injected for tests. Celery `recheck_resolvability` wraps it.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_recheck_task.py
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from ontoexplorer.models.db import Ontology
from ontoexplorer.modules.jobs.tasks import _recheck_batch


async def _o(db, host):
    o = Ontology(id=uuid.uuid4().hex, iri=f"https://{host}/{uuid.uuid4().hex}", shortname=uuid.uuid4().hex[:8],
                 title="O", resolvable=False, resolve_detail={"http_status": "429"},
                 resolve_checked_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    db.add(o); await db.commit(); return o


@pytest.mark.anyio
async def test_recheck_spaces_same_host(db_session):
    await _o(db_session, "w3id.org"); await _o(db_session, "w3id.org")
    slept, applied = [], []

    async def _apply(db, oid, **k): applied.append(oid)
    def _sleep(s): slept.append(s)

    n = await _recheck_batch(db_session, limit=100, min_host_interval_s=2.0, sleep=_sleep, apply=_apply)
    assert n >= 2
    # at least one spacing sleep of >= 2s between the two same-host checks
    assert any(s >= 2.0 for s in slept)


@pytest.mark.anyio
async def test_recheck_noop_when_none(db_session):
    slept = []
    n = await _recheck_batch(db_session, limit=100, min_host_interval_s=2.0,
                             sleep=lambda s: slept.append(s), apply=None)
    assert n == 0 and slept == []
```

- [ ] **Step 2: Run → fail** (`ImportError`).

- [ ] **Step 3: Implement** in `tasks.py`:

```python
async def _recheck_batch(db, *, limit, min_host_interval_s, sleep, apply) -> int:
    """Re-check a capped batch of transient-failure ontologies, spacing requests
    to the same host by >= min_host_interval_s. `sleep(seconds)` and
    `apply(db, ontology_id)` are injected (production: time.sleep + _apply_resolvability)."""
    import time as _t
    from urllib.parse import urlparse
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology

    ids = await _retryable_resolvability_ids(db, limit=limit)
    if not ids:
        return 0
    rows = (await db.execute(select(Ontology.id, Ontology.iri).where(Ontology.id.in_(ids)))).all()
    last_hit: dict[str, float] = {}
    for oid, iri in rows:
        host = (urlparse(iri).hostname or "").lower()
        wait = min_host_interval_s - (_t.monotonic() - last_hit.get(host, -1e9))
        if host in last_hit and wait > 0:
            sleep(wait)
        await apply(db, oid)
        last_hit[host] = _t.monotonic()
    return len(rows)


@celery_app.task(name="ontoexplorer.recheck_resolvability", time_limit=600)
def recheck_resolvability(limit: int = 60, min_host_interval_s: float = 2.0) -> dict:
    """Beat task: politely re-check transient-failure ontologies (429/5xx/timeout),
    spacing same-host requests so we never rate-limit ourselves again."""
    import time, asyncio
    from ontoexplorer.database import make_celery_db_session

    async def _run():
        async with make_celery_db_session()() as db:
            return await _recheck_batch(db, limit=limit, min_host_interval_s=min_host_interval_s,
                                        sleep=time.sleep, apply=_apply_resolvability)

    n = asyncio.run(_run())
    log.info("recheck_resolvability", rechecked=n)
    return {"rechecked": n}
```

> `_apply_resolvability(db, oid)` (PR #304) does the conneg check + stores the result (including the new `retry_after`). The `time.sleep` inside the `asyncio.run` coroutine is acceptable here — the batch is deliberately serial and polite; do not parallelize.

- [ ] **Step 4: Run → pass** (2 tests).

- [ ] **Step 5: Commit** — `feat(resolve): polite per-host-spaced resolvability re-check task`

---

### Task 4: Beat schedule

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py` (the `beat_schedule` dict)
- Test: covered by Task 3 (the task runs); this is config.

- [ ] **Step 1: Add the entry** next to the other `beat_schedule` members:

```python
        # Politely recover transient resolvability failures (429/5xx/timeout):
        # a small per-host-spaced batch every 30 min, so throttled hosts clear
        # over a few runs without us ever bursting them.
        "recheck-resolvability-30min": {
            "task": "ontoexplorer.recheck_resolvability",
            "schedule": 1800.0,
        },
```

- [ ] **Step 2: Sanity** — `uv run python -c "from ontoexplorer.modules.jobs.tasks import celery_app; assert 'recheck-resolvability-30min' in celery_app.conf.beat_schedule"`

- [ ] **Step 3: Commit** — `feat(resolve): schedule polite resolvability re-check every 30m`

---

## Notes for the executor

- **Math:** 60 rows/run × a 2 s per-host floor, every 30 min, drains the ~94 throttled + ~586 timeout rows over a handful of runs — gently. Tune `limit`/`min_host_interval_s` via the task args if a host is still touchy.
- **One-off (ops, optional):** the same `recheck_resolvability.delay(limit=..., min_host_interval_s=...)` can be fired once by hand to speed recovery — still polite because the batch is host-spaced.
- **Relationship to the backfill:** the initial backfill stays a one-shot; this task is the steady-state recovery loop. A future refinement could also re-check *successful* rows on a slow cadence (IRIs rot), but that is out of scope here.
