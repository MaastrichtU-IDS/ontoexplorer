# Ontology Version Diff & Changelog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute, store, and surface structured diffs between ontology versions with a History tab UI and optional LLM changelog narrative.

**Architecture:** A new `ontology_diffs` Postgres table stores pre-computed consecutive diffs (auto-triggered after each ingest) and cached on-demand arbitrary pair diffs. A `diff` FastAPI router exposes 5 endpoints. A React `HistoryTab` component renders the diff with operation toggles, entity/change-type filters, keyword search, and expandable per-entity detail including literal and axiom sub-sections.

**Tech Stack:** pyoxigraph (diff computation via quad iteration), SQLAlchemy/Postgres JSONB (storage), Celery (async compute task), FastAPI (REST), React/TypeScript + TanStack Query (frontend), Anthropic claude-haiku-4-5 (narrative generation)

---

## File Structure

**New files:**
- `alembic/versions/c2d3e4f5a6b7_ontology_diffs.py`
- `ontoexplorer/modules/diff/__init__.py`
- `ontoexplorer/modules/diff/compute.py`
- `ontoexplorer/api/diff.py`
- `tests/unit/test_diff_compute.py`
- `tests/integration/test_diff_api.py`
- `frontend/src/hooks/useDiff.ts`
- `frontend/src/components/HistoryTab.tsx`

**Modified files:**
- `ontoexplorer/models/db.py` — add `OntologyDiff` ORM model
- `ontoexplorer/modules/jobs/tasks.py` — add `compute_diff` Celery task
- `ontoexplorer/modules/ingestion/pipeline.py` — auto-trigger `compute_diff`
- `ontoexplorer/main.py` — register `diff_router`
- `ontoexplorer/config.py` — add `anthropic_api_key`
- `pyproject.toml` — add `anthropic` dependency
- `frontend/src/lib/api.ts` — add diff types + API methods
- `frontend/src/pages/OntologyPage.tsx` — add History tab + render HistoryTab

---

## Phase 1: Compute + Storage

### Task 1: DB Migration + ORM Model

**Files:**
- Create: `alembic/versions/c2d3e4f5a6b7_ontology_diffs.py`
- Modify: `ontoexplorer/models/db.py`

- [ ] **Step 1: Write the migration file**

Create `alembic/versions/c2d3e4f5a6b7_ontology_diffs.py`:

```python
"""add ontology_diffs table

Revision ID: c2d3e4f5a6b7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-16 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ontology_diffs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('ontology_id', sa.String(), nullable=False),
        sa.Column('version_from_id', sa.String(), nullable=False),
        sa.Column('version_to_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('summary', sa.JSON(), nullable=True),
        sa.Column('diff_data', sa.JSON(), nullable=True),
        sa.Column('narrative', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ontology_id'], ['ontologies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['version_from_id'], ['versions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['version_to_id'], ['versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_from_id', 'version_to_id'),
    )


def downgrade() -> None:
    op.drop_table('ontology_diffs')
```

- [ ] **Step 2: Add OntologyDiff ORM model to `ontoexplorer/models/db.py`**

Add after the `OntologyMetaProfile` class (at end of file):

```python
class OntologyDiff(Base):
    __tablename__ = "ontology_diffs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id", ondelete="CASCADE"))
    version_from_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    version_to_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | ready | failed
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diff_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Also add `UniqueConstraint` import — check that `UniqueConstraint` is already in the imports at the top of `models/db.py` (it's used by `OAuthAccount`). If not, add it to the SQLAlchemy imports line.

- [ ] **Step 3: Apply the migration**

```bash
docker compose exec api uv run alembic upgrade head
```

Expected output ends with: `Running upgrade e1f2a3b4c5d6 -> c2d3e4f5a6b7, add ontology_diffs table`

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/c2d3e4f5a6b7_ontology_diffs.py ontoexplorer/models/db.py
git commit -m "feat(diff): add ontology_diffs table and ORM model"
```

---

### Task 2: Diff Compute Module

**Files:**
- Create: `ontoexplorer/modules/diff/__init__.py`
- Create: `ontoexplorer/modules/diff/compute.py`
- Test: `tests/unit/test_diff_compute.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_diff_compute.py`:

```python
"""Unit tests for the ontology diff compute module.

Uses an in-memory pyoxigraph.Store — no mocking needed.
"""
import pyoxigraph as ox
import pytest

from ontoexplorer.modules.diff.compute import run_diff

OID = "test-ont"
FROM_VID = "v1"
TO_VID = "v2"

_OWL_CLASS = ox.NamedNode("http://www.w3.org/2002/07/owl#Class")
_RDF_TYPE  = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_RDFS_LBL  = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
_RDFS_SC   = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")


def _store(from_quads: list[tuple], to_quads: list[tuple]) -> ox.Store:
    """Build an in-memory store with two named graphs."""
    store = ox.Store()
    from_g = ox.NamedNode(f"urn:ontology:{OID}:{FROM_VID}")
    to_g   = ox.NamedNode(f"urn:ontology:{OID}:{TO_VID}")
    store.add_graph(from_g)
    store.add_graph(to_g)
    for s, p, o in from_quads:
        store.add(ox.Quad(s, p, o, from_g))
    for s, p, o in to_quads:
        store.add(ox.Quad(s, p, o, to_g))
    return store


def test_added_class():
    iri = ox.NamedNode("http://example.org/NewClass")
    s = _store(
        from_quads=[],
        to_quads=[
            (iri, _RDF_TYPE, _OWL_CLASS),
            (iri, _RDFS_LBL, ox.Literal("New Class")),
        ],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["added"] == 1
    assert summary["removed"] == 0
    assert summary["modified"] == 0
    assert diff_data["added"][0]["iri"] == str(iri.value)
    assert diff_data["added"][0]["entity_type"] == "class"
    assert diff_data["added"][0]["label"] == "New Class"


def test_removed_class():
    iri = ox.NamedNode("http://example.org/OldClass")
    s = _store(
        from_quads=[(iri, _RDF_TYPE, _OWL_CLASS)],
        to_quads=[],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["removed"] == 1
    assert diff_data["removed"][0]["iri"] == str(iri.value)


def test_label_change():
    iri = ox.NamedNode("http://example.org/ChangedClass")
    shared = [(iri, _RDF_TYPE, _OWL_CLASS)]
    s = _store(
        from_quads=shared + [(iri, _RDFS_LBL, ox.Literal("Old Label", language="en"))],
        to_quads=shared   + [(iri, _RDFS_LBL, ox.Literal("New Label", language="en"))],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 1
    assert summary["literal_changes"] == 1
    assert summary["axiom_changes"] == 0
    m = diff_data["modified"][0]
    assert m["iri"] == str(iri.value)
    lc = m["literal_changes"][0]
    assert lc["removed"] == "Old Label"
    assert lc["added"] == "New Label"
    assert lc["lang"] == "en"
    assert lc["predicate"] == str(_RDFS_LBL.value)


def test_axiom_change():
    iri        = ox.NamedNode("http://example.org/MovedClass")
    parent_old = ox.NamedNode("http://example.org/ParentOld")
    parent_new = ox.NamedNode("http://example.org/ParentNew")
    shared = [(iri, _RDF_TYPE, _OWL_CLASS)]
    s = _store(
        from_quads=shared + [(iri, _RDFS_SC, parent_old)],
        to_quads=shared   + [(iri, _RDFS_SC, parent_new)],
    )
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 1
    assert summary["axiom_changes"] == 1
    assert summary["literal_changes"] == 0
    m = diff_data["modified"][0]
    ops = {ac["op"] for ac in m["axiom_changes"]}
    assert ops == {"added", "removed"}


def test_unchanged_class_omitted():
    iri = ox.NamedNode("http://example.org/Stable")
    quads = [(iri, _RDF_TYPE, _OWL_CLASS), (iri, _RDFS_LBL, ox.Literal("Stable"))]
    s = _store(quads, quads)
    summary, diff_data = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["modified"] == 0
    assert summary["added"] == 0
    assert summary["removed"] == 0


def test_by_entity_type_counts():
    cls = ox.NamedNode("http://example.org/C")
    prop = ox.NamedNode("http://example.org/P")
    _OWL_OBJ_PROP = ox.NamedNode("http://www.w3.org/2002/07/owl#ObjectProperty")
    s = _store(
        from_quads=[],
        to_quads=[
            (cls,  _RDF_TYPE, _OWL_CLASS),
            (prop, _RDF_TYPE, _OWL_OBJ_PROP),
        ],
    )
    summary, _ = run_diff(s, OID, FROM_VID, TO_VID)
    assert summary["by_entity_type"]["class"]["added"] == 1
    assert summary["by_entity_type"]["object_property"]["added"] == 1
```

- [ ] **Step 2: Run tests — confirm failure**

```bash
uv run pytest tests/unit/test_diff_compute.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.diff'`

- [ ] **Step 3: Create the module package**

Create `ontoexplorer/modules/diff/__init__.py` (empty file).

- [ ] **Step 4: Implement `compute.py`**

Create `ontoexplorer/modules/diff/compute.py`:

```python
"""Compute term-level diff between two ontology versions using Oxigraph quad iteration."""
import pyoxigraph as ox

from ontoexplorer.clients.oxigraph import graph_iri

_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

_ENTITY_TYPES: dict[str, str] = {
    "class":               "http://www.w3.org/2002/07/owl#Class",
    "object_property":     "http://www.w3.org/2002/07/owl#ObjectProperty",
    "data_property":       "http://www.w3.org/2002/07/owl#DatatypeProperty",
    "annotation_property": "http://www.w3.org/2002/07/owl#AnnotationProperty",
    "individual":          "http://www.w3.org/2002/07/owl#NamedIndividual",
}


def _collect_iris(store: ox.Store, graph: ox.NamedNode, type_iri: str) -> set[str]:
    rdf_type = ox.NamedNode(_RDF_TYPE)
    type_node = ox.NamedNode(type_iri)
    return {
        q.subject.value
        for q in store.quads_for_pattern(None, rdf_type, type_node, graph)
        if isinstance(q.subject, ox.NamedNode)
    }


def _first_label(store: ox.Store, graph: ox.NamedNode, iri: str) -> str | None:
    label_node = ox.NamedNode(_RDFS_LABEL)
    for q in store.quads_for_pattern(ox.NamedNode(iri), label_node, None, graph):
        if isinstance(q.object, ox.Literal):
            return q.object.value
    return None


def _literal_triples(
    store: ox.Store, graph: ox.NamedNode, iri: str
) -> set[tuple[str, str | None, str]]:
    """Return (predicate_iri, lang_or_none, value) for all literal-valued triples."""
    return {
        (q.predicate.value, q.object.language, q.object.value)
        for q in store.quads_for_pattern(ox.NamedNode(iri), None, None, graph)
        if isinstance(q.object, ox.Literal)
    }


def _structural_triples(
    store: ox.Store, graph: ox.NamedNode, iri: str
) -> set[tuple[str, str]]:
    """Return (predicate_iri, object_value) for all URI/blank-node-valued triples."""
    return {
        (q.predicate.value, q.object.value)
        for q in store.quads_for_pattern(ox.NamedNode(iri), None, None, graph)
        if isinstance(q.object, (ox.NamedNode, ox.BlankNode))
    }


def run_diff(
    store: ox.Store,
    ontology_id: str,
    from_vid: str,
    to_vid: str,
) -> tuple[dict, dict]:
    """
    Compute term-level diff between two named graphs in `store`.

    Returns (summary, diff_data) matching the spec shapes defined in
    docs/superpowers/specs/2026-05-16-ontology-version-diff-design.md.
    Both graphs must already exist in the store.
    """
    from_graph = ox.NamedNode(graph_iri(ontology_id, from_vid))
    to_graph   = ox.NamedNode(graph_iri(ontology_id, to_vid))

    added_list: list[dict] = []
    removed_list: list[dict] = []
    modified_list: list[dict] = []

    for entity_type, type_iri in _ENTITY_TYPES.items():
        from_iris = _collect_iris(store, from_graph, type_iri)
        to_iris   = _collect_iris(store, to_graph, type_iri)

        for iri in to_iris - from_iris:
            added_list.append({
                "iri": iri,
                "label": _first_label(store, to_graph, iri),
                "entity_type": entity_type,
            })

        for iri in from_iris - to_iris:
            removed_list.append({
                "iri": iri,
                "label": _first_label(store, from_graph, iri),
                "entity_type": entity_type,
            })

        for iri in from_iris & to_iris:
            from_lits   = _literal_triples(store, from_graph, iri)
            to_lits     = _literal_triples(store, to_graph, iri)
            from_struct = _structural_triples(store, from_graph, iri)
            to_struct   = _structural_triples(store, to_graph, iri)

            if from_lits == to_lits and from_struct == to_struct:
                continue

            # Pair removed/added literals by (predicate, lang)
            from_lits_map = {(p, lang): v for p, lang, v in from_lits - to_lits}
            to_lits_map   = {(p, lang): v for p, lang, v in to_lits   - from_lits}
            literal_changes = [
                {
                    "predicate": pred,
                    "lang": lang,
                    "removed": from_lits_map.get((pred, lang)),
                    "added":   to_lits_map.get((pred, lang)),
                }
                for pred, lang in sorted(set(from_lits_map) | set(to_lits_map))
            ]

            axiom_changes = [
                {"op": "removed", "axiom": f"<{p}> <{o}>"}
                for p, o in sorted(from_struct - to_struct)
            ] + [
                {"op": "added", "axiom": f"<{p}> <{o}>"}
                for p, o in sorted(to_struct - from_struct)
            ]

            label = _first_label(store, to_graph, iri) or _first_label(store, from_graph, iri)
            modified_list.append({
                "iri": iri,
                "label": label,
                "entity_type": entity_type,
                "literal_changes": literal_changes,
                "axiom_changes": axiom_changes,
            })

    by_type = {
        et: {
            "added":    sum(1 for e in added_list   if e["entity_type"] == et),
            "removed":  sum(1 for e in removed_list if e["entity_type"] == et),
            "modified": sum(1 for e in modified_list if e["entity_type"] == et),
        }
        for et in _ENTITY_TYPES
    }
    summary = {
        "added":           len(added_list),
        "removed":         len(removed_list),
        "modified":        len(modified_list),
        "literal_changes": sum(1 for m in modified_list if m["literal_changes"]),
        "axiom_changes":   sum(1 for m in modified_list if m["axiom_changes"]),
        "by_entity_type":  by_type,
    }
    diff_data = {
        "added":    added_list,
        "removed":  removed_list,
        "modified": modified_list,
    }
    return summary, diff_data
```

- [ ] **Step 5: Run tests — confirm pass**

```bash
uv run pytest tests/unit/test_diff_compute.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/modules/diff/ tests/unit/test_diff_compute.py
git commit -m "feat(diff): diff compute module with unit tests"
```

---

### Task 3: Celery Task + Auto-Trigger

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`
- Modify: `ontoexplorer/modules/ingestion/pipeline.py`

- [ ] **Step 1: Add `compute_diff` Celery task to `tasks.py`**

Add after the `detect_meta_profile` task (around line 106), before `ingest_ontology`:

```python
@celery_app.task(name="ontoexplorer.compute_diff")
def compute_diff(version_from_id: str, version_to_id: str, ontology_id: str) -> dict:
    """Compute diff between two ontology versions and store results in the DB."""
    import asyncio
    from ontoexplorer.database import make_celery_db_session

    async def _run() -> None:
        from sqlalchemy import select
        from ontoexplorer.models.db import OntologyDiff
        from ontoexplorer.modules.diff.compute import run_diff as _run_diff
        from ontoexplorer.clients.oxigraph import get_store

        async with make_celery_db_session()() as db:
            existing = await db.scalar(
                select(OntologyDiff).where(
                    OntologyDiff.version_from_id == version_from_id,
                    OntologyDiff.version_to_id == version_to_id,
                )
            )
            if existing and existing.status == "ready":
                return

            if existing is None:
                diff_row = OntologyDiff(
                    ontology_id=ontology_id,
                    version_from_id=version_from_id,
                    version_to_id=version_to_id,
                    status="pending",
                )
                db.add(diff_row)
                await db.commit()
                await db.refresh(diff_row)
            else:
                diff_row = existing

            try:
                store = get_store()
                summary, diff_data = await asyncio.to_thread(
                    _run_diff, store, ontology_id, version_from_id, version_to_id
                )
                diff_row.summary = summary
                diff_row.diff_data = diff_data
                diff_row.status = "ready"
            except Exception as exc:
                diff_row.status = "failed"
                log.error("compute_diff_failed", from_vid=version_from_id,
                          to_vid=version_to_id, error=str(exc))
            await db.commit()

    try:
        asyncio.run(_run())
        log.info("compute_diff_done", from_vid=version_from_id, to_vid=version_to_id)
    except Exception as exc:
        log.error("compute_diff_task_error", error=str(exc))
    return {"status": "done"}
```

- [ ] **Step 2: Auto-trigger in `pipeline.py` after Step 9**

In `ontoexplorer/modules/ingestion/pipeline.py`, after line 230 (after `detect_meta_profile.delay(...)`), add:

```python
    # ── Step 10: Queue diff computation against previous version ─────────────
    prev_result = await db.execute(
        select(OntologyVersion)
        .where(
            OntologyVersion.ontology_id == ontology_id,
            OntologyVersion.id != version_id,
            OntologyVersion.status != "deprecated",
        )
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )
    prev_version = prev_result.scalar_one_or_none()
    if prev_version:
        from ontoexplorer.modules.jobs.tasks import compute_diff as _compute_diff_task
        _compute_diff_task.delay(str(prev_version.id), version_id, ontology_id)
```

Note: `select` and `OntologyVersion` are already imported in `pipeline.py`. Verify with `grep "from sqlalchemy\|OntologyVersion" ontoexplorer/modules/ingestion/pipeline.py`.

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
uv run pytest tests/ -v -k "not test_diff" 2>&1 | tail -20
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py ontoexplorer/modules/ingestion/pipeline.py
git commit -m "feat(diff): compute_diff Celery task with auto-trigger after ingest"
```

---

### Task 4: API Diff Router

**Files:**
- Create: `ontoexplorer/api/diff.py`
- Modify: `ontoexplorer/main.py`
- Test: `tests/integration/test_diff_api.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/integration/test_diff_api.py`:

```python
"""Integration tests for the ontology diff API endpoints."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.anyio
async def test_get_consecutive_diff_no_previous_version(client, user_and_key):
    """Returns 404 when the version has no predecessor."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    # Submit one ontology version
    from tests.integration.test_ontologies import _MINIMAL_TURTLE
    mock_store = MagicMock(return_value="key.ttl")
    mock_load = MagicMock(return_value=2)
    mock_tasks = MagicMock()
    mock_tasks.delay = MagicMock()

    with (
        patch("ontoexplorer.modules.storage.minio_client.store_ontology", mock_store),
        patch("ontoexplorer.clients.oxigraph.load_graph", mock_load),
        patch("ontoexplorer.modules.ingestion.pipeline.reason_ontology", mock_tasks),
        patch("ontoexplorer.modules.ingestion.pipeline.detect_profile", mock_tasks),
        patch("ontoexplorer.modules.ingestion.pipeline.detect_meta_profile", mock_tasks),
        patch("ontoexplorer.modules.ingestion.pipeline._write_fair_metadata",
              new=pytest.importorskip("unittest.mock").AsyncMock()),
    ):
        resp = await client.post(
            "/api/v1/ontologies",
            content=_MINIMAL_TURTLE,
            headers={**auth, "Content-Type": "text/turtle"},
        )

    assert resp.status_code == 200
    body = resp.json()
    oid = body.get("ontology_id")
    vid = body.get("version_id")
    assert oid and vid

    # First (only) version has no predecessor — expect 404
    r = await client.get(f"/api/v1/ontologies/{oid}/{vid}/diff", headers=auth)
    assert r.status_code == 404
    assert "previous" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_arbitrary_diff_same_version_rejected(client, user_and_key):
    """Returns 400 when from and to are the same version ID."""
    r = await client.get(
        "/api/v1/ontologies/fake-oid/diff",
        params={"from": "same-vid", "to": "same-vid"},
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_get_arbitrary_diff_unknown_version(client, user_and_key):
    """Returns 404 when either version does not exist."""
    r = await client.get(
        "/api/v1/ontologies/nonexistent/diff",
        params={"from": "v1", "to": "v2"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests — confirm failure**

```bash
uv run pytest tests/integration/test_diff_api.py -v 2>&1 | head -20
```

Expected: tests fail with 404 (routes don't exist yet) or import errors.

- [ ] **Step 3: Create `ontoexplorer/api/diff.py`**

```python
"""Ontology version diff REST API."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.logging_config import get_logger
from ontoexplorer.models.db import OntologyDiff, OntologyVersion

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/ontologies", tags=["diff"])


async def _get_version_or_404(
    db: AsyncSession, ontology_id: str, version_id: str
) -> OntologyVersion:
    result = await db.execute(
        select(OntologyVersion).where(
            OntologyVersion.id == version_id,
            OntologyVersion.ontology_id == ontology_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _diff_response(diff: OntologyDiff) -> dict:
    return {
        "status": diff.status,
        "summary": diff.summary,
        "diff_data": diff.diff_data,
        "narrative": diff.narrative,
    }


async def _get_or_enqueue(
    db: AsyncSession,
    ontology_id: str,
    from_vid: str,
    to_vid: str,
) -> dict | JSONResponse:
    existing = await db.scalar(
        select(OntologyDiff).where(
            OntologyDiff.version_from_id == from_vid,
            OntologyDiff.version_to_id == to_vid,
        )
    )
    if existing:
        if existing.status == "ready":
            return _diff_response(existing)
        return JSONResponse(status_code=202, content={"status": existing.status})

    diff_row = OntologyDiff(
        ontology_id=ontology_id,
        version_from_id=from_vid,
        version_to_id=to_vid,
        status="pending",
    )
    db.add(diff_row)
    await db.commit()

    from ontoexplorer.modules.jobs.tasks import compute_diff as _compute_diff_task
    _compute_diff_task.delay(from_vid, to_vid, ontology_id)
    return JSONResponse(status_code=202, content={"status": "pending"})


@router.get("/{ontology_id}/{version_id}/diff",
            summary="Diff between this version and its predecessor")
async def get_consecutive_diff(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    prev = await db.scalar(
        select(OntologyVersion)
        .where(
            OntologyVersion.ontology_id == ontology_id,
            OntologyVersion.id != version_id,
            OntologyVersion.status != "deprecated",
        )
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )
    if not prev:
        raise HTTPException(status_code=404, detail="No previous version found")
    return await _get_or_enqueue(db, ontology_id, str(prev.id), version_id)


@router.get("/{ontology_id}/diff", summary="Diff between any two versions of an ontology")
async def get_arbitrary_diff(
    ontology_id: str,
    from_vid: str = Query(..., alias="from"),
    to_vid: str = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
):
    if from_vid == to_vid:
        raise HTTPException(status_code=400, detail="from and to must be different versions")
    await _get_version_or_404(db, ontology_id, from_vid)
    await _get_version_or_404(db, ontology_id, to_vid)
    return await _get_or_enqueue(db, ontology_id, from_vid, to_vid)


@router.post("/{ontology_id}/diff/compute",
             summary="Trigger async diff computation for an arbitrary version pair")
async def trigger_diff_compute(
    ontology_id: str,
    from_vid: str = Query(..., alias="from"),
    to_vid: str = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
):
    if from_vid == to_vid:
        raise HTTPException(status_code=400, detail="from and to must be different versions")
    await _get_version_or_404(db, ontology_id, from_vid)
    await _get_version_or_404(db, ontology_id, to_vid)
    return await _get_or_enqueue(db, ontology_id, from_vid, to_vid)
```

- [ ] **Step 4: Register `diff_router` in `ontoexplorer/main.py`**

Add the import after the `meta_profile_router` import line:

```python
from ontoexplorer.api.diff import router as diff_router
```

Add the registration before `app.include_router(ontologies_router)`:

```python
    # diff_router before ontologies_router: /{id}/diff static segment must
    # take precedence over ontologies_router's /{id}/{version_id} parameter
    app.include_router(diff_router)
```

- [ ] **Step 5: Run integration tests — confirm pass**

```bash
uv run pytest tests/integration/test_diff_api.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/api/diff.py ontoexplorer/main.py tests/integration/test_diff_api.py
git commit -m "feat(diff): REST endpoints for consecutive and arbitrary version diffs"
```

---

## Phase 2: LLM Narrative Endpoint

### Task 5: LLM Narrative Backend

**Files:**
- Modify: `pyproject.toml`
- Modify: `ontoexplorer/config.py`
- Modify: `ontoexplorer/api/diff.py`

- [ ] **Step 1: Add `anthropic` dependency to `pyproject.toml`**

In `pyproject.toml`, add `"anthropic"` to the `dependencies` list (after `"redis>=6.0"`):

```toml
    "redis>=6.0",
    "anthropic",
```

- [ ] **Step 2: Install the dependency**

```bash
uv sync
```

Expected: resolves and installs `anthropic` SDK.

- [ ] **Step 3: Add `anthropic_api_key` to `ontoexplorer/config.py`**

Find the `Settings` class in `ontoexplorer/config.py` and add the field:

```python
    anthropic_api_key: str = ""
```

Add it alongside the other external service settings (ELK, MinIO, etc.).

- [ ] **Step 4: Add the narrative endpoint to `ontoexplorer/api/diff.py`**

Add after the `trigger_diff_compute` endpoint:

```python
@router.post("/{ontology_id}/{version_id}/diff/narrative",
             summary="Generate or retrieve LLM changelog narrative for consecutive diff")
async def get_or_generate_narrative(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)

    prev = await db.scalar(
        select(OntologyVersion)
        .where(
            OntologyVersion.ontology_id == ontology_id,
            OntologyVersion.id != version_id,
            OntologyVersion.status != "deprecated",
        )
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )
    if not prev:
        raise HTTPException(status_code=404, detail="No previous version found")

    diff_row = await db.scalar(
        select(OntologyDiff).where(
            OntologyDiff.version_from_id == str(prev.id),
            OntologyDiff.version_to_id == version_id,
        )
    )
    if not diff_row or diff_row.status != "ready":
        raise HTTPException(status_code=409, detail="Diff not yet computed")

    if diff_row.narrative:
        return {"narrative": diff_row.narrative}

    import anthropic
    from ontoexplorer.config import get_settings
    settings = get_settings()

    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    summary = diff_row.summary or {}
    by_type = summary.get("by_entity_type", {})
    type_breakdown = ", ".join(
        f"{et.replace('_', ' ')}: +{v['added']} -{v['removed']} ~{v['modified']}"
        for et, v in by_type.items()
        if v["added"] or v["removed"] or v["modified"]
    )

    prompt = (
        "Summarise the changes between two versions of an ontology in 2-3 sentences "
        "suitable for release notes. Be specific about counts and entity types. "
        "Do not start with 'This version' or 'In this version'.\n\n"
        f"Changes:\n"
        f"- Added: {summary.get('added', 0)} entities\n"
        f"- Removed: {summary.get('removed', 0)} entities\n"
        f"- Modified: {summary.get('modified', 0)} entities "
        f"({summary.get('literal_changes', 0)} with literal changes, "
        f"{summary.get('axiom_changes', 0)} with axiom changes)\n"
        f"- By type: {type_breakdown}"
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    narrative = message.content[0].text

    diff_row.narrative = narrative
    await db.commit()
    return {"narrative": narrative}
```

- [ ] **Step 5: Run full test suite to confirm nothing broke**

```bash
uv run pytest tests/ -v 2>&1 | tail -10
```

Expected: all tests pass (the narrative endpoint isn't tested by the integration tests — the Anthropic call would require a live API key, which is intentionally skipped).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml ontoexplorer/config.py ontoexplorer/api/diff.py
git commit -m "feat(diff): LLM narrative endpoint using claude-haiku"
```

---

## Phase 3: Frontend

### Task 6: Frontend API Types + Client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add diff types to `api.ts`**

After the existing `OntologyLanguage` interface (or near other types), add:

```typescript
export interface DiffLiteralChange {
  predicate: string
  lang: string | null
  removed: string | null
  added: string | null
}

export interface DiffAxiomChange {
  op: 'added' | 'removed'
  axiom: string
}

export type DiffEntityType =
  | 'class'
  | 'object_property'
  | 'data_property'
  | 'annotation_property'
  | 'individual'

export interface DiffEntity {
  iri: string
  label: string | null
  entity_type: DiffEntityType
  literal_changes?: DiffLiteralChange[]
  axiom_changes?: DiffAxiomChange[]
}

export interface DiffSummary {
  added: number
  removed: number
  modified: number
  literal_changes: number
  axiom_changes: number
  by_entity_type: Record<DiffEntityType, { added: number; removed: number; modified: number }>
}

export interface OntologyDiff {
  status: 'pending' | 'ready' | 'failed'
  summary?: DiffSummary
  diff_data?: {
    added: DiffEntity[]
    removed: DiffEntity[]
    modified: DiffEntity[]
  }
  narrative?: string | null
}
```

- [ ] **Step 2: Add API methods to the `api.ontologies` object in `api.ts`**

Inside the `ontologies` object (alongside existing methods like `terms`, `ancestors`, etc.), add:

```typescript
    diff: (ontologyId: string, versionId: string) =>
      request<OntologyDiff>(`/ontologies/${ontologyId}/${versionId}/diff`),
    diffArbitrary: (ontologyId: string, fromVid: string, toVid: string) =>
      request<OntologyDiff>(
        `/ontologies/${ontologyId}/diff?from=${encodeURIComponent(fromVid)}&to=${encodeURIComponent(toVid)}`
      ),
    generateNarrative: (ontologyId: string, versionId: string) =>
      request<{ narrative: string }>(
        `/ontologies/${ontologyId}/${versionId}/diff/narrative`,
        { method: 'POST' }
      ),
```

- [ ] **Step 3: Build the frontend to confirm no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | tail -15
```

Expected: build succeeds with no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(diff): frontend API types and client methods"
```

---

### Task 7: useDiff Hook

**Files:**
- Create: `frontend/src/hooks/useDiff.ts`

- [ ] **Step 1: Create `frontend/src/hooks/useDiff.ts`**

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyDiff } from '../lib/api'

function isPending(data: OntologyDiff | undefined): boolean {
  return data?.status === 'pending'
}

export function useConsecutiveDiff(
  ontologyId: string | null,
  versionId: string | null,
) {
  return useQuery({
    queryKey: ['diff', ontologyId, versionId],
    queryFn: () => api.ontologies.diff(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    refetchInterval: (query) => isPending(query.state.data) ? 3000 : false,
    staleTime: 60_000,
  })
}

export function useArbitraryDiff(
  ontologyId: string | null,
  fromVid: string | null,
  toVid: string | null,
) {
  return useQuery({
    queryKey: ['diff', ontologyId, fromVid, toVid],
    queryFn: () => api.ontologies.diffArbitrary(ontologyId!, fromVid!, toVid!),
    enabled: !!ontologyId && !!fromVid && !!toVid && fromVid !== toVid,
    refetchInterval: (query) => isPending(query.state.data) ? 3000 : false,
    staleTime: 60_000,
  })
}

export function useGenerateNarrative(ontologyId: string, versionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.ontologies.generateNarrative(ontologyId, versionId),
    onSuccess: () => {
      // Invalidate the consecutive diff so the narrative appears
      queryClient.invalidateQueries({ queryKey: ['diff', ontologyId, versionId] })
    },
  })
}
```

- [ ] **Step 2: Build to confirm no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useDiff.ts
git commit -m "feat(diff): useDiff, useArbitraryDiff, useGenerateNarrative hooks"
```

---

### Task 8: HistoryTab Component

**Files:**
- Create: `frontend/src/components/HistoryTab.tsx`

- [ ] **Step 1: Create `frontend/src/components/HistoryTab.tsx`**

```typescript
import { useState, useMemo } from 'react'
import { OntologyVersion, OntologyDiff, DiffEntity, DiffEntityType } from '../lib/api'
import { useArbitraryDiff, useGenerateNarrative } from '../hooks/useDiff'

type Op = 'added' | 'removed' | 'modified'
type ChangeFilter = 'all' | 'literal' | 'axiom'

interface Props {
  ontologyId: string
  currentVersionId: string
  versions: OntologyVersion[]
}

const ENTITY_TYPE_LABELS: Record<DiffEntityType, string> = {
  class: 'Class',
  object_property: 'Obj. property',
  data_property: 'Data property',
  annotation_property: 'Ann. property',
  individual: 'Individual',
}

function highlight(text: string, query: string): string {
  if (!query) return text
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return text
  return text.slice(0, idx) + '**' + text.slice(idx, idx + query.length) + '**' + text.slice(idx + query.length)
}

function HighlightedText({ text, query, color }: { text: string; query: string; color?: string }) {
  if (!query) return <span style={{ color }}>{text}</span>
  const lower = text.toLowerCase()
  const lowerQ = query.toLowerCase()
  const idx = lower.indexOf(lowerQ)
  if (idx === -1) return <span style={{ color }}>{text}</span>
  return (
    <span style={{ color }}>
      {text.slice(0, idx)}
      <mark style={{ background: 'rgba(247,185,62,0.25)', color: 'inherit', borderRadius: 2 }}>
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </span>
  )
}

function EntityRow({
  entity, op, search, expanded, onToggle,
}: {
  entity: DiffEntity & { op: Op }
  op: Op
  search: string
  expanded: boolean
  onToggle: () => void
}) {
  const opColor = op === 'added' ? 'var(--green, #3fb950)'
    : op === 'removed' ? 'var(--red, #f85149)' : 'var(--orange, #f0883e)'
  const opBorder = opColor
  const label = entity.label ?? entity.iri.split(/[#/]/).pop() ?? entity.iri

  const hasLiteral = (entity.literal_changes?.length ?? 0) > 0
  const hasAxiom   = (entity.axiom_changes?.length ?? 0) > 0

  return (
    <div style={{ border: `1px solid ${opBorder}`, borderRadius: 5, overflow: 'hidden', fontSize: 11, fontFamily: 'monospace' }}>
      <div
        onClick={op === 'modified' ? onToggle : undefined}
        style={{
          padding: '7px 12px', display: 'flex', alignItems: 'center', gap: 6,
          cursor: op === 'modified' ? 'pointer' : 'default',
          borderBottom: expanded ? '1px solid var(--border, #30363d)' : 'none',
          background: 'var(--bg-secondary, #161b22)',
        }}
      >
        {op === 'modified' && (
          <span style={{ color: opColor, fontSize: 10 }}>{expanded ? '▾' : '▸'}</span>
        )}
        <span style={{ color: opColor, fontWeight: 'bold', width: 12 }}>
          {op === 'added' ? '+' : op === 'removed' ? '−' : '~'}
        </span>
        <span style={{ color: 'var(--text, #e6edf3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
          <HighlightedText text={label} query={search} />
        </span>
        <span style={{ color: 'var(--text-dim, #8b949e)', fontSize: 10, flexShrink: 0 }}>
          {ENTITY_TYPE_LABELS[entity.entity_type]}
        </span>
        {op === 'modified' && (
          <span style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            {hasLiteral && (
              <span style={{ border: '1px solid #a371f7', borderRadius: 3, padding: '1px 6px', fontSize: 9, color: '#a371f7' }}>literal</span>
            )}
            {hasAxiom && (
              <span style={{ border: '1px solid #58a6ff', borderRadius: 3, padding: '1px 6px', fontSize: 9, color: '#58a6ff' }}>axiom</span>
            )}
          </span>
        )}
      </div>

      {expanded && op === 'modified' && (
        <div style={{ padding: '8px 16px', display: 'flex', flexDirection: 'column', gap: 8, background: 'var(--bg, #0d1117)' }}>
          {hasLiteral && (
            <div>
              <div style={{ color: '#a371f7', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Literal changes</div>
              {entity.literal_changes!.map((lc, i) => (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 4, marginBottom: 3 }}>
                  <span style={{ color: 'var(--text-dim, #8b949e)', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {lc.predicate.split(/[#/]/).pop()}{lc.lang ? ` [${lc.lang}]` : ''}
                  </span>
                  <div>
                    {lc.removed != null && (
                      <div>
                        <HighlightedText text={`− "${lc.removed}"`} query={search} color="#f85149" />
                      </div>
                    )}
                    {lc.added != null && (
                      <div>
                        <HighlightedText text={`+ "${lc.added}"`} query={search} color="#3fb950" />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {hasAxiom && (
            <div>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Axiom changes</div>
              {entity.axiom_changes!.map((ac, i) => (
                <div key={i} style={{ color: ac.op === 'added' ? '#3fb950' : '#f85149', fontSize: 10 }}>
                  <HighlightedText
                    text={`${ac.op === 'added' ? '+' : '−'} ${ac.axiom}`}
                    query={search}
                    color={ac.op === 'added' ? '#3fb950' : '#f85149'}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function HistoryTab({ ontologyId, currentVersionId, versions }: Props) {
  const sorted = [...versions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )
  const currentIdx = sorted.findIndex(v => v.id === currentVersionId)
  const defaultFrom = currentIdx < sorted.length - 1 ? sorted[currentIdx + 1].id : ''

  const [fromVid, setFromVid] = useState(defaultFrom)
  const [toVid, setToVid]     = useState(currentVersionId)
  const [ops, setOps]         = useState<Set<Op>>(new Set(['added', 'removed', 'modified']))
  const [typeFilter, setTypeFilter] = useState<DiffEntityType | 'all'>('all')
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>('all')
  const [search, setSearch]   = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const { data: diff, isLoading } = useArbitraryDiff(
    ontologyId, fromVid || null, toVid || null
  )
  const { mutate: generateNarrative, isPending: generatingNarrative } =
    useGenerateNarrative(ontologyId, toVid)

  const toggleOp = (op: Op) => {
    setOps(prev => {
      const next = new Set(prev)
      next.has(op) ? next.delete(op) : next.add(op)
      return next
    })
  }

  const allEntities: (DiffEntity & { op: Op })[] = useMemo(() => {
    if (!diff?.diff_data) return []
    const result: (DiffEntity & { op: Op })[] = []
    if (ops.has('added'))    diff.diff_data.added.forEach(e => result.push({ ...e, op: 'added' }))
    if (ops.has('removed'))  diff.diff_data.removed.forEach(e => result.push({ ...e, op: 'removed' }))
    if (ops.has('modified')) diff.diff_data.modified.forEach(e => result.push({ ...e, op: 'modified' }))
    return result
  }, [diff, ops])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allEntities.filter(e => {
      if (typeFilter !== 'all' && e.entity_type !== typeFilter) return false
      if (changeFilter === 'literal' && e.op === 'modified' && !e.literal_changes?.length) return false
      if (changeFilter === 'axiom'   && e.op === 'modified' && !e.axiom_changes?.length)   return false
      if (changeFilter !== 'all' && e.op !== 'modified') return false
      if (!q) return true
      const label = (e.label ?? '').toLowerCase()
      const iri   = e.iri.toLowerCase()
      const inLit = e.literal_changes?.some(lc =>
        lc.removed?.toLowerCase().includes(q) || lc.added?.toLowerCase().includes(q)
      )
      const inAxiom = e.axiom_changes?.some(ac => ac.axiom.toLowerCase().includes(q))
      return label.includes(q) || iri.includes(q) || !!inLit || !!inAxiom
    })
  }, [allEntities, typeFilter, changeFilter, search])

  if (!fromVid) {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
        This is the only version — no diff available.
      </div>
    )
  }

  const summary = diff?.diff_data
    ? {
        added:    diff.diff_data.added.length,
        removed:  diff.diff_data.removed.length,
        modified: diff.diff_data.modified.length,
      }
    : null

  return (
    <div style={{ padding: 14, fontFamily: 'monospace', fontSize: 11, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Version picker */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: 'var(--text-dim)' }}>Compare</span>
        <select
          value={fromVid}
          onChange={e => setFromVid(e.target.value)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          {sorted.filter(v => v.id !== toVid).map(v => (
            <option key={v.id} value={v.id}>{v.version_iri ?? v.id.slice(0, 8)}</option>
          ))}
        </select>
        <span style={{ color: 'var(--text-dim)' }}>→</span>
        <select
          value={toVid}
          onChange={e => setToVid(e.target.value)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          {sorted.filter(v => v.id !== fromVid).map(v => (
            <option key={v.id} value={v.id}>
              {v.version_iri ?? v.id.slice(0, 8)}{v.id === currentVersionId ? ' (current)' : ''}
            </option>
          ))}
        </select>
        <button
          onClick={() => generateNarrative()}
          disabled={!diff || diff.status !== 'ready' || generatingNarrative}
          style={{
            marginLeft: 'auto', background: '#238636', color: '#fff', border: 'none',
            borderRadius: 4, padding: '3px 10px', cursor: 'pointer', fontSize: 10,
            opacity: (!diff || diff.status !== 'ready') ? 0.5 : 1,
          }}
        >
          {generatingNarrative ? 'Generating…' : 'Generate changelog'}
        </button>
      </div>

      {/* Loading / pending states */}
      {isLoading && (
        <div style={{ color: 'var(--text-dim)' }}>Loading diff…</div>
      )}
      {diff?.status === 'pending' && (
        <div style={{ color: 'var(--text-dim)' }}>Computing diff… (polling every 3 s)</div>
      )}
      {diff?.status === 'failed' && (
        <div style={{ color: '#f85149' }}>Diff computation failed.</div>
      )}

      {diff?.status === 'ready' && summary && (<>
        {/* Operation toggles */}
        <div style={{ display: 'flex', gap: 8 }}>
          {(['added', 'removed', 'modified'] as Op[]).map(op => {
            const count = op === 'added' ? summary.added : op === 'removed' ? summary.removed : summary.modified
            const color = op === 'added' ? '#3fb950' : op === 'removed' ? '#f85149' : '#f0883e'
            const active = ops.has(op)
            return (
              <button
                key={op}
                onClick={() => toggleOp(op)}
                style={{
                  background: active ? `${color}22` : 'var(--bg-secondary)',
                  border: `1px solid ${active ? color : 'var(--border)'}`,
                  borderRadius: 6, padding: '6px 14px', cursor: 'pointer', minWidth: 70,
                  opacity: active ? 1 : 0.4,
                }}
              >
                <div style={{ color, fontSize: 15, fontWeight: 'bold' }}>{count}</div>
                <div style={{ color, fontSize: 10 }}>{op === 'added' ? '+ added' : op === 'removed' ? '− removed' : '~ modified'}</div>
              </button>
            )
          })}
        </div>

        {/* Entity type filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-dim)', marginRight: 4 }}>Type:</span>
          {(['all', 'class', 'object_property', 'data_property', 'annotation_property', 'individual'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              style={{
                background: typeFilter === t ? 'var(--accent, #1f6feb)' : 'var(--bg-secondary)',
                color: typeFilter === t ? '#fff' : 'var(--text-dim)',
                border: `1px solid ${typeFilter === t ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 10, padding: '2px 10px', cursor: 'pointer', fontSize: 10,
              }}
            >
              {t === 'all' ? 'All' : ENTITY_TYPE_LABELS[t as DiffEntityType]}
            </button>
          ))}
        </div>

        {/* Change type filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ color: 'var(--text-dim)', marginRight: 4 }}>Changes:</span>
          {(['all', 'literal', 'axiom'] as ChangeFilter[]).map(cf => (
            <button
              key={cf}
              onClick={() => setChangeFilter(cf)}
              style={{
                background: changeFilter === cf ? 'var(--accent)' : 'var(--bg-secondary)',
                color: changeFilter === cf ? '#fff' : 'var(--text-dim)',
                border: `1px solid ${changeFilter === cf ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 10, padding: '2px 10px', cursor: 'pointer', fontSize: 10,
              }}
            >
              {cf === 'all' ? 'All' : cf.charAt(0).toUpperCase() + cf.slice(1)}
            </button>
          ))}
        </div>

        {/* Keyword search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search label, IRI, or changed value…"
            style={{
              flex: 1, background: 'var(--bg)', border: `1px solid ${search ? 'var(--accent)' : 'var(--border)'}`,
              borderRadius: 4, padding: '5px 10px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace',
            }}
          />
          {search && (
            <button onClick={() => setSearch('')} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 12 }}>✕</button>
          )}
        </div>

        {/* Result count */}
        <div style={{ color: 'var(--text-dim)', fontSize: 10 }}>
          Showing {filtered.length} of {summary.added + summary.removed + summary.modified} entities
          {search && <span> matching <span style={{ color: 'var(--accent)' }}>"{search}"</span></span>}
        </div>

        {/* LLM narrative */}
        {diff.narrative && (
          <div style={{
            background: 'var(--bg)', border: '1px solid #238636', borderRadius: 6,
            padding: '9px 12px', fontSize: 10, lineHeight: 1.6,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ color: '#3fb950', fontWeight: 'bold' }}>Changelog</span>
              <button
                onClick={() => navigator.clipboard.writeText(diff.narrative!)}
                style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 11 }}
                title="Copy to clipboard"
              >
                ⎘
              </button>
            </div>
            <span style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>{diff.narrative}</span>
          </div>
        )}

        {/* Entity list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {filtered.map(entity => (
            <EntityRow
              key={`${entity.op}:${entity.iri}`}
              entity={entity}
              op={entity.op}
              search={search}
              expanded={expanded.has(entity.iri)}
              onToggle={() => setExpanded(prev => {
                const next = new Set(prev)
                next.has(entity.iri) ? next.delete(entity.iri) : next.add(entity.iri)
                return next
              })}
            />
          ))}
          {filtered.length === 0 && (
            <div style={{ color: 'var(--text-dim)', padding: '8px 4px' }}>No matching entities.</div>
          )}
        </div>
      </>)}
    </div>
  )
}
```

- [ ] **Step 2: Build to confirm no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | tail -15
```

Expected: build succeeds with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HistoryTab.tsx
git commit -m "feat(diff): HistoryTab component with filters, search, and entity detail"
```

---

### Task 9: OntologyPage Integration

**Files:**
- Modify: `frontend/src/pages/OntologyPage.tsx`

- [ ] **Step 1: Add the import**

At the top of `OntologyPage.tsx`, with the other component imports:

```typescript
import HistoryTab from '../components/HistoryTab'
```

- [ ] **Step 2: Extend the tab type on line 832**

Change:
```typescript
  const [detailTab, setDetailTab] = useState<'info' | 'metadata' | 'profile'>('info')
```
To:
```typescript
  const [detailTab, setDetailTab] = useState<'info' | 'metadata' | 'profile' | 'history'>('info')
```

- [ ] **Step 3: Add 'history' to the tab array on line 1145**

Change:
```typescript
            {(['info', 'metadata', 'profile'] as const).map(tab => (
```
To:
```typescript
            {(['info', 'metadata', 'profile', 'history'] as const).map(tab => (
```

- [ ] **Step 4: Add the HistoryTab render branch after the profile branch (around line 1176)**

The current final else block renders `<ProfileEditor>`. Add a new branch for `'history'` and adjust the final else:

Change the block starting at `} : detailTab === 'metadata' ? (` to:

```typescript
            ) : detailTab === 'metadata' ? (
              oid && activeVid
                ? <MetaProfileEditor ontologyId={oid} versionId={activeVid} />
                : null
            ) : detailTab === 'history' ? (
              oid && activeVid && versions.length > 1
                ? <HistoryTab
                    ontologyId={oid}
                    currentVersionId={activeVid}
                    versions={versions}
                  />
                : <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
                    Only one version available — no diff to show.
                  </div>
            ) : (
              oid && activeVid
                ? <ProfileEditor ontologyId={oid} versionId={activeVid} />
                : null
            )}
```

- [ ] **Step 5: Build to confirm no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | tail -15
```

Expected: build succeeds.

- [ ] **Step 6: Start the dev server and manually verify the History tab**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. Navigate to an ontology that has at least two ingested versions. Click the **History** tab in the right panel. Verify:
- Version picker dropdowns are populated
- Summary toggles show counts (or "Computing diff…" if Celery hasn't run yet)
- After the diff is ready: filter chips, search bar, and entity rows render correctly
- Expanding a modified entity shows Literal/Axiom sub-sections

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/OntologyPage.tsx
git commit -m "feat(diff): add History tab to OntologyPage"
```

---

## Final: Run all tests

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 2: Run TypeScript build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: zero errors.
