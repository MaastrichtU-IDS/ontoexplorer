# Admin Multi-Version View, Diff Pipeline Controls, and Configurable Paging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the admin interface so all versions of each ontology are visible (expandable rows), the diff pipeline can be triggered per-pair and in bulk, and all three admin tables get configurable paging persisted in localStorage.

**Architecture:** `/admin/overview` stays one-row-per-ontology (latest-version state) so the 10-second polling stays cheap; a new lazy `GET /admin/ontologies/{id}/versions` endpoint fetches all versions when a row is expanded. Five new POST endpoints queue actions or diff jobs against a specific `version_id`. The frontend adds an expandable row, a "Diff vs prev" column, and a small `usePagedTable` hook used by all three admin tables.

**Tech Stack:** Python 3.11+ (FastAPI, SQLAlchemy 2 async, Celery), pytest+anyio, React 18 + TypeScript, React Query (TanStack), Vitest.

**Reference spec:** [`docs/superpowers/specs/2026-05-19-admin-multi-version-and-paging-design.md`](../specs/2026-05-19-admin-multi-version-and-paging-design.md)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ontoexplorer/api/admin.py` | MODIFY | Add `_diff_status_for_pair` helper; new GET versions endpoint; 4 per-version action endpoints; 2 diff queue endpoints |
| `tests/integration/test_admin.py` | MODIFY | Tests for the 7 new endpoints + the helper |
| `frontend/src/lib/api.ts` | MODIFY | Add `AdminVersionEntry` / `AdminVersionsResponse` types + 7 new client methods under `api.admin` |
| `frontend/src/hooks/usePagedTable.ts` | CREATE | Reusable hook: pageSize (localStorage-persisted, default 10), page state, slicing |
| `frontend/src/hooks/usePagedTable.test.ts` | CREATE | Hook tests: default, persistence, invalid fallback, page reset |
| `frontend/src/components/TablePager.tsx` | CREATE | Renders the rows-per-page input + page nav controls |
| `frontend/src/components/TablePager.test.tsx` | CREATE | UI tests for the pager |
| `frontend/src/pages/AdminPage.tsx` | MODIFY | Wire `usePagedTable` into all 3 tables; add expansion state + "Diff vs prev" column; per-version action handlers; bulk "Recompute all diffs" button |

---

## Task 1: Backend — `_diff_status_for_pair` helper

**Files:**
- Modify: `ontoexplorer/api/admin.py`
- Modify: `tests/integration/test_admin.py`

This helper takes a `(from_version_id, to_version_id)` pair and returns a status string used by the versions endpoint. The same definition will be reused by the bulk recompute endpoint.

- [ ] **Step 1: Add the failing test**

Append to `tests/integration/test_admin.py`:

```python
@pytest.mark.anyio
async def test_diff_status_for_pair_missing(db_session):
    """No OntologyDiff row → status='missing'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion

    ont = Ontology(iri="http://example.org/ds-missing.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsm1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsm2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2)
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "missing"
    assert result["diff_id"] is None
    assert result["computed_at"] is None


@pytest.mark.anyio
async def test_diff_status_for_pair_ready(db_session):
    """Ready diff with inferred_status ready on both sides → 'ready'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff

    ont = Ontology(iri="http://example.org/ds-ready.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsr1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsr2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    diff = OntologyDiff(
        ontology_id=ont.id, version_from_id=v1.id, version_to_id=v2.id,
        status="ready",
        summary={"inferred_status": {"from_version": "ready", "to_version": "ready"}},
    )
    db_session.add(diff)
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "ready"
    assert result["diff_id"] == diff.id


@pytest.mark.anyio
async def test_diff_status_for_pair_pending(db_session):
    """OntologyDiff.status='pending' → 'pending'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff

    ont = Ontology(iri="http://example.org/ds-pending.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsp1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsp2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    db_session.add(OntologyDiff(
        ontology_id=ont.id, version_from_id=v1.id, version_to_id=v2.id,
        status="pending", summary=None,
    ))
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "pending"


@pytest.mark.anyio
async def test_diff_status_for_pair_failed(db_session):
    """OntologyDiff.status='failed' → 'failed'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff

    ont = Ontology(iri="http://example.org/ds-failed.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsf1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsf2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    db_session.add(OntologyDiff(
        ontology_id=ont.id, version_from_id=v1.id, version_to_id=v2.id,
        status="failed", summary=None,
    ))
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "failed"


@pytest.mark.anyio
async def test_diff_status_for_pair_stale_when_inferred_missing(db_session):
    """Ready diff with inferred_status='missing' for a side whose reason job is 'done' → 'stale'."""
    from ontoexplorer.api.admin import _diff_status_for_pair
    from ontoexplorer.models.db import Ontology, OntologyVersion, OntologyDiff, Job

    ont = Ontology(iri="http://example.org/ds-stale.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dsst1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dsst2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.flush()
    db_session.add(OntologyDiff(
        ontology_id=ont.id, version_from_id=v1.id, version_to_id=v2.id,
        status="ready",
        summary={"inferred_status": {"from_version": "missing", "to_version": "ready"}},
    ))
    # Now reasoning for v1 has actually completed but the diff hasn't been refreshed yet.
    db_session.add(Job(version_id=v1.id, type="reason", status="done"))
    await db_session.commit()

    result = await _diff_status_for_pair(db_session, v1.id, v2.id)
    assert result["status"] == "stale"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/micheldumontier/code/ontoexplorer && uv run pytest tests/integration/test_admin.py -v -k diff_status_for_pair 2>&1 | tail -15`

Expected: 5 FAILED (cannot import `_diff_status_for_pair`).

- [ ] **Step 3: Add the helper**

In `ontoexplorer/api/admin.py`, after the existing `_reasoning_status` function (near line 116), add:

```python
async def _diff_status_for_pair(db: AsyncSession, from_vid: str, to_vid: str) -> dict:
    """Return the diff-pipeline status for an ordered (from, to) version pair.

    Status semantics:
      - 'missing'  — no OntologyDiff row exists for this pair
      - 'pending'  — OntologyDiff.status == 'pending'
      - 'running'  — there is a running Job(type='diff') for either version (rare;
                     compute_diff doesn't always insert a Job, so primarily we
                     trust OntologyDiff.status)
      - 'failed'   — OntologyDiff.status == 'failed'
      - 'stale'    — OntologyDiff.status == 'ready' BUT summary.inferred_status
                     shows a side != 'ready' while that side's reasoning Job is
                     now 'done' (Phase 4 stale-detection condition)
      - 'ready'    — OntologyDiff.status == 'ready' and not stale
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Job, OntologyDiff

    diff = (await db.execute(
        select(OntologyDiff).where(
            OntologyDiff.version_from_id == from_vid,
            OntologyDiff.version_to_id == to_vid,
        )
    )).scalar_one_or_none()

    if diff is None:
        return {"status": "missing", "diff_id": None, "computed_at": None}

    base = {
        "diff_id": diff.id,
        "computed_at": diff.created_at.isoformat() if diff.created_at else None,
    }

    if diff.status in ("pending", "running", "failed"):
        return {"status": diff.status, **base}

    # status == 'ready' — check for staleness
    inferred = (diff.summary or {}).get("inferred_status", {})
    for side, vid in (("from_version", from_vid), ("to_version", to_vid)):
        if inferred.get(side) != "ready":
            reason_done = (await db.execute(
                select(Job).where(
                    Job.version_id == vid,
                    Job.type == "reason",
                    Job.status == "done",
                ).limit(1)
            )).scalar_one_or_none()
            if reason_done is not None:
                return {"status": "stale", **base}

    return {"status": "ready", **base}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_admin.py -v -k diff_status_for_pair 2>&1 | tail -10`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add ontoexplorer/api/admin.py tests/integration/test_admin.py
git commit -m "feat(admin): _diff_status_for_pair helper"
```

---

## Task 2: Backend — `GET /admin/ontologies/{ontology_id}/versions`

**Files:**
- Modify: `ontoexplorer/api/admin.py`
- Modify: `tests/integration/test_admin.py`

Returns all versions for an ontology with per-version pipeline state + `diff_vs_prev`.

- [ ] **Step 1: Add failing tests**

Append to `tests/integration/test_admin.py`:

```python
@pytest.mark.anyio
async def test_admin_versions_returns_all_versions_newest_first(client, user_and_key, monkeypatch, db_session):
    """GET /admin/ontologies/{id}/versions returns all versions, newest first."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/av1.owl", shortname="av1")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="av101", format="turtle", status="deprecated", triple_count=100)
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="av102", format="turtle", status="ready", triple_count=200)
    db_session.add(v1); db_session.add(v2)
    await db_session.commit()

    with (
        patch("ontoexplorer.api.admin._search_redis", return_value=MagicMock(exists=lambda k: False)),
        patch("ontoexplorer.api.admin._reasoning_status", new=AsyncMock(return_value="not_started")),
    ):
        resp = await client.get(
            f"/api/v1/admin/ontologies/{ont.id}/versions",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ontology_id"] == ont.id
    versions = body["versions"]
    assert len(versions) == 2
    # Newest first
    assert versions[0]["version_id"] == v2.id
    assert versions[1]["version_id"] == v1.id
    # Newest is_latest
    assert versions[0]["is_latest"] is True
    assert versions[1]["is_latest"] is False
    # diff_vs_prev shape on the oldest version: previous_version_id is None
    assert versions[1]["diff_vs_prev"]["previous_version_id"] is None
    assert versions[1]["diff_vs_prev"]["status"] == "missing"
    # diff_vs_prev on the newer version: previous_version_id == v1.id
    assert versions[0]["diff_vs_prev"]["previous_version_id"] == v1.id


@pytest.mark.anyio
async def test_admin_versions_404_for_unknown_ontology(client, user_and_key, monkeypatch):
    """Unknown ontology_id → 404."""
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key
    resp = await client.get(
        "/api/v1/admin/ontologies/nonexistent-id/versions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_admin_versions_requires_admin(client, user_and_key, db_session):
    """Non-admin → 403."""
    from ontoexplorer.models.db import Ontology
    _, raw_key = user_and_key
    ont = Ontology(iri="http://example.org/av2.owl")
    db_session.add(ont); await db_session.commit()

    resp = await client.get(
        f"/api/v1/admin/ontologies/{ont.id}/versions",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 403
```

Make sure the test file imports at the top include:
```python
from unittest.mock import AsyncMock, MagicMock, patch
```
(They already do; this is a sanity check.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_admin.py -v -k admin_versions 2>&1 | tail -10`

Expected: 3 FAILED with 404 (route not registered).

- [ ] **Step 3: Add the endpoint**

In `ontoexplorer/api/admin.py`, after `admin_overview` (before the `# ── Workers ──` divider near line 239), add:

```python
@router.get(
    "/ontologies/{ontology_id}/versions",
    summary="List all versions of an ontology with per-version pipeline state",
)
async def admin_ontology_versions(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Returns every version of an ontology (newest first), each with the same
    pipeline fields as AdminOntologyEntry plus a diff_vs_prev block for the
    diff against the immediately-older version (None for the oldest)."""
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion

    ont = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()
    if ont is None:
        raise HTTPException(status_code=404, detail="Ontology not found")

    # Versions newest first.
    versions = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .order_by(OntologyVersion.created_at.desc())
    )).scalars().all()

    if not versions:
        return {"ontology_id": ontology_id, "versions": []}

    # Embedding counts in one grouped query.
    version_ids = [v.id for v in versions]
    count_rows = (await db.execute(
        text("""
            SELECT version_id, COUNT(*) AS cnt
            FROM term_embeddings
            WHERE version_id = ANY(:ids)
            GROUP BY version_id
        """),
        {"ids": version_ids},
    )).all()
    embed_counts = {str(r.version_id): int(r.cnt) for r in count_rows}

    search_r = await asyncio.to_thread(_search_redis)
    latest_id = versions[0].id  # newest-first

    # diff_vs_prev needs the "previous" version, which is the one immediately
    # older. Because we ordered DESC, previous_version_id for versions[i] is
    # versions[i+1].id (the next-older one).
    async def _entry(idx: int, v: OntologyVersion) -> dict:
        vid = v.id
        indexed = await asyncio.to_thread(
            lambda: bool(search_r.exists(f"search:meta:{vid}"))
        )
        reasoning = await _reasoning_status(vid)

        prev_version_id = versions[idx + 1].id if idx + 1 < len(versions) else None
        if prev_version_id is not None:
            diff_vs_prev = await _diff_status_for_pair(db, prev_version_id, vid)
            diff_vs_prev["previous_version_id"] = prev_version_id
        else:
            diff_vs_prev = {
                "previous_version_id": None,
                "status": "missing",
                "diff_id": None,
                "computed_at": None,
            }

        return {
            "version_id": vid,
            "triple_count": v.triple_count,
            "ingestion_status": v.status,
            "indexed": indexed,
            "embed_count": embed_counts.get(vid, 0),
            "reasoning_status": reasoning,
            "version_created_at": v.created_at.isoformat() if v.created_at else None,
            "source_url": v.source_url,
            "is_latest": vid == latest_id,
            "diff_vs_prev": diff_vs_prev,
        }

    entries = await asyncio.gather(*[_entry(i, v) for i, v in enumerate(versions)])
    return {"ontology_id": ontology_id, "versions": list(entries)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_admin.py -v -k admin_versions 2>&1 | tail -10`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/admin.py tests/integration/test_admin.py
git commit -m "feat(admin): GET /admin/ontologies/{id}/versions lazy endpoint"
```

---

## Task 3: Backend — per-version action endpoints (index, embed, reason)

**Files:**
- Modify: `ontoexplorer/api/admin.py`
- Modify: `tests/integration/test_admin.py`

Three sibling endpoints that take `version_id` and dispatch the existing Celery tasks for that exact version.

- [ ] **Step 1: Add failing tests**

Append to `tests/integration/test_admin.py`:

```python
@pytest.mark.anyio
async def test_admin_version_action_index_queues_task(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/va-idx.owl")
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="vai01", format="turtle", status="ready")
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-idx-1")
    with patch("ontoexplorer.modules.jobs.tasks.index_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/index",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "task_id": "task-idx-1"}
    m.assert_called_once_with(version_id=v.id, ontology_id=ont.id)


@pytest.mark.anyio
async def test_admin_version_action_embed_queues_task(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/va-emb.owl")
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="vae01", format="turtle", status="ready")
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-emb-1")
    with patch("ontoexplorer.modules.jobs.tasks.embed_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/embed",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "task_id": "task-emb-1"}
    m.assert_called_once_with(version_id=v.id, ontology_id=ont.id)


@pytest.mark.anyio
async def test_admin_version_action_reason_queues_task(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/va-rsn.owl")
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="var01", format="turtle", status="ready")
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-rsn-1")
    with patch("ontoexplorer.modules.jobs.tasks.reason_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/reason",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "task_id": "task-rsn-1"}
    m.assert_called_once_with(version_id=v.id)


@pytest.mark.anyio
async def test_admin_version_action_404_for_unknown_version(client, user_and_key, monkeypatch):
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key
    resp = await client.post(
        "/api/v1/admin/versions/no-such-vid/index",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_admin.py -v -k admin_version_action 2>&1 | tail -10`

Expected: 4 FAILED.

- [ ] **Step 3: Add the endpoints**

In `ontoexplorer/api/admin.py`, after `admin_queue_reason` (the existing per-ontology one near line 552), add:

```python
# ── Per-version actions (operate on a specific version_id) ────────────────────

async def _load_version(db: AsyncSession, version_id: str):
    """Load an OntologyVersion by id or raise 404."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyVersion
    v = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == version_id)
    )).scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return v


@router.post(
    "/versions/{version_id}/index",
    summary="Queue search re-index for a specific version",
)
async def admin_queue_index_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tasks import index_ontology
    v = await _load_version(db, version_id)
    task = index_ontology.delay(version_id=v.id, ontology_id=v.ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post(
    "/versions/{version_id}/embed",
    summary="Queue embedding generation for a specific version",
)
async def admin_queue_embed_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tasks import embed_ontology
    v = await _load_version(db, version_id)
    task = embed_ontology.delay(version_id=v.id, ontology_id=v.ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post(
    "/versions/{version_id}/reason",
    summary="Queue OWL reasoning for a specific version",
)
async def admin_queue_reason_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tasks import reason_ontology
    v = await _load_version(db, version_id)
    task = reason_ontology.delay(version_id=v.id)
    return {"status": "queued", "task_id": task.id}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_admin.py -v -k admin_version_action 2>&1 | tail -10`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/admin.py tests/integration/test_admin.py
git commit -m "feat(admin): per-version POST endpoints for index/embed/reason"
```

---

## Task 4: Backend — per-version ingest endpoint

**Files:**
- Modify: `ontoexplorer/api/admin.py`
- Modify: `tests/integration/test_admin.py`

Re-fetches the version's `source_url` (falling back to the parent ontology IRI with content negotiation), dispatching `ingest_ontology.delay(...)`. Note: this creates a new version if bytes have changed; the pipeline is content-addressed by SHA-256 so it cannot mutate an existing version.

- [ ] **Step 1: Add failing tests**

Append:

```python
@pytest.mark.anyio
async def test_admin_version_action_ingest_uses_source_url(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/va-ing.owl", owner_id=None)
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(
        ontology_id=ont.id, minio_key="k", sha256="vain01", format="turtle",
        status="ready", source_url="https://example.org/ont.ttl",
    )
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-ing-1")
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/ingest",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert resp.json()["method"] == "url"
    m.assert_called_once()
    kwargs = m.call_args.kwargs
    assert kwargs["url"] == "https://example.org/ont.ttl"
    assert kwargs["iri"] is None


@pytest.mark.anyio
async def test_admin_version_action_ingest_falls_back_to_iri(client, user_and_key, monkeypatch, db_session):
    """No source_url → falls back to ontology IRI with content negotiation."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/has-iri.owl", owner_id=None)
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="vain02", format="turtle", status="ready", source_url=None)
    db_session.add(v); await db_session.commit()

    mock_task = MagicMock(id="task-ing-2")
    with patch("ontoexplorer.modules.jobs.tasks.ingest_ontology.delay", return_value=mock_task) as m:
        resp = await client.post(
            f"/api/v1/admin/versions/{v.id}/ingest",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 200
    assert resp.json()["method"] == "iri"
    kwargs = m.call_args.kwargs
    assert kwargs["iri"] == "http://example.org/has-iri.owl"
    assert kwargs["url"] is None


@pytest.mark.anyio
async def test_admin_version_action_ingest_422_when_no_source(client, user_and_key, monkeypatch, db_session):
    """No source_url and no IRI on the parent → 422."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="", owner_id=None)  # blank IRI
    db_session.add(ont); await db_session.flush()
    v = OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="vain03", format="turtle", status="ready", source_url=None)
    db_session.add(v); await db_session.commit()

    resp = await client.post(
        f"/api/v1/admin/versions/{v.id}/ingest",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_admin.py -v -k admin_version_action_ingest 2>&1 | tail -10`

Expected: 3 FAILED.

- [ ] **Step 3: Add the endpoint**

In `ontoexplorer/api/admin.py`, immediately after `admin_queue_reason_for_version`, add:

```python
@router.post(
    "/versions/{version_id}/ingest",
    summary="Re-fetch a specific version's source URL (creates a new version if bytes have changed)",
)
async def admin_queue_ingest_for_version(
    version_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Dispatches ingest_ontology against this version's source_url (or the
    ontology's IRI via content negotiation when no source_url is set).

    Important: the ingestion pipeline is content-addressed by SHA-256, so if
    the bytes haven't changed, the existing version is returned and nothing
    happens. If they have changed, a NEW version is created — versions are
    immutable.
    """
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    v = await _load_version(db, version_id)
    ont = (await db.execute(
        select(Ontology).where(Ontology.id == v.ontology_id)
    )).scalar_one()

    fetch_url = v.source_url
    use_iri = False
    if not fetch_url:
        if not ont.iri:
            raise HTTPException(
                status_code=422,
                detail="Version has no source_url and parent ontology has no IRI",
            )
        fetch_url = ont.iri
        use_iri = True

    task = ingest_ontology.delay(
        iri=fetch_url if use_iri else None,
        url=fetch_url if not use_iri else None,
        raw_bytes_hex=None,
        filename=None,
        content_type=None,
        owner_id=ont.owner_id,
        groups=list(ont.groups or []),
    )
    return {"status": "queued", "task_id": task.id, "method": "iri" if use_iri else "url"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_admin.py -v -k admin_version_action_ingest 2>&1 | tail -10`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/admin.py tests/integration/test_admin.py
git commit -m "feat(admin): per-version POST /versions/{vid}/ingest endpoint"
```

---

## Task 5: Backend — diff queue endpoints

**Files:**
- Modify: `ontoexplorer/api/admin.py`
- Modify: `tests/integration/test_admin.py`

Two endpoints:
- `POST /admin/diffs/queue` — queue one diff
- `POST /admin/ontologies/{ontology_id}/diffs/recompute-all` — queue diffs for every consecutive version pair

- [ ] **Step 1: Add failing tests**

Append:

```python
@pytest.mark.anyio
async def test_admin_queue_diff_dispatches_compute_diff(client, user_and_key, monkeypatch, db_session):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/dq.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="dq01", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="dq02", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.commit()

    mock_task = MagicMock(id="task-diff-1")
    with patch("ontoexplorer.modules.jobs.tasks.compute_diff.delay", return_value=mock_task) as m:
        resp = await client.post(
            "/api/v1/admin/diffs/queue",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"from_version_id": v1.id, "to_version_id": v2.id},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert resp.json()["task_id"] == "task-diff-1"
    m.assert_called_once_with(v1.id, v2.id, ont.id)


@pytest.mark.anyio
async def test_admin_queue_diff_422_when_versions_belong_to_different_ontologies(
    client, user_and_key, monkeypatch, db_session
):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    o1 = Ontology(iri="http://example.org/dq-a.owl")
    o2 = Ontology(iri="http://example.org/dq-b.owl")
    db_session.add(o1); db_session.add(o2); await db_session.flush()
    v1 = OntologyVersion(ontology_id=o1.id, minio_key="k", sha256="dqx1", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=o2.id, minio_key="k", sha256="dqx2", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); await db_session.commit()

    resp = await client.post(
        "/api/v1/admin/diffs/queue",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"from_version_id": v1.id, "to_version_id": v2.id},
    )
    assert resp.status_code == 422
    assert "different ontologies" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_admin_recompute_all_diffs_queues_consecutive_pairs(
    client, user_and_key, monkeypatch, db_session
):
    """Three versions → two consecutive pairs queued."""
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/rcad.owl")
    db_session.add(ont); await db_session.flush()
    v1 = OntologyVersion(ontology_id=ont.id, minio_key="k1", sha256="rcad01", format="turtle", status="ready")
    v2 = OntologyVersion(ontology_id=ont.id, minio_key="k2", sha256="rcad02", format="turtle", status="ready")
    v3 = OntologyVersion(ontology_id=ont.id, minio_key="k3", sha256="rcad03", format="turtle", status="ready")
    db_session.add(v1); db_session.add(v2); db_session.add(v3); await db_session.commit()

    calls = []
    with patch(
        "ontoexplorer.modules.jobs.tasks.compute_diff.delay",
        side_effect=lambda *a, **kw: calls.append((a, kw)) or MagicMock(id="t"),
    ):
        resp = await client.post(
            f"/api/v1/admin/ontologies/{ont.id}/diffs/recompute-all",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

    assert resp.status_code == 200
    assert resp.json()["queued"] == 2
    # Pairs are (oldest→middle) and (middle→newest)
    assert calls[0][0] == (v1.id, v2.id, ont.id)
    assert calls[1][0] == (v2.id, v3.id, ont.id)


@pytest.mark.anyio
async def test_admin_recompute_all_diffs_single_version_returns_zero(
    client, user_and_key, monkeypatch, db_session
):
    from ontoexplorer.models.db import Ontology, OntologyVersion
    monkeypatch.setattr("ontoexplorer.api.admin.is_admin", lambda u: True)
    _, raw_key = user_and_key

    ont = Ontology(iri="http://example.org/rcad-one.owl")
    db_session.add(ont); await db_session.flush()
    db_session.add(OntologyVersion(ontology_id=ont.id, minio_key="k", sha256="rcad11", format="turtle", status="ready"))
    await db_session.commit()

    with patch("ontoexplorer.modules.jobs.tasks.compute_diff.delay") as m:
        resp = await client.post(
            f"/api/v1/admin/ontologies/{ont.id}/diffs/recompute-all",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 200
    assert resp.json()["queued"] == 0
    m.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_admin.py -v -k "queue_diff or recompute_all" 2>&1 | tail -10`

Expected: 4 FAILED.

- [ ] **Step 3: Add the endpoints**

In `ontoexplorer/api/admin.py`, at the end of the file, add:

```python
# ── Diff queue endpoints ──────────────────────────────────────────────────────

from pydantic import BaseModel


class _DiffQueueBody(BaseModel):
    from_version_id: str
    to_version_id: str


@router.post(
    "/diffs/queue",
    summary="Queue compute_diff for a specific (from, to) version pair",
)
async def admin_queue_diff(
    body: _DiffQueueBody,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Both versions must belong to the same ontology."""
    from sqlalchemy import select
    from ontoexplorer.models.db import OntologyVersion
    from ontoexplorer.modules.jobs.tasks import compute_diff

    v_from = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == body.from_version_id)
    )).scalar_one_or_none()
    v_to = (await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == body.to_version_id)
    )).scalar_one_or_none()
    if v_from is None or v_to is None:
        raise HTTPException(status_code=404, detail="One or both versions not found")
    if v_from.ontology_id != v_to.ontology_id:
        raise HTTPException(
            status_code=422,
            detail="Versions belong to different ontologies — use the /compare endpoint",
        )

    task = compute_diff.delay(v_from.id, v_to.id, v_from.ontology_id)
    return {"status": "queued", "task_id": task.id}


@router.post(
    "/ontologies/{ontology_id}/diffs/recompute-all",
    summary="Queue compute_diff for every consecutive version pair of an ontology",
)
async def admin_recompute_all_diffs(
    ontology_id: str,
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion
    from ontoexplorer.modules.jobs.tasks import compute_diff

    ont = (await db.execute(
        select(Ontology).where(Ontology.id == ontology_id)
    )).scalar_one_or_none()
    if ont is None:
        raise HTTPException(status_code=404, detail="Ontology not found")

    versions = (await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology_id)
        .order_by(OntologyVersion.created_at.asc())
    )).scalars().all()

    queued = 0
    for prev, curr in zip(versions, versions[1:]):
        compute_diff.delay(prev.id, curr.id, ontology_id)
        queued += 1

    return {"queued": queued}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_admin.py -v -k "queue_diff or recompute_all" 2>&1 | tail -10`

Expected: 4 passed. Also confirm the full file is green: `uv run pytest tests/integration/test_admin.py 2>&1 | tail -5`.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/admin.py tests/integration/test_admin.py
git commit -m "feat(admin): diff queue endpoints (single pair + recompute-all)"
```

---

## Task 6: Frontend — types and API client methods

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the types**

In `frontend/src/lib/api.ts`, immediately after `AdminOverview` (around [api.ts:677](frontend/src/lib/api.ts#L677)), add:

```typescript
export interface AdminVersionEntry {
  version_id: string
  triple_count: number | null
  ingestion_status: string
  indexed: boolean
  embed_count: number
  reasoning_status: 'ready' | 'running' | 'not_started'
  version_created_at: string | null
  source_url: string | null
  is_latest: boolean
  diff_vs_prev: {
    previous_version_id: string | null
    status: 'ready' | 'running' | 'pending' | 'failed' | 'missing' | 'stale'
    diff_id: string | null
    computed_at: string | null
  }
}

export interface AdminVersionsResponse {
  ontology_id: string
  versions: AdminVersionEntry[]
}
```

- [ ] **Step 2: Add the client methods**

In the `admin: { ... }` block (starting [api.ts:1126](frontend/src/lib/api.ts#L1126)), append after `reindexAll`:

```typescript
    versions: (ontologyId: string) =>
      request<AdminVersionsResponse>(`/admin/ontologies/${ontologyId}/versions`),

    queueIndexForVersion: (versionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/versions/${versionId}/index`,
        { method: 'POST' }
      ),

    queueEmbedForVersion: (versionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/versions/${versionId}/embed`,
        { method: 'POST' }
      ),

    queueReasonForVersion: (versionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/versions/${versionId}/reason`,
        { method: 'POST' }
      ),

    queueIngestForVersion: (versionId: string) =>
      request<{ status: string; task_id: string; method: 'iri' | 'url' }>(
        `/admin/versions/${versionId}/ingest`,
        { method: 'POST' }
      ),

    queueDiff: (fromVersionId: string, toVersionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/diffs/queue`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ from_version_id: fromVersionId, to_version_id: toVersionId }),
        }
      ),

    recomputeAllDiffs: (ontologyId: string) =>
      request<{ queued: number }>(
        `/admin/ontologies/${ontologyId}/diffs/recompute-all`,
        { method: 'POST' }
      ),
```

- [ ] **Step 3: Type-check**

Run: `cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: clean (no errors mentioning `api.ts` or the new types).

- [ ] **Step 4: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/lib/api.ts
git commit -m "feat(api): admin per-version + diff queue client methods"
```

---

## Task 7: Frontend — `usePagedTable` hook

**Files:**
- Create: `frontend/src/hooks/usePagedTable.ts`
- Create: `frontend/src/hooks/usePagedTable.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/hooks/usePagedTable.test.ts`:

```typescript
import { describe, expect, test, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePagedTable } from './usePagedTable'

beforeEach(() => {
  localStorage.clear()
})

const ROWS = Array.from({ length: 27 }, (_, i) => i)

describe('usePagedTable', () => {
  test('defaults pageSize to 10 and slices accordingly', () => {
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-a'))
    expect(result.current.pageSize).toBe(10)
    expect(result.current.paged).toHaveLength(10)
    expect(result.current.paged[0]).toBe(0)
    expect(result.current.totalPages).toBe(3)
  })

  test('setPage advances slicing', () => {
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-b'))
    act(() => result.current.setPage(1))
    expect(result.current.paged[0]).toBe(10)
    expect(result.current.paged).toHaveLength(10)
    act(() => result.current.setPage(2))
    expect(result.current.paged).toHaveLength(7)
  })

  test('setPageSize resets page to 0 and re-slices', () => {
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-c'))
    act(() => result.current.setPage(2))
    expect(result.current.page).toBe(2)
    act(() => result.current.setPageSize(20))
    expect(result.current.page).toBe(0)
    expect(result.current.paged).toHaveLength(20)
  })

  test('pageSize persists to localStorage and reads back', () => {
    const { result, unmount } = renderHook(() => usePagedTable(ROWS, 'test-d'))
    act(() => result.current.setPageSize(15))
    unmount()
    const { result: result2 } = renderHook(() => usePagedTable(ROWS, 'test-d'))
    expect(result2.current.pageSize).toBe(15)
  })

  test('invalid stored value falls back to default 10', () => {
    localStorage.setItem('admin.rowsPerPage.test-e', 'not-a-number')
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-e'))
    expect(result.current.pageSize).toBe(10)
  })

  test('out-of-range stored value falls back to default 10', () => {
    localStorage.setItem('admin.rowsPerPage.test-f', '99999')
    const { result } = renderHook(() => usePagedTable(ROWS, 'test-f'))
    expect(result.current.pageSize).toBe(10)
  })

  test('page snaps to last when input list shrinks below current offset', () => {
    let rows = ROWS
    const { result, rerender } = renderHook(({ r }) => usePagedTable(r, 'test-g'), {
      initialProps: { r: rows },
    })
    act(() => result.current.setPage(2))
    expect(result.current.page).toBe(2)
    rows = ROWS.slice(0, 5)
    rerender({ r: rows })
    expect(result.current.page).toBe(0)
    expect(result.current.paged).toHaveLength(5)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/micheldumontier/code/ontoexplorer/frontend && npx vitest run src/hooks/usePagedTable.test.ts 2>&1 | tail -10`

Expected: 7 FAILED (module not found).

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/usePagedTable.ts`:

```typescript
import { useEffect, useMemo, useState } from 'react'

const DEFAULT_PAGE_SIZE = 10
const MIN_PAGE_SIZE = 1
const MAX_PAGE_SIZE = 500
const LS_PREFIX = 'admin.rowsPerPage.'

function readStoredPageSize(scopeKey: string): number {
  try {
    const raw = localStorage.getItem(LS_PREFIX + scopeKey)
    if (raw == null) return DEFAULT_PAGE_SIZE
    const n = Number(raw)
    if (!Number.isFinite(n) || n < MIN_PAGE_SIZE || n > MAX_PAGE_SIZE) {
      return DEFAULT_PAGE_SIZE
    }
    return Math.floor(n)
  } catch {
    return DEFAULT_PAGE_SIZE
  }
}

export interface UsePagedTableResult<T> {
  paged: T[]
  page: number
  setPage: (p: number) => void
  pageSize: number
  setPageSize: (n: number) => void
  totalPages: number
  total: number
}

export function usePagedTable<T>(rows: T[], scopeKey: string): UsePagedTableResult<T> {
  const [pageSize, setPageSizeRaw] = useState<number>(() => readStoredPageSize(scopeKey))
  const [page, setPage] = useState(0)

  function setPageSize(n: number) {
    const valid = Number.isFinite(n) && n >= MIN_PAGE_SIZE && n <= MAX_PAGE_SIZE
    const next = valid ? Math.floor(n) : DEFAULT_PAGE_SIZE
    setPageSizeRaw(next)
    setPage(0)
    if (valid) {
      try {
        localStorage.setItem(LS_PREFIX + scopeKey, String(next))
      } catch {
        // Ignore quota / privacy-mode errors.
      }
    }
  }

  const total = rows.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  // If the input list shrinks past the current page, snap to page 0.
  useEffect(() => {
    if (page * pageSize >= total && page !== 0) {
      setPage(0)
    }
  }, [total, page, pageSize])

  const paged = useMemo(
    () => rows.slice(page * pageSize, (page + 1) * pageSize),
    [rows, page, pageSize],
  )

  return { paged, page, setPage, pageSize, setPageSize, totalPages, total }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/micheldumontier/code/ontoexplorer/frontend && npx vitest run src/hooks/usePagedTable.test.ts 2>&1 | tail -10`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/hooks/usePagedTable.ts frontend/src/hooks/usePagedTable.test.ts
git commit -m "feat(frontend): usePagedTable hook with localStorage-persisted pageSize"
```

---

## Task 8: Frontend — `<TablePager>` component

**Files:**
- Create: `frontend/src/components/TablePager.tsx`
- Create: `frontend/src/components/TablePager.test.tsx`

A small presentational component used by all three tables. The Rows input commits on blur or Enter.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/components/TablePager.test.tsx`:

```tsx
import { describe, expect, test, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TablePager } from './TablePager'

function Setup(props: Partial<React.ComponentProps<typeof TablePager>> = {}) {
  const defaults: React.ComponentProps<typeof TablePager> = {
    total: 47, page: 0, pageSize: 10,
    onPage: () => {}, onPageSize: () => {},
  }
  return <TablePager {...defaults} {...props} />
}

describe('TablePager', () => {
  test('renders "Rows", current input, and range', () => {
    render(<Setup />)
    expect(screen.getByLabelText(/rows/i)).toHaveValue(10)
    expect(screen.getByText(/1\D+10\D+of\D+47/)).toBeInTheDocument()
  })

  test('Prev is disabled on page 0; Next enabled', () => {
    render(<Setup page={0} />)
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /next/i })).not.toBeDisabled()
  })

  test('Next is disabled on last page', () => {
    render(<Setup page={4} />)  // 47 / 10 → pages 0..4
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
  })

  test('clicking Next calls onPage(page+1)', () => {
    const onPage = vi.fn()
    render(<Setup page={1} onPage={onPage} />)
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(onPage).toHaveBeenCalledWith(2)
  })

  test('changing rows input and blurring calls onPageSize with the number', () => {
    const onPageSize = vi.fn()
    render(<Setup onPageSize={onPageSize} />)
    const input = screen.getByLabelText(/rows/i)
    fireEvent.change(input, { target: { value: '25' } })
    fireEvent.blur(input)
    expect(onPageSize).toHaveBeenCalledWith(25)
  })

  test('pressing Enter commits the rows value', () => {
    const onPageSize = vi.fn()
    render(<Setup onPageSize={onPageSize} />)
    const input = screen.getByLabelText(/rows/i)
    fireEvent.change(input, { target: { value: '5' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onPageSize).toHaveBeenCalledWith(5)
  })

  test('blank input on commit falls back to default 10', () => {
    const onPageSize = vi.fn()
    render(<Setup onPageSize={onPageSize} />)
    const input = screen.getByLabelText(/rows/i)
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)
    expect(onPageSize).toHaveBeenCalledWith(10)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/micheldumontier/code/ontoexplorer/frontend && npx vitest run src/components/TablePager.test.tsx 2>&1 | tail -10`

Expected: 7 FAILED (module not found).

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/TablePager.tsx`:

```tsx
import { useEffect, useState } from 'react'

export interface TablePagerProps {
  total: number
  page: number
  pageSize: number
  onPage: (page: number) => void
  onPageSize: (size: number) => void
}

const DEFAULT_PAGE_SIZE = 10

export function TablePager({ total, page, pageSize, onPage, onPageSize }: TablePagerProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const start = total === 0 ? 0 : page * pageSize + 1
  const end = Math.min((page + 1) * pageSize, total)

  // Mirror pageSize in a local string so the input is editable.
  const [draft, setDraft] = useState(String(pageSize))
  useEffect(() => {
    setDraft(String(pageSize))
  }, [pageSize])

  function commit() {
    const n = Number(draft)
    if (!Number.isFinite(n) || n < 1) {
      onPageSize(DEFAULT_PAGE_SIZE)
      setDraft(String(DEFAULT_PAGE_SIZE))
    } else {
      const v = Math.floor(n)
      onPageSize(v)
      setDraft(String(v))
    }
  }

  const btnStyle = (disabled: boolean): React.CSSProperties => ({
    background: 'none',
    border: '1px solid var(--border)',
    borderRadius: 4,
    color: disabled ? 'var(--text-dim)' : 'var(--text)',
    fontSize: 11,
    padding: '2px 10px',
    cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.4 : 1,
  })

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
      <label style={{ color: 'var(--text-dim)', fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}>
        Rows:
        <input
          type="number"
          min={1}
          max={500}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => { if (e.key === 'Enter') commit() }}
          style={{
            width: 56,
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            color: 'var(--text)',
            fontSize: 11,
            padding: '2px 6px',
            outline: 'none',
          }}
        />
      </label>
      <div style={{ flex: 1 }} />
      <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
        {start}–{end} of {total}
      </span>
      <button onClick={() => onPage(page - 1)} disabled={page === 0} style={btnStyle(page === 0)}>
        ‹ Prev
      </button>
      <button
        onClick={() => onPage(page + 1)}
        disabled={page >= totalPages - 1}
        style={btnStyle(page >= totalPages - 1)}
      >
        Next ›
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/micheldumontier/code/ontoexplorer/frontend && npx vitest run src/components/TablePager.test.tsx 2>&1 | tail -10`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/TablePager.tsx frontend/src/components/TablePager.test.tsx
git commit -m "feat(frontend): TablePager component"
```

---

## Task 9: Frontend — wire `usePagedTable` + `<TablePager>` into all three admin tables

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`

This task replaces the hardcoded `PAGE_SIZE = 25` in `OntologyTable` and adds paging to `JobsTable` and `WorkersPanel`.

- [ ] **Step 1: Update `OntologyTable`**

In `frontend/src/pages/AdminPage.tsx`:

1. At the top of the file, add imports:

```tsx
import { usePagedTable } from '../hooks/usePagedTable'
import { TablePager } from '../components/TablePager'
```

2. Delete the line `const PAGE_SIZE = 25` ([AdminPage.tsx:138](frontend/src/pages/AdminPage.tsx#L138)).

3. Inside `OntologyTable`, replace the local `page` state and the manual paging slice. Find:

```tsx
  const [page, setPage] = useState(0)
```

and the block:

```tsx
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE)
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
```

Replace them with:

```tsx
  const {
    paged,
    page, setPage,
    pageSize, setPageSize,
    total,
  } = usePagedTable(sorted, 'ontologies')
```

Also remove `setPage(0)` from `handleSearch` and the sort toggle — `usePagedTable`'s `setPageSize` already resets page to 0, and the list-shrink effect handles search filtering naturally.

Actually keep the `setPage(0)` calls because filtering doesn't change `total` shape, it changes `sorted` contents. Both work; leaving them in is harmless and clearer. Concretely the function signatures stay:

```tsx
  function toggleSort(col: SortCol) {
    setSort(s => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' })
    setPage(0)
  }

  function handleSearch(q: string) {
    setSearch(q)
    setPage(0)
  }
```

4. Replace the existing custom paging footer block:

```tsx
      {totalPages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length}
          </span>
          <button onClick={() => setPage(p => p - 1)} disabled={page === 0} style={btnStyle(page === 0)}>
            ‹ Prev
          </button>
          <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages - 1} style={btnStyle(page >= totalPages - 1)}>
            Next ›
          </button>
        </div>
      )}
```

with a single line:

```tsx
      <TablePager total={total} page={page} pageSize={pageSize} onPage={setPage} onPageSize={setPageSize} />
```

You can also remove the now-unused `btnStyle` local inside `OntologyTable`.

- [ ] **Step 2: Update `JobsTable`**

`JobsTable` currently has no paging. Modify its signature to accept jobs and slice them internally:

Replace the current `function JobsTable({ jobs }: { jobs: AdminJobEntry[] }) { ... }` body (around [AdminPage.tsx:371](frontend/src/pages/AdminPage.tsx#L371)) with:

```tsx
function JobsTable({ jobs }: { jobs: AdminJobEntry[] }) {
  const {
    paged,
    page, setPage,
    pageSize, setPageSize,
    total,
  } = usePagedTable(jobs, 'jobs')

  return (
    <div>
      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
              {['Type', 'Ontology', 'Status', 'Duration', 'Started'].map(h => (
                <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Type' || h === 'Ontology' ? 'left' : 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.map(job => (
              <tr key={job.id} style={{
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                background: job.status === 'failed' ? 'rgba(248,81,73,0.06)' : undefined,
              }}>
                <td style={{ padding: '6px 10px', color: JOB_TYPE_COLOR[job.type] ?? 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', fontWeight: 600 }}>
                  {job.type}
                </td>
                <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                  {job.ontology_shortname ?? job.ontology_iri?.split(/[/#]/).pop() ?? '—'}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  <StatusDot status={job.status} />
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  {fmtDuration(job.started_at, job.finished_at)}
                  {job.status === 'running' && <span style={{ color: 'var(--text-dim)' }}>…</span>}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                  {fmtAge(job.started_at)}
                </td>
              </tr>
            ))}
            {paged.length === 0 && (
              <tr>
                <td colSpan={5} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)' }}>
                  No jobs yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <TablePager total={total} page={page} pageSize={pageSize} onPage={setPage} onPageSize={setPageSize} />
    </div>
  )
}
```

- [ ] **Step 3: Update `WorkersPanel`**

Inside `WorkersPanel` (around [AdminPage.tsx:449](frontend/src/pages/AdminPage.tsx#L449)), find the `const tasks = data?.tasks ?? []` line. Below it, add:

```tsx
  const {
    paged: pagedTasks,
    page, setPage,
    pageSize, setPageSize,
    total,
  } = usePagedTable(tasks, 'workers')
```

Then in the JSX, replace `{tasks.map(t => ( ... ))}` with `{pagedTasks.map(t => ( ... ))}` and replace `{tasks.length === 0 && ( ... )}` with `{pagedTasks.length === 0 && ( ... )}`.

After the closing `</div>` of the table wrapper (the outer `<div style={{ background: 'var(--bg-secondary)', ... }}>`), but still inside the function's returned fragment, add:

```tsx
      <TablePager total={total} page={page} pageSize={pageSize} onPage={setPage} onPageSize={setPageSize} />
```

Since `WorkersPanel` currently returns a single `<div>` containing the table, change it to return a fragment containing the table div and the pager — or wrap them in a `<div>`:

```tsx
  return (
    <div>
      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        {/* existing table */}
      </div>
      <TablePager total={total} page={page} pageSize={pageSize} onPage={setPage} onPageSize={setPageSize} />
    </div>
  )
```

- [ ] **Step 4: Type-check + Vitest**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10
npx vitest run 2>&1 | tail -5
```

Both expected: clean (no new errors).

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/AdminPage.tsx
git commit -m "feat(admin): configurable paging via TablePager on Ontology/Jobs/Workers tables"
```

---

## Task 10: Frontend — expandable rows + per-version subtable

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`

This task adds the ▸/▾ caret column, the expansion state, the lazy `useQuery` that hits `/admin/ontologies/{id}/versions`, and renders the per-version sub-rows. Per-version action buttons and the new "Diff vs prev" column come in subsequent tasks. For now, the sub-rows show the same pipeline columns as the parent but with read-only badges (no action buttons yet).

- [ ] **Step 1: Add expansion state and the versions query**

In `AdminPage.tsx`, modify the `OntologyTable` component:

1. Add imports at top of file (if not already present):

```tsx
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AdminVersionEntry, AdminVersionsResponse } from '../lib/api'
```

(`useQuery` is already imported; check.)

2. Add expansion state inside `OntologyTable`:

```tsx
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggleExpanded(ontologyId: string) {
    setExpanded(s => {
      const n = new Set(s)
      if (n.has(ontologyId)) n.delete(ontologyId)
      else n.add(ontologyId)
      return n
    })
  }
```

3. In the `<thead>` row, prepend a caret column header:

```tsx
            <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
              <th style={{ width: 28 }} />
              <SortTh col="ontology" label="Ontology" align="left" />
              {/* ... rest unchanged */}
            </tr>
```

4. In each parent `<tr>` body, prepend a caret cell that toggles expansion:

```tsx
              <tr key={row.version_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '6px 4px 6px 10px', textAlign: 'center', cursor: 'pointer', color: 'var(--text-dim)' }}
                    onClick={() => toggleExpanded(row.id)}>
                  {expanded.has(row.id) ? '▾' : '▸'}
                </td>
                <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                  {/* ontology cell unchanged */}
                </td>
                {/* ... rest unchanged */}
              </tr>
```

5. After each parent `<tr>`, render an expansion `<tr>` when the row is expanded:

```tsx
              {expanded.has(row.id) && (
                <VersionsSubRows ontologyId={row.id} colSpan={8} latestVersionId={row.version_id} />
              )}
```

(Use `colSpan={8}` because columns now are: caret, Ontology, Triples, Ingestion, Indexed, Embeddings, Reasoning, Updated — 8 in total. Once Task 11 adds "Diff vs prev", bump to 9 in that task.)

6. Define `VersionsSubRows` near the bottom of the file (above `AdminPage`):

```tsx
function VersionsSubRows({
  ontologyId, colSpan, latestVersionId,
}: {
  ontologyId: string
  colSpan: number
  latestVersionId: string
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-versions', ontologyId],
    queryFn: () => api.admin.versions(ontologyId),
    refetchInterval: 10_000,
  })

  if (isLoading) {
    return (
      <tr>
        <td colSpan={colSpan} style={{ padding: '8px 16px', color: 'var(--text-dim)', fontSize: 11 }}>
          Loading versions…
        </td>
      </tr>
    )
  }
  if (isError || !data) {
    return (
      <tr>
        <td colSpan={colSpan} style={{ padding: '8px 16px', color: '#f85149', fontSize: 11 }}>
          Failed to load versions
        </td>
      </tr>
    )
  }

  // Skip the latest version (already shown by the parent row).
  const others = data.versions.filter(v => v.version_id !== latestVersionId)
  if (others.length === 0) {
    return (
      <tr>
        <td colSpan={colSpan} style={{ padding: '8px 16px', color: 'var(--text-dim)', fontSize: 11 }}>
          No older versions
        </td>
      </tr>
    )
  }

  return (
    <>
      {others.map(v => (
        <tr key={v.version_id} style={{ background: 'rgba(255,255,255,0.02)' }}>
          <td />
          <td style={{ padding: '6px 10px', color: 'var(--text-muted)', fontSize: 11 }}>
            ↳ <span style={{ fontFamily: 'monospace' }}>{v.version_id.slice(0, 8)}…</span>
            {v.ingestion_status === 'deprecated' && (
              <span style={{ marginLeft: 6, color: '#f85149' }}>● deprecated</span>
            )}
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
            {fmtTriples(v.triple_count)}
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <StatusDot status={v.ingestion_status} />
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <StatusDot status={v.indexed ? 'done' : 'not_started'} label={v.indexed ? 'yes' : 'no'} />
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center', color: v.embed_count > 0 ? 'var(--accent-green, #3fb950)' : 'var(--text-dim)' }}>
            {v.embed_count > 0 ? fmtTriples(v.embed_count) : '—'}
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <StatusDot status={v.reasoning_status} label={v.reasoning_status.replace('_', ' ')} />
          </td>
          <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
            {fmtAge(v.version_created_at)}
          </td>
        </tr>
      ))}
    </>
  )
}
```

- [ ] **Step 2: Type-check + run all tests**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10
npx vitest run 2>&1 | tail -5
```

Expected: clean.

- [ ] **Step 3: Sanity-render in the browser (manual)**

Start the dev server: `cd frontend && npm run dev`. Log in as admin, navigate to `/admin`, click the ▸ on an ontology with multiple versions, and confirm sub-rows render with the per-version status badges. Older versions should show "↳ <short-id>" and any deprecated ones get the red dot.

- [ ] **Step 4: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/AdminPage.tsx
git commit -m "feat(admin): expandable rows showing all versions per ontology"
```

---

## Task 11: Frontend — "Diff vs prev" column + per-pair / bulk diff actions

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`

Adds the new "Diff vs prev" column to both the parent table and `VersionsSubRows`, a per-row queue button, and the per-ontology bulk button in the parent's "Ontology" cell.

- [ ] **Step 1: Add diff column to the header**

In `OntologyTable`'s `<thead>`, append a `<th>` after "Updated":

```tsx
              <SortTh col="updated" label="Updated" />
              <th style={{ padding: '7px 10px', textAlign: 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                Diff vs prev
              </th>
```

Bump `colSpan` from 8 → 9 in the no-matching-ontologies row AND in the `<VersionsSubRows>` invocation.

- [ ] **Step 2: Add bulk "Recompute all diffs" button to the parent's Ontology cell**

In `AdminPage` (the page component), add state and handlers near the other action states:

```tsx
  const [recomputeStates, setRecomputeStates] = useState<Record<string, UpdateState>>({})
  const [pairDiffStates, setPairDiffStates] = useState<Record<string, UpdateState>>({})  // keyed by "from->to"

  async function handleRecomputeAll(ontologyId: string) {
    setRecomputeStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try {
      await api.admin.recomputeAllDiffs(ontologyId)
    } catch {
      setRecomputeStates(s => ({ ...s, [ontologyId]: 'error' }))
    }
  }

  async function handlePairDiff(fromVid: string, toVid: string) {
    const key = `${fromVid}->${toVid}`
    setPairDiffStates(s => ({ ...s, [key]: 'queued' }))
    try {
      await api.admin.queueDiff(fromVid, toVid)
    } catch {
      setPairDiffStates(s => ({ ...s, [key]: 'error' }))
    }
  }
```

Thread `recomputeStates`, `onRecomputeAll`, `pairDiffStates`, `onPairDiff` through `<OntologyTable ... />` props, alongside the existing `updateStates`, `onUpdate`, etc. Add to `OntologyTable`'s prop type:

```tsx
  recomputeStates: Record<string, UpdateState>
  onRecomputeAll: (ontologyId: string) => void
  pairDiffStates: Record<string, UpdateState>
  onPairDiff: (fromVid: string, toVid: string) => void
```

- [ ] **Step 3: Render the bulk button in the Ontology cell**

Inside the parent row's "Ontology" `<td>`, after the existing label:

```tsx
                  <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                    <div>{ontologyDisplayName(row)}</div>
                    {row.label && row.label !== ontologyDisplayName(row) && (
                      <div style={{ color: 'var(--text-dim)', fontSize: 10 }}>{row.label}</div>
                    )}
                    <ActionButton
                      label="⚖ recompute all diffs"
                      title="Queue compute_diff for every consecutive version pair of this ontology"
                      state={recomputeStates[row.id] ?? 'idle'}
                      onClick={() => onRecomputeAll(row.id)}
                    />
                  </td>
```

- [ ] **Step 4: Render the per-row "Diff vs prev" cell**

The parent row shows the diff for `latest_prev → latest`. Because `AdminOntologyEntry` doesn't carry the previous version id today, fall back to **rendering `—` on the parent row** (so the parent row's diff column is informational only — the bulk button covers it). The per-version data is shown in the expanded sub-rows.

At the end of the parent `<tr>`, after the "Updated" cell, add:

```tsx
                  <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                    —
                  </td>
```

- [ ] **Step 5: Render "Diff vs prev" in sub-rows**

Update `VersionsSubRows` props to receive `pairDiffStates` + `onPairDiff`:

```tsx
function VersionsSubRows({
  ontologyId, colSpan, latestVersionId,
  pairDiffStates, onPairDiff,
}: {
  ontologyId: string
  colSpan: number
  latestVersionId: string
  pairDiffStates: Record<string, UpdateState>
  onPairDiff: (fromVid: string, toVid: string) => void
}) {
  // ... existing useQuery body unchanged ...
```

Inside the per-version `<tr>`, after the "Updated" cell, add a Diff cell:

```tsx
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <DiffStatusBadge status={v.diff_vs_prev.status} />
              {v.diff_vs_prev.previous_version_id && (
                <ActionButton
                  label={diffActionLabelFor(v.diff_vs_prev.status)}
                  title={`Queue compute_diff against ${v.diff_vs_prev.previous_version_id.slice(0, 8)}…`}
                  state={pairDiffStates[`${v.diff_vs_prev.previous_version_id}->${v.version_id}`] ?? 'idle'}
                  onClick={() => onPairDiff(v.diff_vs_prev.previous_version_id!, v.version_id)}
                />
              )}
            </div>
          </td>
```

Define helpers near the top of the file (e.g., next to `StatusDot`):

```tsx
function DiffStatusBadge({ status }: { status: AdminVersionEntry['diff_vs_prev']['status'] }) {
  const text = status === 'missing' ? 'none' : status
  if (status === 'ready')   return <span style={{ color: 'var(--accent-green, #3fb950)', fontSize: 11 }}>● {text}</span>
  if (status === 'running' || status === 'pending') return <span style={{ color: '#58a6ff', fontSize: 11 }}>⟳ {text}</span>
  if (status === 'failed')  return <span style={{ color: '#f85149', fontSize: 11 }}>✕ {text}</span>
  if (status === 'stale')   return <span style={{ color: '#d29922', fontSize: 11 }}>↻ {text}</span>
  return <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>— {text}</span>
}

function diffActionLabelFor(status: AdminVersionEntry['diff_vs_prev']['status']): string {
  if (status === 'failed') return '✕ retry'
  if (status === 'stale')  return '↻ refresh'
  return '⚖ diff'
}
```

Thread `pairDiffStates` and `onPairDiff` from `OntologyTable` (which received them via props from `AdminPage`) down to the `<VersionsSubRows>` invocation.

- [ ] **Step 6: Type-check + Vitest**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10
npx vitest run 2>&1 | tail -5
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/AdminPage.tsx
git commit -m "feat(admin): Diff vs prev column + per-pair/bulk diff queue actions"
```

---

## Task 12: Frontend — per-version action buttons in sub-rows

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`

Adds re-index, re-embed, re-reason, and re-ingest buttons to each child row, using the per-version endpoints from Tasks 3 and 4.

- [ ] **Step 1: Wire new state and handlers in `AdminPage`**

Near the other action-state maps:

```tsx
  const [versionIndexStates, setVersionIndexStates] = useState<Record<string, UpdateState>>({})
  const [versionEmbedStates, setVersionEmbedStates] = useState<Record<string, UpdateState>>({})
  const [versionReasonStates, setVersionReasonStates] = useState<Record<string, UpdateState>>({})
  const [versionIngestStates, setVersionIngestStates] = useState<Record<string, UpdateState>>({})

  async function handleVersionIndex(versionId: string) {
    setVersionIndexStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueIndexForVersion(versionId) }
    catch { setVersionIndexStates(s => ({ ...s, [versionId]: 'error' })) }
  }
  async function handleVersionEmbed(versionId: string) {
    setVersionEmbedStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueEmbedForVersion(versionId) }
    catch { setVersionEmbedStates(s => ({ ...s, [versionId]: 'error' })) }
  }
  async function handleVersionReason(versionId: string) {
    setVersionReasonStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueReasonForVersion(versionId) }
    catch { setVersionReasonStates(s => ({ ...s, [versionId]: 'error' })) }
  }
  async function handleVersionIngest(versionId: string) {
    setVersionIngestStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueIngestForVersion(versionId) }
    catch { setVersionIngestStates(s => ({ ...s, [versionId]: 'error' })) }
  }
```

Pass all four state maps and handlers into `<OntologyTable>` (add to its props type, just like in Task 11).

- [ ] **Step 2: Thread to `VersionsSubRows`**

Add four more props to `VersionsSubRows`:

```tsx
  versionIndexStates: Record<string, UpdateState>
  onVersionIndex: (versionId: string) => void
  versionEmbedStates: Record<string, UpdateState>
  onVersionEmbed: (versionId: string) => void
  versionReasonStates: Record<string, UpdateState>
  onVersionReason: (versionId: string) => void
  versionIngestStates: Record<string, UpdateState>
  onVersionIngest: (versionId: string) => void
```

- [ ] **Step 3: Render the buttons inside each sub-row's status cells**

Inside `VersionsSubRows`, replace the read-only cells (Ingestion, Indexed, Embeddings, Reasoning) with cells that include `ActionButton` children, mirroring how the parent row does it. For a deprecated version, still allow the action (admin tool, no policy restriction) but the badge stays red.

Example for the Ingestion cell:

```tsx
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <StatusDot status={v.ingestion_status} />
              {(v.source_url || true) && (
                <ActionButton
                  label={v.source_url ? '↑ url' : '↑ iri'}
                  title={v.source_url
                    ? `Re-fetch ${v.source_url} — creates a new version if bytes changed`
                    : `Re-fetch the ontology IRI — creates a new version if bytes changed`}
                  state={versionIngestStates[v.version_id] ?? 'idle'}
                  onClick={() => onVersionIngest(v.version_id)}
                />
              )}
            </div>
          </td>
```

For Indexed:

```tsx
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <StatusDot status={v.indexed ? 'done' : 'not_started'} label={v.indexed ? 'yes' : 'no'} />
              <ActionButton
                label="↺ index"
                title="Re-index search for this specific version"
                state={versionIndexStates[v.version_id] ?? 'idle'}
                onClick={() => onVersionIndex(v.version_id)}
              />
            </div>
          </td>
```

For Embeddings:

```tsx
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <span style={{ color: v.embed_count > 0 ? 'var(--accent-green, #3fb950)' : 'var(--text-dim)', fontSize: 11 }}>
                {v.embed_count > 0 ? fmtTriples(v.embed_count) : '—'}
              </span>
              <ActionButton
                label="⬡ embed"
                title="Generate embeddings for this specific version"
                state={versionEmbedStates[v.version_id] ?? 'idle'}
                onClick={() => onVersionEmbed(v.version_id)}
              />
            </div>
          </td>
```

For Reasoning:

```tsx
          <td style={{ padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <StatusDot status={v.reasoning_status} label={v.reasoning_status.replace('_', ' ')} />
              <ActionButton
                label="⚙ reason"
                title="Run OWL-EL classification for this specific version"
                state={versionReasonStates[v.version_id] ?? 'idle'}
                onClick={() => onVersionReason(v.version_id)}
              />
            </div>
          </td>
```

- [ ] **Step 4: Type-check + Vitest**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10
npx vitest run 2>&1 | tail -5
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/AdminPage.tsx
git commit -m "feat(admin): per-version action buttons (index/embed/reason/ingest) in sub-rows"
```

---

## Task 13: Manual end-to-end sanity check

**Files:** none — operational.

- [ ] **Step 1: Run the full test suite**

```bash
cd /home/micheldumontier/code/ontoexplorer
uv run pytest tests/integration/test_admin.py 2>&1 | tail -5
cd frontend && npx vitest run 2>&1 | tail -5
```

Both expected: all green.

- [ ] **Step 2: Rebuild containers**

```bash
cd /home/micheldumontier/code/ontoexplorer
docker compose build api
docker compose up -d api
```

(Worker image is unchanged — no new Celery tasks.)

- [ ] **Step 3: Browser walkthrough**

Log in as admin and open `/admin`. Verify:

1. The ontology table loads with one row per ontology and a ▸ caret.
2. The "Rows" input defaults to 10. Change to 5; refresh; confirm it persists. Set to garbage; confirm fallback to 10.
3. Click ▸ on an ontology with multiple versions. The sub-rows load and show all versions newest-first, with status badges + the "Diff vs prev" column.
4. Click "↺ index" on an older version. Confirm the badge flips to "↑ queued" and the workers panel shows the task.
5. Click "⚖ diff" in a "Diff vs prev" cell. Confirm the diff queues; refresh and check the status flips to "pending" → "ready".
6. Click "⚖ recompute all diffs" on the parent row. Confirm N tasks queue (where N = versions − 1).
7. Recent Jobs and Workers panels also respect rows-per-page settings, independent of the Ontology table.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| `_diff_status_for_pair` helper | Task 1 |
| `GET /admin/ontologies/{id}/versions` | Task 2 |
| Per-version action endpoints (index/embed/reason) | Task 3 |
| Per-version ingest endpoint | Task 4 |
| `POST /admin/diffs/queue` | Task 5 |
| `POST /admin/ontologies/{id}/diffs/recompute-all` | Task 5 |
| Frontend types + client methods | Task 6 |
| `usePagedTable` hook | Task 7 |
| `<TablePager>` component | Task 8 |
| Wire paging into all 3 tables | Task 9 |
| Expandable rows + lazy versions query | Task 10 |
| "Diff vs prev" column + per-pair / bulk diff buttons | Task 11 |
| Per-version action buttons in sub-rows | Task 12 |
| Operational rollout | Task 13 |

**Placeholder scan:** every step contains concrete code or commands. No TBD, no "similar to Task N", no "add appropriate error handling."

**Type consistency:**
- Backend `_diff_status_for_pair` returns `{status, diff_id, computed_at}`; the versions endpoint adds `previous_version_id` to it before returning. The frontend `AdminVersionEntry.diff_vs_prev` matches this shape.
- TS `AdminVersionEntry.diff_vs_prev.status` ∈ `'ready' | 'running' | 'pending' | 'failed' | 'missing' | 'stale'` — matches the Python helper's outputs.
- The `pairDiffStates` map is keyed `"${from}->${to}"` consistently in both `handlePairDiff` and the `<ActionButton state>` lookup in `VersionsSubRows`.
- `usePagedTable` returns `{paged, page, setPage, pageSize, setPageSize, totalPages, total}`; `<TablePager>` consumes `total, page, pageSize, onPage, onPageSize`. The three table sites destructure consistently.
- LocalStorage keys: `admin.rowsPerPage.ontologies`, `admin.rowsPerPage.jobs`, `admin.rowsPerPage.workers` — referenced only by their `scopeKey` argument.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-19-admin-multi-version-and-paging.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
