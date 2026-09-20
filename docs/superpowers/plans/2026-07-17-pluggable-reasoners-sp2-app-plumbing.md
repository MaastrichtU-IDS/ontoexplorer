# Pluggable Reasoners — SP2 App Plumbing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the reasoner a first-class per-ontology property in the main app — selected at ingest, stored on the version, and routed to the reasoner-service for both classification and justification.

**Architecture:** A `reasoner` column on `versions` (default `whelk`) is set at ingest from the request (validated against `GET /reasoners`) or the app default `DEFAULT_REASONER`. The `reason_ontology` task and every reasoning-service client call thread the version's reasoner. Justification routes by the version's reasoner, passes the `format` through, and treats a no-justify reasoner as "not available" rather than an error.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async) + Alembic, Celery, httpx, Redis, pytest.

## Global Constraints

- Depends on SP1 (branch `feat/pluggable-reasoners-sp2` is cut from `feat/pluggable-reasoners`). The SP1 reasoner-service is NOT modified.
- Reasoner names are the exact lowercase strings `whelk`, `rdflib`, `rustdl`, `konclude`. The default everywhere is `whelk`.
- `versions.reasoner` is `String`, `NOT NULL`, `server_default='whelk'`; existing rows backfill to `'whelk'`.
- Reasoner is bound per version and immutable after ingest (no re-classify endpoint in SP2).
- Justification `format` values: `"ntriples"` (whelk/rdflib) | `"manchester"` (rustdl). A reasoner lacking the justify capability → the reasoner-service returns HTTP 422; the app converts that to `{"reasoning_available": false, ...}`, never a 500.
- Submit-time reasoner validation is a guardrail: if `GET /reasoners` is unreachable, fall back to accepting the four known names and log a warning — never hard-block ingest on the service being down.
- Non-standard local env: `python` is not on PATH and `uv run` fails (network). Use `/path/to/ontoexplorer/.venv/bin/python -m pytest`. The app test suite needs the full app env (sqlalchemy etc.); if a needed dep is missing install it targeted via `UV_HTTP_TIMEOUT=300 uv pip install <name>` — never `uv sync`.
- Commits use `git -c user.email=admin@example.org` and end with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.
- No UI work (SP3): the app returns the data; typed Manchester rendering and the admin dropdown are out of scope.

---

## File Structure

- **Modify** `ontoexplorer/models/db.py:111` (`OntologyVersion`) — add `reasoner` column.
- **Create** `alembic/versions/<rev>_add_reasoner_to_versions.py` — migration + backfill.
- **Modify** `ontoexplorer/config.py` — add `default_reasoner`.
- **Modify** `ontoexplorer/clients/reasoning.py` — thread `reasoner` through `classify_v2`, `superclasses`, `subclasses`, `consistency`, `request_justification`; add `list_reasoners()`.
- **Modify** `ontoexplorer/api/ontologies.py:214` (`submit_ontology`) — accept + validate `reasoner`, thread to `ingest_ontology.delay(...)`; and the term-inference + justification endpoints load `version.reasoner` and pass it.
- **Modify** `ontoexplorer/modules/jobs/tasks.py` — `ingest_ontology` accepts `reasoner`; `_run_reasoning` reads `version.reasoner` and passes it to `classify_v2`.
- **Modify** `ontoexplorer/modules/ingestion/pipeline.py:71` (`IngestionRequest`) + `:200` (`OntologyVersion(...)`) — carry + persist `reasoner`.
- **Tests** under `tests/` mirroring the repo's existing async test style.

---

## Task 1: `reasoner` column on versions (model + migration)

**Files:**
- Modify: `ontoexplorer/models/db.py:111-127` (`OntologyVersion`)
- Create: `alembic/versions/<rev>_add_reasoner_to_versions.py`
- Test: `tests/test_reasoner_column_migration.py`

**Interfaces:**
- Produces: `OntologyVersion.reasoner: str` (attribute), non-null, default `"whelk"`.

- [ ] **Step 1: Add the model column**

In `ontoexplorer/models/db.py`, inside `class OntologyVersion`, after the `status` column add:

```python
    reasoner: Mapped[str] = mapped_column(String, nullable=False, server_default="whelk")
```

- [ ] **Step 2: Generate a migration skeleton, then hand-author it**

Find the current head revision:

```bash
cd ~/code/ontoexplorer && .venv/bin/python -m alembic heads 2>/dev/null || docker compose exec -T api alembic heads
```

Create `alembic/versions/<newrev>_add_reasoner_to_versions.py` (pick a unique `<newrev>` slug matching the repo's convention; set `down_revision` to the current head printed above):

```python
"""add reasoner column to versions

Revision ID: a1b2c3d4e5f7
Revises: <CURRENT_HEAD>
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f7"
down_revision = "<CURRENT_HEAD>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "versions",
        sa.Column("reasoner", sa.String(), nullable=False, server_default="whelk"),
    )
    # Existing versions were classified by whelk; the server_default already
    # backfills them, but be explicit for databases that don't apply the default
    # to existing rows on ADD COLUMN.
    op.execute("UPDATE versions SET reasoner = 'whelk' WHERE reasoner IS NULL")


def downgrade() -> None:
    op.drop_column("versions", "reasoner")
```

- [ ] **Step 3: Write the migration test**

Create `tests/test_reasoner_column_migration.py`:

```python
"""The reasoner column exists, is NOT NULL, and defaults to whelk."""
import sqlalchemy as sa
from ontoexplorer.models.db import OntologyVersion


def test_model_has_reasoner_default():
    col = OntologyVersion.__table__.c.reasoner
    assert col.nullable is False
    assert col.server_default is not None
    assert "whelk" in str(col.server_default.arg)
```

- [ ] **Step 4: Run the model test**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_reasoner_column_migration.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Apply the migration against the running DB and verify**

```bash
cd ~/code/ontoexplorer
docker compose exec -T api alembic upgrade head
docker compose exec -T postgres psql -U ontoexplorer -d ontoexplorer -c "\d versions" | grep reasoner
```
Expected: a `reasoner | character varying | not null` row, and existing versions (doid/go/ro) now have `reasoner='whelk'` (verify: `SELECT DISTINCT reasoner FROM versions;` → `whelk`).

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/models/db.py alembic/versions/*add_reasoner* tests/test_reasoner_column_migration.py
git -c user.email=admin@example.org commit -m "feat(app): add reasoner column to versions (default whelk)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `DEFAULT_REASONER` config + `list_reasoners()` client helper

**Files:**
- Modify: `ontoexplorer/config.py` (near the `reasoner_service_*` settings, ~line 54-62)
- Modify: `ontoexplorer/clients/reasoning.py`
- Test: `tests/test_default_reasoner_config.py`, `tests/test_list_reasoners_client.py`

**Interfaces:**
- Produces: `get_settings().default_reasoner: str` (default `"whelk"`, env `DEFAULT_REASONER`); `reasoning.list_reasoners() -> list[dict]` returning the `/reasoners` payload (each `{name, profile, capabilities, available}`); `reasoning.available_reasoner_names() -> set[str]` (names with `available: true`, or the four known names if the service is unreachable).

- [ ] **Step 1: Write the config test**

Create `tests/test_default_reasoner_config.py`:

```python
from ontoexplorer.config import get_settings


def test_default_reasoner_defaults_to_whelk(monkeypatch):
    monkeypatch.delenv("DEFAULT_REASONER", raising=False)
    get_settings.cache_clear()
    assert get_settings().default_reasoner == "whelk"


def test_default_reasoner_from_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_REASONER", "rustdl")
    get_settings.cache_clear()
    assert get_settings().default_reasoner == "rustdl"
```

- [ ] **Step 2: Run it (fails — no setting yet)**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_default_reasoner_config.py -q`
Expected: FAIL (`AttributeError: default_reasoner`).

- [ ] **Step 3: Add the setting**

In `ontoexplorer/config.py`, immediately after the `reasoner_service_timeout` field, add:

```python
    # Reasoner selected for an ontology when the ingest request omits one.
    default_reasoner: str = "whelk"
```

(pydantic-settings maps the field to the `DEFAULT_REASONER` env var case-insensitively; no explicit alias needed.)

- [ ] **Step 4: Run the config test**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_default_reasoner_config.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the client-helper test**

Create `tests/test_list_reasoners_client.py`:

```python
import httpx
import pytest
from ontoexplorer.clients import reasoning


class _FakeResp:
    def __init__(self, payload): self._p = payload; self.status_code = 200
    def json(self): return self._p
    def raise_for_status(self): pass


@pytest.mark.asyncio
async def test_available_reasoner_names_from_service(monkeypatch):
    payload = [
        {"name": "whelk", "capabilities": ["classify"], "available": True},
        {"name": "rustdl", "capabilities": ["classify"], "available": True},
        {"name": "konclude", "capabilities": ["classify"], "available": False},
    ]

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _FakeResp(payload)

    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _Client())
    names = await reasoning.available_reasoner_names()
    assert names == {"whelk", "rustdl"}          # konclude excluded (available False)


@pytest.mark.asyncio
async def test_available_reasoner_names_falls_back_when_unreachable(monkeypatch):
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise httpx.ConnectError("down")

    monkeypatch.setattr(reasoning.httpx, "AsyncClient", lambda *a, **k: _Client())
    names = await reasoning.available_reasoner_names()
    assert names == {"whelk", "rdflib", "rustdl", "konclude"}   # known-names fallback
```

- [ ] **Step 6: Run it (fails — no helper)**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_list_reasoners_client.py -q`
Expected: FAIL (`AttributeError: available_reasoner_names`).

- [ ] **Step 7: Implement the helpers**

In `ontoexplorer/clients/reasoning.py`, add near the top (after the existing imports and `_elk_url`):

```python
_KNOWN_REASONERS = {"whelk", "rdflib", "rustdl", "konclude"}


async def list_reasoners() -> list[dict]:
    """Return the reasoner-service /reasoners payload."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_elk_url("/reasoners"))
        resp.raise_for_status()
        return resp.json()


async def available_reasoner_names() -> set[str]:
    """Names of reasoners reporting available=true. Falls back to the known set
    if the reasoner-service can't be reached (validation must not block ingest)."""
    try:
        return {r["name"] for r in await list_reasoners() if r.get("available")}
    except Exception:
        log.warning("reasoners_unreachable_fallback_to_known_names")
        return set(_KNOWN_REASONERS)
```

(Use the module's existing logger; if none, add `import logging; log = logging.getLogger(__name__)`.)

- [ ] **Step 8: Run the client-helper test**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_list_reasoners_client.py -q`
Expected: PASS (2 passed). (If `pytest-asyncio` isn't configured, mirror how the repo's existing async tests are marked — check `tests/conftest.py`/`pyproject.toml` for `asyncio_mode`.)

- [ ] **Step 9: Commit**

```bash
git add ontoexplorer/config.py ontoexplorer/clients/reasoning.py tests/test_default_reasoner_config.py tests/test_list_reasoners_client.py
git -c user.email=admin@example.org commit -m "feat(app): DEFAULT_REASONER setting + reasoners discovery client helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Thread reasoner through ingest (submit → task → pipeline → version row)

**Files:**
- Modify: `ontoexplorer/api/ontologies.py:214-266` (`submit_ontology`)
- Modify: `ontoexplorer/modules/jobs/tasks.py:320-340` (`ingest_ontology`)
- Modify: `ontoexplorer/modules/ingestion/pipeline.py:71-79` (`IngestionRequest`) + `:200-210` (`OntologyVersion(...)`)
- Test: `tests/test_submit_reasoner.py`

**Interfaces:**
- Consumes: `get_settings().default_reasoner`, `reasoning.available_reasoner_names()` (Task 2).
- Produces: `ingest_ontology(..., reasoner: str = "whelk")`; `IngestionRequest.reasoner: str`; `OntologyVersion(reasoner=...)` persisted.

- [ ] **Step 1: Write the submit test**

Create `tests/test_submit_reasoner.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from ontoexplorer.main import app
from ontoexplorer.clients import reasoning


@pytest.fixture(autouse=True)
def _reasoners(monkeypatch):
    async def _names(): return {"whelk", "rustdl"}
    monkeypatch.setattr(reasoning, "available_reasoner_names", _names)


@pytest.mark.asyncio
async def test_submit_rejects_unknown_reasoner(monkeypatch):
    captured = {}
    from ontoexplorer.modules.jobs import tasks
    monkeypatch.setattr(tasks.ingest_ontology, "delay",
                        lambda **kw: captured.update(kw) or type("T", (), {"id": "t1"})())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/ontologies", json={"iri": "http://x/o.owl", "reasoner": "hermit"})
    assert r.status_code == 422
    assert "hermit" in r.text


@pytest.mark.asyncio
async def test_submit_threads_reasoner_to_task(monkeypatch):
    captured = {}
    from ontoexplorer.modules.jobs import tasks
    monkeypatch.setattr(tasks.ingest_ontology, "delay",
                        lambda **kw: captured.update(kw) or type("T", (), {"id": "t1"})())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/ontologies", json={"iri": "http://x/o.owl", "reasoner": "rustdl"})
    assert r.status_code == 200
    assert captured.get("reasoner") == "rustdl"


@pytest.mark.asyncio
async def test_submit_defaults_reasoner_when_omitted(monkeypatch):
    captured = {}
    from ontoexplorer.modules.jobs import tasks
    monkeypatch.setattr(tasks.ingest_ontology, "delay",
                        lambda **kw: captured.update(kw) or type("T", (), {"id": "t1"})())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/ontologies", json={"iri": "http://x/o.owl"})
    assert r.status_code == 200
    assert captured.get("reasoner") == "whelk"   # app default
```

- [ ] **Step 2: Run it (fails)**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_submit_reasoner.py -q`
Expected: FAIL (reasoner not threaded / not validated). If the app import needs a DB, follow the repo's existing API-test setup in `tests/` (there are async httpx ASGI tests already — mirror their fixtures).

- [ ] **Step 3: Add reasoner resolution + validation to `submit_ontology`**

In `ontoexplorer/api/ontologies.py` `submit_ontology`, after `owner_id = ...` and before the branches, add:

```python
    from ontoexplorer.clients import reasoning as _reasoning
    from ontoexplorer.config import get_settings as _get_settings

    # Reasoner: from body/form, else app default; validate against the service.
    async def _resolve_reasoner() -> str:
        req_reasoner = None
        if "multipart/form-data" in content_type and file:
            form = await request.form()
            req_reasoner = form.get("reasoner")
        else:
            try:
                req_reasoner = (await request.json()).get("reasoner")
            except Exception:
                req_reasoner = None
        chosen = req_reasoner or _get_settings().default_reasoner
        available = await _reasoning.available_reasoner_names()
        if chosen not in available:
            raise HTTPException(
                status_code=422,
                detail=f"unknown or unavailable reasoner '{chosen}'; available: {sorted(available)}",
            )
        return chosen

    reasoner = await _resolve_reasoner()
```

Then add `reasoner=reasoner` to **every** `ingest_ontology.delay(...)` call in this function (the multipart branch, the `iri`/`url`/`content` branches). NOTE: `request.json()` / `request.form()` can only be read once — the function already calls `await request.json()` later; refactor so the body is read once into a local `body` dict at the top and reused (both by `_resolve_reasoner` and the existing branches). Keep behavior identical otherwise.

- [ ] **Step 4: Add `reasoner` to the task + request + version row**

In `ontoexplorer/modules/jobs/tasks.py` `ingest_ontology`, add `reasoner: str = "whelk",` to the keyword args, and pass `reasoner=reasoner` into `IngestionRequest(...)`.

In `ontoexplorer/modules/ingestion/pipeline.py`:
- `IngestionRequest` (line 71): add field `reasoner: str = "whelk"`.
- `OntologyVersion(...)` (line 200): add `reasoner=request.reasoner,`.

- [ ] **Step 5: Run the submit tests**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_submit_reasoner.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/ontologies.py ontoexplorer/modules/jobs/tasks.py ontoexplorer/modules/ingestion/pipeline.py tests/test_submit_reasoner.py
git -c user.email=admin@example.org commit -m "feat(app): select+validate reasoner at ingest, persist on version

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Thread reasoner through the reasoning client

**Files:**
- Modify: `ontoexplorer/clients/reasoning.py` (`classify_v2`, `superclasses`, `subclasses`, `consistency`, `request_justification`)
- Test: `tests/test_reasoning_client_reasoner.py`

**Interfaces:**
- Produces (all default `reasoner: str = "whelk"`, appended as the last param to preserve existing positional calls):
  - `classify_v2(graph, version_id, reasoner="whelk")` — POST body gains `"reasoner"`, poll GET gains `?reasoner=`.
  - `superclasses(version_id, class_iri, direct=False, reasoner="whelk")` — GET gains `?reasoner=` (alongside existing params).
  - `subclasses(version_id, class_iri, direct=False, reasoner="whelk")` — same.
  - `consistency(version_id, reasoner="whelk")` — GET gains `?reasoner=`.
  - `request_justification(version_id, sub, sup, max_justifications, reasoner="whelk")` — POST body gains `"reasoner"`; on HTTP 422 (no-justify) returns `{"justifications": [], "reasoning_available": False, "reason": <detail>}` instead of raising.

- [ ] **Step 1: Write the client test**

Create `tests/test_reasoning_client_reasoner.py`:

```python
import httpx
import pytest
from ontoexplorer.clients import reasoning


def _client_capturing(calls, *, justify_422=False):
    class _Resp:
        def __init__(self, status=200, payload=None):
            self.status_code = status; self._p = payload or {}
        def json(self): return self._p
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            calls.append(("POST", url, json))
            if justify_422 and url.endswith("/justification"):
                return _Resp(422, {"detail": "reasoner 'konclude' does not support justifications"})
            return _Resp(202, {"status": "running"})
        async def get(self, url):
            calls.append(("GET", url, None))
            return _Resp(200, {"superclasses": {}, "consistent": True})
    return lambda *a, **k: _Client()


@pytest.mark.asyncio
async def test_request_justification_reasoner_in_body(monkeypatch):
    calls = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing(calls))
    await reasoning.request_justification("v1", "s", "o", 1, reasoner="rustdl")
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[2]["reasoner"] == "rustdl"


@pytest.mark.asyncio
async def test_request_justification_422_becomes_unavailable(monkeypatch):
    calls = []
    monkeypatch.setattr(reasoning.httpx, "AsyncClient", _client_capturing(calls, justify_422=True))
    result = await reasoning.request_justification("v1", "s", "o", 1, reasoner="konclude")
    assert result["reasoning_available"] is False
    assert result["justifications"] == []
```

- [ ] **Step 2: Run it (fails)**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_reasoning_client_reasoner.py -q`
Expected: FAIL (`reasoner` kw not accepted / 422 raises).

- [ ] **Step 3: Thread reasoner into every client call**

In `ontoexplorer/clients/reasoning.py`:

`classify_v2` — add `reasoner: str = "whelk"` param; change the POST to
`json={"ntriples": ntriples, "version_id": version_id, "reasoner": reasoner}`;
change the poll GET URL to `_elk_url(f"/classify/{version_id}?reasoner={reasoner}")`.

`superclasses`/`subclasses` — add `reasoner: str = "whelk"`; append `reasoner` to the GET params (the code builds a query — add `"reasoner": reasoner` to the params dict, or append `&reasoner={reasoner}` to the URL, matching how `direct`/`cls` are passed).

`consistency` — add `reasoner: str = "whelk"`; GET `_elk_url(f"/classify/{version_id}/consistency?reasoner={reasoner}")`.

`request_justification` — add `reasoner: str = "whelk"`; include `"reasoner": reasoner` in the POST json; and handle the no-justify 422:

```python
        resp = await client.post(_elk_url(f"/classify/{version_id}/justification"),
                                 json={..., "reasoner": reasoner})
        if resp.status_code == 422:
            detail = resp.json().get("detail", "reasoner does not support justifications")
            return {"justifications": [], "reasoning_available": False, "reason": detail}
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        ...
```

(Preserve the existing 409/ReasoningNotReadyError handling and the return shape for the success path.)

- [ ] **Step 4: Run the client tests**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_reasoning_client_reasoner.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/clients/reasoning.py tests/test_reasoning_client_reasoner.py
git -c user.email=admin@example.org commit -m "feat(app): reasoning client threads reasoner; 422 -> reasoning_available:false

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Reason via the version's reasoner (task + term-inference endpoints)

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py:397-453` (`_run_reasoning`)
- Modify: `ontoexplorer/api/ontologies.py` — the term superclasses/subclasses/consistency endpoints that call `reasoning.superclasses/subclasses/consistency`
- Test: `tests/test_run_reasoning_uses_version_reasoner.py`

**Interfaces:**
- Consumes: `OntologyVersion.reasoner` (Task 1); the reasoner-threaded client calls (Task 4).
- Produces: `_run_reasoning` and every term-inference endpoint pass `version.reasoner` to the client.

- [ ] **Step 1: Write the test**

Create `tests/test_run_reasoning_uses_version_reasoner.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from ontoexplorer.modules.jobs import tasks


@pytest.mark.asyncio
async def test_run_reasoning_passes_version_reasoner(db_session, make_version):
    # make_version: repo fixture creating an OntologyVersion; set reasoner=rustdl.
    version = await make_version(reasoner="rustdl", status="ingested")
    with patch.object(tasks.reasoning_client, "classify_v2", new=AsyncMock(return_value={"inferred_count": 0})) as m:
        await tasks._run_reasoning(db_session, version.id)
    # classify_v2(graph, version_id, reasoner) — reasoner is the 3rd positional or kw
    _, kwargs = m.call_args
    passed = kwargs.get("reasoner") or (m.call_args[0][2] if len(m.call_args[0]) > 2 else None)
    assert passed == "rustdl"
```

If the repo lacks `make_version`/`db_session` fixtures, write a minimal one in this test module that inserts an `OntologyVersion` row (with an `Ontology` parent) into the test DB session the repo's conftest provides. Mirror an existing task test in `tests/` for the DB fixture pattern.

- [ ] **Step 2: Run it (fails)**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_run_reasoning_uses_version_reasoner.py -q`
Expected: FAIL (`classify_v2` called without reasoner / with default).

- [ ] **Step 3: Read the version's reasoner in `_run_reasoning`**

In `ontoexplorer/modules/jobs/tasks.py` `_run_reasoning`, after the version is loaded (it already fetches the version to get graph IRIs — reuse that object; if not, `SELECT` it), pass its reasoner:

```python
    await reasoning_client.classify_v2(asserted_graph, version_id, reasoner=version.reasoner)
```

(Ensure `version` — the `OntologyVersion` row — is in scope; the function already loads version data for the asserted-graph IRI. If it only has the id, add `version = await db.get(OntologyVersion, version_id)`.)

- [ ] **Step 4: Thread reasoner into the term-inference endpoints**

In `ontoexplorer/api/ontologies.py`, find every call to `reasoning.superclasses(...)`, `reasoning.subclasses(...)`, `reasoning.consistency(...)` (the term-detail / hierarchy endpoints). Each endpoint already loads the version (via `_get_version_or_404` or similar) — pass `reasoner=version.reasoner` to the client call. Where an endpoint has only `version_id`, load `version = await _get_version_or_404(db, ontology_id, version_id)` (already common in this file) and use `version.reasoner`.

- [ ] **Step 5: Run the test**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_run_reasoning_uses_version_reasoner.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py ontoexplorer/api/ontologies.py tests/test_run_reasoning_uses_version_reasoner.py
git -c user.email=admin@example.org commit -m "feat(app): classify + term inferences use the version's reasoner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Justification routes the version's reasoner + manchester passthrough

**Files:**
- Modify: `ontoexplorer/api/ontologies.py` — the synchronous `get_justification` GET endpoint (~line 2600-2668) and the async `compute_justification` path if it renders
- Test: `tests/test_justification_reasoner_routing.py`

**Interfaces:**
- Consumes: `OntologyVersion.reasoner`; `reasoning.request_justification(..., reasoner=)` (Task 4, returns `reasoning_available: False` for no-justify).
- Produces: justification response routes by the version's reasoner; `format == "manchester"` → response carries the raw axiom strings under `{"format": "manchester", "justifications": [[str, ...]]}`; `format == "ntriples"` → existing AST render (`justifications` as rendered axiom objects); no-justify reasoner → `{"justifications": [], "reasoning_available": False, "reason": ...}`.

- [ ] **Step 1: Write the test**

Create `tests/test_justification_reasoner_routing.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from ontoexplorer.main import app


@pytest.mark.asyncio
async def test_konclude_version_reports_no_explanations(make_version):
    version = await make_version(reasoner="konclude", status="ready")
    unavailable = {"justifications": [], "reasoning_available": False,
                   "reason": "reasoner 'konclude' does not support justifications"}
    with patch("ontoexplorer.api.ontologies.elk_request_justification",
               new=AsyncMock(return_value=unavailable)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get(f"/api/v1/ontologies/{version.ontology_id}/{version.id}"
                            f"/justification?sub=http://x/A&sup=http://x/C")
    assert r.status_code == 200
    assert r.json()["reasoning_available"] is False


@pytest.mark.asyncio
async def test_rustdl_manchester_passthrough(make_version):
    version = await make_version(reasoner="rustdl", status="ready")
    manchester = {"format": "manchester", "timed_out": False,
                  "justifications": [["SubClassOf(A B)", "SubClassOf(B C)"]]}
    with patch("ontoexplorer.api.ontologies.elk_request_justification",
               new=AsyncMock(return_value=manchester)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get(f"/api/v1/ontologies/{version.ontology_id}/{version.id}"
                            f"/justification?sub=http://x/A&sup=http://x/C")
    body = r.json()
    assert body["format"] == "manchester"
    assert body["justifications"] == [["SubClassOf(A B)", "SubClassOf(B C)"]]
```

- [ ] **Step 2: Run it (fails)**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_justification_reasoner_routing.py -q`
Expected: FAIL (reasoner not passed; manchester/unavailable not handled).

- [ ] **Step 3: Route reasoner + branch on format in `get_justification`**

In the synchronous `get_justification` GET endpoint in `ontoexplorer/api/ontologies.py`:
- Load the version (the endpoint has `ontology_id`, `version_id`): `version = await _get_version_or_404(db, ontology_id, version_id)`.
- Pass `reasoner=version.reasoner` into the `elk_request_justification(version_id, sub, sup, max_justifications, reasoner=version.reasoner)` call.
- Right after the call, before the existing timed-out/render logic, handle the two new cases:

```python
        if elk_result.get("reasoning_available") is False:
            return {"justifications": [], "reasoning_available": False,
                    "reason": elk_result.get("reason", "reasoner has no explanations")}
        if elk_result.get("format") == "manchester":
            return {"justifications": elk_result.get("justifications", []),
                    "format": "manchester", "timed_out": bool(elk_result.get("timed_out")),
                    "reasoning_available": True}
```

Leave the existing `timed_out` path and the N-Triples `_render_justification` path (the `format == "ntriples"` / default case) unchanged, and keep the Oxigraph BFS fallback.

- [ ] **Step 4: Run the test**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/test_justification_reasoner_routing.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Full app test sanity + integration smoke**

Run: `cd ~/code/ontoexplorer && .venv/bin/python -m pytest tests/ -q -k "reasoner or justification or submit"`
Expected: the SP2 tests pass; note any pre-existing unrelated failures.

Integration (best-effort, stack running): ingest a tiny ontology with `reasoner=rustdl`, confirm `SELECT reasoner FROM versions WHERE ...` is `rustdl`, classification completes, and a term's inferred superclasses return.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/ontologies.py tests/test_justification_reasoner_routing.py
git -c user.email=admin@example.org commit -m "feat(app): justification routes version reasoner; manchester passthrough + no-justify handling

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- reasoner column on versions + backfill → Task 1. ✓
- DEFAULT_REASONER config → Task 2. ✓
- submit accepts + validates reasoner (body+form, 422, fallback) → Task 3 + Task 2 helper. ✓
- reasoner persisted on version via pipeline → Task 3. ✓
- reason_ontology sends version's reasoner → Task 5. ✓
- client threads reasoner (classify + GETs + justification) → Task 4. ✓
- justification routes by reasoner, manchester passthrough, no-justify handling → Task 6 + Task 4. ✓
- immutable-after-ingest → enforced by absence of any update path (no task needed). ✓
- validation fallback when service down → Task 2 `available_reasoner_names`. ✓

**Placeholder scan:** No TBD/TODO. Two spots depend on the repo's existing test fixtures (`make_version`, `db_session`, async marking) — each step says to mirror the existing `tests/` pattern and names the fallback (write a minimal inline fixture). These are real, codebase-specific lookups, not placeholders.

**Type consistency:** `reasoner: str` (default `"whelk"`) is the consistent name/type across model, config, `IngestionRequest`, `ingest_ontology`, and all client functions. Client functions take `reasoner` as a trailing keyword to preserve existing positional call sites. `available_reasoner_names() -> set[str]` used the same way in Task 2 test and Task 3 submit. Justification response keys (`reasoning_available`, `format`, `justifications`) match between Task 4 (client) and Task 6 (endpoint).

**Known codebase-specific risk:** `submit_ontology` currently reads `await request.json()` once; Task 3 Step 3 explicitly calls out reading the body once and reusing it (double-read of the request stream would break). Flagged in-task.
