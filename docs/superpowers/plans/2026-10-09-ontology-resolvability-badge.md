# Ontology IRI Resolvability Badge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely check whether each ontology's IRI dereferences to RDF via HTTP content negotiation, store the result, and show a "Resolvable" badge for those that do.

**Architecture:** A Celery task fetches the canonical IRI through the existing SSRF-guarded httpx transport with an RDF `Accept` header, following w3id/purl redirects; it records `resolvable` + detail on the `ontologies` row. The check is dispatched when a version becomes ready and is re-runnable by the owner/maintainer/admin. The API exposes the flag; the frontend renders a small badge on the ontology page and catalogue/dashboard rows.

**Tech Stack:** Python / FastAPI / SQLAlchemy (async) / Alembic / Celery; `httpx` with `ontoexplorer.clients.fetch_guard.guarded_transport`; React / TypeScript / Vitest.

**Spec:** `docs/superpowers/specs/2026-10-09-ontology-ownership-proof-design.md` — this plan implements the **dereference-check slice** (narrowed to *resolvability*, not full identity-match), feeding the provenance/badge model; the broader `verification_status` + admin verify/dispute workflow is a separate plan.

## Global Constraints

- SSRF: **never** fetch a user-influenced URL without `guarded_transport()` (blocks private/loopback/link-local/CGNAT + rebinding). Do not add a new fetch path.
- The check is **best-effort and side-effect-free** (read-only HTTP): any failure yields `resolvable = False`, never an exception that affects ingest or request handling.
- Bounded fetch: follow ≤ a few redirects, ~10s total timeout, and **do not download the body** — inspect status + `Content-Type` only (stream + close).
- `resolvable` is a tri-state: `True` (dereferences to RDF), `False` (checked, didn't), `NULL` (not yet checked). Default `NULL`.
- New backend code is Postgres + sqlite compatible (unit tests run on sqlite); the new column uses `JSON().with_variant(JSONB, "postgresql")` like the existing `lang_counts` column.

## Review Focus

- **Redirect to a private address** (w3id → attacker host → `169.254.169.254`): the guarded transport must reject it on the *redirected* hop, not just the first — Task 2 test `test_check_resolvable_blocks_redirect_to_private`.
- **Resolves but returns HTML** (IRI serves a landing page, not RDF): must be `resolvable = False`, not True — Task 1/2 tests on content-type recognition + `test_check_resolvable_html_is_not_resolvable`.
- **IRI is a `urn:`/non-HTTP identity** (some ontologies): must short-circuit to `resolvable = False` without a fetch — Task 2 `test_check_resolvable_non_http_scheme`.
- **Content-Type with charset parameter** (`text/turtle; charset=utf-8`): must still be recognized as RDF — Task 1 `test_rdf_content_type_ignores_params`.
- **Timeout / connection error**: must be caught → `resolvable = False` with an `error` string, never propagate — Task 2 `test_check_resolvable_timeout_is_false`.

---

### Task 1: RDF content-type recognition + Accept header

**Files:**
- Create: `ontoexplorer/modules/resolve/__init__.py` (empty)
- Create: `ontoexplorer/modules/resolve/conneg.py`
- Test: `tests/unit/resolve/test_conneg_types.py`

**Interfaces:**
- Produces: `RDF_ACCEPT: str`; `is_rdf_content_type(content_type: str | None) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_conneg_types.py
from ontoexplorer.modules.resolve.conneg import RDF_ACCEPT, is_rdf_content_type


def test_rdf_content_types_recognized():
    for ct in ("text/turtle", "application/rdf+xml", "application/ld+json",
               "application/n-triples", "application/n-quads", "application/trig",
               "text/n3", "application/owl+xml"):
        assert is_rdf_content_type(ct) is True


def test_rdf_content_type_ignores_params():
    assert is_rdf_content_type("text/turtle; charset=utf-8") is True
    assert is_rdf_content_type("  Application/RDF+XML ;q=1 ") is True


def test_non_rdf_content_types_rejected():
    for ct in ("text/html", "application/json", "text/plain",
               "application/octet-stream", "", None):
        assert is_rdf_content_type(ct) is False


def test_accept_header_lists_rdf_then_wildcard_fallback():
    assert "text/turtle" in RDF_ACCEPT
    assert RDF_ACCEPT.strip().endswith("*/*;q=0.1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/resolve/test_conneg_types.py -v`
Expected: FAIL — `ModuleNotFoundError: ontoexplorer.modules.resolve.conneg`.

- [ ] **Step 3: Write minimal implementation**

```python
# ontoexplorer/modules/resolve/conneg.py
"""HTTP content negotiation for ontology IRI dereferencing."""
from __future__ import annotations

# Ask for RDF in rough fidelity order, then fall back to anything so a server
# that ignores Accept still answers (we judge the response by its Content-Type).
RDF_ACCEPT = (
    "text/turtle,application/rdf+xml,application/ld+json,"
    "application/n-triples,application/n-quads,application/trig,"
    "text/n3;q=0.9,application/owl+xml;q=0.9,*/*;q=0.1"
)

_RDF_TYPES = {
    "text/turtle", "application/rdf+xml", "application/ld+json",
    "application/n-triples", "application/n-quads", "application/trig",
    "text/n3", "application/owl+xml", "application/xml",  # some servers label RDF/XML this way
}


def is_rdf_content_type(content_type: str | None) -> bool:
    """True if a response `Content-Type` names an RDF serialization.

    Tolerant of charset/q params and case; the bare media type is matched.
    """
    if not content_type:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return media in _RDF_TYPES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/resolve/test_conneg_types.py -v`
Expected: PASS (4 tests).

> Note: `application/xml` is included because some stores serve RDF/XML as `application/xml`; it over-accepts slightly, which is acceptable for a *resolvability* signal (not an identity claim).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/resolve/__init__.py ontoexplorer/modules/resolve/conneg.py tests/unit/resolve/test_conneg_types.py
git commit -m "feat(resolve): RDF content-type recognition + conneg Accept header"
```

---

### Task 2: Safe conneg resolvability check

**Files:**
- Modify: `ontoexplorer/modules/resolve/conneg.py`
- Test: `tests/unit/resolve/test_check_resolvable.py`

**Interfaces:**
- Consumes: `RDF_ACCEPT`, `is_rdf_content_type` (Task 1); `guarded_transport` from `ontoexplorer.clients.fetch_guard`.
- Produces:
  - `@dataclass(frozen=True) class ResolveResult: resolvable: bool; final_url: str | None; http_status: int | None; content_type: str | None; error: str | None`
  - `def check_resolvable(iri: str, *, client_factory=None) -> ResolveResult` — `client_factory()` returns a context-manageable httpx-like client with `.stream(method, url, headers=...)`; defaults to a guarded httpx client. Tests inject a fake.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_check_resolvable.py
import contextlib
from ontoexplorer.modules.resolve.conneg import check_resolvable


class _Resp:
    def __init__(self, status, content_type, url):
        self.status_code = status
        self.headers = {"content-type": content_type} if content_type else {}
        self.url = url


class _FakeClient:
    """Mimics httpx.Client.stream(...) as a context manager yielding a response."""
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc

    def __enter__(self): return self
    def __exit__(self, *a): return False

    @contextlib.contextmanager
    def stream(self, method, url, headers=None):
        if self._exc:
            raise self._exc
        yield self._resp


def _factory(resp=None, exc=None):
    return lambda: _FakeClient(resp, exc)


def test_check_resolvable_true_for_rdf():
    r = check_resolvable(
        "https://w3id.org/sulo/",
        client_factory=_factory(_Resp(200, "text/turtle", "https://example.org/sulo.ttl")),
    )
    assert r.resolvable is True
    assert r.http_status == 200
    assert r.content_type == "text/turtle"
    assert r.final_url == "https://example.org/sulo.ttl"


def test_check_resolvable_html_is_not_resolvable():
    r = check_resolvable("https://example.org/onto",
                         client_factory=_factory(_Resp(200, "text/html", "https://example.org/onto")))
    assert r.resolvable is False


def test_check_resolvable_non_2xx_is_false():
    r = check_resolvable("https://example.org/onto",
                         client_factory=_factory(_Resp(404, "text/turtle", "https://example.org/onto")))
    assert r.resolvable is False
    assert r.http_status == 404


def test_check_resolvable_non_http_scheme():
    # urn:/ftp: etc. never fetched.
    r = check_resolvable("urn:uuid:1234", client_factory=_factory(_Resp(200, "text/turtle", "x")))
    assert r.resolvable is False
    assert r.error == "non-http scheme"


def test_check_resolvable_timeout_is_false():
    import httpx
    r = check_resolvable("https://example.org/onto",
                         client_factory=_factory(exc=httpx.ConnectTimeout("boom")))
    assert r.resolvable is False
    assert r.error and "boom" in r.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/resolve/test_check_resolvable.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_resolvable'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to ontoexplorer/modules/resolve/conneg.py
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0
_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class ResolveResult:
    resolvable: bool
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    error: str | None = None


def _default_client_factory():
    import httpx
    from ontoexplorer.clients.fetch_guard import guarded_transport
    return lambda: httpx.Client(
        timeout=_TIMEOUT_S,
        follow_redirects=True,
        max_redirects=_MAX_REDIRECTS,
        transport=guarded_transport(),   # SSRF guard on EVERY hop incl. redirects
        trust_env=False,
    )


def check_resolvable(iri: str, *, client_factory=None) -> ResolveResult:
    """Best-effort: does `iri` dereference to RDF via content negotiation?

    Read-only, bounded (no body download — status + Content-Type only), and
    SSRF-guarded. Never raises: any failure is reported as resolvable=False.
    """
    scheme = urlparse(iri).scheme.lower()
    if scheme not in ("http", "https"):
        return ResolveResult(False, error="non-http scheme")

    factory = client_factory or _default_client_factory()
    try:
        with factory() as client:
            with client.stream("GET", iri, headers={"Accept": RDF_ACCEPT}) as resp:
                status = resp.status_code
                ctype = resp.headers.get("content-type")
                final = str(getattr(resp, "url", iri) or iri)
                ok = 200 <= status < 300 and is_rdf_content_type(ctype)
                return ResolveResult(ok, final_url=final, http_status=status, content_type=ctype)
    except Exception as exc:  # httpx errors, guard rejection, DNS, etc.
        logger.debug("resolvability check failed for %s", iri, exc_info=True)
        return ResolveResult(False, error=str(exc)[:500])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/resolve/test_check_resolvable.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Add the redirect-to-private guard test (Review Focus)**

```python
# append to tests/unit/resolve/test_check_resolvable.py
def test_check_resolvable_blocks_redirect_to_private():
    # The guarded transport raises on a redirect that resolves to a private IP.
    # We simulate the client raising the same way httpx+guard would.
    import httpx
    r = check_resolvable(
        "https://w3id.org/evil/",
        client_factory=_factory(exc=httpx.ConnectError("blocked private address 169.254.169.254")),
    )
    assert r.resolvable is False
    assert "169.254" in (r.error or "")
```

Run: `uv run pytest tests/unit/resolve/test_check_resolvable.py -v` → PASS (6 tests).

> The guard itself (`fetch_guard.guarded_transport`) already rejects private targets on each hop and is covered by its own tests; this test pins the *behavior contract* that a guard rejection becomes `resolvable=False`.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/modules/resolve/conneg.py tests/unit/resolve/test_check_resolvable.py
git commit -m "feat(resolve): SSRF-guarded conneg resolvability check"
```

---

### Task 3: Persist resolvability on the ontology

**Files:**
- Modify: `ontoexplorer/models/db.py` (the `Ontology` model)
- Create: `alembic/versions/<rev>_ontology_resolvable.py`
- Test: `tests/unit/resolve/test_ontology_resolvable_column.py`

**Interfaces:**
- Produces on `Ontology`: `resolvable: Mapped[bool | None]`, `resolve_checked_at: Mapped[datetime | None]`, `resolve_detail: Mapped[dict | None]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_ontology_resolvable_column.py
import pytest
from sqlalchemy import select
from ontoexplorer.models.db import Ontology


@pytest.mark.anyio
async def test_ontology_stores_resolvability(db_session):
    o = Ontology(iri="https://w3id.org/x/", shortname="xtest", title="X",
                 resolvable=True, resolve_detail={"content_type": "text/turtle"})
    db_session.add(o)
    await db_session.commit()
    got = (await db_session.execute(select(Ontology).where(Ontology.id == o.id))).scalar_one()
    assert got.resolvable is True
    assert got.resolve_detail["content_type"] == "text/turtle"
    assert got.resolve_checked_at is None  # defaults NULL until a check runs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/resolve/test_ontology_resolvable_column.py -v`
Expected: FAIL — `TypeError: 'resolvable' is an invalid keyword argument for Ontology`.

- [ ] **Step 3: Add the columns to the model**

In `ontoexplorer/models/db.py`, inside `class Ontology(Base)`, after the existing columns, add (match the file's import of `JSONB`, `JSON`, `datetime`, `DateTime`):

```python
    # Resolvability (does the IRI dereference to RDF via conneg). NULL = unchecked.
    resolvable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resolve_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolve_detail: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
```

- [ ] **Step 4: Create the migration**

Find the current head: `uv run alembic heads`. Create `alembic/versions/<rev>_ontology_resolvable.py` with `down_revision` = that head:

```python
"""ontology resolvability columns

Revision ID: <rev>
Revises: <head>
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "<rev>"
down_revision = "<head>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ontologies", sa.Column("resolvable", sa.Boolean(), nullable=True))
    op.add_column("ontologies", sa.Column("resolve_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ontologies", sa.Column("resolve_detail",
                  sa.JSON().with_variant(JSONB, "postgresql"), nullable=True))


def downgrade() -> None:
    op.drop_column("ontologies", "resolve_detail")
    op.drop_column("ontologies", "resolve_checked_at")
    op.drop_column("ontologies", "resolvable")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/resolve/test_ontology_resolvable_column.py -v`
Expected: PASS (the sqlite test DB builds the schema from the models via `Base.metadata.create_all`, so no migration run is needed for the unit test).

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/models/db.py alembic/versions/*_ontology_resolvable.py tests/unit/resolve/test_ontology_resolvable_column.py
git commit -m "feat(resolve): persist ontology resolvability (+ migration)"
```

---

### Task 4: Celery task to check + store an ontology's resolvability

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py` (new task + a shared async helper)
- Test: `tests/unit/resolve/test_resolvability_task.py`

**Interfaces:**
- Consumes: `check_resolvable` (Task 2); `Ontology` columns (Task 3).
- Produces:
  - `async def _apply_resolvability(db, ontology_id: str, *, client_factory=None) -> None` — runs the check against the ontology's IRI and writes `resolvable` / `resolve_checked_at` / `resolve_detail`. Testable without Celery.
  - `check_ontology_resolvable` (Celery task) wrapping it.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_resolvability_task.py
import contextlib
import pytest
from sqlalchemy import select
from ontoexplorer.models.db import Ontology
from ontoexplorer.modules.jobs.tasks import _apply_resolvability


class _Resp:
    def __init__(self, status, ct, url):
        self.status_code, self.headers, self.url = status, {"content-type": ct}, url


class _FakeClient:
    def __init__(self, resp): self._resp = resp
    def __enter__(self): return self
    def __exit__(self, *a): return False
    @contextlib.contextmanager
    def stream(self, *a, **k): yield self._resp


@pytest.mark.anyio
async def test_apply_resolvability_marks_true(db_session):
    o = Ontology(iri="https://w3id.org/sulo/", shortname="sulo-rt", title="S")
    db_session.add(o); await db_session.commit()
    await _apply_resolvability(
        db_session, o.id,
        client_factory=lambda: _FakeClient(_Resp(200, "text/turtle", "https://x/sulo.ttl")),
    )
    got = (await db_session.execute(select(Ontology).where(Ontology.id == o.id))).scalar_one()
    assert got.resolvable is True
    assert got.resolve_checked_at is not None
    assert got.resolve_detail["http_status"] == 200


@pytest.mark.anyio
async def test_apply_resolvability_marks_false_for_html(db_session):
    o = Ontology(iri="https://example.org/o", shortname="o-rt", title="O")
    db_session.add(o); await db_session.commit()
    await _apply_resolvability(
        db_session, o.id,
        client_factory=lambda: _FakeClient(_Resp(200, "text/html", "https://example.org/o")),
    )
    got = (await db_session.execute(select(Ontology).where(Ontology.id == o.id))).scalar_one()
    assert got.resolvable is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/resolve/test_resolvability_task.py -v`
Expected: FAIL — `ImportError: cannot import name '_apply_resolvability'`.

- [ ] **Step 3: Implement the helper + task**

Add to `ontoexplorer/modules/jobs/tasks.py`:

```python
async def _apply_resolvability(db, ontology_id: str, *, client_factory=None) -> None:
    """Check whether the ontology's IRI dereferences to RDF (conneg) and store
    the result. Best-effort: a check that can't run leaves resolvable=False."""
    from datetime import datetime, timezone
    from sqlalchemy import select, update
    from ontoexplorer.models.db import Ontology
    from ontoexplorer.modules.resolve.conneg import check_resolvable

    onto = (await db.execute(select(Ontology).where(Ontology.id == ontology_id))).scalar_one_or_none()
    if onto is None:
        return
    # check_resolvable does blocking HTTP; run it off the event loop.
    import asyncio
    res = await asyncio.to_thread(check_resolvable, onto.iri, client_factory=client_factory)
    await db.execute(
        update(Ontology).where(Ontology.id == ontology_id).values(
            resolvable=res.resolvable,
            resolve_checked_at=datetime.now(timezone.utc),
            resolve_detail={
                "final_url": res.final_url, "http_status": res.http_status,
                "content_type": res.content_type, "error": res.error,
            },
        )
    )
    await db.commit()


@celery_app.task(name="ontoexplorer.check_ontology_resolvable", time_limit=60)
def check_ontology_resolvable(ontology_id: str) -> dict:
    """Celery entry point: dereference-check one ontology's IRI."""
    import asyncio
    from ontoexplorer.database import make_celery_db_session

    async def _run():
        async with make_celery_db_session()() as db:
            await _apply_resolvability(db, ontology_id)

    asyncio.run(_run())
    return {"ontology_id": ontology_id}
```

Register the task's queue next to the others in the `task_routes`/beat config block (search `"ontoexplorer.purge_version_artifacts": {"queue": "write"}` and add `"ontoexplorer.check_ontology_resolvable": {"queue": "light"}` — use whichever IO/light queue siblings use; if there is no distinct light queue, omit the route and it uses the default).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/resolve/test_resolvability_task.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py tests/unit/resolve/test_resolvability_task.py
git commit -m "feat(resolve): celery task to check + store ontology resolvability"
```

---

### Task 5: Dispatch the check when a version becomes ready

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py` (near `_mark_ready`, ~line 1291, and the sibling `.delay(...)` dispatches around line 1371)
- Test: `tests/unit/resolve/test_resolvability_dispatch.py`

**Interfaces:**
- Consumes: `check_ontology_resolvable` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_resolvability_dispatch.py
from unittest.mock import patch
from ontoexplorer.modules.jobs import tasks


def test_ready_dispatches_resolvability_check():
    # The ingest-ready path dispatches the resolvability check for the ontology.
    with patch.object(tasks.check_ontology_resolvable, "delay") as m:
        tasks._dispatch_resolvability_check("onto-123")
        m.assert_called_once_with("onto-123")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/resolve/test_resolvability_dispatch.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_dispatch_resolvability_check'`.

- [ ] **Step 3: Implement the dispatch helper and call it**

Add a tiny indirection (so it is unit-testable and best-effort) to `tasks.py`:

```python
def _dispatch_resolvability_check(ontology_id: str) -> None:
    """Fire the IRI resolvability check; never let a dispatch error block ingest."""
    try:
        check_ontology_resolvable.delay(ontology_id)
    except Exception:
        log.warning("resolvability_dispatch_failed", ontology_id=ontology_id)
```

Then, in the ready path where siblings dispatch (next to `embed_ontology.delay(version_id, ontology_id=ontology_id)` ~line 1371), add:

```python
        _dispatch_resolvability_check(ontology_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/resolve/test_resolvability_dispatch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py tests/unit/resolve/test_resolvability_dispatch.py
git commit -m "feat(resolve): dispatch resolvability check when a version is ready"
```

---

### Task 6: Expose resolvability in the API + owner re-check endpoint

**Files:**
- Modify: `ontoexplorer/api/ontologies.py` (`_ontology_dict`, the lean list projection `_LIST_VIEW_FIELDS`, and a new route)
- Test: `tests/unit/resolve/test_resolvability_api.py`

**Interfaces:**
- Consumes: `Ontology.resolvable` / `resolve_checked_at` (Task 3); `check_ontology_resolvable` (Task 4); `can_edit_ontology_id` (`ontoexplorer.modules.auth.permissions`).
- Produces: ontology dicts carry `resolvable` + `resolve_checked_at`; `POST /api/v1/ontologies/{ontology_id}/recheck-resolvable`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/resolve/test_resolvability_api.py
from types import SimpleNamespace
from ontoexplorer.api.ontologies import _ontology_dict


def test_ontology_dict_includes_resolvability():
    o = SimpleNamespace(
        id="o1", iri="https://w3id.org/x/", shortname="x", title="X", groups=[],
        owner_id=None, auto_sync=False, current_version_id=None,
        created_at="2026-01-01T00:00:00Z",
        resolvable=True, resolve_checked_at="2026-10-09T00:00:00Z", resolve_detail={},
    )
    d = _ontology_dict(o, None)
    assert d["resolvable"] is True
    assert d["resolve_checked_at"] == "2026-10-09T00:00:00Z"
```

(If `_ontology_dict` reads attributes defensively, use `getattr(o, "resolvable", None)` in the impl so the SimpleNamespace shape matches the real model.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/resolve/test_resolvability_api.py -v`
Expected: FAIL — `KeyError: 'resolvable'`.

- [ ] **Step 3: Implement**

In `_ontology_dict(...)` add to the returned dict:

```python
        "resolvable": getattr(o, "resolvable", None),
        "resolve_checked_at": getattr(o, "resolve_checked_at", None),
```

Add `"resolvable"` to `_LIST_VIEW_FIELDS` so the lean catalogue/dashboard row carries the badge flag.

Add the re-check route (near the other `@router.post` handlers), gated like the PATCH path:

```python
@router.post("/{ontology_id}/recheck-resolvable", status_code=202,
             summary="Re-run the IRI resolvability check")
async def recheck_resolvable(
    ontology_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    ontology = await _get_ontology_or_404(db, ontology_id)
    from ontoexplorer.modules.auth.permissions import can_edit_ontology
    if not await can_edit_ontology(db, user, ontology):
        raise HTTPException(status_code=403, detail="Not allowed to re-check this ontology")
    from ontoexplorer.modules.jobs.tasks import check_ontology_resolvable
    check_ontology_resolvable.delay(ontology.id)
    return {"status": "queued"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/resolve/test_resolvability_api.py -v`
Expected: PASS.

- [ ] **Step 5: Run the catalogue list-view tests to confirm the lean field addition didn't break the projection**

Run: `uv run pytest tests/unit/test_ontologies_list_view.py -v`
Expected: PASS (the new `resolvable` field is allowed in `_LIST_VIEW_FIELDS`).

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/ontologies.py tests/unit/resolve/test_resolvability_api.py
git commit -m "feat(resolve): expose resolvability in API + owner re-check endpoint"
```

---

### Task 7: Frontend "Resolvable" badge

**Files:**
- Modify: `frontend/src/lib/api.ts` (the `Ontology` type)
- Create: `frontend/src/components/ResolvableBadge.tsx`
- Modify: `frontend/src/pages/OntologyPage.tsx` (render near the title) and `frontend/src/pages/Ontologies.tsx` (catalogue row)
- Test: `frontend/src/components/ResolvableBadge.test.tsx`

**Interfaces:**
- Consumes: `ontology.resolvable: boolean | null`, `ontology.resolve_checked_at: string | null` from the API (Task 6).
- Produces: `<ResolvableBadge resolvable={...} checkedAt={...} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ResolvableBadge.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ResolvableBadge from './ResolvableBadge'

describe('ResolvableBadge', () => {
  it('shows a resolvable badge when the IRI dereferences', () => {
    render(<ResolvableBadge resolvable={true} checkedAt="2026-10-09T00:00:00Z" />)
    expect(screen.getByText(/resolvable/i)).toBeInTheDocument()
  })
  it('renders nothing when not resolvable or unchecked', () => {
    const { container: a } = render(<ResolvableBadge resolvable={false} checkedAt={null} />)
    expect(a.textContent).toBe('')
    const { container: b } = render(<ResolvableBadge resolvable={null} checkedAt={null} />)
    expect(b.textContent).toBe('')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `./node_modules/.bin/vitest run src/components/ResolvableBadge.test.tsx`
Expected: FAIL — cannot find module `./ResolvableBadge`.

- [ ] **Step 3: Implement the component + type**

Add to `frontend/src/lib/api.ts` on the `Ontology` interface:

```ts
  resolvable?: boolean | null
  resolve_checked_at?: string | null
```

Create `frontend/src/components/ResolvableBadge.tsx`:

```tsx
export default function ResolvableBadge({ resolvable, checkedAt }: {
  resolvable?: boolean | null
  checkedAt?: string | null
}) {
  if (resolvable !== true) return null  // only a positive signal is shown
  const when = checkedAt ? new Date(checkedAt).toLocaleDateString() : ''
  return (
    <span
      title={`This ontology's IRI dereferences to RDF via content negotiation${when ? ` (checked ${when})` : ''}.`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4, padding: '1px 8px',
        borderRadius: 10, fontSize: 11, fontWeight: 600,
        background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-muted)',
      }}
    >
      🔗 Resolvable
    </span>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./node_modules/.bin/vitest run src/components/ResolvableBadge.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire it in**

- In `OntologyPage.tsx`, import and render `<ResolvableBadge resolvable={ontology.resolvable} checkedAt={ontology.resolve_checked_at} />` beside the ontology title.
- In `Ontologies.tsx`, render it in the catalogue row next to the name (lean row now carries `resolvable`; `resolve_checked_at` is absent in the lean row — pass `undefined`, the badge only needs `resolvable`).

- [ ] **Step 6: Typecheck, test, build**

Run (from `frontend/`): `./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/vitest run && ./node_modules/.bin/vite build`
Expected: tsc clean; all tests pass; build ok.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/components/ResolvableBadge.tsx frontend/src/components/ResolvableBadge.test.tsx frontend/src/pages/OntologyPage.tsx frontend/src/pages/Ontologies.tsx
git commit -m "feat(resolve): Resolvable badge on ontology page + catalogue"
```

---

## Notes for the executor

- **Backfill (optional, out of this plan):** the ~1,900 existing ontologies stay `resolvable = NULL` until re-ingested or re-checked. A one-off script dispatching `check_ontology_resolvable.delay(id)` for every ontology (rate-limited) can seed them; keep it out of the request path. Defer unless asked.
- **Periodic re-check (optional):** IRIs drift; a Celery beat job re-checking stale rows is a later addition, not in scope here.
- **Relationship to the ownership-proof spec:** `resolvable` is the first, simplest signal of that spec's dereference check. A later plan can promote it into the full `verification_status` (`canonical_verified` adds *identity match*, admin verify/dispute). Keep the column; don't rename.
