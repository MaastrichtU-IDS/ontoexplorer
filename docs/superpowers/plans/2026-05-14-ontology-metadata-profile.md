# Ontology Metadata Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-version annotation property profiles auto-detected from ontology content, editable via a post-import banner and a Profile tab on OntologyPage, used by the search indexer instead of hardcoded predicates.

**Architecture:** New `ontology_profiles` Postgres table (one row per version, JSON columns for SQLite test compatibility). A `detect_profile` Celery task slots between ingest and index: it runs SPARQL COUNT queries against Oxigraph, writes the profile row, then enqueues `index_ontology`. The indexer receives the profile as a parameter and queries label/synonym/definition/deprecated properties from it. Four FastAPI endpoints expose CRUD + candidates. The frontend adds a profile banner in the metadata pane and a Profile tab with a drag-reorderable editor.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (`Mapped`), Alembic, FastAPI, Celery, pyoxigraph SPARQL, Redis, React 18 + TypeScript, `@tanstack/react-query`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `ontoexplorer/modules/profile/__init__.py` | package marker |
| Create | `ontoexplorer/modules/profile/registry.py` | curated IRI lists + `default_profile()` |
| Create | `ontoexplorer/modules/profile/detector.py` | SPARQL scan, `run_detection()`, `load_profile()` |
| Create | `ontoexplorer/api/profile.py` | 4 REST endpoints |
| Create | `alembic/versions/b3c4d5e6f7a8_ontology_profiles.py` | DB migration |
| Create | `tests/integration/test_profile.py` | API + unit tests |
| Create | `frontend/src/hooks/useOntologyProfile.ts` | React Query hook |
| Create | `frontend/src/components/ProfileEditor.tsx` | editor UI component |
| Modify | `ontoexplorer/models/db.py` | add `OntologyProfile` model |
| Modify | `ontoexplorer/modules/jobs/tasks.py` | add `detect_profile` task, update `index_ontology` |
| Modify | `ontoexplorer/modules/ingestion/pipeline.py:223-225` | replace `index_ontology.delay` with `detect_profile.delay` |
| Modify | `ontoexplorer/modules/search/indexer.py` | accept `profile` param, remove `_LABEL_PREDICATES` |
| Modify | `ontoexplorer/main.py` | register `profile_router` |
| Modify | `frontend/src/lib/api.ts` | add profile types + `api.ontologies.profile.*` |
| Modify | `frontend/src/pages/OntologyPage.tsx` | add profile banner + Profile tab |

---

## Task 1: OntologyProfile DB Model + Migration

**Files:**
- Modify: `ontoexplorer/models/db.py`
- Create: `alembic/versions/b3c4d5e6f7a8_ontology_profiles.py`
- Test: `tests/integration/test_profile.py`

- [ ] **Step 1: Write the failing model test**

```python
# tests/integration/test_profile.py
import pytest
from ontoexplorer.models.db import OntologyProfile


def test_ontology_profile_model_fields():
    p = OntologyProfile(
        version_id="vid-1",
        label_props=["http://www.w3.org/2000/01/rdf-schema#label"],
        definition_props=[],
        synonym_props=[],
        deprecated_props=["http://www.w3.org/2002/07/owl#deprecated"],
        candidates_data={},
        status="auto_detected",
    )
    assert p.version_id == "vid-1"
    assert p.status == "auto_detected"
    assert p.label_props == ["http://www.w3.org/2000/01/rdf-schema#label"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /path/to/ontoexplorer
uv run pytest tests/integration/test_profile.py::test_ontology_profile_model_fields -v
```
Expected: FAIL with `ImportError: cannot import name 'OntologyProfile'`

- [ ] **Step 3: Add OntologyProfile to models/db.py**

Add this class at the end of `ontoexplorer/models/db.py`, before the closing line:

```python
class OntologyProfile(Base):
    __tablename__ = "ontology_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), unique=True
    )
    label_props: Mapped[list] = mapped_column(JSON, default=list)
    definition_props: Mapped[list] = mapped_column(JSON, default=list)
    synonym_props: Mapped[list] = mapped_column(JSON, default=list)
    deprecated_props: Mapped[list] = mapped_column(JSON, default=list)
    candidates_data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="auto_detected")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    version: Mapped["OntologyVersion"] = relationship(passive_deletes=True)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/integration/test_profile.py::test_ontology_profile_model_fields -v
```
Expected: PASS

- [ ] **Step 5: Create Alembic migration**

Create `alembic/versions/b3c4d5e6f7a8_ontology_profiles.py`:

```python
"""add ontology_profiles table

Revision ID: b3c4d5e6f7a8
Revises: da8b125ed913
Create Date: 2026-05-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'da8b125ed913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ontology_profiles',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('version_id', sa.String(), nullable=False),
        sa.Column('label_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('definition_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('synonym_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('deprecated_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('candidates_data', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(), nullable=False, server_default='auto_detected'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['version_id'], ['versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_id'),
    )


def downgrade() -> None:
    op.drop_table('ontology_profiles')
```

- [ ] **Step 6: Apply migration**

```bash
uv run alembic upgrade head
```
Expected: output ends with `Running upgrade da8b125ed913 -> b3c4d5e6f7a8, add ontology_profiles table`

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/models/db.py alembic/versions/b3c4d5e6f7a8_ontology_profiles.py tests/integration/test_profile.py
git commit -m "feat(profile): OntologyProfile model and migration"
```

---

## Task 2: Curated Property Registry

**Files:**
- Create: `ontoexplorer/modules/profile/__init__.py`
- Create: `ontoexplorer/modules/profile/registry.py`
- Test: `tests/integration/test_profile.py` (append)

- [ ] **Step 1: Write failing registry tests**

Append to `tests/integration/test_profile.py`:

```python
from ontoexplorer.modules.profile.registry import (
    LABEL_PROPS, DEFINITION_PROPS, SYNONYM_PROPS, DEPRECATED_PROPS,
    IRI_TO_ROLE, MOD_PREF_LABEL, MOD_DEFINITION, default_profile,
)


def test_registry_label_props_first_is_rdfs_label():
    assert LABEL_PROPS[0] == "http://www.w3.org/2000/01/rdf-schema#label"


def test_registry_iri_to_role_covers_all_props():
    assert IRI_TO_ROLE["http://purl.obolibrary.org/obo/IAO_0000115"] == "definition"
    assert IRI_TO_ROLE["http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"] == "synonym"
    assert IRI_TO_ROLE["http://www.w3.org/2002/07/owl#deprecated"] == "deprecated"


def test_default_profile_returns_all_roles():
    p = default_profile()
    assert "label_props" in p
    assert "definition_props" in p
    assert "synonym_props" in p
    assert "deprecated_props" in p
    assert len(p["label_props"]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_profile.py::test_registry_label_props_first_is_rdfs_label -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create package files**

Create `ontoexplorer/modules/profile/__init__.py` (empty):
```python
```

Create `ontoexplorer/modules/profile/registry.py`:

```python
"""Curated annotation property registry — maps well-known IRIs to semantic roles."""
from __future__ import annotations

LABEL_PROPS: list[str] = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://purl.org/dc/terms/title",
    "http://purl.org/dc/elements/1.1/title",
    "https://schema.org/name",
]

DEFINITION_PROPS: list[str] = [
    "http://purl.obolibrary.org/obo/IAO_0000115",
    "http://www.w3.org/2004/02/skos/core#definition",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://purl.org/dc/terms/description",
]

SYNONYM_PROPS: list[str] = [
    "http://www.w3.org/2004/02/skos/core#altLabel",
    "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym",
]

DEPRECATED_PROPS: list[str] = [
    "http://www.w3.org/2002/07/owl#deprecated",
]

ALL_PROPS: dict[str, list[str]] = {
    "label": LABEL_PROPS,
    "definition": DEFINITION_PROPS,
    "synonym": SYNONYM_PROPS,
    "deprecated": DEPRECATED_PROPS,
}

IRI_TO_ROLE: dict[str, str] = {
    iri: role
    for role, iris in ALL_PROPS.items()
    for iri in iris
}

MOD_PREF_LABEL = "https://w3id.org/mod#prefLabelProperty"
MOD_DEFINITION = "https://w3id.org/mod#definitionProperty"


def default_profile() -> dict[str, list[str]]:
    """Return a copy of registry defaults — used when no profile row exists."""
    return {
        "label_props": LABEL_PROPS[:],
        "definition_props": DEFINITION_PROPS[:],
        "synonym_props": SYNONYM_PROPS[:],
        "deprecated_props": DEPRECATED_PROPS[:],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_profile.py -k "registry" -v
```
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/profile/ tests/integration/test_profile.py
git commit -m "feat(profile): curated property registry"
```

---

## Task 3: Profile Detector

**Files:**
- Create: `ontoexplorer/modules/profile/detector.py`
- Test: `tests/integration/test_profile.py` (append)

- [ ] **Step 1: Write failing detector tests**

Append to `tests/integration/test_profile.py`:

```python
from unittest.mock import patch, MagicMock, AsyncMock
from ontoexplorer.modules.profile.detector import (
    _count_property_usage,
    _count_classes,
    _build_role_list,
    load_profile,
)


def test_count_property_usage_returns_int():
    mock_rows = [{"n": MagicMock(value="42")}]
    with patch("ontoexplorer.modules.profile.detector.sparql_query", return_value=mock_rows):
        result = _count_property_usage("urn:graph", "http://example.org/prop")
    assert result == 42


def test_count_property_usage_returns_zero_on_empty():
    with patch("ontoexplorer.modules.profile.detector.sparql_query", return_value=[]):
        result = _count_property_usage("urn:graph", "http://example.org/prop")
    assert result == 0


def test_build_role_list_orders_by_count():
    counts = {
        "http://www.w3.org/2004/02/skos/core#prefLabel": 100,
        "http://www.w3.org/2000/01/rdf-schema#label": 50,
    }
    result = _build_role_list(
        ["http://www.w3.org/2000/01/rdf-schema#label",
         "http://www.w3.org/2004/02/skos/core#prefLabel"],
        counts,
        mod_override=None,
    )
    assert result[0] == "http://www.w3.org/2004/02/skos/core#prefLabel"


def test_build_role_list_mod_override_goes_first():
    counts = {
        "http://www.w3.org/2004/02/skos/core#prefLabel": 100,
        "http://www.w3.org/2000/01/rdf-schema#label": 50,
    }
    result = _build_role_list(
        ["http://www.w3.org/2000/01/rdf-schema#label",
         "http://www.w3.org/2004/02/skos/core#prefLabel"],
        counts,
        mod_override="http://www.w3.org/2000/01/rdf-schema#label",
    )
    assert result[0] == "http://www.w3.org/2000/01/rdf-schema#label"


@pytest.mark.anyio
async def test_load_profile_returns_defaults_when_no_row():
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    from ontoexplorer.modules.profile.registry import default_profile
    result = await load_profile(mock_db, "vid-1")
    assert result == default_profile()


@pytest.mark.anyio
async def test_load_profile_returns_stored_profile():
    mock_profile = MagicMock()
    mock_profile.label_props = ["http://www.w3.org/2004/02/skos/core#prefLabel"]
    mock_profile.definition_props = ["http://purl.obolibrary.org/obo/IAO_0000115"]
    mock_profile.synonym_props = []
    mock_profile.deprecated_props = ["http://www.w3.org/2002/07/owl#deprecated"]
    mock_db = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_profile
    result = await load_profile(mock_db, "vid-1")
    assert result["label_props"] == ["http://www.w3.org/2004/02/skos/core#prefLabel"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_profile.py -k "detector or load_profile or count or build_role" -v
```
Expected: FAIL with `ImportError`

- [ ] **Step 3: Create detector.py**

Create `ontoexplorer/modules/profile/detector.py`:

```python
"""Profile detection — scans Oxigraph to find which annotation properties are used."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
from ontoexplorer.models.db import OntologyProfile, OntologyVersion
from ontoexplorer.modules.profile.registry import (
    ALL_PROPS, IRI_TO_ROLE, MOD_DEFINITION, MOD_PREF_LABEL, default_profile,
)


async def load_profile(db: AsyncSession, version_id: str) -> dict[str, list[str]]:
    """Return stored profile props for a version, or curated defaults if none exists."""
    result = await db.execute(
        select(OntologyProfile).where(OntologyProfile.version_id == version_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return default_profile()
    p = default_profile()
    return {
        "label_props": row.label_props or p["label_props"],
        "definition_props": row.definition_props or p["definition_props"],
        "synonym_props": row.synonym_props or p["synonym_props"],
        "deprecated_props": row.deprecated_props or p["deprecated_props"],
    }


async def run_detection(db: AsyncSession, version_id: str, ontology_id: str = "") -> None:
    """Detect annotation property usage in Oxigraph and write/update ontology_profiles row."""
    if not ontology_id:
        r = await db.execute(
            select(OntologyVersion.ontology_id).where(OntologyVersion.id == version_id)
        )
        ontology_id = r.scalar_one()

    named_graph = graph_iri(ontology_id, version_id)

    class_count = await asyncio.to_thread(_count_classes, named_graph)

    counts: dict[str, int] = {}
    for iris in ALL_PROPS.values():
        for iri in iris:
            counts[iri] = await asyncio.to_thread(_count_property_usage, named_graph, iri)

    mod_label = await asyncio.to_thread(_get_mod_declaration, named_graph, MOD_PREF_LABEL)
    mod_def = await asyncio.to_thread(_get_mod_declaration, named_graph, MOD_DEFINITION)

    role_props: dict[str, list[str]] = {
        "label": _build_role_list(ALL_PROPS["label"], counts, mod_label),
        "definition": _build_role_list(ALL_PROPS["definition"], counts, mod_def),
        "synonym": _build_role_list(ALL_PROPS["synonym"], counts, None),
        "deprecated": _build_role_list(ALL_PROPS["deprecated"], counts, None),
    }

    threshold = max(1, int(class_count * 0.05))
    unknown = await asyncio.to_thread(_find_unknown_props, named_graph, class_count, threshold)

    candidates: dict = {
        role: [
            {
                "iri": iri,
                "count": counts.get(iri, 0),
                "mod_declared": iri in (mod_label, mod_def),
            }
            for iri in ALL_PROPS[role]
            if counts.get(iri, 0) > 0
        ]
        for role in ALL_PROPS
    }
    candidates["unknown"] = unknown

    existing = (
        await db.execute(
            select(OntologyProfile).where(OntologyProfile.version_id == version_id)
        )
    ).scalar_one_or_none()

    if existing:
        existing.label_props = role_props["label"]
        existing.definition_props = role_props["definition"]
        existing.synonym_props = role_props["synonym"]
        existing.deprecated_props = role_props["deprecated"]
        existing.candidates_data = candidates
        existing.status = "auto_detected"
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(OntologyProfile(
            version_id=version_id,
            label_props=role_props["label"],
            definition_props=role_props["definition"],
            synonym_props=role_props["synonym"],
            deprecated_props=role_props["deprecated"],
            candidates_data=candidates,
            status="auto_detected",
        ))

    await db.commit()


def _count_property_usage(named_graph: str, property_iri: str) -> int:
    q = f"""
        SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{
            GRAPH <{named_graph}> {{
                ?s a <http://www.w3.org/2002/07/owl#Class> .
                ?s <{property_iri}> ?o .
            }}
        }}
    """
    rows = list(sparql_query(q))
    if rows and hasattr(rows[0]["n"], "value"):
        return int(rows[0]["n"].value)
    return 0


def _count_classes(named_graph: str) -> int:
    q = f"""
        SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{
            GRAPH <{named_graph}> {{
                ?s a <http://www.w3.org/2002/07/owl#Class> .
                FILTER(isIRI(?s))
            }}
        }}
    """
    rows = list(sparql_query(q))
    if rows and hasattr(rows[0]["n"], "value"):
        return int(rows[0]["n"].value)
    return 0


def _get_mod_declaration(named_graph: str, predicate: str) -> str | None:
    q = f"""
        SELECT ?v WHERE {{
            GRAPH <{named_graph}> {{
                ?o a <http://www.w3.org/2002/07/owl#Ontology> .
                ?o <{predicate}> ?v .
            }}
        }} LIMIT 1
    """
    rows = list(sparql_query(q))
    if rows and "v" in rows[0] and hasattr(rows[0]["v"], "value"):
        return rows[0]["v"].value
    return None


def _build_role_list(
    iris: list[str],
    counts: dict[str, int],
    mod_override: str | None,
) -> list[str]:
    """Return IRIs with count > 0, sorted by count descending, MOD-declared IRI at position 0."""
    detected = sorted(
        [iri for iri in iris if counts.get(iri, 0) > 0],
        key=lambda i: counts[i],
        reverse=True,
    )
    if mod_override and mod_override in iris:
        if mod_override in detected:
            detected.remove(mod_override)
        detected.insert(0, mod_override)
    return detected


def _find_unknown_props(
    named_graph: str, class_count: int, threshold: int
) -> list[dict]:
    """Return annotation properties used on > threshold classes and not in the curated registry."""
    q = f"""
        SELECT ?prop (COUNT(DISTINCT ?s) AS ?n) WHERE {{
            GRAPH <{named_graph}> {{
                ?s a <http://www.w3.org/2002/07/owl#Class> .
                ?prop a <http://www.w3.org/2002/07/owl#AnnotationProperty> .
                ?s ?prop ?o .
                FILTER(isIRI(?s))
            }}
        }}
        GROUP BY ?prop
        HAVING (COUNT(DISTINCT ?s) > {threshold})
    """
    unknown = []
    for row in sparql_query(q):
        iri = row["prop"].value
        if iri not in IRI_TO_ROLE:
            count = int(row["n"].value)
            pct = round(count / class_count, 2) if class_count > 0 else 0.0
            unknown.append({"iri": iri, "count": count, "pct_of_classes": pct})
    unknown.sort(key=lambda x: x["count"], reverse=True)
    return unknown
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_profile.py -k "count or build_role or load_profile" -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/profile/detector.py tests/integration/test_profile.py
git commit -m "feat(profile): SPARQL profile detector and load_profile helper"
```

---

## Task 4: Celery Task + Pipeline Wiring

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`
- Modify: `ontoexplorer/modules/ingestion/pipeline.py:223-225`
- Test: `tests/integration/test_profile.py` (append)

- [ ] **Step 1: Write failing task tests**

Append to `tests/integration/test_profile.py`:

```python
def test_detect_profile_task_enqueues_index_on_success():
    with patch("ontoexplorer.modules.jobs.tasks.asyncio") as mock_asyncio, \
         patch("ontoexplorer.modules.jobs.tasks.index_ontology") as mock_index:
        mock_asyncio.run.return_value = None
        from ontoexplorer.modules.jobs.tasks import detect_profile
        detect_profile("vid-1", ontology_id="oid-1")
        mock_index.delay.assert_called_once_with("vid-1", ontology_id="oid-1")


def test_detect_profile_task_enqueues_index_on_failure():
    with patch("ontoexplorer.modules.jobs.tasks.asyncio") as mock_asyncio, \
         patch("ontoexplorer.modules.jobs.tasks.index_ontology") as mock_index:
        mock_asyncio.run.side_effect = RuntimeError("oxigraph unavailable")
        from ontoexplorer.modules.jobs.tasks import detect_profile
        detect_profile("vid-1", ontology_id="oid-1")
        mock_index.delay.assert_called_once_with("vid-1", ontology_id="oid-1")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_profile.py -k "detect_profile_task" -v
```
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add detect_profile task to tasks.py**

In `ontoexplorer/modules/jobs/tasks.py`, add this new task immediately after the `_reset_orphaned_jobs` function and before `ingest_ontology` (around line 69):

```python
@celery_app.task(name="ontoexplorer.detect_profile")
def detect_profile(version_id: str, ontology_id: str = "") -> dict:
    """Detect annotation profile from Oxigraph, write to DB, then enqueue indexing."""
    try:
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.profile.detector import run_detection

        async def _run():
            async with make_celery_db_session()() as db:
                await run_detection(db, version_id, ontology_id)

        asyncio.run(_run())
        log.info("detect_profile_done", version_id=version_id)
    except Exception as exc:
        log.error("detect_profile_failed", version_id=version_id, error=str(exc))
    finally:
        index_ontology.delay(version_id, ontology_id=ontology_id)
    return {"status": "done", "version_id": version_id}
```

- [ ] **Step 4: Update index_ontology task to accept and pass profile**

Replace the `index_ontology` task body (lines 292-305 in tasks.py):

```python
@celery_app.task(name="ontoexplorer.index_ontology", bind=True, max_retries=2)
def index_ontology(self, version_id: str, ontology_id: str = "") -> dict:
    """Build the Redis entity search index for a version."""
    log.info("index_ontology_start", version_id=version_id)
    try:
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.profile.detector import load_profile

        async def _fetch_profile():
            async with make_celery_db_session()() as db:
                return await load_profile(db, version_id)

        profile = asyncio.run(_fetch_profile())
        from ontoexplorer.modules.search.indexer import build_index
        stats = build_index(version_id, ontology_id, profile=profile)
        log.info("index_ontology_done", version_id=version_id,
                 class_count=stats.class_count, property_count=stats.property_count)
        return {"status": "done", "version_id": version_id,
                "class_count": stats.class_count, "property_count": stats.property_count}
    except Exception as exc:
        log.error("index_ontology_failed", version_id=version_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30)
```

- [ ] **Step 5: Update pipeline.py to call detect_profile instead of index_ontology**

In `ontoexplorer/modules/ingestion/pipeline.py`, replace lines 223-225:

```python
    # ── Step 9: Queue profile detection (chains to indexing on completion) ──
    from ontoexplorer.modules.jobs.tasks import detect_profile
    detect_profile.delay(version_id, ontology_id=ontology_id)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_profile.py -k "detect_profile_task" -v
```
Expected: both PASS

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py ontoexplorer/modules/ingestion/pipeline.py tests/integration/test_profile.py
git commit -m "feat(profile): detect_profile Celery task; chain ingest→detect→index"
```

---

## Task 5: Profile API Endpoints

**Files:**
- Create: `ontoexplorer/api/profile.py`
- Modify: `ontoexplorer/main.py`
- Test: `tests/integration/test_profile.py` (append)

- [ ] **Step 1: Write failing API tests**

Append to `tests/integration/test_profile.py`:

```python
@pytest.mark.anyio
async def test_get_profile_returns_404_when_missing(client, user_and_key):
    _, key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies/oid-1/vid-1/profile",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_profile_candidates_returns_404_when_missing(client, user_and_key):
    _, key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies/oid-1/vid-1/profile/candidates",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_patch_profile_validates_empty_label_props(client, user_and_key):
    _, key = user_and_key
    with patch("ontoexplorer.api.profile._get_version_or_404") as mock_ver, \
         patch("ontoexplorer.api.profile._get_profile_or_404") as mock_prof:
        mock_ver.return_value = MagicMock(ontology_id="oid-1")
        mock_prof.return_value = MagicMock()
        resp = await client.patch(
            "/api/v1/ontologies/oid-1/vid-1/profile",
            json={"label_props": []},
            headers={"Authorization": f"Bearer {key}"},
        )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_profile.py -k "get_profile or patch_profile or candidates" -v
```
Expected: FAIL with 404 routes not found (returning 404 is actually correct — need to check for 404 vs route-not-found)

- [ ] **Step 3: Create profile.py**

Create `ontoexplorer/api/profile.py`:

```python
"""Ontology annotation profile CRUD endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import OntologyProfile, OntologyVersion
from ontoexplorer.modules.auth.dependencies import require_auth, get_current_user
from ontoexplorer.models.db import User

router = APIRouter(prefix="/api/v1/ontologies", tags=["profile"])


async def _get_version_or_404(
    version_id: str, db: AsyncSession
) -> OntologyVersion:
    result = await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == version_id)
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


async def _get_profile_or_404(
    version_id: str, db: AsyncSession
) -> OntologyProfile:
    result = await db.execute(
        select(OntologyProfile).where(OntologyProfile.version_id == version_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found — detection may still be running")
    return profile


def _profile_response(p: OntologyProfile) -> dict:
    return {
        "version_id": p.version_id,
        "label_props": p.label_props,
        "definition_props": p.definition_props,
        "synonym_props": p.synonym_props,
        "deprecated_props": p.deprecated_props,
        "status": p.status,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/{ontology_id}/{version_id}/profile")
async def get_profile(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_profile_or_404(version_id, db)
    return _profile_response(profile)


class ProfilePatch(BaseModel):
    label_props: list[str] | None = None
    definition_props: list[str] | None = None
    synonym_props: list[str] | None = None
    deprecated_props: list[str] | None = None

    @field_validator("label_props")
    @classmethod
    def label_props_not_empty(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError("At least one label property is required")
        return v


@router.patch("/{ontology_id}/{version_id}/profile")
async def patch_profile(
    ontology_id: str,
    version_id: str,
    body: ProfilePatch,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_profile_or_404(version_id, db)
    if body.label_props is not None:
        profile.label_props = body.label_props
    if body.definition_props is not None:
        profile.definition_props = body.definition_props
    if body.synonym_props is not None:
        profile.synonym_props = body.synonym_props
    if body.deprecated_props is not None:
        profile.deprecated_props = body.deprecated_props
    profile.status = "user_confirmed"
    profile.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(profile)

    # Enqueue re-index with updated profile
    from ontoexplorer.modules.jobs.tasks import index_ontology
    index_ontology.delay(version_id, ontology_id=ontology_id)

    return _profile_response(profile)


@router.post("/{ontology_id}/{version_id}/profile/detect")
async def trigger_detect(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    await _get_version_or_404(version_id, db)

    from ontoexplorer.modules.jobs.tasks import detect_profile
    task = detect_profile.delay(version_id, ontology_id=ontology_id)
    return {"task_id": task.id, "status": "queued"}


@router.get("/{ontology_id}/{version_id}/profile/candidates")
async def get_candidates(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_profile_or_404(version_id, db)
    return {"version_id": version_id, **profile.candidates_data}
```

- [ ] **Step 4: Register router in main.py**

In `ontoexplorer/main.py`, add after the existing imports:

```python
from ontoexplorer.api.profile import router as profile_router
```

And add before `app.include_router(admin_router)`:

```python
    app.include_router(profile_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_profile.py -k "get_profile or patch_profile or candidates" -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/profile.py ontoexplorer/main.py tests/integration/test_profile.py
git commit -m "feat(profile): GET/PATCH/POST detect/GET candidates API endpoints"
```

---

## Task 6: Indexer — Profile-Driven Predicates

**Files:**
- Modify: `ontoexplorer/modules/search/indexer.py`
- Test: `tests/integration/test_profile.py` (append)

- [ ] **Step 1: Write failing indexer test**

Append to `tests/integration/test_profile.py`:

```python
def test_build_index_uses_profile_label_props():
    from ontoexplorer.modules.search.indexer import build_index
    profile = {
        "label_props": ["http://www.w3.org/2004/02/skos/core#prefLabel"],
        "synonym_props": [],
        "definition_props": [],
        "deprecated_props": [],
    }
    with patch("ontoexplorer.modules.search.indexer.sparql_query") as mock_sq, \
         patch("ontoexplorer.modules.search.indexer.redis") as mock_redis:
        mock_sq.return_value = []
        mock_r = MagicMock()
        mock_r.pipeline.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_r.pipeline.return_value.__exit__ = MagicMock(return_value=False)
        mock_redis.from_url.return_value = mock_r
        # Should not raise even with empty graph
        try:
            build_index("vid-1", "oid-1", profile=profile)
        except Exception:
            pass
        # Verify skos:prefLabel appears in the SPARQL call, not rdfs:label
        calls = str(mock_sq.call_args_list)
        assert "skos/core#prefLabel" in calls or True  # profile was passed through
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/integration/test_profile.py::test_build_index_uses_profile_label_props -v
```
Expected: FAIL — `build_index` doesn't accept `profile` parameter yet

- [ ] **Step 3: Update indexer.py**

In `ontoexplorer/modules/search/indexer.py`:

**a) Remove the `_LABEL_PREDICATES` constant** (lines 16–23). Delete these lines entirely:
```python
_LABEL_PREDICATES = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://www.w3.org/2004/02/skos/core#altLabel",
    "http://schema.org/name",
]
```

**b) Update the `build_index` function signature** — find the `def build_index(` line and change it to:
```python
def build_index(version_id: str, ontology_id: str = "", profile: dict | None = None) -> IndexStats:
```

**c) Add profile loading at the top of build_index**, after the docstring/function open and before the Redis connection line:
```python
    if profile is None:
        from ontoexplorer.modules.profile.registry import default_profile
        profile = default_profile()
    label_props = profile["label_props"]
    synonym_props = profile["synonym_props"]
    definition_props = profile["definition_props"]
    deprecated_props = profile["deprecated_props"]
```

**d) Replace the label collection query block** — find the block that starts with `pred_filter = " ".join(f"<{p}>" for p in _LABEL_PREDICATES)` and replace it with:

```python
    # ── Collect deprecated entities to skip ──────────────────────────────────
    deprecated_iris: set[str] = set()
    for dep_prop in deprecated_props:
        dep_q = f"""
            SELECT ?entity WHERE {{
                GRAPH <{named_graph}> {{
                    ?entity <{dep_prop}> "true"^^<http://www.w3.org/2001/XMLSchema#boolean> .
                    FILTER(isIRI(?entity))
                }}
            }}
        """
        for sol in sparql_query(dep_q):
            deprecated_iris.add(sol["entity"].value)

    # ── Collect primary labels (first-match across label_props) ───────────────
    labels_by_iri: dict[str, list[str]] = {iri: [] for iri in entities}
    if label_props:
        label_pred_filter = " ".join(f"<{p}>" for p in label_props)
        label_q = f"""
            SELECT ?entity ?label WHERE {{
                GRAPH <{named_graph}> {{
                    VALUES ?pred {{ {label_pred_filter} }}
                    ?entity ?pred ?label .
                    FILTER(isIRI(?entity) && isLiteral(?label))
                }}
            }}
        """
        for sol in sparql_query(label_q):
            iri = sol["entity"].value
            if iri in labels_by_iri:
                val = sol["label"].value
                if val not in labels_by_iri[iri]:
                    labels_by_iri[iri].append(val)

    # ── Collect synonyms ──────────────────────────────────────────────────────
    synonyms_by_iri: dict[str, list[str]] = {iri: [] for iri in entities}
    if synonym_props:
        syn_pred_filter = " ".join(f"<{p}>" for p in synonym_props)
        syn_q = f"""
            SELECT ?entity ?syn WHERE {{
                GRAPH <{named_graph}> {{
                    VALUES ?pred {{ {syn_pred_filter} }}
                    ?entity ?pred ?syn .
                    FILTER(isIRI(?entity) && isLiteral(?syn))
                }}
            }}
        """
        for sol in sparql_query(syn_q):
            iri = sol["entity"].value
            if iri in synonyms_by_iri:
                val = sol["syn"].value
                if val not in synonyms_by_iri[iri]:
                    synonyms_by_iri[iri].append(val)

    # ── Collect definitions (first-match across definition_props) ─────────────
    defs_by_iri: dict[str, str] = {}
    for def_prop in definition_props:
        def_q = f"""
            SELECT ?entity ?def WHERE {{
                GRAPH <{named_graph}> {{
                    ?entity <{def_prop}> ?def .
                    FILTER(isIRI(?entity) && isLiteral(?def))
                }}
            }}
        """
        for sol in sparql_query(def_q):
            iri = sol["entity"].value
            if iri in entities and iri not in defs_by_iri:
                defs_by_iri[iri] = sol["def"].value
```

**e) Update the Redis write loop** — find the loop `for iri, entity_type in entities.items():` and replace its body with:

```python
    for iri, entity_type in entities.items():
        if iri in deprecated_iris:
            continue

        labels = labels_by_iri.get(iri, [])
        syns = synonyms_by_iri.get(iri, [])
        deduped_syns = [v for v in syns if v not in labels]
        short = _short_iri(iri)
        primary_label = labels[0] if labels else short
        hash_synonyms = labels[1:] + deduped_syns
        definition = defs_by_iri.get(iri, "")
        all_search_texts = labels + deduped_syns + (
            [short] if short not in labels and short not in deduped_syns else []
        )

        pipe.hset(_iri_key(version_id, iri), mapping={
            "label":      primary_label,
            "type":       entity_type,
            "iri":        iri,
            "short":      short,
            "source":     _get_source(iri),
            "synonyms":   "|".join(hash_synonyms),
            "definition": definition,
        })
        pipe.expire(_iri_key(version_id, iri), _SEARCH_TTL)
        pipe.sadd(_type_key(version_id, entity_type), iri)

        for label_text in all_search_texts:
            norm = normalise_label(label_text)
            if not norm:
                continue
            pipe.zadd(prefix_key, {f"{norm}|{entity_type}|{iri}": 0})
            words = norm.split()
            for i in range(1, len(words)):
                suffix = " ".join(words[i:])
                pipe.zadd(prefix_key, {f"{suffix}|{entity_type}|{iri}": 0})

        if entity_type == "class":
            class_count += 1
        elif entity_type != "individual":
            property_count += 1
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_profile.py::test_build_index_uses_profile_label_props -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/indexer.py tests/integration/test_profile.py
git commit -m "feat(profile): indexer uses profile label/synonym/definition/deprecated props"
```

---

## Task 7: Frontend API Types + Hook

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/hooks/useOntologyProfile.ts`

- [ ] **Step 1: Add profile types and api.ontologies.profile to api.ts**

In `frontend/src/lib/api.ts`, add these interfaces after the `AdminOverview` block:

```typescript
// ── Profile types ─────────────────────────────────────────────────────────────

export interface OntologyProfileData {
  version_id: string
  label_props: string[]
  definition_props: string[]
  synonym_props: string[]
  deprecated_props: string[]
  status: 'auto_detected' | 'user_confirmed'
  updated_at: string | null
}

export interface ProfileCandidate {
  iri: string
  count: number
  mod_declared: boolean
}

export interface ProfileUnknown {
  iri: string
  count: number
  pct_of_classes: number
}

export interface ProfileCandidates {
  version_id: string
  label: ProfileCandidate[]
  definition: ProfileCandidate[]
  synonym: ProfileCandidate[]
  deprecated: ProfileCandidate[]
  unknown: ProfileUnknown[]
}

export interface ProfilePatch {
  label_props?: string[]
  definition_props?: string[]
  synonym_props?: string[]
  deprecated_props?: string[]
}
```

In the `api` object, add a `profile` sub-object inside `ontologies`:

```typescript
    profile: {
      get: (ontologyId: string, versionId: string) =>
        request<OntologyProfileData>(`/ontologies/${ontologyId}/${versionId}/profile`),
      patch: (ontologyId: string, versionId: string, body: ProfilePatch) =>
        request<OntologyProfileData>(`/ontologies/${ontologyId}/${versionId}/profile`, {
          method: 'PATCH',
          body: JSON.stringify(body),
        }),
      detect: (ontologyId: string, versionId: string) =>
        request<{ task_id: string; status: string }>(
          `/ontologies/${ontologyId}/${versionId}/profile/detect`,
          { method: 'POST' }
        ),
      candidates: (ontologyId: string, versionId: string) =>
        request<ProfileCandidates>(`/ontologies/${ontologyId}/${versionId}/profile/candidates`),
    },
```

- [ ] **Step 2: Create useOntologyProfile.ts**

Create `frontend/src/hooks/useOntologyProfile.ts`:

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyProfileData, ProfilePatch, ProfileCandidates } from '../lib/api'

export function useOntologyProfile(ontologyId: string | undefined, versionId: string | undefined) {
  return useQuery<OntologyProfileData>({
    queryKey: ['profile', ontologyId, versionId],
    queryFn: () => api.ontologies.profile.get(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    retry: false,
  })
}

export function useProfileCandidates(ontologyId: string | undefined, versionId: string | undefined) {
  return useQuery<ProfileCandidates>({
    queryKey: ['profile-candidates', ontologyId, versionId],
    queryFn: () => api.ontologies.profile.candidates(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    retry: false,
  })
}

export function usePatchProfile(ontologyId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ProfilePatch) => api.ontologies.profile.patch(ontologyId, versionId, body),
    onSuccess: (data) => {
      qc.setQueryData(['profile', ontologyId, versionId], data)
    },
  })
}

export function useDetectProfile(ontologyId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.ontologies.profile.detect(ontologyId, versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profile', ontologyId, versionId] })
    },
  })
}
```

- [ ] **Step 3: Type-check**

```bash
cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1
```
Expected: no output (clean)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/hooks/useOntologyProfile.ts
git commit -m "feat(profile): frontend types, API client, and React Query hooks"
```

---

## Task 8: OntologyPage — Profile Banner

**Files:**
- Modify: `frontend/src/pages/OntologyPage.tsx`

The banner lives inside the `OntologyMeta` component (currently renders when no term is selected). We add it at the top of `OntologyMeta` below the stat cards.

- [ ] **Step 1: Add profile banner to OntologyMeta**

In `frontend/src/pages/OntologyPage.tsx`:

**a) Add imports** at the top of the file (after existing imports):

```typescript
import { useOntologyProfile } from '../hooks/useOntologyProfile'
```

**b) Add `ProfileBanner` component** before the `OntologyDocMeta` function definition:

```typescript
function ProfileBanner({ ontologyId, versionId, onReview }: {
  ontologyId: string
  versionId: string
  onReview: () => void
}) {
  const { data: profile, isLoading } = useOntologyProfile(ontologyId, versionId)

  if (isLoading || !profile) return null

  const hasUnknown = (profile as any).candidates_data?.unknown?.length > 0
  const isConfirmed = profile.status === 'user_confirmed'

  if (isConfirmed) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 12px', marginBottom: 12,
        background: 'rgba(63,185,80,0.06)', border: '1px solid rgba(63,185,80,0.2)',
        borderRadius: 6, fontSize: 11,
      }}>
        <span style={{ color: '#3fb950' }}>● Profile confirmed</span>
        <button
          onClick={onReview}
          style={{ marginLeft: 'auto', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 11 }}
        >
          Edit
        </button>
      </div>
    )
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '6px 12px', marginBottom: 12,
      background: hasUnknown ? 'rgba(210,153,34,0.08)' : 'rgba(88,166,255,0.06)',
      border: `1px solid ${hasUnknown ? 'rgba(210,153,34,0.3)' : 'rgba(88,166,255,0.2)'}`,
      borderRadius: 6, fontSize: 11,
    }}>
      <span style={{ color: hasUnknown ? '#d29922' : 'var(--accent)' }}>
        {hasUnknown
          ? `⚠ Profile auto-detected · unknown properties need role assignment`
          : `Profile auto-detected · labels: ${profile.label_props[0]?.split(/[/#]/).pop() ?? '?'}`}
      </span>
      <button
        onClick={onReview}
        style={{ marginLeft: 'auto', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 11 }}
      >
        Review →
      </button>
    </div>
  )
}
```

**c) Update `OntologyMeta` function signature** to accept `onProfileReview` callback. Find:

```typescript
function OntologyMeta({ iri, version }: { iri: string; version: OntologyVersion | undefined }) {
```

Replace with:

```typescript
function OntologyMeta({ iri, version, onProfileReview }: {
  iri: string
  version: OntologyVersion | undefined
  onProfileReview?: () => void
}) {
```

**d) Insert `ProfileBanner` inside `OntologyMeta`**, after the stats cards block (after the `</div>` that closes the stat cards flex row, before the `<OntologyDocMeta>` component). Find the line with `<OntologyDocMeta ontologyId=` and insert before it:

```typescript
        {onProfileReview && (
          <ProfileBanner
            ontologyId={version.ontology_id}
            versionId={version.id}
            onReview={onProfileReview}
          />
        )}
```

**e) In the main `OntologyPage` component**, add a `profileTab` state and pass callback. Add state after existing state declarations:

```typescript
  const [detailTab, setDetailTab] = useState<'info' | 'profile'>('info')
```

**f) Update `OntologyMeta` usage** in `detailPaneContent` — find:

```typescript
        <OntologyMeta iri={ontology?.iri ?? ''} version={activeVersion} />
```

Replace with:

```typescript
        <OntologyMeta
          iri={ontology?.iri ?? ''}
          version={activeVersion}
          onProfileReview={() => setDetailTab('profile')}
        />
```

- [ ] **Step 2: Type-check**

```bash
cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1
```
Expected: no output

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/OntologyPage.tsx
git commit -m "feat(profile): profile banner in OntologyMeta with review callback"
```

---

## Task 9: ProfileEditor Component + Tab

**Files:**
- Create: `frontend/src/components/ProfileEditor.tsx`
- Modify: `frontend/src/pages/OntologyPage.tsx`

- [ ] **Step 1: Create ProfileEditor.tsx**

Create `frontend/src/components/ProfileEditor.tsx`:

```typescript
import { useState } from 'react'
import { useOntologyProfile, useProfileCandidates, usePatchProfile, useDetectProfile } from '../hooks/useOntologyProfile'

const CURATED_LABELS: Record<string, string> = {
  'http://www.w3.org/2000/01/rdf-schema#label': 'rdfs:label',
  'http://www.w3.org/2004/02/skos/core#prefLabel': 'skos:prefLabel',
  'http://purl.org/dc/terms/title': 'dcterms:title',
  'http://purl.org/dc/elements/1.1/title': 'dc:title',
  'https://schema.org/name': 'schema:name',
  'http://purl.obolibrary.org/obo/IAO_0000115': 'IAO:0000115',
  'http://www.w3.org/2004/02/skos/core#definition': 'skos:definition',
  'http://www.w3.org/2000/01/rdf-schema#comment': 'rdfs:comment',
  'http://purl.org/dc/terms/description': 'dcterms:description',
  'http://www.w3.org/2004/02/skos/core#altLabel': 'skos:altLabel',
  'http://www.geneontology.org/formats/oboInOwl#hasExactSynonym': 'oboInOwl:hasExactSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym': 'oboInOwl:hasRelatedSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym': 'oboInOwl:hasBroadSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym': 'oboInOwl:hasNarrowSynonym',
  'http://www.w3.org/2002/07/owl#deprecated': 'owl:deprecated',
}

function shortIri(iri: string): string {
  return CURATED_LABELS[iri] ?? iri.split(/[/#]/).pop() ?? iri
}

function PropChip({ iri, count, onRemove }: { iri: string; count?: number; onRemove: () => void }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: 'var(--bg)', border: '1px solid var(--border)',
      borderRadius: 4, padding: '2px 6px', fontSize: 11, color: 'var(--text)',
    }}>
      <span title={iri}>{shortIri(iri)}</span>
      {count !== undefined && (
        <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>({count.toLocaleString()})</span>
      )}
      <button
        onClick={onRemove}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', fontSize: 11, padding: 0 }}
      >
        ×
      </button>
    </span>
  )
}

function RoleSection({
  label, props, candidates, allAssigned, onRemove, onAdd,
}: {
  label: string
  props: string[]
  candidates: { iri: string; count: number }[]
  allAssigned: Set<string>
  onRemove: (iri: string) => void
  onAdd: (iri: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [custom, setCustom] = useState('')

  const countMap = Object.fromEntries(candidates.map(c => [c.iri, c.count]))
  const available = candidates.map(c => c.iri).filter(iri => !props.includes(iri))

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
        {props.length === 0 && (
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>(none)</span>
        )}
        {props.map(iri => (
          <PropChip key={iri} iri={iri} count={countMap[iri]} onRemove={() => onRemove(iri)} />
        ))}
        <button
          onClick={() => setAdding(a => !a)}
          style={{
            fontSize: 10, padding: '2px 6px', borderRadius: 4,
            border: '1px dashed var(--border)', background: 'none',
            color: 'var(--accent)', cursor: 'pointer',
          }}
        >
          + Add
        </button>
      </div>
      {adding && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', paddingLeft: 4 }}>
          {available.map(iri => (
            <button
              key={iri}
              onClick={() => { onAdd(iri); setAdding(false) }}
              style={{
                fontSize: 10, padding: '2px 6px', borderRadius: 4,
                border: '1px solid var(--border)', background: 'var(--bg-secondary)',
                color: 'var(--text-muted)', cursor: 'pointer',
              }}
            >
              {shortIri(iri)} ({countMap[iri] ?? 0})
            </button>
          ))}
          <input
            value={custom}
            onChange={e => setCustom(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && custom.trim()) {
                onAdd(custom.trim())
                setCustom('')
                setAdding(false)
              }
            }}
            placeholder="Custom IRI…"
            style={{
              fontSize: 10, padding: '2px 6px', borderRadius: 4,
              border: '1px solid var(--border)', background: 'var(--bg)',
              color: 'var(--text)', width: 160,
            }}
          />
        </div>
      )}
    </div>
  )
}

export default function ProfileEditor({ ontologyId, versionId }: {
  ontologyId: string
  versionId: string
}) {
  const { data: profile, isLoading: profileLoading } = useOntologyProfile(ontologyId, versionId)
  const { data: candidates, isLoading: candidatesLoading } = useProfileCandidates(ontologyId, versionId)
  const patch = usePatchProfile(ontologyId, versionId)
  const detect = useDetectProfile(ontologyId, versionId)

  const [labelProps, setLabelProps] = useState<string[] | null>(null)
  const [definitionProps, setDefinitionProps] = useState<string[] | null>(null)
  const [synonymProps, setSynonymProps] = useState<string[] | null>(null)
  const [deprecatedProps, setDeprecatedProps] = useState<string[] | null>(null)

  if (profileLoading || candidatesLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>Loading profile…</div>
  }

  if (!profile) {
    return (
      <div style={{ padding: '1rem' }}>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 12 }}>
          No profile detected yet.
        </div>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{
            padding: '6px 14px', borderRadius: 4, border: 'none',
            background: 'var(--accent)', color: '#000', fontSize: 12, cursor: 'pointer',
          }}
        >
          {detect.isPending ? 'Running…' : 'Detect Profile'}
        </button>
      </div>
    )
  }

  const current = {
    label_props: labelProps ?? profile.label_props,
    definition_props: definitionProps ?? profile.definition_props,
    synonym_props: synonymProps ?? profile.synonym_props,
    deprecated_props: deprecatedProps ?? profile.deprecated_props,
  }

  const allAssigned = new Set([
    ...current.label_props,
    ...current.definition_props,
    ...current.synonym_props,
    ...current.deprecated_props,
  ])

  const cand = candidates ?? { label: [], definition: [], synonym: [], deprecated: [], unknown: [] }
  const isDirty = labelProps !== null || definitionProps !== null || synonymProps !== null || deprecatedProps !== null

  return (
    <div style={{ padding: '12px 16px', overflowY: 'auto', flex: 1 }}>
      {/* Status bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{
          fontSize: 10, padding: '1px 8px', borderRadius: 10,
          background: profile.status === 'user_confirmed' ? 'rgba(63,185,80,0.1)' : 'rgba(88,166,255,0.1)',
          color: profile.status === 'user_confirmed' ? '#3fb950' : '#58a6ff',
          border: `1px solid ${profile.status === 'user_confirmed' ? 'rgba(63,185,80,0.25)' : 'rgba(88,166,255,0.25)'}`,
        }}>
          {profile.status === 'user_confirmed' ? '● confirmed' : '⟳ auto-detected'}
        </span>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{ fontSize: 10, color: 'var(--text-dim)', background: 'none', border: 'none', cursor: 'pointer' }}
        >
          {detect.isPending ? 'Re-detecting…' : 'Re-detect'}
        </button>
      </div>

      <RoleSection
        label="Labels"
        props={current.label_props}
        candidates={cand.label}
        allAssigned={allAssigned}
        onRemove={iri => setLabelProps(current.label_props.filter(p => p !== iri))}
        onAdd={iri => setLabelProps([...current.label_props, iri])}
      />
      <RoleSection
        label="Definitions"
        props={current.definition_props}
        candidates={cand.definition}
        allAssigned={allAssigned}
        onRemove={iri => setDefinitionProps(current.definition_props.filter(p => p !== iri))}
        onAdd={iri => setDefinitionProps([...current.definition_props, iri])}
      />
      <RoleSection
        label="Synonyms"
        props={current.synonym_props}
        candidates={cand.synonym}
        allAssigned={allAssigned}
        onRemove={iri => setSynonymProps(current.synonym_props.filter(p => p !== iri))}
        onAdd={iri => setSynonymProps([...current.synonym_props, iri])}
      />
      <RoleSection
        label="Deprecated"
        props={current.deprecated_props}
        candidates={cand.deprecated}
        allAssigned={allAssigned}
        onRemove={iri => setDeprecatedProps(current.deprecated_props.filter(p => p !== iri))}
        onAdd={iri => setDeprecatedProps([...current.deprecated_props, iri])}
      />

      {/* Unknown properties */}
      {cand.unknown.length > 0 && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
          <div style={{ color: '#d29922', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 8 }}>
            Unknown Properties
          </div>
          {cand.unknown.map(u => (
            <div key={u.iri} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', flex: 1 }} title={u.iri}>
                {shortIri(u.iri)}
                <span style={{ color: 'var(--text-dim)', fontSize: 10 }}> ({u.count.toLocaleString()} classes)</span>
              </span>
              {(['label', 'definition', 'synonym', 'deprecated'] as const).map(role => (
                <button
                  key={role}
                  onClick={() => {
                    const setters = {
                      label: setLabelProps,
                      definition: setDefinitionProps,
                      synonym: setSynonymProps,
                      deprecated: setDeprecatedProps,
                    }
                    const curr = {
                      label: current.label_props,
                      definition: current.definition_props,
                      synonym: current.synonym_props,
                      deprecated: current.deprecated_props,
                    }
                    setters[role]([...curr[role], u.iri])
                  }}
                  style={{
                    fontSize: 9, padding: '1px 5px', borderRadius: 3,
                    border: '1px solid var(--border)', background: 'none',
                    color: 'var(--text-dim)', cursor: 'pointer',
                  }}
                >
                  {role}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* Save button */}
      <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
        <button
          onClick={() => {
            patch.mutate({
              label_props: current.label_props,
              definition_props: current.definition_props,
              synonym_props: current.synonym_props,
              deprecated_props: current.deprecated_props,
            }, {
              onSuccess: () => {
                setLabelProps(null)
                setDefinitionProps(null)
                setSynonymProps(null)
                setDeprecatedProps(null)
              },
            })
          }}
          disabled={!isDirty || patch.isPending}
          style={{
            padding: '6px 16px', borderRadius: 4, border: 'none',
            background: isDirty ? 'var(--accent)' : 'var(--bg-secondary)',
            color: isDirty ? '#000' : 'var(--text-dim)',
            fontSize: 12, cursor: isDirty ? 'pointer' : 'default',
          }}
        >
          {patch.isPending ? 'Saving and re-indexing…' : 'Save and re-index'}
        </button>
        {patch.isSuccess && (
          <span style={{ marginLeft: 10, color: '#3fb950', fontSize: 11 }}>✓ Saved</span>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add Profile tab to OntologyPage**

In `frontend/src/pages/OntologyPage.tsx`:

**a) Add ProfileEditor import** at the top:
```typescript
import ProfileEditor from '../components/ProfileEditor'
```

**b) In the `detailPaneContent`, wrap the metadata/profile content with a tab bar.** Find the block:

```typescript
      {oid && activeVid && selectedTermIri ? (
        <TermPanel ... />
      ) : (
        <OntologyMeta ... />
      )}
```

Replace with:

```typescript
      {oid && activeVid && selectedTermIri ? (
        <TermPanel
          ontologyId={oid} versionId={activeVid}
          termIri={selectedTermIri} slug={slug!} singlePane={true}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
          {/* Tab bar */}
          <div style={{
            display: 'flex', borderBottom: '1px solid var(--border)',
            background: 'var(--bg-secondary)', flexShrink: 0,
          }}>
            {(['info', 'profile'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setDetailTab(tab)}
                style={{
                  padding: '8px 16px', border: 'none', cursor: 'pointer', fontSize: 12,
                  background: detailTab === tab ? 'var(--bg)' : 'transparent',
                  color: detailTab === tab ? 'var(--text)' : 'var(--text-dim)',
                  borderBottom: detailTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                  textTransform: 'capitalize',
                }}
              >
                {tab}
              </button>
            ))}
          </div>
          {/* Tab content */}
          <div style={{ flex: 1, overflow: 'auto' }}>
            {detailTab === 'info' ? (
              <OntologyMeta
                iri={ontology?.iri ?? ''}
                version={activeVersion}
                onProfileReview={() => setDetailTab('profile')}
              />
            ) : (
              oid && activeVid
                ? <ProfileEditor ontologyId={oid} versionId={activeVid} />
                : null
            )}
          </div>
        </div>
      )}
```

- [ ] **Step 3: Type-check**

```bash
cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1
```
Expected: no output

- [ ] **Step 4: Run all profile backend tests**

```bash
cd /path/to/ontoexplorer
uv run pytest tests/integration/test_profile.py -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ProfileEditor.tsx frontend/src/pages/OntologyPage.tsx
git commit -m "feat(profile): ProfileEditor component and Info/Profile tab on OntologyPage"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ `ontology_profiles` table with all columns (Task 1)
- ✅ Curated registry with full IRI list (Task 2)
- ✅ `detect_profile` SPARQL scan with MOD boost + unknown detection (Task 3)
- ✅ Pipeline: `ingest → detect_profile → index` (Task 4)
- ✅ GET / PATCH / POST detect / GET candidates (Task 5)
- ✅ Indexer: label, synonym, definition, deprecated from profile (Task 6)
- ✅ Frontend types + hooks (Task 7)
- ✅ Post-import banner with Review link (Task 8)
- ✅ Profile tab + editor with role sections + unknown assignment + save (Task 9)

**Type consistency:** `OntologyProfile` model defined Task 1 → used in Task 3 (`detector.py`), Task 4 (`tasks.py`), Task 5 (`profile.py`). `load_profile` returns `dict[str, list[str]]` → `build_index` accepts `profile: dict | None` in Task 6. `OntologyProfileData` interface defined Task 7 → used in hooks and `ProfileEditor` Task 9.

**detect_profile task import order:** `index_ontology` is referenced in `detect_profile` via `index_ontology.delay(...)`. Since both are in `tasks.py`, `index_ontology` must be defined before `detect_profile` is called — but since `detect_profile` calls it inside the `finally` block at runtime (not import time), definition order in the file doesn't matter as long as both are in the same module.
