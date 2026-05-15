# Ontology Auto-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep registered ontologies up-to-date automatically via (1) hourly Celery beat polling that re-fetches URL-sourced ontologies when their content changes, and (2) an inbound GitHub webhook endpoint that triggers immediate re-ingestion when a push event changes a tracked file.

**Architecture:** Both paths reuse the existing `ingest_ontology` Celery task — deduplication by SHA-256 in the ingestion pipeline ensures no-ops when content hasn't changed. A new `source_url` column on `OntologyVersion` records where each version came from; a new `auto_sync` flag on `Ontology` gates polling. The GitHub endpoint is unauthenticated but HMAC-verified; it matches push event file paths to stored `source_url`s and queues ingestion.

**Tech Stack:** SQLAlchemy async, Alembic, Celery + Celery Beat, httpx, FastAPI, pytest + anyio

---

## File Map

| File | Change |
|---|---|
| `ontoexplorer/models/db.py` | Add `source_url` to `OntologyVersion`, `auto_sync` to `Ontology` |
| `alembic/versions/d7e8f9a0b1c2_add_source_url_auto_sync.py` | Migration |
| `ontoexplorer/modules/ingestion/pipeline.py` | Set `source_url` when creating `OntologyVersion` |
| `ontoexplorer/modules/jobs/tasks.py` | Add `poll_for_updates` task; add `beat_schedule` to conf |
| `ontoexplorer/api/ontologies.py` | Add `PATCH /api/v1/ontologies/{id}` for `auto_sync` toggle |
| `ontoexplorer/api/inbound.py` | New: `POST /api/v1/inbound/github` — receive GitHub push events |
| `ontoexplorer/main.py` | Register `inbound_router` |
| `ontoexplorer/config.py` | Add `github_webhook_secret` |
| `.env.example` | Document new env var |
| `docker-compose.yml` | Add `beat` service |
| `tests/integration/test_auto_sync.py` | New: all tests for this feature |

---

## Task 1: DB migration — add source_url and auto_sync

**Files:**
- Modify: `ontoexplorer/models/db.py`
- Create: `alembic/versions/d7e8f9a0b1c2_add_source_url_auto_sync.py`
- Test: `tests/integration/test_auto_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_auto_sync.py
"""Tests for ontology auto-sync: polling and GitHub inbound webhook."""
import pytest
from ontoexplorer.models.db import Ontology, OntologyVersion


@pytest.mark.anyio
async def test_ontology_has_auto_sync_field(db_session):
    """Ontology model has auto_sync defaulting to False."""
    ont = Ontology(iri="http://example.org/sync-test.owl")
    db_session.add(ont)
    await db_session.commit()
    await db_session.refresh(ont)
    assert ont.auto_sync is False


@pytest.mark.anyio
async def test_version_has_source_url_field(db_session):
    """OntologyVersion model has source_url defaulting to None."""
    ont = Ontology(iri="http://example.org/sync-test2.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key.ttl",
        sha256="abc123unique",
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/onto.ttl",
    )
    db_session.add(ver)
    await db_session.commit()
    await db_session.refresh(ver)
    assert ver.source_url == "https://raw.githubusercontent.com/owner/repo/main/onto.ttl"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/micheldumontier/code/ontoexplorer
uv run pytest tests/integration/test_auto_sync.py -v
```

Expected: FAIL — `Ontology has no attribute 'auto_sync'` or similar.

- [ ] **Step 3: Add columns to models**

In `ontoexplorer/models/db.py`, update `Ontology`:

```python
class Ontology(Base):
    __tablename__ = "ontologies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    iri: Mapped[str] = mapped_column(String, unique=True)
    shortname: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped[User | None] = relationship(back_populates="ontologies")
    versions: Mapped[list["OntologyVersion"]] = relationship(back_populates="ontology", cascade="all, delete-orphan")
```

In `ontoexplorer/models/db.py`, update `OntologyVersion`:

```python
class OntologyVersion(Base):
    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id", ondelete="CASCADE"))
    version_iri: Mapped[str | None] = mapped_column(String, nullable=True)
    minio_key: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String, unique=True)
    format: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ingested")
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    triple_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ontology: Mapped[Ontology] = relationship(back_populates="versions")
    imports: Mapped[list["OntologyImport"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="version", passive_deletes=True)
```

- [ ] **Step 4: Write the Alembic migration**

Create `alembic/versions/d7e8f9a0b1c2_add_source_url_auto_sync.py`:

```python
"""add source_url and auto_sync

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa

revision = "d7e8f9a0b1c2"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("versions", sa.Column("source_url", sa.String(), nullable=True))
    op.add_column(
        "ontologies",
        sa.Column("auto_sync", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("versions", "source_url")
    op.drop_column("ontologies", "auto_sync")
```

- [ ] **Step 5: Run the test — should pass now**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_ontology_has_auto_sync_field tests/integration/test_auto_sync.py::test_version_has_source_url_field -v
```

Expected: PASS (SQLite in-memory creates tables fresh from models, so no migration needed for tests).

- [ ] **Step 6: Apply the migration to the running Docker Postgres**

```bash
docker compose exec api uv run alembic upgrade head
```

Expected: `Running upgrade c1d2e3f4a5b6 -> d7e8f9a0b1c2, add source_url and auto_sync`

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/models/db.py alembic/versions/d7e8f9a0b1c2_add_source_url_auto_sync.py tests/integration/test_auto_sync.py
git commit -m "feat(sync): add source_url and auto_sync columns with migration"
```

---

## Task 2: Store source_url at ingestion time

**Files:**
- Modify: `ontoexplorer/modules/ingestion/pipeline.py`
- Test: `tests/integration/test_auto_sync.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_auto_sync.py`:

```python
@pytest.mark.anyio
async def test_ingestion_stores_source_url(db_session):
    """run_ingestion sets source_url on the created OntologyVersion."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, run_ingestion

    _TURTLE = b"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/SrcUrlOntology> a owl:Ontology .
"""

    with (
        patch("ontoexplorer.modules.storage.minio_client.store_ontology",
              MagicMock(return_value="ont/ver/sha.ttl")),
        patch("ontoexplorer.clients.oxigraph.load_graph", MagicMock(return_value=1)),
        patch("ontoexplorer.modules.ingestion.pipeline._write_fair_metadata", new=AsyncMock()),
        patch("ontoexplorer.modules.jobs.tasks.reason_ontology",
              MagicMock(delay=MagicMock()), create=True),
        patch("ontoexplorer.modules.jobs.tasks.index_ontology",
              MagicMock(delay=MagicMock()), create=True),
    ):
        result = await run_ingestion(
            db_session,
            IngestionRequest(url="https://raw.githubusercontent.com/owner/repo/main/onto.ttl",
                             raw_bytes=_TURTLE),
        )

    from sqlalchemy import select
    ver_row = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.id == result.version_id)
    )
    ver = ver_row.scalar_one()
    assert ver.source_url == "https://raw.githubusercontent.com/owner/repo/main/onto.ttl"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_ingestion_stores_source_url -v
```

Expected: FAIL — `AssertionError: assert None == 'https://...'`

- [ ] **Step 3: Store source_url in the pipeline**

In `ontoexplorer/modules/ingestion/pipeline.py`, find the `OntologyVersion(...)` constructor call (around the `# ── Persist version record` comment) and add `source_url`:

```python
    version = OntologyVersion(
        id=version_id,
        ontology_id=ontology_id,
        version_iri=version_iri,
        minio_key=minio_key,
        sha256=sha256,
        format=fmt.value,
        status="ingested",
        triple_count=triple_count,
        source_url=source.final_url or request.url or request.iri,
    )
```

- [ ] **Step 4: Run the test — should pass now**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_ingestion_stores_source_url -v
```

Expected: PASS

- [ ] **Step 5: Run the full test suite to catch regressions**

```bash
uv run pytest tests/ -v --ignore=tests/integration/test_reasoning_api.py -x
```

Expected: all pass (ignore `test_reasoning_api.py` — requires live ELK service).

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/modules/ingestion/pipeline.py tests/integration/test_auto_sync.py
git commit -m "feat(sync): persist source_url on OntologyVersion at ingestion time"
```

---

## Task 3: PATCH /api/v1/ontologies/{id} to toggle auto_sync

**Files:**
- Modify: `ontoexplorer/api/ontologies.py`
- Test: `tests/integration/test_auto_sync.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_auto_sync.py`:

```python
@pytest.mark.anyio
async def test_patch_auto_sync_on(client, user_and_key, db_session):
    """PATCH /ontologies/{id} sets auto_sync=True for the owner."""
    user, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    ont = Ontology(iri="http://example.org/patch-test.owl", owner_id=user.id)
    db_session.add(ont)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/ontologies/{ont.id}",
        json={"auto_sync": True},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["auto_sync"] is True

    await db_session.refresh(ont)
    assert ont.auto_sync is True


@pytest.mark.anyio
async def test_patch_auto_sync_wrong_user(client, db_session):
    """PATCH by a different user returns 403."""
    import hashlib, uuid as _uuid
    from ontoexplorer.models.db import ApiKey, User

    other_user = User(id=str(_uuid.uuid4()), email="other@example.com")
    raw_key2 = f"oe_test_{_uuid.uuid4().hex}"
    key_hash2 = hashlib.sha256(raw_key2.encode()).hexdigest()
    api_key2 = ApiKey(id=str(_uuid.uuid4()), user_id=other_user.id,
                      key_hash=key_hash2, name="k2", scopes=["read", "write"])
    ont = Ontology(iri="http://example.org/other-owner.owl", owner_id="some-other-id")
    db_session.add_all([other_user, api_key2, ont])
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/ontologies/{ont.id}",
        json={"auto_sync": True},
        headers={"Authorization": f"Bearer {raw_key2}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_patch_auto_sync_on tests/integration/test_auto_sync.py::test_patch_auto_sync_wrong_user -v
```

Expected: FAIL — 404 or 405 (endpoint doesn't exist yet).

- [ ] **Step 3: Add PATCH endpoint to ontologies router**

In `ontoexplorer/api/ontologies.py`, add after the existing imports and before the first `@router.get`:

```python
class OntologyPatch(BaseModel):
    auto_sync: bool | None = None
```

Then add the endpoint (place it near other single-ontology endpoints):

```python
@router.patch("/{ontology_id}", summary="Update ontology settings")
async def patch_ontology(
    ontology_id: str,
    body: OntologyPatch,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ontology).where(Ontology.id == ontology_id))
    ont = result.scalar_one_or_none()
    if not ont:
        raise HTTPException(status_code=404, detail="Ontology not found")
    if ont.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the owner")
    if body.auto_sync is not None:
        ont.auto_sync = body.auto_sync
    await db.commit()
    await db.refresh(ont)
    return {"id": ont.id, "iri": ont.iri, "auto_sync": ont.auto_sync}
```

- [ ] **Step 4: Run the tests — should pass now**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_patch_auto_sync_on tests/integration/test_auto_sync.py::test_patch_auto_sync_wrong_user -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/ontologies.py tests/integration/test_auto_sync.py
git commit -m "feat(sync): PATCH /ontologies/{id} to toggle auto_sync"
```

---

## Task 4: Polling Celery task + beat schedule

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`
- Test: `tests/integration/test_auto_sync.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_auto_sync.py`:

```python
@pytest.mark.anyio
async def test_poll_queues_ingest_when_content_changes(db_session):
    """poll_for_updates queues ingest when fetched SHA-256 differs from stored."""
    from unittest.mock import MagicMock, patch
    from ontoexplorer.modules.jobs.tasks import _run_poll

    _NEW_CONTENT = b"new-content-bytes"
    _OLD_SHA256 = "aaaa1111"

    ont = Ontology(iri="http://example.org/poll-test.owl", auto_sync=True)
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key.ttl",
        sha256=_OLD_SHA256,
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/onto.ttl",
    )
    db_session.add(ver)
    await db_session.commit()

    mock_ingest = MagicMock()
    mock_ingest.delay = MagicMock()

    mock_resp = MagicMock()
    mock_resp.content = _NEW_CONTENT
    mock_resp.raise_for_status = MagicMock()

    with (
        patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", mock_ingest),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        await _run_poll(db_session)

    mock_ingest.delay.assert_called_once_with(
        url="https://raw.githubusercontent.com/owner/repo/main/onto.ttl",
        owner_id=None,
    )


@pytest.mark.anyio
async def test_poll_skips_when_content_unchanged(db_session):
    """poll_for_updates does NOT queue ingest when SHA-256 matches."""
    from unittest.mock import MagicMock, patch
    from ontoexplorer.modules.jobs.tasks import _run_poll
    import hashlib

    _CONTENT = b"unchanged-content"
    _SHA256 = hashlib.sha256(_CONTENT).hexdigest()

    ont = Ontology(iri="http://example.org/poll-noop.owl", auto_sync=True)
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key2.ttl",
        sha256=_SHA256,
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/onto2.ttl",
    )
    db_session.add(ver)
    await db_session.commit()

    mock_ingest = MagicMock()
    mock_ingest.delay = MagicMock()

    mock_resp = MagicMock()
    mock_resp.content = _CONTENT
    mock_resp.raise_for_status = MagicMock()

    with (
        patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", mock_ingest),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        await _run_poll(db_session)

    mock_ingest.delay.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_poll_queues_ingest_when_content_changes tests/integration/test_auto_sync.py::test_poll_skips_when_content_unchanged -v
```

Expected: FAIL — `ImportError: cannot import name '_run_poll'`

- [ ] **Step 3: Add the polling task to tasks.py**

At the end of `ontoexplorer/modules/jobs/tasks.py`, add:

```python
async def _run_poll(db) -> None:
    """Async body of poll_for_updates: check each auto_sync ontology for changes."""
    import hashlib
    import httpx as _httpx

    from sqlalchemy import select
    from ontoexplorer.models.db import Ontology, OntologyVersion

    result = await db.execute(
        select(Ontology).where(Ontology.auto_sync.is_(True))
    )
    ontologies = result.scalars().all()

    for ont in ontologies:
        ver_result = await db.execute(
            select(OntologyVersion)
            .where(OntologyVersion.ontology_id == ont.id)
            .where(OntologyVersion.status != "deprecated")
            .where(OntologyVersion.source_url.is_not(None))
            .order_by(OntologyVersion.created_at.desc())
            .limit(1)
        )
        version = ver_result.scalar_one_or_none()
        if not version:
            continue

        try:
            with _httpx.Client(timeout=_httpx.Timeout(60.0), follow_redirects=True) as client:
                resp = client.get(version.source_url)
                resp.raise_for_status()
                new_sha256 = hashlib.sha256(resp.content).hexdigest()
        except Exception as exc:
            log.warning("poll_fetch_failed", ontology_id=ont.id,
                        source_url=version.source_url, error=str(exc))
            continue

        if new_sha256 == version.sha256:
            log.info("poll_no_change", ontology_id=ont.id, source_url=version.source_url)
            continue

        log.info("poll_change_detected", ontology_id=ont.id,
                 source_url=version.source_url, old_sha256=version.sha256, new_sha256=new_sha256)
        ingest_ontology.delay(url=version.source_url, owner_id=ont.owner_id)


@celery_app.task(name="ontoexplorer.poll_for_updates")
def poll_for_updates() -> None:
    """Periodic task: re-fetch all auto_sync ontologies and queue re-ingestion if changed."""
    from ontoexplorer.database import make_celery_db_session

    async def _run():
        async with make_celery_db_session()() as db:
            await _run_poll(db)

    asyncio.run(_run())
```

Also add the beat schedule to `celery_app.conf.update(...)`. Append these keys to the existing dict passed to `celery_app.conf.update`:

```python
    beat_schedule={
        "poll-for-updates-hourly": {
            "task": "ontoexplorer.poll_for_updates",
            "schedule": 3600.0,  # seconds
        },
    },
```

- [ ] **Step 4: Run the tests — should pass now**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_poll_queues_ingest_when_content_changes tests/integration/test_auto_sync.py::test_poll_skips_when_content_unchanged -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py tests/integration/test_auto_sync.py
git commit -m "feat(sync): hourly poll_for_updates Celery beat task"
```

---

## Task 5: GitHub inbound webhook endpoint

**Files:**
- Modify: `ontoexplorer/config.py`
- Create: `ontoexplorer/api/inbound.py`
- Modify: `ontoexplorer/main.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Test: `tests/integration/test_auto_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_auto_sync.py`:

```python
import hashlib
import hmac
import json


def _gh_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.anyio
async def test_github_inbound_queues_ingest(client, db_session):
    """Valid GitHub push event queues ingest for matching source_url."""
    from unittest.mock import MagicMock, patch

    ont = Ontology(iri="http://example.org/gh-sync.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/gh.ttl",
        sha256="deadbeef",
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/ontology.owl",
    )
    db_session.add(ver)
    await db_session.commit()

    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "owner/repo"},
        "commits": [{"added": [], "modified": ["ontology.owl"], "removed": []}],
    }
    body = json.dumps(payload).encode()
    secret = "test-gh-secret"
    sig = _gh_sig(secret, body)

    mock_ingest = MagicMock()
    mock_ingest.delay = MagicMock()

    with (
        patch("ontoexplorer.api.inbound.get_settings",
              return_value=MagicMock(github_webhook_secret=secret)),
        patch("ontoexplorer.api.inbound.ingest_ontology", mock_ingest),
    ):
        resp = await client.post(
            "/api/v1/inbound/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": sig,
            },
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["queued"] == 1
    mock_ingest.delay.assert_called_once_with(
        url="https://raw.githubusercontent.com/owner/repo/main/ontology.owl"
    )


@pytest.mark.anyio
async def test_github_inbound_rejects_bad_signature(client):
    """Invalid HMAC signature returns 401."""
    from unittest.mock import patch

    body = b'{"ref": "refs/heads/main"}'
    with patch("ontoexplorer.api.inbound.get_settings",
               return_value=MagicMock(github_webhook_secret="real-secret")):
        resp = await client.post(
            "/api/v1/inbound/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=badhex",
            },
        )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_github_inbound_ignores_non_push_events(client):
    """Non-push events return 200 with queued=0 without error."""
    from unittest.mock import patch

    body = b'{}'
    secret = "test-secret"
    sig = _gh_sig(secret, body)

    with patch("ontoexplorer.api.inbound.get_settings",
               return_value=MagicMock(github_webhook_secret=secret)):
        resp = await client.post(
            "/api/v1/inbound/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": sig,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["queued"] == 0


@pytest.mark.anyio
async def test_github_inbound_no_secret_configured(client):
    """Returns 501 when GITHUB_WEBHOOK_SECRET is not configured."""
    from unittest.mock import patch

    body = b'{}'
    with patch("ontoexplorer.api.inbound.get_settings",
               return_value=MagicMock(github_webhook_secret="")):
        resp = await client.post(
            "/api/v1/inbound/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=anything",
            },
        )
    assert resp.status_code == 501
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_github_inbound_queues_ingest tests/integration/test_auto_sync.py::test_github_inbound_rejects_bad_signature tests/integration/test_auto_sync.py::test_github_inbound_ignores_non_push_events tests/integration/test_auto_sync.py::test_github_inbound_no_secret_configured -v
```

Expected: FAIL — 404 (endpoint doesn't exist yet).

- [ ] **Step 3: Add github_webhook_secret to config**

In `ontoexplorer/config.py`, add after the GitHub OAuth fields:

```python
    # Inbound GitHub webhook — set to the secret you configure in the GitHub repo's webhook settings
    github_webhook_secret: str = ""
```

- [ ] **Step 4: Create the inbound router**

Create `ontoexplorer/api/inbound.py`:

```python
"""Inbound webhook receivers — GitHub push events."""

import hashlib
import hmac

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import OntologyVersion
from ontoexplorer.modules.jobs.tasks import ingest_ontology
from ontoexplorer.logging_config import get_logger
from fastapi import Depends

router = APIRouter(prefix="/api/v1/inbound", tags=["inbound"])
log = get_logger(__name__)


def _verify_github_signature(secret: str, body: bytes, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("/github", summary="Receive GitHub push webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=501, detail="GITHUB_WEBHOOK_SECRET not configured")

    body = await request.body()
    if not _verify_github_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event != "push":
        return {"queued": 0, "detail": f"Ignoring event: {x_github_event}"}

    payload = await request.json()
    ref = payload.get("ref", "")
    repo_full_name = payload.get("repository", {}).get("full_name", "")
    if not ref or not repo_full_name:
        return {"queued": 0}

    # Extract branch or tag name from refs/heads/main or refs/tags/v1.0
    ref_parts = ref.split("/", 2)
    ref_name = ref_parts[2] if len(ref_parts) == 3 else ref_parts[-1]

    # Collect all changed/added file paths
    changed_paths: set[str] = set()
    for commit in payload.get("commits", []):
        changed_paths.update(commit.get("added", []))
        changed_paths.update(commit.get("modified", []))

    if not changed_paths:
        return {"queued": 0}

    # Build raw GitHub URLs for each changed path
    candidate_urls = [
        f"https://raw.githubusercontent.com/{repo_full_name}/{ref_name}/{path}"
        for path in changed_paths
    ]

    # Find registered ontologies whose source_url matches
    result = await db.execute(
        select(OntologyVersion.source_url)
        .where(OntologyVersion.source_url.in_(candidate_urls))
        .where(OntologyVersion.status != "deprecated")
        .distinct()
    )
    matched_urls = result.scalars().all()

    for url in matched_urls:
        ingest_ontology.delay(url=url)
        log.info("github_sync_queued", url=url, repo=repo_full_name, ref=ref)

    return {"queued": len(matched_urls), "urls": matched_urls}
```

- [ ] **Step 5: Register the inbound router in main.py**

In `ontoexplorer/main.py`, add the import:

```python
from ontoexplorer.api.inbound import router as inbound_router
```

And register it (add after `app.include_router(webhooks_router)`):

```python
    app.include_router(inbound_router)
```

- [ ] **Step 6: Run the tests — should pass now**

```bash
uv run pytest tests/integration/test_auto_sync.py::test_github_inbound_queues_ingest tests/integration/test_auto_sync.py::test_github_inbound_rejects_bad_signature tests/integration/test_auto_sync.py::test_github_inbound_ignores_non_push_events tests/integration/test_auto_sync.py::test_github_inbound_no_secret_configured -v
```

Expected: PASS

- [ ] **Step 7: Add the beat service to docker-compose.yml**

In `docker-compose.yml`, add a `beat` service after the `worker` service block. Copy the worker block and change the command:

```yaml
  beat:
    build: .
    command: celery -A ontoexplorer.modules.jobs.tasks beat --loglevel=info
    env_file: .env
    depends_on:
      - postgres
      - redis
    volumes:
      - ./ontoexplorer:/app/ontoexplorer
```

- [ ] **Step 8: Document the new env var in .env.example**

In `.env.example`, add after the ELK service block:

```bash
# ── GitHub inbound webhook ────────────────────────────────────────────────────
# Set this to the secret you configure in your GitHub repo's webhook settings.
# Leave empty to disable the /api/v1/inbound/github endpoint.
GITHUB_WEBHOOK_SECRET=
```

- [ ] **Step 9: Run the full test suite**

```bash
uv run pytest tests/ -v --ignore=tests/integration/test_reasoning_api.py -x
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add ontoexplorer/config.py ontoexplorer/api/inbound.py ontoexplorer/main.py docker-compose.yml .env.example tests/integration/test_auto_sync.py
git commit -m "feat(sync): inbound GitHub push webhook at POST /api/v1/inbound/github"
```

---

## Self-Review

**Spec coverage:**
- [x] Polling: `poll_for_updates` task, `beat_schedule`, `auto_sync` toggle, `source_url` storage — Tasks 1–4
- [x] GitHub inbound webhook: HMAC verification, push event parsing, source_url matching, ingest queuing — Task 5
- [x] Both paths reuse `ingest_ontology` (SHA-256 dedup handles no-ops) — unchanged task, verified in tests
- [x] Docker Compose: `beat` service added — Task 5, Step 7

**Placeholder scan:** None found. Every step has actual code.

**Type consistency:**
- `_run_poll(db)` defined in Task 4 Step 3, imported as `from ontoexplorer.modules.jobs.tasks import _run_poll` in Task 4 tests — consistent.
- `ingest_ontology.delay(url=..., owner_id=...)` in `_run_poll`; `ingest_ontology.delay(url=...)` in inbound (no owner). Both are valid — `owner_id` is an optional keyword arg in the Celery task signature.
- `OntologyVersion.source_url` added in Task 1, used in Tasks 2, 4, 5 — consistent.
- `Ontology.auto_sync` added in Task 1, used in Tasks 3, 4 — consistent.

**One gap fixed:** The `_run_poll` test in Task 4 patches `httpx.Client` (sync client used in `_run_poll`), which is correct since `_run_poll` uses synchronous httpx inside `asyncio.run`. Verified the httpx patch target matches the implementation.
