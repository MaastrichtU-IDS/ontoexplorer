# Cross-Ontology Compare (/compare) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/compare` route + page that lets users pick any two ontologies (and any versions of each) and produces the same Manchester-formatted diff currently shown for two versions of the same ontology.

**Architecture:** Extract a graph-IRI-parameterized core from the existing `run_diff` and call it from two thin wrappers — the legacy `run_diff` (same ontology) and a new `run_comparison` (cross-ontology). Persist results in a new `ontology_comparisons` table that mirrors `ontology_diffs` but carries two ontology IDs. Refactor the diff result rendering out of `HistoryTab` into a reusable `DiffResultView`, mounted by both the existing history tab and the new `Compare` page.

**Tech Stack:** Python 3.11+, SQLAlchemy + Alembic, FastAPI, Celery, pyoxigraph, React + TypeScript, React Query, React Router.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ontoexplorer/models/db.py` | MODIFY | Add `OntologyComparison` model |
| `alembic/versions/c1c0a1b2c3d4_add_ontology_comparisons.py` | NEW | Create the `ontology_comparisons` table |
| `ontoexplorer/modules/diff/compute.py` | MODIFY | Extract `_run_diff_core(store, from_graph_iri, to_graph_iri)` helper; `run_diff` becomes a thin wrapper |
| `ontoexplorer/modules/compare/__init__.py` | NEW | Empty package init |
| `ontoexplorer/modules/compare/compute.py` | NEW | `run_comparison(store, from_ontology_id, from_vid, to_ontology_id, to_vid)` |
| `ontoexplorer/modules/jobs/tasks.py` | MODIFY | Add `compute_ontology_comparison` Celery task |
| `ontoexplorer/api/compare.py` | NEW | REST endpoints under `/api/v1/compare` |
| `ontoexplorer/main.py` | MODIFY (1 line) | Mount the new `compare` router |
| `tests/unit/test_compare_compute.py` | NEW | Unit tests for `run_comparison` |
| `tests/unit/test_diff_compute.py` | MODIFY | Sanity check after `_run_diff_core` extraction |
| `frontend/src/lib/api.ts` | MODIFY | `OntologyComparison` type + `api.compare.get/compute` |
| `frontend/src/hooks/useCompare.ts` | NEW | `useArbitraryComparison` hook (polls until ready) |
| `frontend/src/components/DiffResultView.tsx` | NEW | Extracted from `HistoryTab`; renders added/removed/modified buckets |
| `frontend/src/components/HistoryTab.tsx` | MODIFY | Mount `DiffResultView` with `variant='version-diff'` |
| `frontend/src/pages/Compare.tsx` | NEW | The `/compare` page: ontology + version dropdowns + result |
| `frontend/src/App.tsx` | MODIFY (1 line) | Register `/compare` route |
| `frontend/src/components/NavBar.tsx` | MODIFY (1 line) | Add "Compare" nav link |

---

## Task 1: Add `OntologyComparison` model

**Files:**
- Modify: `ontoexplorer/models/db.py`

- [ ] **Step 1: Add the new model class**

In `ontoexplorer/models/db.py`, add this class immediately after the existing `OntologyDiff` class (around line 263 — right before `class TermEmbedding`):

```python
class OntologyComparison(Base):
    """Cross-ontology comparison between two version IDs from (possibly)
    different ontologies. Mirrors OntologyDiff but carries TWO ontology IDs.
    """
    __tablename__ = "ontology_comparisons"
    __table_args__ = (UniqueConstraint("version_from_id", "version_to_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    from_ontology_id: Mapped[str] = mapped_column(
        ForeignKey("ontologies.id", ondelete="CASCADE")
    )
    to_ontology_id: Mapped[str] = mapped_column(
        ForeignKey("ontologies.id", ondelete="CASCADE")
    )
    version_from_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE")
    )
    version_to_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | ready | failed
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diff_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 2: Verify the model imports cleanly**

Run: `cd /path/to/ontoexplorer && uv run python -c "from ontoexplorer.models.db import OntologyComparison; print(OntologyComparison.__tablename__)"`

Expected: `ontology_comparisons`

- [ ] **Step 3: Commit**

```bash
git add ontoexplorer/models/db.py
git commit -m "feat(models): add OntologyComparison model"
```

---

## Task 2: Alembic migration for `ontology_comparisons`

**Files:**
- Create: `alembic/versions/c1c0a1b2c3d4_add_ontology_comparisons.py`

- [ ] **Step 1: Find the previous migration head**

Run: `cd /path/to/ontoexplorer && .venv/bin/alembic heads 2>/dev/null || uv run alembic heads`

Expected: one revision ID (e.g. `e1f2a3b4c5d6` from the existing tip). Note this value — you will use it as `down_revision`.

- [ ] **Step 2: Create the migration file**

Write to `alembic/versions/c1c0a1b2c3d4_add_ontology_comparisons.py` — replace `<PREVIOUS_HEAD>` with the value from Step 1:

```python
"""add ontology_comparisons table

Revision ID: c1c0a1b2c3d4
Revises: <PREVIOUS_HEAD>
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa


revision = "c1c0a1b2c3d4"
down_revision = "<PREVIOUS_HEAD>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_comparisons",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "from_ontology_id",
            sa.String(),
            sa.ForeignKey("ontologies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_ontology_id",
            sa.String(),
            sa.ForeignKey("ontologies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_from_id",
            sa.String(),
            sa.ForeignKey("versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_to_id",
            sa.String(),
            sa.ForeignKey("versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("diff_data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "version_from_id", "version_to_id",
            name="uq_ontology_comparisons_version_pair",
        ),
    )


def downgrade() -> None:
    op.drop_table("ontology_comparisons")
```

- [ ] **Step 3: Apply the migration in the dev DB**

Run: `cd /path/to/ontoexplorer && docker compose exec -T api alembic upgrade head 2>&1 | tail -5`

Expected: a line like `Running upgrade <PREVIOUS_HEAD> -> c1c0a1b2c3d4, add ontology_comparisons table`.

- [ ] **Step 4: Verify the table exists**

Run: `docker compose exec -T postgres psql -U ontoexplorer -d ontoexplorer -c "\d ontology_comparisons" 2>&1 | tail -20`

Expected: a table description showing all 9 columns (`id`, `from_ontology_id`, `to_ontology_id`, `version_from_id`, `version_to_id`, `status`, `summary`, `diff_data`, `created_at`) and the unique constraint.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/c1c0a1b2c3d4_add_ontology_comparisons.py
git commit -m "feat(db): migration for ontology_comparisons table"
```

---

## Task 3: Extract `_run_diff_core` from `run_diff`

This is a pure refactor: the existing `run_diff` body that takes `(ontology_id, from_vid, to_vid)` is split into a private helper that takes two graph IRIs directly. `run_diff` becomes a thin wrapper. No behavior change; existing tests must still pass.

**Files:**
- Modify: `ontoexplorer/modules/diff/compute.py`

- [ ] **Step 1: Read the current `run_diff`**

Run: `grep -n "^def run_diff\|^def _run_diff_core" /path/to/ontoexplorer/ontoexplorer/modules/diff/compute.py`

Locate the start of `run_diff`. The function body has the entire entity-comparison loop you need to extract.

- [ ] **Step 2: Refactor — add `_run_diff_core`, rewrite `run_diff` as a wrapper**

In `ontoexplorer/modules/diff/compute.py`, replace the existing `run_diff` function with this two-function version. The first function is `_run_diff_core` (the extracted body); the second is `run_diff` (the wrapper):

```python
def _run_diff_core(
    store: ox.Store,
    from_graph: ox.NamedNode,
    to_graph: ox.NamedNode,
) -> tuple[dict, dict]:
    """Diff two named graphs in `store`. Pure function over graph IRIs —
    callers build the IRIs from their own identifiers (ontology_id+version
    for intra-ontology diffs, two ontology_ids for cross-ontology compare).

    Returns (summary, diff_data). diff_data has the shape
        {"added": [...], "removed": [...], "modified": [...]}
    matching the existing OntologyDiff JSON contract.
    """
    added_list: list[dict] = []
    removed_list: list[dict] = []
    modified_list: list[dict] = []
    labels: dict[str, str] = {}

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
            from_struct, from_terms = _structural_triples(store, from_graph, iri)
            to_struct,   to_terms   = _structural_triples(store, to_graph, iri)

            if from_lits == to_lits and from_struct == to_struct:
                continue

            from_lits_map = {(p, lang): v for p, lang, v in from_lits - to_lits}
            to_lits_map   = {(p, lang): v for p, lang, v in to_lits   - from_lits}
            literal_changes = [
                {
                    "predicate": pred,
                    "lang": lang,
                    "removed": from_lits_map.get((pred, lang)),
                    "added":   to_lits_map.get((pred, lang)),
                }
                for pred, lang in sorted(
                    set(from_lits_map) | set(to_lits_map),
                    key=lambda t: (t[0], t[1] or ""),
                )
            ]

            change_records: list[dict] = []
            for p_iri, o_repr in sorted(from_struct - to_struct):
                change_records.append({
                    "op": "removed",
                    "predicate": p_iri,
                    "object": from_terms[(p_iri, o_repr)],
                    "graph": from_graph,
                })
            for p_iri, o_repr in sorted(to_struct - from_struct):
                change_records.append({
                    "op": "added",
                    "predicate": p_iri,
                    "object": to_terms[(p_iri, o_repr)],
                    "graph": to_graph,
                })

            axiom_changes: list[dict] = []
            for rec in change_records:
                axiom_str = _mos.render_axiom(
                    store, rec["graph"], iri,
                    rec["predicate"], rec["object"],
                    labels=labels, entity_type=entity_type,
                )
                if axiom_str is None:
                    obj_val = rec["object"].value if hasattr(rec["object"], "value") else str(rec["object"])
                    axiom_str = f"<{rec['predicate']}> <{obj_val}>"
                axiom_changes.append({"op": rec["op"], "axiom": axiom_str})

            manchester_frame = _mos.render_frame(
                store, iri, entity_type, change_records, labels=labels,
            )

            label = _first_label(store, to_graph, iri) or _first_label(store, from_graph, iri)
            modified_list.append({
                "iri": iri,
                "label": label,
                "entity_type": entity_type,
                "literal_changes": literal_changes,
                "axiom_changes": axiom_changes,
                "manchester_frame": manchester_frame,
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


def run_diff(
    store: ox.Store,
    ontology_id: str,
    from_vid: str,
    to_vid: str,
) -> tuple[dict, dict]:
    """Compute term-level diff between two named graphs of the same ontology."""
    from_graph = ox.NamedNode(graph_iri(ontology_id, from_vid))
    to_graph   = ox.NamedNode(graph_iri(ontology_id, to_vid))
    return _run_diff_core(store, from_graph, to_graph)
```

- [ ] **Step 3: Run all existing diff tests to verify no regression**

Run: `cd /path/to/ontoexplorer && uv run pytest tests/unit/test_diff_compute.py tests/unit/test_manchester_render.py -v 2>&1 | tail -20`

Expected: all tests pass (the count should match what's there today — refactor is behavior-preserving).

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/modules/diff/compute.py
git commit -m "refactor(diff/compute): extract _run_diff_core; run_diff becomes a wrapper"
```

---

## Task 4: New `compare` module with `run_comparison`

**Files:**
- Create: `ontoexplorer/modules/compare/__init__.py`
- Create: `ontoexplorer/modules/compare/compute.py`
- Create: `tests/unit/test_compare_compute.py`

- [ ] **Step 1: Create the package init**

Write to `ontoexplorer/modules/compare/__init__.py`:

```python
"""Cross-ontology comparison.

Reuses the diff infrastructure (Manchester renderer, _run_diff_core) but
operates over two ontologies' named graphs instead of two versions of the
same ontology.
"""
```

- [ ] **Step 2: Write the failing tests**

Write to `tests/unit/test_compare_compute.py`:

```python
"""Unit tests for ontoexplorer.modules.compare.compute.run_comparison."""
import pyoxigraph as ox

from ontoexplorer.modules.compare.compute import run_comparison

OID_A = "ont-a"
OID_B = "ont-b"
VID_A = "vA"
VID_B = "vB"

_OWL_CLASS = ox.NamedNode("http://www.w3.org/2002/07/owl#Class")
_RDF_TYPE  = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_RDFS_LBL  = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
_RDFS_SC   = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")


def _store(*, a_quads: list[tuple], b_quads: list[tuple]) -> ox.Store:
    """Build an in-memory store with two named graphs, one per ontology."""
    store = ox.Store()
    g_a = ox.NamedNode(f"urn:ontology:{OID_A}:{VID_A}")
    g_b = ox.NamedNode(f"urn:ontology:{OID_B}:{VID_B}")
    store.add_graph(g_a)
    store.add_graph(g_b)
    for s, p, o in a_quads:
        store.add(ox.Quad(s, p, o, g_a))
    for s, p, o in b_quads:
        store.add(ox.Quad(s, p, o, g_b))
    return store


def test_run_comparison_all_disjoint():
    """Two ontologies with no shared IRIs: everything lands in added/removed."""
    cls_a = ox.NamedNode("http://a.org/Foo")
    cls_b = ox.NamedNode("http://b.org/Bar")
    s = _store(
        a_quads=[(cls_a, _RDF_TYPE, _OWL_CLASS)],
        b_quads=[(cls_b, _RDF_TYPE, _OWL_CLASS)],
    )
    summary, diff_data = run_comparison(s, OID_A, VID_A, OID_B, VID_B)
    assert summary["added"] == 1
    assert summary["removed"] == 1
    assert summary["modified"] == 0
    assert diff_data["added"][0]["iri"] == cls_b.value
    assert diff_data["removed"][0]["iri"] == cls_a.value


def test_run_comparison_shared_iri_axioms_differ():
    """Same IRI declared as owl:Class in both, but axioms differ → modified."""
    cls = ox.NamedNode("http://shared.org/Thing")
    parent_a = ox.NamedNode("http://shared.org/ParentA")
    parent_b = ox.NamedNode("http://shared.org/ParentB")
    s = _store(
        a_quads=[
            (cls, _RDF_TYPE, _OWL_CLASS),
            (cls, _RDFS_SC, parent_a),
        ],
        b_quads=[
            (cls, _RDF_TYPE, _OWL_CLASS),
            (cls, _RDFS_SC, parent_b),
        ],
    )
    summary, diff_data = run_comparison(s, OID_A, VID_A, OID_B, VID_B)
    assert summary["modified"] == 1
    assert summary["axiom_changes"] == 1
    m = diff_data["modified"][0]
    assert m["iri"] == cls.value
    ops = {ac["op"] for ac in m["axiom_changes"]}
    assert ops == {"added", "removed"}


def test_run_comparison_same_ontology_same_version_yields_no_changes():
    """Comparing an ontology to itself (same graph IRIs) produces zero changes —
    sanity check that run_comparison composes correctly with _run_diff_core."""
    cls = ox.NamedNode("http://a.org/Foo")
    quads = [(cls, _RDF_TYPE, _OWL_CLASS), (cls, _RDFS_LBL, ox.Literal("Foo"))]
    s = _store(a_quads=quads, b_quads=quads)
    # Force same graph IRI on both sides by reusing OID_A/VID_A
    summary, diff_data = run_comparison(s, OID_A, VID_A, OID_A, VID_A)
    assert summary["added"] == 0
    assert summary["removed"] == 0
    assert summary["modified"] == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /path/to/ontoexplorer && uv run pytest tests/unit/test_compare_compute.py -v 2>&1 | tail -10`

Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.compare.compute'` (or 3 FAILED with similar import error).

- [ ] **Step 4: Write the implementation**

Write to `ontoexplorer/modules/compare/compute.py`:

```python
"""Cross-ontology comparison.

run_comparison builds two graph IRIs from two (ontology_id, version_id) pairs
and delegates to the existing _run_diff_core helper. Identity is IRI-based.
"""
import pyoxigraph as ox

from ontoexplorer.clients.oxigraph import graph_iri
from ontoexplorer.modules.diff.compute import _run_diff_core


def run_comparison(
    store: ox.Store,
    from_ontology_id: str,
    from_vid: str,
    to_ontology_id: str,
    to_vid: str,
) -> tuple[dict, dict]:
    """Compute a diff between two ontology versions, possibly from different
    ontologies. Same JSON shape as `run_diff` (added/removed/modified buckets
    plus Manchester frames on modified entities). Two entities are "the same"
    iff they share an IRI.
    """
    from_graph = ox.NamedNode(graph_iri(from_ontology_id, from_vid))
    to_graph   = ox.NamedNode(graph_iri(to_ontology_id,   to_vid))
    return _run_diff_core(store, from_graph, to_graph)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /path/to/ontoexplorer && uv run pytest tests/unit/test_compare_compute.py -v 2>&1 | tail -10`

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/modules/compare/__init__.py ontoexplorer/modules/compare/compute.py tests/unit/test_compare_compute.py
git commit -m "feat(compare): run_comparison for cross-ontology diffs"
```

---

## Task 5: Celery task `compute_ontology_comparison`

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`

- [ ] **Step 1: Read the existing `compute_diff` task**

Run: `grep -n "compute_diff\|def compute_diff" /path/to/ontoexplorer/ontoexplorer/modules/jobs/tasks.py | head -5`

Locate `compute_diff` so you can append the new task next to it.

- [ ] **Step 2: Append the new task**

Add this function in `ontoexplorer/modules/jobs/tasks.py` immediately after the existing `compute_diff` task (around line 175, after `compute_diff`'s closing `return {"status": "done"}`):

```python
@celery_app.task(name="ontoexplorer.compute_ontology_comparison", time_limit=600)
def compute_ontology_comparison(version_from_id: str, version_to_id: str) -> dict:
    """Compute a cross-ontology comparison between two version IDs.

    Resolves each version's ontology_id from the DB, runs run_comparison,
    and persists results to the ontology_comparisons table.
    """
    import uuid
    from ontoexplorer.database import make_celery_db_session

    async def _run() -> None:
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from ontoexplorer.clients.oxigraph import get_store
        from ontoexplorer.models.db import OntologyComparison, OntologyVersion
        from ontoexplorer.modules.compare.compute import run_comparison as _run_comparison

        async with make_celery_db_session()() as db:
            from_ver = await db.scalar(
                select(OntologyVersion).where(OntologyVersion.id == version_from_id)
            )
            to_ver = await db.scalar(
                select(OntologyVersion).where(OntologyVersion.id == version_to_id)
            )
            if from_ver is None or to_ver is None:
                log.error(
                    "compute_ontology_comparison_missing_version",
                    from_vid=version_from_id, to_vid=version_to_id,
                )
                return

            existing = await db.scalar(
                select(OntologyComparison).where(
                    OntologyComparison.version_from_id == version_from_id,
                    OntologyComparison.version_to_id == version_to_id,
                )
            )
            if existing and existing.status == "ready":
                return

            await db.execute(
                pg_insert(OntologyComparison)
                .values(
                    id=str(uuid.uuid4()),
                    from_ontology_id=from_ver.ontology_id,
                    to_ontology_id=to_ver.ontology_id,
                    version_from_id=version_from_id,
                    version_to_id=version_to_id,
                    status="pending",
                )
                .on_conflict_do_nothing()
            )
            await db.commit()

            row = await db.scalar(
                select(OntologyComparison).where(
                    OntologyComparison.version_from_id == version_from_id,
                    OntologyComparison.version_to_id == version_to_id,
                )
            )
            if row is None:
                return  # should not happen, but guard

            try:
                store = get_store()
                summary, diff_data = await asyncio.to_thread(
                    _run_comparison,
                    store,
                    str(from_ver.ontology_id), version_from_id,
                    str(to_ver.ontology_id),   version_to_id,
                )
                row.summary = summary
                row.diff_data = diff_data
                row.status = "ready"
            except Exception as exc:
                row.status = "failed"
                log.error(
                    "compute_ontology_comparison_failed",
                    from_vid=version_from_id, to_vid=version_to_id, error=str(exc),
                )
            await db.commit()

    try:
        asyncio.run(_run())
        log.info(
            "compute_ontology_comparison_done",
            from_vid=version_from_id, to_vid=version_to_id,
        )
    except Exception as exc:
        log.error("compute_ontology_comparison_task_error", error=str(exc))
        raise
    return {"status": "done"}
```

- [ ] **Step 3: Verify the task imports cleanly**

Run: `cd /path/to/ontoexplorer && uv run python -c "from ontoexplorer.modules.jobs.tasks import compute_ontology_comparison; print(compute_ontology_comparison.name)"`

Expected: `ontoexplorer.compute_ontology_comparison`

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py
git commit -m "feat(jobs): compute_ontology_comparison Celery task"
```

---

## Task 6: REST endpoints for `/compare`

**Files:**
- Create: `ontoexplorer/api/compare.py`
- Modify: `ontoexplorer/main.py` (1 line to mount the router)

- [ ] **Step 1: Create the router**

Write to `ontoexplorer/api/compare.py`:

```python
"""Cross-ontology comparison REST API."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.logging_config import get_logger
from ontoexplorer.models.db import OntologyComparison, OntologyVersion

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/compare", tags=["compare"])


async def _get_version_or_404(db: AsyncSession, version_id: str) -> OntologyVersion:
    version = await db.scalar(
        select(OntologyVersion).where(OntologyVersion.id == version_id)
    )
    if version is None:
        raise HTTPException(status_code=404, detail=f"Version {version_id} not found")
    return version


def _comparison_response(row: OntologyComparison) -> dict:
    return {
        "status": row.status,
        "summary": row.summary,
        "diff_data": row.diff_data,
        "from_ontology_id": row.from_ontology_id,
        "to_ontology_id": row.to_ontology_id,
        "version_from_id": row.version_from_id,
        "version_to_id": row.version_to_id,
    }


@router.get("", summary="Get a cross-ontology comparison result")
async def get_comparison(
    from_version_id: str = Query(..., description="Version ID for the 'from' side"),
    to_version_id: str = Query(..., description="Version ID for the 'to' side"),
    db: AsyncSession = Depends(get_db),
):
    if from_version_id == to_version_id:
        raise HTTPException(
            status_code=400,
            detail="from_version_id and to_version_id must differ",
        )
    row = await db.scalar(
        select(OntologyComparison).where(
            OntologyComparison.version_from_id == from_version_id,
            OntologyComparison.version_to_id == to_version_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Comparison not yet requested")
    if row.status == "ready":
        return _comparison_response(row)
    return JSONResponse(status_code=202, content={"status": row.status})


@router.post("/compute", summary="Trigger compute for a cross-ontology comparison")
async def trigger_compute(
    from_version_id: str = Query(...),
    to_version_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if from_version_id == to_version_id:
        raise HTTPException(
            status_code=400,
            detail="from_version_id and to_version_id must differ",
        )
    await _get_version_or_404(db, from_version_id)
    await _get_version_or_404(db, to_version_id)

    existing = await db.scalar(
        select(OntologyComparison).where(
            OntologyComparison.version_from_id == from_version_id,
            OntologyComparison.version_to_id == to_version_id,
        )
    )
    if existing:
        return JSONResponse(status_code=202, content={"status": existing.status})

    from ontoexplorer.modules.jobs.tasks import compute_ontology_comparison
    compute_ontology_comparison.delay(from_version_id, to_version_id)
    return JSONResponse(status_code=202, content={"status": "pending"})
```

- [ ] **Step 2: Mount the router in `main.py`**

In `ontoexplorer/main.py`, find the block where existing routers are imported and included. Add the import next to the other API imports:

```python
from ontoexplorer.api.compare import router as compare_router
```

And add this line in the `app.include_router(...)` block (immediately after the existing `app.include_router(diff_router)` line):

```python
    app.include_router(compare_router)
```

- [ ] **Step 3: Smoke-test the endpoint**

Restart the API service so it reloads with the new router:

Run: `cd /path/to/ontoexplorer && docker compose restart api 2>&1 | tail -2`

Then probe the OpenAPI schema:

Run: `sleep 3 && curl -s http://localhost:8000/openapi.json | python3 -c "import json,sys;d=json.load(sys.stdin);print([p for p in d['paths'] if 'compare' in p])"`

Expected: `['/api/v1/compare', '/api/v1/compare/compute']`

- [ ] **Step 4: Verify a 404 for an unknown comparison**

Run: `curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8000/api/v1/compare?from_version_id=does-not-exist&to_version_id=also-fake"`

Expected: `404`

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/compare.py ontoexplorer/main.py
git commit -m "feat(api): /api/v1/compare endpoints for cross-ontology diffs"
```

---

## Task 7: TypeScript types + API client for the new endpoints

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Find the existing diff API section**

Run: `grep -n "diff:\|diffArbitrary\|OntologyDiff\b\|api = {" /path/to/ontoexplorer/frontend/src/lib/api.ts | head -10`

Locate where `OntologyDiff` is defined and where `api.ontologies.diff` is wired, so you know where to add the new types.

- [ ] **Step 2: Add the `OntologyComparison` type next to `OntologyDiff`**

In `frontend/src/lib/api.ts`, find the `OntologyDiff` interface definition. Immediately after it, add:

```typescript
export interface OntologyComparison {
  status: 'pending' | 'ready' | 'failed'
  from_ontology_id: string
  to_ontology_id: string
  version_from_id: string
  version_to_id: string
  summary?: DiffSummary
  diff_data?: {
    added: DiffEntity[]
    removed: DiffEntity[]
    modified: DiffEntity[]
  }
}

export interface ComparisonPending {
  status: 'pending' | 'failed'
}
```

- [ ] **Step 3: Add the `compare` namespace to the `api` object**

In the same file, find the `api = { ... }` object. Inside it, add a new `compare` property next to `ontologies` and the other namespaces:

```typescript
  compare: {
    get: (fromVid: string, toVid: string) =>
      request<OntologyComparison | ComparisonPending>(
        `/compare?from_version_id=${encodeURIComponent(fromVid)}&to_version_id=${encodeURIComponent(toVid)}`
      ),
    compute: (fromVid: string, toVid: string) =>
      request<{ status: string }>(
        `/compare/compute?from_version_id=${encodeURIComponent(fromVid)}&to_version_id=${encodeURIComponent(toVid)}`,
        { method: 'POST' }
      ),
  },
```

- [ ] **Step 4: Run type-check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: no new errors (the pre-existing `Sparql.test.tsx` fixture error is unrelated and filtered out).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(api): OntologyComparison type and api.compare client"
```

---

## Task 8: `useArbitraryComparison` hook

**Files:**
- Create: `frontend/src/hooks/useCompare.ts`

- [ ] **Step 1: Write the hook**

Write to `frontend/src/hooks/useCompare.ts`:

```typescript
import { useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyComparison, ComparisonPending } from '../lib/api'

function isPending(data: OntologyComparison | ComparisonPending | undefined): boolean {
  return data?.status === 'pending'
}

/**
 * Polls /compare every 3s until the result is ready or failed.
 * `enabled` controls when polling starts (both version IDs present + distinct).
 *
 * Caller flow: call api.compare.compute(...) once via useTriggerComparison,
 * then read the result via this hook. The hook is keyed off the version pair.
 */
export function useArbitraryComparison(
  fromVid: string | null,
  toVid: string | null,
) {
  const enabled = !!fromVid && !!toVid && fromVid !== toVid
  return useQuery({
    queryKey: ['compare', fromVid, toVid],
    enabled,
    queryFn: async () => {
      try {
        return await api.compare.get(fromVid!, toVid!)
      } catch (err) {
        // 404 = comparison not yet requested. Return a synthetic pending
        // status so the polling loop can wait until POST /compute lands a row.
        if (err instanceof Error && /404/.test(err.message)) {
          return { status: 'pending' } as ComparisonPending
        }
        throw err
      }
    },
    refetchInterval: (query) => isPending(query.state.data) ? 3000 : false,
    staleTime: 60_000,
  })
}

/**
 * One-shot POST /compare/compute. Use with the version pair to trigger the
 * Celery task. Successful POST returns immediately with a "pending" status
 * even if the worker hasn't finished yet — useArbitraryComparison handles
 * the polling.
 */
export function useTriggerComparison() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ fromVid, toVid }: { fromVid: string; toVid: string }) =>
      api.compare.compute(fromVid, toVid),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['compare', vars.fromVid, vars.toVid] })
    },
  })
}
```

- [ ] **Step 2: Type-check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useCompare.ts
git commit -m "feat(frontend): useArbitraryComparison + useTriggerComparison hooks"
```

---

## Task 9: Extract `DiffResultView` component

This refactor pulls the entity-row rendering out of `HistoryTab.tsx` into a standalone component so the new `Compare` page can mount it too. The HistoryTab continues to drive its own version pickers, filters, and narrative — only the result rendering is extracted.

**Files:**
- Create: `frontend/src/components/DiffResultView.tsx`
- Modify: `frontend/src/components/HistoryTab.tsx`

- [ ] **Step 1: Read the current entity-rendering section of `HistoryTab.tsx`**

Run: `grep -n "EntityRow\|allEntities\|filtered\|by_entity_type" /path/to/ontoexplorer/frontend/src/components/HistoryTab.tsx | head -20`

Locate the `EntityRow` component (top of file) and where it's used inside `HistoryTab`. You'll need to move the row-rendering logic and the filter UI into the new component.

- [ ] **Step 2: Create `DiffResultView.tsx`**

Write to `frontend/src/components/DiffResultView.tsx`:

```tsx
import { useState, useMemo } from 'react'
import { DiffEntity, DiffEntityType, DiffSummary } from '../lib/api'
import ManchesterFrame from './ManchesterFrame'

type Op = 'added' | 'removed' | 'modified'
type ChangeFilter = 'all' | 'literal' | 'axiom'

const ENTITY_TYPE_LABELS: Record<DiffEntityType, string> = {
  class: 'Class',
  object_property: 'Obj. property',
  data_property: 'Data property',
  annotation_property: 'Ann. property',
  individual: 'Individual',
}

interface Props {
  data: {
    added: DiffEntity[]
    removed: DiffEntity[]
    modified: DiffEntity[]
  }
  summary?: DiffSummary
  variant: 'version-diff' | 'cross-compare'
  fromLabel?: string  // for cross-compare bucket headers
  toLabel?: string
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
  entity, op, search, expanded, onToggle, variant, fromLabel, toLabel,
}: {
  entity: DiffEntity & { op: Op }
  op: Op
  search: string
  expanded: boolean
  onToggle: () => void
  variant: 'version-diff' | 'cross-compare'
  fromLabel?: string
  toLabel?: string
}) {
  const opColor = op === 'added' ? 'var(--green, #3fb950)'
    : op === 'removed' ? 'var(--red, #f85149)' : 'var(--orange, #f0883e)'
  const label = entity.label ?? entity.iri.split(/[#/]/).pop() ?? entity.iri
  const opSign = op === 'added' ? '+' : op === 'removed' ? '−' : '~'

  // Header label varies by variant. For cross-compare we use "Only in X" / "Only in Y".
  const opTextVersion =
    op === 'added' ? 'added' :
    op === 'removed' ? 'removed' :
    'modified'
  const opTextCross =
    op === 'added' ? `only in ${toLabel ?? 'B'}` :
    op === 'removed' ? `only in ${fromLabel ?? 'A'}` :
    'shared, axioms differ'
  const opLabel = variant === 'cross-compare' ? opTextCross : opTextVersion

  const hasLiteral = entity.literal_changes.length > 0
  const hasAxiom = entity.axiom_changes.length > 0

  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <div
        onClick={onToggle}
        style={{
          padding: '6px 10px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
      >
        <span style={{ color: opColor, fontWeight: 'bold', minWidth: 12 }}>{opSign}</span>
        <span style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', minWidth: 70 }}>
          {ENTITY_TYPE_LABELS[entity.entity_type]}
        </span>
        <span style={{ color: 'var(--text)', fontSize: 12, flex: 1 }}>
          <HighlightedText text={label} query={search} />
        </span>
        <span style={{ color: opColor, fontSize: 10, fontStyle: 'italic' }}>{opLabel}</span>
      </div>
      {expanded && op === 'modified' && (
        <div style={{ padding: '4px 10px 10px 30px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {hasLiteral && (
            <div>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Literal changes</div>
              {entity.literal_changes.map((lc, i) => (
                <div key={i} style={{ fontSize: 10, marginBottom: 4 }}>
                  <div style={{ color: 'var(--text-dim)' }}>
                    {lc.predicate}{lc.lang ? ` @${lc.lang}` : ''}
                  </div>
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
          {entity.manchester_frame && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Axiom changes</div>
              <ManchesterFrame frame={entity.manchester_frame} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function DiffResultView({ data, summary, variant, fromLabel, toLabel }: Props) {
  const [ops, setOps]               = useState<Set<Op>>(new Set(['added', 'removed', 'modified']))
  const [typeFilter, setTypeFilter] = useState<DiffEntityType | 'all'>('all')
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>('all')
  const [search, setSearch]         = useState('')
  const [expanded, setExpanded]     = useState<Set<string>>(new Set())

  const toggleOp = (op: Op) => {
    setOps(prev => {
      const next = new Set(prev)
      next.has(op) ? next.delete(op) : next.add(op)
      return next
    })
  }

  const allEntities: (DiffEntity & { op: Op })[] = useMemo(() => {
    const result: (DiffEntity & { op: Op })[] = []
    if (ops.has('added'))    data.added.forEach(e => result.push({ ...e, op: 'added' }))
    if (ops.has('removed'))  data.removed.forEach(e => result.push({ ...e, op: 'removed' }))
    if (ops.has('modified')) data.modified.forEach(e => result.push({ ...e, op: 'modified' }))
    return result
  }, [data, ops])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allEntities.filter(e => {
      if (typeFilter !== 'all' && e.entity_type !== typeFilter) return false
      if (changeFilter === 'literal' && e.op === 'modified' && !e.literal_changes.length) return false
      if (changeFilter === 'axiom'   && e.op === 'modified' && !e.axiom_changes.length)   return false
      if (changeFilter !== 'all' && e.op !== 'modified') return false
      if (!q) return true
      const label = (e.label ?? '').toLowerCase()
      const iri   = e.iri.toLowerCase()
      const inLit = e.literal_changes.some(lc =>
        lc.removed?.toLowerCase().includes(q) || lc.added?.toLowerCase().includes(q)
      )
      const inAxiom = e.axiom_changes.some(ac => ac.axiom.toLowerCase().includes(q))
      return label.includes(q) || iri.includes(q) || inLit || inAxiom
    })
  }, [allEntities, typeFilter, changeFilter, search])

  const opLabels: Record<Op, string> = variant === 'cross-compare'
    ? {
        added: toLabel ? `Only in ${toLabel}` : 'Only in B',
        removed: fromLabel ? `Only in ${fromLabel}` : 'Only in A',
        modified: 'Shared (axioms differ)',
      }
    : { added: 'Added', removed: 'Removed', modified: 'Modified' }

  return (
    <div style={{ padding: 14, fontFamily: 'monospace', fontSize: 11, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        {(['added', 'removed', 'modified'] as Op[]).map(op => (
          <label key={op} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={ops.has(op)} onChange={() => toggleOp(op)} />
            <span>{opLabels[op]} ({data[op].length})</span>
          </label>
        ))}
        <span style={{ flex: 1 }} />
        <select
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value as DiffEntityType | 'all')}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          <option value="all">All types</option>
          {Object.entries(ENTITY_TYPE_LABELS).map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
        <select
          value={changeFilter}
          onChange={e => setChangeFilter(e.target.value as ChangeFilter)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          <option value="all">All changes</option>
          <option value="literal">Literal changes</option>
          <option value="axiom">Axiom changes</option>
        </select>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search…"
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace', minWidth: 180 }}
        />
      </div>

      {summary && (
        <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>
          {summary.added} added, {summary.removed} removed, {summary.modified} modified
          {' '}({summary.literal_changes} literal, {summary.axiom_changes} axiom)
        </div>
      )}

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        {filtered.map(entity => (
          <EntityRow
            key={`${entity.op}-${entity.iri}`}
            entity={entity}
            op={entity.op}
            search={search}
            expanded={expanded.has(`${entity.op}-${entity.iri}`)}
            onToggle={() => {
              setExpanded(prev => {
                const key = `${entity.op}-${entity.iri}`
                const next = new Set(prev)
                next.has(key) ? next.delete(key) : next.add(key)
                return next
              })
            }}
            variant={variant}
            fromLabel={fromLabel}
            toLabel={toLabel}
          />
        ))}
        {filtered.length === 0 && (
          <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
            No entities match the current filters.
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Refactor `HistoryTab.tsx` to use `DiffResultView`**

Open `frontend/src/components/HistoryTab.tsx`. Remove the inline `EntityRow`, `HighlightedText`, `allEntities`, `filtered`, the filter-state `useState` calls, and the JSX that renders the filter chips and entity list. Replace the rendering block with a single `<DiffResultView ... />`.

The HistoryTab keeps:
- Its props (`ontologyId`, `currentVersionId`, `versions`)
- The two version `<select>` dropdowns and their state (`fromVid`, `toVid`)
- The narrative button + state (`generateNarrative`)
- The `useArbitraryDiff` query

The new structure of `HistoryTab`'s render is roughly:

```tsx
import DiffResultView from './DiffResultView'

// ... existing imports

export default function HistoryTab({ ontologyId, currentVersionId, versions }: Props) {
  const sorted = [...versions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )
  const currentIdx = sorted.findIndex(v => v.id === currentVersionId)
  const defaultFrom = currentIdx < sorted.length - 1 ? sorted[currentIdx + 1].id : ''

  const [fromVid, setFromVid] = useState(defaultFrom)
  const [toVid, setToVid]     = useState(currentVersionId)

  const { data: diff, isLoading } = useArbitraryDiff(
    ontologyId, fromVid || null, toVid || null
  )
  const { mutate: generateNarrative, isPending: generatingNarrative } =
    useGenerateNarrative(ontologyId, toVid)

  const toVidIdx = sorted.findIndex(v => v.id === toVid)
  const consecutivePrev = toVidIdx < sorted.length - 1 ? sorted[toVidIdx + 1].id : ''
  const isConsecutivePair = fromVid === consecutivePrev

  if (!fromVid) {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
        This is the only version — no diff available.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {/* Version picker — keep the existing two-select layout */}
      <div style={{ padding: 14, display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'monospace', fontSize: 11 }}>
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
            <option key={v.id} value={v.id}>{v.version_iri ?? v.id.slice(0, 8)}</option>
          ))}
        </select>
        {isConsecutivePair && diff?.diff_data && (
          <button
            onClick={() => generateNarrative()}
            disabled={generatingNarrative}
            style={{
              marginLeft: 'auto',
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              borderRadius: 4, padding: '4px 12px',
              color: 'var(--text)', fontSize: 11, cursor: generatingNarrative ? 'wait' : 'pointer',
            }}
          >
            {generatingNarrative ? 'Generating…' : 'Generate narrative'}
          </button>
        )}
      </div>

      {diff?.narrative && (
        <div style={{ padding: '0 14px 10px 14px', fontSize: 12, color: 'var(--text-dim)', fontStyle: 'italic' }}>
          {diff.narrative}
        </div>
      )}

      {isLoading || !diff?.diff_data ? (
        <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
          {diff?.status === 'pending' ? 'Computing diff…' : 'Loading…'}
        </div>
      ) : (
        <DiffResultView
          data={diff.diff_data}
          summary={diff.summary}
          variant="version-diff"
        />
      )}
    </div>
  )
}
```

Apply this rewrite. Remove the now-unused imports (`useMemo`, `HighlightedText`, etc.) from the top of the file.

- [ ] **Step 4: Type-check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: no new errors.

- [ ] **Step 5: Smoke-test in the browser (best-effort)**

Confirm the dev server is up:

Run: `curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:5173`

Expected: `frontend: 200`. (Visual verification of the History tab still rendering correctly is deferred to the user.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DiffResultView.tsx frontend/src/components/HistoryTab.tsx
git commit -m "refactor(frontend): extract DiffResultView from HistoryTab"
```

---

## Task 10: `Compare.tsx` page

**Files:**
- Create: `frontend/src/pages/Compare.tsx`

- [ ] **Step 1: Write the page**

Write to `frontend/src/pages/Compare.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, Ontology, OntologyVersion } from '../lib/api'
import { useArbitraryComparison, useTriggerComparison } from '../hooks/useCompare'
import DiffResultView from '../components/DiffResultView'

function ontologyDisplayName(o: Ontology): string {
  return (
    o.shortname
    || o.iri.replace(/[/#]+$/, '').split(/[/#]/).pop()?.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
    || o.iri
  )
}

function OntologyPicker({
  ontologies,
  value,
  onChange,
  side,
  disabledId,
}: {
  ontologies: Ontology[]
  value: string
  onChange: (id: string) => void
  side: 'from' | 'to'
  disabledId?: string
}) {
  const [query, setQuery] = useState('')
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return ontologies
    return ontologies.filter(o =>
      ontologyDisplayName(o).toLowerCase().includes(q) ||
      o.iri.toLowerCase().includes(q) ||
      (o.title ?? '').toLowerCase().includes(q)
    )
  }, [ontologies, query])

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {side === 'from' ? 'From ontology' : 'To ontology'}
      </label>
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Filter ontologies…"
        style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '6px 10px', color: 'var(--text)', fontSize: 12,
        }}
      />
      <select
        size={Math.min(8, Math.max(3, filtered.length))}
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '4px 6px', color: 'var(--text)', fontSize: 12,
          fontFamily: 'monospace', minHeight: 90,
        }}
      >
        {filtered.map(o => (
          <option key={o.id} value={o.id} disabled={o.id === disabledId}>
            {ontologyDisplayName(o)}{o.title ? ` — ${o.title}` : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function VersionPicker({
  ontologyId,
  value,
  onChange,
  side,
}: {
  ontologyId: string
  value: string
  onChange: (vid: string) => void
  side: 'from' | 'to'
}) {
  const { data } = useQuery({
    queryKey: ['versions', ontologyId],
    queryFn: () => api.ontologies.versions(ontologyId),
    enabled: !!ontologyId,
  })

  const versions: OntologyVersion[] = useMemo(
    () => (data?.versions ?? []).filter(v => v.status !== 'deprecated'),
    [data],
  )

  useEffect(() => {
    if (!value && versions.length > 0) onChange(versions[0].id)
  }, [versions, value, onChange])

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {side === 'from' ? 'From version' : 'To version'}
      </label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '6px 10px', color: 'var(--text)', fontSize: 12,
          fontFamily: 'monospace',
        }}
      >
        {versions.map(v => (
          <option key={v.id} value={v.id}>
            {v.version_iri ?? `${v.id.slice(0, 8)} · ${new Date(v.created_at).toLocaleDateString()}`}
          </option>
        ))}
      </select>
    </div>
  )
}

export default function Compare() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const urlFrom = params.get('from')
  const urlTo = params.get('to')

  const [fromOnt, setFromOnt] = useState('')
  const [toOnt,   setToOnt]   = useState('')
  const [fromVid, setFromVid] = useState(urlFrom ?? '')
  const [toVid,   setToVid]   = useState(urlTo ?? '')

  const { data: onts } = useQuery({
    queryKey: ['ontologies', 'all'],
    queryFn: () => api.ontologies.list(),
  })
  const ontologies: Ontology[] = onts?.ontologies ?? []

  const trigger = useTriggerComparison()
  const { data: comparison } = useArbitraryComparison(
    fromVid || null, toVid || null
  )

  // If the URL had ?from&to on mount, kick off the compute immediately.
  useEffect(() => {
    if (urlFrom && urlTo && urlFrom !== urlTo && !trigger.isPending) {
      trigger.mutate({ fromVid: urlFrom, toVid: urlTo })
    }
    // run-once on mount only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canCompare = !!fromVid && !!toVid && fromVid !== toVid

  function handleCompare() {
    navigate(`/compare?from=${encodeURIComponent(fromVid)}&to=${encodeURIComponent(toVid)}`, { replace: true })
    trigger.mutate({ fromVid, toVid })
  }

  const fromOntObj = ontologies.find(o => o.id === fromOnt)
  const toOntObj   = ontologies.find(o => o.id === toOnt)

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '1.5rem 2rem', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <h1 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0 }}>Compare ontologies</h1>
      <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
        Pick any two ontologies. The comparison aligns entities by exact IRI match.
      </div>

      {/* Step 1: pick the two ontologies */}
      <div style={{ display: 'flex', gap: 16 }}>
        <OntologyPicker
          ontologies={ontologies}
          value={fromOnt}
          onChange={setFromOnt}
          side="from"
          disabledId={toOnt}
        />
        <OntologyPicker
          ontologies={ontologies}
          value={toOnt}
          onChange={setToOnt}
          side="to"
          disabledId={fromOnt}
        />
      </div>

      {/* Step 2: pick versions (only shown once an ontology is selected on the corresponding side) */}
      {(fromOnt || toOnt) && (
        <div style={{ display: 'flex', gap: 16 }}>
          {fromOnt ? (
            <VersionPicker ontologyId={fromOnt} value={fromVid} onChange={setFromVid} side="from" />
          ) : <div style={{ flex: 1 }} />}
          {toOnt ? (
            <VersionPicker ontologyId={toOnt} value={toVid} onChange={setToVid} side="to" />
          ) : <div style={{ flex: 1 }} />}
        </div>
      )}

      <div>
        <button
          onClick={handleCompare}
          disabled={!canCompare || trigger.isPending}
          style={{
            background: canCompare ? 'var(--accent)' : 'var(--bg-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 6, padding: '8px 18px',
            color: canCompare ? '#0f172a' : 'var(--text-dim)',
            fontSize: 13, fontWeight: 600,
            cursor: canCompare && !trigger.isPending ? 'pointer' : 'default',
          }}
        >
          {trigger.isPending ? 'Queuing…' : 'Compare'}
        </button>
      </div>

      {/* Result section */}
      {fromVid && toVid && fromVid !== toVid && comparison && (
        <>
          {comparison.status === 'pending' && (
            <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
              Computing comparison… this can take up to a minute for large ontologies.
            </div>
          )}
          {comparison.status === 'failed' && (
            <div style={{ padding: '1rem', color: '#f85149', fontSize: 12 }}>
              Comparison failed. Click Compare to retry.
            </div>
          )}
          {comparison.status === 'ready' && 'diff_data' in comparison && comparison.diff_data && (
            <DiffResultView
              data={comparison.diff_data}
              summary={comparison.summary}
              variant="cross-compare"
              fromLabel={fromOntObj ? ontologyDisplayName(fromOntObj) : 'A'}
              toLabel={toOntObj ? ontologyDisplayName(toOntObj) : 'B'}
            />
          )}
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: no new errors. (If `useNavigate`/`useSearchParams` aren't imported in this project's React Router version, the import should still resolve — both are in `react-router-dom` v6+.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Compare.tsx
git commit -m "feat(frontend): Compare page with ontology + version pickers"
```

---

## Task 11: Mount the `/compare` route

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Import the page**

In `frontend/src/App.tsx`, add this import near the other page imports at the top of the file:

```tsx
import Compare from './pages/Compare'
```

- [ ] **Step 2: Add the route**

Inside the `<Routes>` block in `App.tsx`, add the following route immediately after the line `<Route path="/ontologies/:slug/:version" element={<Shell><OntologyPage /></Shell>} />`:

```tsx
<Route path="/compare" element={<Shell><Compare /></Shell>} />
```

- [ ] **Step 3: Type-check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: no new errors.

- [ ] **Step 4: Probe the route in the browser (best-effort)**

Run: `curl -sIL http://localhost:5173/compare 2>&1 | head -3`

Expected: HTTP 200 (Vite will serve the SPA shell for any path). The actual page renders client-side.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(frontend): register /compare route"
```

---

## Task 12: Add "Compare" link to the NavBar

**Files:**
- Modify: `frontend/src/components/NavBar.tsx`

- [ ] **Step 1: Add the link to `navLinks`**

In `frontend/src/components/NavBar.tsx`, find the existing array:

```typescript
const navLinks = [
  { to: '/ontologies', label: 'Ontologies' },
]
```

Replace it with:

```typescript
const navLinks = [
  { to: '/ontologies', label: 'Ontologies' },
  { to: '/compare',    label: 'Compare' },
]
```

- [ ] **Step 2: Type-check**

Run: `cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep -v "Sparql.test.tsx" | head -10`

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/NavBar.tsx
git commit -m "feat(frontend): add Compare link to top nav"
```

---

## Self-Review Checklist

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| New `OntologyComparison` model | Task 1 |
| Alembic migration | Task 2 |
| `_run_diff_core` extraction | Task 3 |
| `run_comparison` function | Task 4 |
| `compute_ontology_comparison` Celery task | Task 5 |
| `GET /api/v1/compare` + `POST /api/v1/compare/compute` | Task 6 |
| `OntologyComparison` TypeScript type + `api.compare` client | Task 7 |
| `useArbitraryComparison` hook | Task 8 |
| `DiffResultView` extracted from `HistoryTab` | Task 9 |
| `Compare.tsx` page with searchable ontology + version pickers | Task 10 |
| `/compare` route registration | Task 11 |
| "Compare" link in top NavBar | Task 12 |
| Cross-compare bucket relabeling ("Only in X" / "Only in Y" / "Shared, axioms differ") | Task 9 (`variant="cross-compare"` branch in `DiffResultView`) |
| URL state (`?from=&to=`) | Task 10 |
| Unit tests for `run_comparison` | Task 4 |
| Sanity test for `_run_diff_core` extraction | Task 3 (re-runs existing tests) |

All spec sections are addressed.

**2. Placeholder scan:** No "TBD", "TODO", "implement later", or "Similar to Task N" patterns. The Alembic migration in Task 2 has a single `<PREVIOUS_HEAD>` placeholder — that is a runtime lookup value, not a content placeholder, and Step 1 explicitly tells the engineer how to find it.

**3. Type consistency:**

- `OntologyComparison` model fields: `from_ontology_id`, `to_ontology_id`, `version_from_id`, `version_to_id`, `status`, `summary`, `diff_data`, `created_at`. Used consistently in Tasks 1, 2, 5, 6, 7.
- Celery task name: `ontoexplorer.compute_ontology_comparison` (Task 5) — referenced in Task 6 via `compute_ontology_comparison.delay(...)`. Consistent.
- API endpoint paths: `/api/v1/compare` and `/api/v1/compare/compute` (Task 6) — frontend client paths in Task 7 use the same `/compare` and `/compare/compute` (the `/api/v1` prefix is added by the request helper).
- Frontend types `OntologyComparison`, `ComparisonPending` (Task 7) — used by `useArbitraryComparison` in Task 8 and consumed by `Compare.tsx` in Task 10.
- `DiffResultView` props: `data`, `summary`, `variant`, `fromLabel`, `toLabel` (Task 9) — used identically by the refactored `HistoryTab` (Task 9 itself) and by `Compare.tsx` (Task 10).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-ontology-compare.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
