# Ontology-Level Metadata Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-version ontology-level metadata profiles that auto-detect which RDF properties an ontology uses for title/description/creator/license/etc., cache resolved values in Postgres, expose CRUD + bulk-harmonized API endpoints, and display structured metadata throughout the platform.

**Architecture:** New `ontology_meta_profiles` table (one row per version, 18 JSON role-IRI columns + a `resolved` JSON blob). A `detect_meta_profile` Celery task runs independently after ingest: one SPARQL query fetches all triples on the `owl:Ontology` node, resolved values are extracted and cached. Five FastAPI endpoints expose CRUD + bulk access. The frontend gains a Metadata tab on OntologyPage and uses `resolved.title`/`resolved.description` on the list page and Admin table.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (`Mapped`), Alembic, FastAPI, Celery, pyoxigraph SPARQL, React 18 + TypeScript, `@tanstack/react-query`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `ontoexplorer/modules/meta_profile/__init__.py` | package marker |
| Create | `ontoexplorer/modules/meta_profile/registry.py` | 18 role IRI lists + helpers |
| Create | `ontoexplorer/modules/meta_profile/detector.py` | SPARQL fetch, resolve, write row |
| Create | `ontoexplorer/api/meta_profile.py` | 5 REST endpoints |
| Create | `alembic/versions/a1b2c3d4e5f6_ontology_meta_profiles.py` | DB migration |
| Create | `tests/integration/test_meta_profile.py` | backend tests |
| Create | `frontend/src/hooks/useOntologyMeta.ts` | React Query hooks |
| Create | `frontend/src/components/MetaProfileEditor.tsx` | curation UI |
| Modify | `ontoexplorer/models/db.py` | add `OntologyMetaProfile` model |
| Modify | `ontoexplorer/modules/jobs/tasks.py` | add `detect_meta_profile` task |
| Modify | `ontoexplorer/modules/ingestion/pipeline.py:228-229` | enqueue `detect_meta_profile` |
| Modify | `ontoexplorer/main.py` | register `meta_profile_router` |
| Modify | `ontoexplorer/api/ontologies.py:330-395` | enrich list with resolved title/description |
| Modify | `frontend/src/lib/api.ts` | types + `api.ontologies.meta.*` + `api.meta.bulk()` |
| Modify | `frontend/src/pages/OntologyPage.tsx` | Metadata tab, MetaBanner, structured Info |
| Modify | `frontend/src/pages/Ontologies.tsx` | show resolved title |
| Modify | `frontend/src/pages/AdminPage.tsx` | title column |

---

## Task 1: OntologyMetaProfile DB Model + Migration

**Files:**
- Modify: `ontoexplorer/models/db.py`
- Create: `alembic/versions/a1b2c3d4e5f6_ontology_meta_profiles.py`
- Test: `tests/integration/test_meta_profile.py`

- [ ] **Step 1: Write the failing model test**

Create `tests/integration/test_meta_profile.py`:

```python
import pytest
from ontoexplorer.models.db import OntologyMetaProfile


def test_ontology_meta_profile_model_fields():
    p = OntologyMetaProfile(
        version_id="vid-1",
        title_props=["http://purl.org/dc/terms/title"],
        shortname_props=[],
        description_props=[],
        creator_props=[],
        contributor_props=[],
        publisher_props=[],
        license_props=[],
        homepage_props=[],
        version_info_props=[],
        prefix_props=[],
        namespace_uri_props=[],
        created_props=[],
        modified_props=[],
        language_props=[],
        citation_props=[],
        funding_props=[],
        status_props=[],
        syntax_props=[],
        resolved={},
        candidates_data={},
        status="auto_detected",
    )
    assert p.version_id == "vid-1"
    assert p.title_props == ["http://purl.org/dc/terms/title"]
    assert p.status == "auto_detected"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /path/to/ontoexplorer
uv run pytest tests/integration/test_meta_profile.py::test_ontology_meta_profile_model_fields -v
```
Expected: FAIL with `ImportError: cannot import name 'OntologyMetaProfile'`

- [ ] **Step 3: Add OntologyMetaProfile to models/db.py**

Append at the end of `ontoexplorer/models/db.py` (after the `OntologyProfile` class):

```python
class OntologyMetaProfile(Base):
    __tablename__ = "ontology_meta_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), unique=True
    )
    title_props: Mapped[list] = mapped_column(JSON, default=list)
    shortname_props: Mapped[list] = mapped_column(JSON, default=list)
    description_props: Mapped[list] = mapped_column(JSON, default=list)
    creator_props: Mapped[list] = mapped_column(JSON, default=list)
    contributor_props: Mapped[list] = mapped_column(JSON, default=list)
    publisher_props: Mapped[list] = mapped_column(JSON, default=list)
    license_props: Mapped[list] = mapped_column(JSON, default=list)
    homepage_props: Mapped[list] = mapped_column(JSON, default=list)
    version_info_props: Mapped[list] = mapped_column(JSON, default=list)
    prefix_props: Mapped[list] = mapped_column(JSON, default=list)
    namespace_uri_props: Mapped[list] = mapped_column(JSON, default=list)
    created_props: Mapped[list] = mapped_column(JSON, default=list)
    modified_props: Mapped[list] = mapped_column(JSON, default=list)
    language_props: Mapped[list] = mapped_column(JSON, default=list)
    citation_props: Mapped[list] = mapped_column(JSON, default=list)
    funding_props: Mapped[list] = mapped_column(JSON, default=list)
    status_props: Mapped[list] = mapped_column(JSON, default=list)
    syntax_props: Mapped[list] = mapped_column(JSON, default=list)
    resolved: Mapped[dict] = mapped_column(JSON, default=dict)
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
uv run pytest tests/integration/test_meta_profile.py::test_ontology_meta_profile_model_fields -v
```
Expected: PASS

- [ ] **Step 5: Create Alembic migration**

Create `alembic/versions/a1b2c3d4e5f6_ontology_meta_profiles.py`:

```python
"""add ontology_meta_profiles table

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ontology_meta_profiles',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('version_id', sa.String(), nullable=False),
        sa.Column('title_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('shortname_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('description_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('creator_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('contributor_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('publisher_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('license_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('homepage_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('version_info_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('prefix_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('namespace_uri_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('modified_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('language_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('citation_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('funding_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('status_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('syntax_props', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('resolved', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('candidates_data', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(), nullable=False, server_default='auto_detected'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['version_id'], ['versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_id'),
    )


def downgrade() -> None:
    op.drop_table('ontology_meta_profiles')
```

- [ ] **Step 6: Apply migration inside the API container**

```bash
docker compose exec api uv run alembic upgrade head
```
Expected: output ends with `Running upgrade f1a2b3c4d5e6 -> a1b2c3d4e5f6, add ontology_meta_profiles table`

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/models/db.py alembic/versions/a1b2c3d4e5f6_ontology_meta_profiles.py tests/integration/test_meta_profile.py
git commit -m "feat(meta-profile): OntologyMetaProfile model and migration"
```

---

## Task 2: Curated Meta-Profile Registry

**Files:**
- Create: `ontoexplorer/modules/meta_profile/__init__.py`
- Create: `ontoexplorer/modules/meta_profile/registry.py`
- Test: `tests/integration/test_meta_profile.py` (append)

- [ ] **Step 1: Write failing registry tests**

Append to `tests/integration/test_meta_profile.py`:

```python
from ontoexplorer.modules.meta_profile.registry import (
    ALL_META_ROLES,
    MULTI_VALUE_ROLES,
    ROLE_RESOLVED_KEY,
    default_meta_profile,
)


def test_registry_all_meta_roles_has_18_roles():
    assert len(ALL_META_ROLES) == 18


def test_registry_title_props_dcterms_first():
    assert ALL_META_ROLES["title"][0] == "http://purl.org/dc/terms/title"


def test_registry_multi_value_roles():
    assert MULTI_VALUE_ROLES == {"creator", "contributor", "publisher"}


def test_registry_role_resolved_key_creator_is_plural():
    assert ROLE_RESOLVED_KEY["creator"] == "creators"
    assert ROLE_RESOLVED_KEY["contributor"] == "contributors"
    assert ROLE_RESOLVED_KEY["publisher"] == "publishers"


def test_default_meta_profile_has_all_roles():
    p = default_meta_profile()
    for role in ALL_META_ROLES:
        assert f"{role}_props" in p
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_meta_profile.py -k "registry" -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create package and registry files**

Create `ontoexplorer/modules/meta_profile/__init__.py` (empty file).

Create `ontoexplorer/modules/meta_profile/registry.py`:

```python
from __future__ import annotations

TITLE_PROPS: list[str] = [
    "http://purl.org/dc/terms/title",
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://purl.org/dc/elements/1.1/title",
]

SHORTNAME_PROPS: list[str] = [
    "http://purl.org/dc/terms/alternative",
    "http://www.w3.org/2002/07/owl#acronym",
    "http://purl.org/vocab/vann/preferredNamespacePrefix",
]

DESCRIPTION_PROPS: list[str] = [
    "http://purl.org/dc/terms/description",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://purl.org/dc/elements/1.1/description",
]

CREATOR_PROPS: list[str] = [
    "http://purl.org/dc/terms/creator",
    "http://purl.org/dc/elements/1.1/creator",
    "http://purl.org/pav/authoredBy",
]

CONTRIBUTOR_PROPS: list[str] = [
    "http://purl.org/dc/terms/contributor",
]

PUBLISHER_PROPS: list[str] = [
    "http://purl.org/dc/terms/publisher",
]

LICENSE_PROPS: list[str] = [
    "http://purl.org/dc/terms/license",
    "http://purl.org/dc/terms/rights",
]

HOMEPAGE_PROPS: list[str] = [
    "http://xmlns.com/foaf/0.1/homepage",
    "http://www.w3.org/ns/dcat#accessURL",
    "https://schema.org/includedInDataCatalog",
]

VERSION_INFO_PROPS: list[str] = [
    "http://www.w3.org/2002/07/owl#versionInfo",
]

PREFIX_PROPS: list[str] = [
    "http://purl.org/vocab/vann/preferredNamespacePrefix",
]

NAMESPACE_URI_PROPS: list[str] = [
    "http://purl.org/vocab/vann/preferredNamespaceUri",
]

CREATED_PROPS: list[str] = [
    "http://purl.org/dc/terms/created",
    "http://purl.org/dc/terms/issued",
]

MODIFIED_PROPS: list[str] = [
    "http://purl.org/dc/terms/modified",
]

LANGUAGE_PROPS: list[str] = [
    "http://purl.org/dc/terms/language",
]

CITATION_PROPS: list[str] = [
    "http://purl.org/dc/terms/bibliographicCitation",
]

FUNDING_PROPS: list[str] = [
    "https://schema.org/funding",
]

STATUS_PROPS: list[str] = [
    "https://w3id.org/mod#status",
]

SYNTAX_PROPS: list[str] = [
    "https://w3id.org/mod#hasSyntax",
    "https://w3id.org/mod#hasRepresentationLanguage",
]

ALL_META_ROLES: dict[str, list[str]] = {
    "title": TITLE_PROPS,
    "shortname": SHORTNAME_PROPS,
    "description": DESCRIPTION_PROPS,
    "creator": CREATOR_PROPS,
    "contributor": CONTRIBUTOR_PROPS,
    "publisher": PUBLISHER_PROPS,
    "license": LICENSE_PROPS,
    "homepage": HOMEPAGE_PROPS,
    "version_info": VERSION_INFO_PROPS,
    "prefix": PREFIX_PROPS,
    "namespace_uri": NAMESPACE_URI_PROPS,
    "created": CREATED_PROPS,
    "modified": MODIFIED_PROPS,
    "language": LANGUAGE_PROPS,
    "citation": CITATION_PROPS,
    "funding": FUNDING_PROPS,
    "status": STATUS_PROPS,
    "syntax": SYNTAX_PROPS,
}

MULTI_VALUE_ROLES: set[str] = {"creator", "contributor", "publisher"}

ROLE_RESOLVED_KEY: dict[str, str] = {
    "title": "title",
    "shortname": "shortname",
    "description": "description",
    "creator": "creators",
    "contributor": "contributors",
    "publisher": "publishers",
    "license": "license",
    "homepage": "homepage",
    "version_info": "version_info",
    "prefix": "prefix",
    "namespace_uri": "namespace_uri",
    "created": "created",
    "modified": "modified",
    "language": "language",
    "citation": "citation",
    "funding": "funding",
    "status": "status",
    "syntax": "syntax",
}

ALL_KNOWN_IRIS: set[str] = {iri for iris in ALL_META_ROLES.values() for iri in iris}


def default_meta_profile() -> dict[str, list[str]]:
    """Return registry defaults keyed as column names (role_props)."""
    return {f"{role}_props": iris[:] for role, iris in ALL_META_ROLES.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_meta_profile.py -k "registry" -v
```
Expected: all 5 PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/meta_profile/ tests/integration/test_meta_profile.py
git commit -m "feat(meta-profile): curated 18-role registry"
```

---

## Task 3: Meta-Profile Detector

**Files:**
- Create: `ontoexplorer/modules/meta_profile/detector.py`
- Test: `tests/integration/test_meta_profile.py` (append)

- [ ] **Step 1: Write failing detector tests**

Append to `tests/integration/test_meta_profile.py`:

```python
from unittest.mock import patch, MagicMock, AsyncMock
from ontoexplorer.modules.meta_profile.detector import (
    _fetch_onto_triples,
    _resolve_values,
    _build_role_props,
)
from ontoexplorer.modules.meta_profile.registry import ALL_META_ROLES, ROLE_RESOLVED_KEY


def test_fetch_onto_triples_returns_dict():
    mock_rows = [
        {
            "pred": MagicMock(value="http://purl.org/dc/terms/title"),
            "obj": MagicMock(value="My Ontology", language="en", spec=["value", "language"]),
        }
    ]
    with patch("ontoexplorer.modules.meta_profile.detector.sparql_query", return_value=mock_rows):
        result = _fetch_onto_triples("urn:graph:test", "http://example.org/onto")
    assert "http://purl.org/dc/terms/title" in result
    assert result["http://purl.org/dc/terms/title"][0]["value"] == "My Ontology"
    assert result["http://purl.org/dc/terms/title"][0]["language"] == "en"


def test_fetch_onto_triples_empty_graph():
    with patch("ontoexplorer.modules.meta_profile.detector.sparql_query", return_value=[]):
        result = _fetch_onto_triples("urn:graph:empty", "http://example.org/onto")
    assert result == {}


def test_resolve_values_single_role():
    triples = {
        "http://purl.org/dc/terms/title": [
            {"value": "My Ontology", "is_iri": False, "language": "en"}
        ]
    }
    role_props = {"title": ["http://purl.org/dc/terms/title"]}
    result = _resolve_values(triples, role_props)
    assert result["title"] == "My Ontology"


def test_resolve_values_multi_role_collects_all():
    triples = {
        "http://purl.org/dc/terms/creator": [
            {"value": "https://orcid.org/0000-0001", "is_iri": True, "language": None},
            {"value": "https://orcid.org/0000-0002", "is_iri": True, "language": None},
        ]
    }
    role_props = {"creator": ["http://purl.org/dc/terms/creator"]}
    result = _resolve_values(triples, role_props)
    assert result["creators"] == ["https://orcid.org/0000-0001", "https://orcid.org/0000-0002"]


def test_resolve_values_prefers_english():
    triples = {
        "http://purl.org/dc/terms/title": [
            {"value": "Mon Ontologie", "is_iri": False, "language": "fr"},
            {"value": "My Ontology", "is_iri": False, "language": "en"},
        ]
    }
    role_props = {"title": ["http://purl.org/dc/terms/title"]}
    result = _resolve_values(triples, role_props)
    assert result["title"] == "My Ontology"


def test_resolve_values_missing_role_returns_none():
    triples = {}
    role_props = {"title": ["http://purl.org/dc/terms/title"]}
    result = _resolve_values(triples, role_props)
    assert result["title"] is None


def test_build_role_props_only_detected():
    triples = {
        "http://purl.org/dc/terms/title": [{"value": "X", "is_iri": False, "language": None}],
    }
    result = _build_role_props(
        ["http://purl.org/dc/terms/title", "http://www.w3.org/2000/01/rdf-schema#label"],
        triples,
    )
    assert result == ["http://purl.org/dc/terms/title"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_meta_profile.py -k "fetch_onto or resolve_values or build_role_props" -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create detector.py**

Create `ontoexplorer/modules/meta_profile/detector.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion
from ontoexplorer.modules.meta_profile.registry import (
    ALL_KNOWN_IRIS,
    ALL_META_ROLES,
    MULTI_VALUE_ROLES,
    ROLE_RESOLVED_KEY,
    default_meta_profile,
)


async def run_meta_detection(
    db: AsyncSession, version_id: str, ontology_id: str = ""
) -> None:
    """Detect ontology-level metadata from the owl:Ontology node and write profile row."""
    if not ontology_id:
        r = await db.execute(
            select(OntologyVersion.ontology_id).where(OntologyVersion.id == version_id)
        )
        ontology_id = r.scalar_one()

    r2 = await db.execute(select(Ontology.iri).where(Ontology.id == ontology_id))
    onto_iri = r2.scalar_one()

    named_graph = graph_iri(ontology_id, version_id)
    triples = await asyncio.to_thread(_fetch_onto_triples, named_graph, onto_iri)

    role_props: dict[str, list[str]] = {
        role: _build_role_props(iris, triples)
        for role, iris in ALL_META_ROLES.items()
    }
    resolved = _resolve_values(triples, role_props)

    candidates: dict = {
        role: [
            {"iri": iri, "values": triples[iri]}
            for iri in iris
            if iri in triples
        ]
        for role, iris in ALL_META_ROLES.items()
    }
    candidates["unknown"] = [
        {"iri": pred, "values": vals}
        for pred, vals in triples.items()
        if pred not in ALL_KNOWN_IRIS
    ]

    row_kwargs = {f"{role}_props": props for role, props in role_props.items()}

    existing = (
        await db.execute(
            select(OntologyMetaProfile).where(OntologyMetaProfile.version_id == version_id)
        )
    ).scalar_one_or_none()

    if existing:
        for col, val in row_kwargs.items():
            setattr(existing, col, val)
        existing.resolved = resolved
        existing.candidates_data = candidates
        existing.status = "auto_detected"
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(OntologyMetaProfile(
            version_id=version_id,
            **row_kwargs,
            resolved=resolved,
            candidates_data=candidates,
            status="auto_detected",
        ))

    await db.commit()

    if resolved.get("shortname"):
        r3 = await db.execute(select(Ontology).where(Ontology.id == ontology_id))
        ont = r3.scalar_one_or_none()
        if ont and not ont.shortname:
            ont.shortname = resolved["shortname"]
            await db.commit()


def _fetch_onto_triples(named_graph: str, onto_iri: str) -> dict[str, list[dict]]:
    """Return all predicate→value entries on the owl:Ontology node."""
    q = f"""
        SELECT ?pred ?obj WHERE {{
            GRAPH <{named_graph}> {{
                <{onto_iri}> ?pred ?obj .
            }}
        }}
    """
    triples: dict[str, list[dict]] = {}
    for row in sparql_query(q):
        pred = row["pred"].value
        obj = row["obj"]
        entry = {
            "value": obj.value,
            "is_iri": not hasattr(obj, "language"),
            "language": getattr(obj, "language", None),
        }
        triples.setdefault(pred, []).append(entry)
    return triples


def _build_role_props(iris: list[str], triples: dict[str, list[dict]]) -> list[str]:
    """Return registered IRIs that are present in the triples, in registry priority order."""
    return [iri for iri in iris if iri in triples]


def _resolve_values(
    triples: dict[str, list[dict]],
    role_props: dict[str, list[str]],
) -> dict:
    """Extract resolved scalar/list values using the role→IRI mapping."""
    resolved: dict = {}
    for role, props in role_props.items():
        key = ROLE_RESOLVED_KEY[role]
        if role in MULTI_VALUE_ROLES:
            values: list[str] = []
            for iri in props:
                for entry in triples.get(iri, []):
                    v = entry["value"]
                    if v not in values:
                        values.append(v)
            resolved[key] = values
        else:
            value = None
            for iri in props:
                entries = triples.get(iri, [])
                if entries:
                    en = next((e for e in entries if e.get("language") == "en"), None)
                    value = (en or entries[0])["value"]
                    break
            resolved[key] = value
    return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_meta_profile.py -k "fetch_onto or resolve_values or build_role_props" -v
```
Expected: all 7 PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/meta_profile/detector.py tests/integration/test_meta_profile.py
git commit -m "feat(meta-profile): SPARQL detector and resolve helpers"
```

---

## Task 4: Celery Task + Pipeline Wiring

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`
- Modify: `ontoexplorer/modules/ingestion/pipeline.py`
- Test: `tests/integration/test_meta_profile.py` (append)

- [ ] **Step 1: Write failing task tests**

Append to `tests/integration/test_meta_profile.py`:

```python
def test_detect_meta_profile_task_runs_and_returns_done():
    with patch("ontoexplorer.modules.jobs.tasks.asyncio") as mock_asyncio:
        mock_asyncio.run.return_value = None
        from ontoexplorer.modules.jobs.tasks import detect_meta_profile
        result = detect_meta_profile("vid-1", ontology_id="oid-1")
    assert result["status"] == "done"
    assert result["version_id"] == "vid-1"


def test_detect_meta_profile_task_handles_exception_gracefully():
    with patch("ontoexplorer.modules.jobs.tasks.asyncio") as mock_asyncio:
        mock_asyncio.run.side_effect = RuntimeError("oxigraph down")
        from ontoexplorer.modules.jobs.tasks import detect_meta_profile
        result = detect_meta_profile("vid-1", ontology_id="oid-1")
    assert result["status"] == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_meta_profile.py -k "detect_meta_profile_task" -v
```
Expected: FAIL with `ImportError: cannot import name 'detect_meta_profile'`

- [ ] **Step 3: Add detect_meta_profile task to tasks.py**

In `ontoexplorer/modules/jobs/tasks.py`, add this new task immediately after the `detect_profile` task (after line ~89, before `@celery_app.task(bind=True, name="ontoexplorer.ingest_ontology"`):

```python
@celery_app.task(name="ontoexplorer.detect_meta_profile")
def detect_meta_profile(version_id: str, ontology_id: str = "") -> dict:
    """Detect ontology-level metadata profile from Oxigraph and write to DB."""
    try:
        from ontoexplorer.database import make_celery_db_session
        from ontoexplorer.modules.meta_profile.detector import run_meta_detection

        async def _run():
            async with make_celery_db_session()() as db:
                await run_meta_detection(db, version_id, ontology_id)

        asyncio.run(_run())
        log.info("detect_meta_profile_done", version_id=version_id)
    except Exception as exc:
        log.error("detect_meta_profile_failed", version_id=version_id, error=str(exc))
    return {"status": "done", "version_id": version_id}
```

- [ ] **Step 4: Update pipeline.py to also enqueue detect_meta_profile**

In `ontoexplorer/modules/ingestion/pipeline.py`, find the lines (around line 228):

```python
    from ontoexplorer.modules.jobs.tasks import detect_profile
    detect_profile.delay(version_id, ontology_id=ontology_id)
```

Replace with:

```python
    from ontoexplorer.modules.jobs.tasks import detect_profile, detect_meta_profile
    detect_profile.delay(version_id, ontology_id=ontology_id)
    detect_meta_profile.delay(version_id, ontology_id=ontology_id)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_meta_profile.py -k "detect_meta_profile_task" -v
```
Expected: both PASS

- [ ] **Step 6: Rebuild the worker container to pick up the new task**

```bash
docker compose up -d --build worker
```
Expected: worker restarts without errors

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py ontoexplorer/modules/ingestion/pipeline.py tests/integration/test_meta_profile.py
git commit -m "feat(meta-profile): detect_meta_profile Celery task; enqueue after ingest"
```

---

## Task 5: Meta-Profile API Endpoints

**Files:**
- Create: `ontoexplorer/api/meta_profile.py`
- Modify: `ontoexplorer/main.py`
- Test: `tests/integration/test_meta_profile.py` (append)

- [ ] **Step 1: Write failing API tests**

Append to `tests/integration/test_meta_profile.py`:

```python
@pytest.mark.anyio
async def test_get_meta_profile_returns_404_when_missing(client, user_and_key):
    _, key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies/oid-1/vid-1/meta",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_meta_candidates_returns_404_when_missing(client, user_and_key):
    _, key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies/oid-1/vid-1/meta/candidates",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_patch_meta_validates_empty_title_props(client, user_and_key):
    _, key = user_and_key
    with patch("ontoexplorer.api.meta_profile._get_meta_profile_or_404") as mock_prof:
        mock_prof.return_value = MagicMock()
        resp = await client.patch(
            "/api/v1/ontologies/oid-1/vid-1/meta",
            json={"title_props": []},
            headers={"Authorization": f"Bearer {key}"},
        )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_post_detect_meta_returns_404_for_unknown_version(client, user_and_key):
    _, key = user_and_key
    resp = await client.post(
        "/api/v1/ontologies/oid-1/nonexistent-vid/meta/detect",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_meta_profile.py -k "meta_profile_returns_404 or meta_candidates or patch_meta_validates or post_detect_meta" -v
```
Expected: FAIL (routes not registered)

- [ ] **Step 3: Create meta_profile.py**

Create `ontoexplorer/api/meta_profile.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion, User
from ontoexplorer.modules.auth.dependencies import require_auth
from ontoexplorer.modules.meta_profile.registry import ALL_META_ROLES

router = APIRouter(prefix="/api/v1", tags=["meta-profile"])


async def _get_meta_profile_or_404(version_id: str, db: AsyncSession) -> OntologyMetaProfile:
    result = await db.execute(
        select(OntologyMetaProfile).where(OntologyMetaProfile.version_id == version_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Metadata profile not found — detection may still be running")
    return row


async def _get_version_or_404(version_id: str, db: AsyncSession) -> OntologyVersion:
    result = await db.execute(
        select(OntologyVersion).where(OntologyVersion.id == version_id)
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return v


def _meta_profile_response(p: OntologyMetaProfile) -> dict:
    d: dict = {"version_id": p.version_id}
    for role in ALL_META_ROLES:
        col = f"{role}_props"
        d[col] = getattr(p, col)
    d["resolved"] = p.resolved
    d["status"] = p.status
    d["updated_at"] = p.updated_at.isoformat() if p.updated_at else None
    return d


@router.get("/ontologies/{ontology_id}/{version_id}/meta")
async def get_meta_profile(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    return _meta_profile_response(await _get_meta_profile_or_404(version_id, db))


class MetaProfilePatch(BaseModel):
    title_props: list[str] | None = None
    shortname_props: list[str] | None = None
    description_props: list[str] | None = None
    creator_props: list[str] | None = None
    contributor_props: list[str] | None = None
    publisher_props: list[str] | None = None
    license_props: list[str] | None = None
    homepage_props: list[str] | None = None
    version_info_props: list[str] | None = None
    prefix_props: list[str] | None = None
    namespace_uri_props: list[str] | None = None
    created_props: list[str] | None = None
    modified_props: list[str] | None = None
    language_props: list[str] | None = None
    citation_props: list[str] | None = None
    funding_props: list[str] | None = None
    status_props: list[str] | None = None
    syntax_props: list[str] | None = None

    @field_validator("title_props")
    @classmethod
    def title_props_not_empty(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError("At least one title property is required")
        return v


@router.patch("/ontologies/{ontology_id}/{version_id}/meta")
async def patch_meta_profile(
    ontology_id: str,
    version_id: str,
    body: MetaProfilePatch,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_meta_profile_or_404(version_id, db)

    updated_any = False
    for role in ALL_META_ROLES:
        col = f"{role}_props"
        val = getattr(body, col, None)
        if val is not None:
            setattr(profile, col, val)
            updated_any = True

    if not updated_any:
        return _meta_profile_response(profile)

    # Re-resolve values in-process using the updated role props
    r = await db.execute(
        select(Ontology.iri).join(
            OntologyVersion, OntologyVersion.ontology_id == Ontology.id
        ).where(OntologyVersion.id == version_id)
    )
    onto_iri = r.scalar_one()

    from ontoexplorer.clients.oxigraph import graph_iri
    from ontoexplorer.modules.meta_profile.detector import _fetch_onto_triples, _resolve_values

    named_graph = graph_iri(ontology_id, version_id)
    triples = await asyncio.to_thread(_fetch_onto_triples, named_graph, onto_iri)
    new_role_props = {role: getattr(profile, f"{role}_props") for role in ALL_META_ROLES}
    profile.resolved = _resolve_values(triples, new_role_props)
    profile.status = "user_confirmed"
    profile.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(profile)
    return _meta_profile_response(profile)


@router.post("/ontologies/{ontology_id}/{version_id}/meta/detect")
async def trigger_meta_detect(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    await _get_version_or_404(version_id, db)
    from ontoexplorer.modules.jobs.tasks import detect_meta_profile
    task = detect_meta_profile.delay(version_id, ontology_id=ontology_id)
    return {"task_id": task.id, "status": "queued"}


@router.get("/ontologies/{ontology_id}/{version_id}/meta/candidates")
async def get_meta_candidates(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    profile = await _get_meta_profile_or_404(version_id, db)
    return {"version_id": version_id, **profile.candidates_data}


@router.get("/meta")
async def get_bulk_meta(
    ids: str = Query(..., description="Comma-separated ontology IDs"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_auth),
):
    """Return harmonized resolved metadata for multiple ontologies (latest ready version each)."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        return []

    result = await db.execute(
        select(
            OntologyVersion.ontology_id,
            OntologyVersion.id.label("version_id"),
            OntologyMetaProfile.resolved,
            OntologyMetaProfile.status.label("profile_status"),
        )
        .join(OntologyMetaProfile, OntologyMetaProfile.version_id == OntologyVersion.id)
        .where(
            OntologyVersion.ontology_id.in_(id_list),
            OntologyVersion.status == "ready",
        )
        .order_by(OntologyVersion.ontology_id, OntologyVersion.created_at.desc())
    )
    rows = result.all()

    seen: set[str] = set()
    items = []
    for row in rows:
        if row.ontology_id not in seen:
            seen.add(row.ontology_id)
            items.append({
                "ontology_id": row.ontology_id,
                "version_id": row.version_id,
                "profile_status": row.profile_status,
                **(row.resolved or {}),
            })
    return items
```

- [ ] **Step 4: Register router in main.py**

In `ontoexplorer/main.py`, add the import after the existing profile import:

```python
from ontoexplorer.api.meta_profile import router as meta_profile_router
```

And add before `profile_router` in the `include_router` block (meta endpoints also have static paths that must precede `ontologies_router`):

```python
    app.include_router(meta_profile_router)
    # profile_router before ontologies_router: /profile and /profile/candidates static
    app.include_router(profile_router)
    app.include_router(ontologies_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_meta_profile.py -k "meta_profile_returns_404 or meta_candidates or patch_meta_validates or post_detect_meta" -v
```
Expected: all 4 PASS

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/meta_profile.py ontoexplorer/main.py tests/integration/test_meta_profile.py
git commit -m "feat(meta-profile): 5 API endpoints (GET/PATCH/detect/candidates/bulk)"
```

---

## Task 6: Enrich /ontologies List with Resolved Title + Description

**Files:**
- Modify: `ontoexplorer/api/ontologies.py`
- Test: `tests/integration/test_meta_profile.py` (append)

The `list_ontologies` handler already sets `d["label"]` and `d["description"]` (currently from a Redis cache that never populates them). This task overwrites those with values from `ontology_meta_profiles.resolved`.

- [ ] **Step 1: Write failing enrichment test**

Append to `tests/integration/test_meta_profile.py`:

```python
@pytest.mark.anyio
async def test_list_ontologies_includes_label_field(client, user_and_key):
    _, key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    for ont in data.get("ontologies", []):
        assert "label" in ont
        assert "description" in ont
```

- [ ] **Step 2: Run test to verify it passes already (fields exist, just empty)**

```bash
uv run pytest tests/integration/test_meta_profile.py::test_list_ontologies_includes_label_field -v
```
Expected: PASS (fields already present, just empty strings — this test only checks presence)

- [ ] **Step 3: Add resolved-metadata batch load to list_ontologies**

In `ontoexplorer/api/ontologies.py`, locate the `list_ontologies` function. After the `stats_by_vid` batch-load block (around line 370, after the `except Exception: pass` line), add:

```python
    # Batch-load resolved metadata from ontology_meta_profiles
    from ontoexplorer.models.db import OntologyMetaProfile
    meta_by_oid: dict[str, dict] = {}
    if ontology_ids:
        subq2 = (
            select(
                OntologyVersion.ontology_id,
                func.max(OntologyVersion.created_at).label("max_created"),
            )
            .where(
                OntologyVersion.ontology_id.in_(ontology_ids),
                OntologyVersion.status == "ready",
            )
            .group_by(OntologyVersion.ontology_id)
            .subquery()
        )
        mr = await db.execute(
            select(OntologyVersion.ontology_id, OntologyMetaProfile.resolved)
            .join(
                subq2,
                (OntologyVersion.ontology_id == subq2.c.ontology_id)
                & (OntologyVersion.created_at == subq2.c.max_created),
            )
            .join(OntologyMetaProfile, OntologyMetaProfile.version_id == OntologyVersion.id)
        )
        for row in mr.all():
            meta_by_oid[row.ontology_id] = row.resolved or {}
```

Then, in the `rows` building loop, find these two lines inside the `if v:` block:

```python
            d["label"] = s.get("label") or ""
            d["description"] = s.get("description") or ""
```

Replace with:

```python
            meta = meta_by_oid.get(o.id, {})
            d["label"] = meta.get("title") or s.get("label") or ""
            d["description"] = meta.get("description") or s.get("description") or ""
```

And find the `else:` branch lines:

```python
            d["label"] = ""
            d["description"] = ""
```

Replace with:

```python
            meta = meta_by_oid.get(o.id, {})
            d["label"] = meta.get("title") or ""
            d["description"] = meta.get("description") or ""
```

- [ ] **Step 4: Run all meta profile tests**

```bash
uv run pytest tests/integration/test_meta_profile.py -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/api/ontologies.py tests/integration/test_meta_profile.py
git commit -m "feat(meta-profile): enrich /ontologies list with resolved title and description"
```

---

## Task 7: Frontend Types + Hooks

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/hooks/useOntologyMeta.ts`

- [ ] **Step 1: Add types and API methods to api.ts**

In `frontend/src/lib/api.ts`, add these interfaces after the `ProfilePatch` interface block:

```typescript
// ── Meta-profile types ────────────────────────────────────────────────────────

export interface OntologyMetaResolved {
  title: string | null
  shortname: string | null
  description: string | null
  creators: string[]
  contributors: string[]
  publishers: string[]
  license: string | null
  homepage: string | null
  version_info: string | null
  prefix: string | null
  namespace_uri: string | null
  created: string | null
  modified: string | null
  language: string | null
  citation: string | null
  funding: string | null
  status: string | null
  syntax: string | null
}

export interface OntologyMetaProfile {
  version_id: string
  title_props: string[]
  shortname_props: string[]
  description_props: string[]
  creator_props: string[]
  contributor_props: string[]
  publisher_props: string[]
  license_props: string[]
  homepage_props: string[]
  version_info_props: string[]
  prefix_props: string[]
  namespace_uri_props: string[]
  created_props: string[]
  modified_props: string[]
  language_props: string[]
  citation_props: string[]
  funding_props: string[]
  status_props: string[]
  syntax_props: string[]
  resolved: OntologyMetaResolved
  status: 'auto_detected' | 'user_confirmed'
  updated_at: string | null
}

export interface MetaProfilePatch {
  title_props?: string[]
  shortname_props?: string[]
  description_props?: string[]
  creator_props?: string[]
  contributor_props?: string[]
  publisher_props?: string[]
  license_props?: string[]
  homepage_props?: string[]
  version_info_props?: string[]
  prefix_props?: string[]
  namespace_uri_props?: string[]
  created_props?: string[]
  modified_props?: string[]
  language_props?: string[]
  citation_props?: string[]
  funding_props?: string[]
  status_props?: string[]
  syntax_props?: string[]
}

export interface BulkMetaItem extends OntologyMetaResolved {
  ontology_id: string
  version_id: string
  profile_status: string
}
```

In the `api` object, add a `meta` sub-object inside `ontologies` (alongside the existing `profile` sub-object):

```typescript
      meta: {
        get: (ontologyId: string, versionId: string) =>
          request<OntologyMetaProfile>(`/ontologies/${ontologyId}/${versionId}/meta`),
        patch: (ontologyId: string, versionId: string, body: MetaProfilePatch) =>
          request<OntologyMetaProfile>(`/ontologies/${ontologyId}/${versionId}/meta`, {
            method: 'PATCH',
            body: JSON.stringify(body),
          }),
        detect: (ontologyId: string, versionId: string) =>
          request<{ task_id: string; status: string }>(
            `/ontologies/${ontologyId}/${versionId}/meta/detect`,
            { method: 'POST' }
          ),
        candidates: (ontologyId: string, versionId: string) =>
          request<{ version_id: string; [key: string]: unknown }>(
            `/ontologies/${ontologyId}/${versionId}/meta/candidates`
          ),
      },
```

Also add a top-level `meta` object to the `api` export (at the same level as `ontologies`):

```typescript
  meta: {
    bulk: (ids: string[]) =>
      request<BulkMetaItem[]>(`/meta?ids=${ids.join(',')}`),
  },
```

- [ ] **Step 2: Create useOntologyMeta.ts**

Create `frontend/src/hooks/useOntologyMeta.ts`:

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyMetaProfile, MetaProfilePatch } from '../lib/api'

export function useOntologyMeta(
  ontologyId: string | undefined,
  versionId: string | undefined,
) {
  return useQuery<OntologyMetaProfile>({
    queryKey: ['meta-profile', ontologyId, versionId],
    queryFn: () => api.ontologies.meta.get(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    retry: false,
  })
}

export function useMetaCandidates(
  ontologyId: string | undefined,
  versionId: string | undefined,
) {
  return useQuery<{ version_id: string; [key: string]: unknown }>({
    queryKey: ['meta-candidates', ontologyId, versionId],
    queryFn: () => api.ontologies.meta.candidates(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    retry: false,
  })
}

export function usePatchMeta(ontologyId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: MetaProfilePatch) =>
      api.ontologies.meta.patch(ontologyId, versionId, body),
    onSuccess: (data) => {
      qc.setQueryData(['meta-profile', ontologyId, versionId], data)
    },
  })
}

export function useDetectMeta(ontologyId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.ontologies.meta.detect(ontologyId, versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['meta-profile', ontologyId, versionId] })
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
git add frontend/src/lib/api.ts frontend/src/hooks/useOntologyMeta.ts
git commit -m "feat(meta-profile): frontend types, API client, and React Query hooks"
```

---

## Task 8: MetaProfileEditor Component

**Files:**
- Create: `frontend/src/components/MetaProfileEditor.tsx`

- [ ] **Step 1: Create MetaProfileEditor.tsx**

Create `frontend/src/components/MetaProfileEditor.tsx`:

```typescript
import { useState } from 'react'
import { useOntologyMeta, useMetaCandidates, usePatchMeta, useDetectMeta } from '../hooks/useOntologyMeta'
import { MetaProfilePatch } from '../lib/api'

const ROLE_LABELS: Record<string, string> = {
  title_props: 'Title',
  shortname_props: 'Shortname / Acronym',
  description_props: 'Description',
  creator_props: 'Creator',
  contributor_props: 'Contributor',
  publisher_props: 'Publisher',
  license_props: 'License',
  homepage_props: 'Homepage',
  version_info_props: 'Version Info',
  prefix_props: 'Namespace Prefix',
  namespace_uri_props: 'Namespace URI',
  created_props: 'Created',
  modified_props: 'Modified',
  language_props: 'Language',
  citation_props: 'Citation',
  funding_props: 'Funding',
  status_props: 'Status',
  syntax_props: 'Syntax',
}

const IRI_LABELS: Record<string, string> = {
  'http://purl.org/dc/terms/title': 'dcterms:title',
  'http://www.w3.org/2000/01/rdf-schema#label': 'rdfs:label',
  'http://purl.org/dc/elements/1.1/title': 'dc:title',
  'http://purl.org/dc/terms/alternative': 'dcterms:alternative',
  'http://www.w3.org/2002/07/owl#acronym': 'owl:acronym',
  'http://purl.org/vocab/vann/preferredNamespacePrefix': 'vann:preferredNamespacePrefix',
  'http://purl.org/dc/terms/description': 'dcterms:description',
  'http://www.w3.org/2000/01/rdf-schema#comment': 'rdfs:comment',
  'http://purl.org/dc/elements/1.1/description': 'dc:description',
  'http://purl.org/dc/terms/creator': 'dcterms:creator',
  'http://purl.org/dc/elements/1.1/creator': 'dc:creator',
  'http://purl.org/pav/authoredBy': 'pav:authoredBy',
  'http://purl.org/dc/terms/contributor': 'dcterms:contributor',
  'http://purl.org/dc/terms/publisher': 'dcterms:publisher',
  'http://purl.org/dc/terms/license': 'dcterms:license',
  'http://purl.org/dc/terms/rights': 'dcterms:rights',
  'http://xmlns.com/foaf/0.1/homepage': 'foaf:homepage',
  'http://www.w3.org/ns/dcat#accessURL': 'dcat:accessURL',
  'https://schema.org/includedInDataCatalog': 'schema:includedInDataCatalog',
  'http://www.w3.org/2002/07/owl#versionInfo': 'owl:versionInfo',
  'http://purl.org/vocab/vann/preferredNamespaceUri': 'vann:preferredNamespaceUri',
  'http://purl.org/dc/terms/created': 'dcterms:created',
  'http://purl.org/dc/terms/issued': 'dcterms:issued',
  'http://purl.org/dc/terms/modified': 'dcterms:modified',
  'http://purl.org/dc/terms/language': 'dcterms:language',
  'http://purl.org/dc/terms/bibliographicCitation': 'dcterms:bibliographicCitation',
  'https://schema.org/funding': 'schema:funding',
  'https://w3id.org/mod#status': 'mod:status',
  'https://w3id.org/mod#hasSyntax': 'mod:hasSyntax',
  'https://w3id.org/mod#hasRepresentationLanguage': 'mod:hasRepresentationLanguage',
}

const ALL_ROLE_COLS = Object.keys(ROLE_LABELS) as (keyof MetaProfilePatch)[]

function shortIri(iri: string): string {
  return IRI_LABELS[iri] ?? iri.split(/[/#]/).pop() ?? iri
}

function PropChip({
  iri, onRemove,
}: { iri: string; onRemove: () => void }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: 'var(--bg)', border: '1px solid var(--border)',
      borderRadius: 4, padding: '2px 6px', fontSize: 11, color: 'var(--text)',
    }}>
      <span title={iri}>{shortIri(iri)}</span>
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
  col, props, candidateIris, onRemove, onAdd,
}: {
  col: keyof MetaProfilePatch
  props: string[]
  candidateIris: string[]
  onRemove: (iri: string) => void
  onAdd: (iri: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [custom, setCustom] = useState('')
  const available = candidateIris.filter(iri => !props.includes(iri))

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 5 }}>
        {ROLE_LABELS[col]}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 3 }}>
        {props.length === 0 && (
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>(none)</span>
        )}
        {props.map(iri => (
          <PropChip key={iri} iri={iri} onRemove={() => onRemove(iri)} />
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
              {shortIri(iri)}
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

export default function MetaProfileEditor({
  ontologyId,
  versionId,
}: {
  ontologyId: string
  versionId: string
}) {
  const { data: profile, isLoading: profileLoading } = useOntologyMeta(ontologyId, versionId)
  const { data: candidates } = useMetaCandidates(ontologyId, versionId)
  const patch = usePatchMeta(ontologyId, versionId)
  const detect = useDetectMeta(ontologyId, versionId)

  const [edits, setEdits] = useState<Partial<MetaProfilePatch>>({})

  if (profileLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>Loading…</div>
  }

  if (!profile) {
    return (
      <div style={{ padding: '1rem' }}>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 12 }}>
          No metadata profile detected yet.
        </div>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{
            padding: '6px 14px', borderRadius: 4, border: 'none',
            background: 'var(--accent)', color: '#000', fontSize: 12, cursor: 'pointer',
          }}
        >
          {detect.isPending ? 'Running…' : 'Detect Metadata'}
        </button>
      </div>
    )
  }

  const current = ALL_ROLE_COLS.reduce((acc, col) => {
    acc[col] = (edits[col] ?? (profile as any)[col]) as string[]
    return acc
  }, {} as Record<keyof MetaProfilePatch, string[]>)

  // Build candidate IRI lists per role from candidates_data
  const candidatesByCol: Record<string, string[]> = {}
  for (const col of ALL_ROLE_COLS) {
    const role = col.replace(/_props$/, '')
    const roleData = (candidates as any)?.[role]
    candidatesByCol[col] = Array.isArray(roleData)
      ? roleData.map((c: { iri: string }) => c.iri)
      : []
  }

  const isDirty = Object.keys(edits).length > 0

  return (
    <div style={{ padding: '12px 16px', overflowY: 'auto', flex: 1 }}>
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

      {ALL_ROLE_COLS.map(col => (
        <RoleSection
          key={col}
          col={col}
          props={current[col] ?? []}
          candidateIris={candidatesByCol[col] ?? []}
          onRemove={iri => setEdits(prev => ({ ...prev, [col]: (current[col] ?? []).filter(p => p !== iri) }))}
          onAdd={iri => setEdits(prev => ({ ...prev, [col]: [...(current[col] ?? []), iri] }))}
        />
      ))}

      <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
        <button
          onClick={() =>
            patch.mutate(
              ALL_ROLE_COLS.reduce((acc, col) => {
                acc[col] = current[col]
                return acc
              }, {} as MetaProfilePatch),
              { onSuccess: () => setEdits({}) }
            )
          }
          disabled={!isDirty || patch.isPending}
          style={{
            padding: '6px 16px', borderRadius: 4, border: 'none',
            background: isDirty ? 'var(--accent)' : 'var(--bg-secondary)',
            color: isDirty ? '#000' : 'var(--text-dim)',
            fontSize: 12, cursor: isDirty ? 'pointer' : 'default',
          }}
        >
          {patch.isPending ? 'Saving…' : 'Save and re-resolve'}
        </button>
        {patch.isSuccess && (
          <span style={{ marginLeft: 10, color: '#3fb950', fontSize: 11 }}>✓ Saved</span>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1
```
Expected: no output

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MetaProfileEditor.tsx
git commit -m "feat(meta-profile): MetaProfileEditor component with 18 role sections"
```

---

## Task 9: OntologyPage — Metadata Tab + Structured Info Display

**Files:**
- Modify: `frontend/src/pages/OntologyPage.tsx`

- [ ] **Step 1: Add MetaBanner and Metadata tab**

In `frontend/src/pages/OntologyPage.tsx`:

**a) Add imports** at the top of the file:

```typescript
import MetaProfileEditor from '../components/MetaProfileEditor'
import { useOntologyMeta } from '../hooks/useOntologyMeta'
```

**b) Add `MetaBanner` component** before the `OntologyDocMeta` function definition:

```typescript
function MetaBanner({ ontologyId, versionId, onReview }: {
  ontologyId: string
  versionId: string
  onReview: () => void
}) {
  const { data: meta, isLoading } = useOntologyMeta(ontologyId, versionId)
  if (isLoading || !meta) return null

  const isConfirmed = meta.status === 'user_confirmed'
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '6px 12px', marginBottom: 8,
      background: isConfirmed ? 'rgba(63,185,80,0.06)' : 'rgba(88,166,255,0.06)',
      border: `1px solid ${isConfirmed ? 'rgba(63,185,80,0.2)' : 'rgba(88,166,255,0.2)'}`,
      borderRadius: 6, fontSize: 11,
    }}>
      <span style={{ color: isConfirmed ? '#3fb950' : 'var(--accent)' }}>
        {isConfirmed
          ? `● Metadata confirmed · ${meta.resolved?.title ?? ''}`
          : `Metadata auto-detected · title: ${meta.resolved?.title ?? '?'}`}
      </span>
      <button
        onClick={onReview}
        style={{ marginLeft: 'auto', color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 11 }}
      >
        {isConfirmed ? 'Edit' : 'Review →'}
      </button>
    </div>
  )
}
```

**c) Update `detailTab` state** — find:

```typescript
  const [detailTab, setDetailTab] = useState<'info' | 'profile'>('info')
```

Replace with:

```typescript
  const [detailTab, setDetailTab] = useState<'info' | 'metadata' | 'profile'>('info')
```

**d) Update the tab bar** — find:

```typescript
            {(['info', 'profile'] as const).map(tab => (
```

Replace with:

```typescript
            {(['info', 'metadata', 'profile'] as const).map(tab => (
```

**e) Add MetaBanner inside `OntologyMeta`** — find the `OntologyMeta` function's return and add the banner just before the `<OntologyDocMeta` component:

```typescript
        {onMetaReview && version && (
          <MetaBanner
            ontologyId={version.ontology_id}
            versionId={version.id}
            onReview={onMetaReview}
          />
        )}
```

To do this, first update the `OntologyMeta` function signature. Find:

```typescript
function OntologyMeta({ iri, version, onProfileReview }: {
  iri: string
  version: OntologyVersion | undefined
  onProfileReview?: () => void
}) {
```

Replace with:

```typescript
function OntologyMeta({ iri, version, onProfileReview, onMetaReview }: {
  iri: string
  version: OntologyVersion | undefined
  onProfileReview?: () => void
  onMetaReview?: () => void
}) {
```

**f) Update tab content rendering** — find:

```typescript
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
```

Replace with:

```typescript
            {detailTab === 'info' ? (
              <OntologyMeta
                iri={ontology?.iri ?? ''}
                version={activeVersion}
                onProfileReview={() => setDetailTab('profile')}
                onMetaReview={() => setDetailTab('metadata')}
              />
            ) : detailTab === 'metadata' ? (
              oid && activeVid
                ? <MetaProfileEditor ontologyId={oid} versionId={activeVid} />
                : null
            ) : (
              oid && activeVid
                ? <ProfileEditor ontologyId={oid} versionId={activeVid} />
                : null
            )}
```

- [ ] **Step 2: Type-check**

```bash
cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1
```
Expected: no output

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/OntologyPage.tsx
git commit -m "feat(meta-profile): Metadata tab, MetaBanner in OntologyPage"
```

---

## Task 10: Ontologies List + Admin Page — Show Resolved Titles

**Files:**
- Modify: `frontend/src/pages/Ontologies.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`

The `Ontology.label` field is already in the type and now populated by the enriched `/ontologies` endpoint from Task 6. This task updates the display to use it.

- [ ] **Step 1: Update Ontologies.tsx to show label when available**

In `frontend/src/pages/Ontologies.tsx`, find the ontology card rendering. Look for where the ontology name is shown — it currently shows shortname or IRI segment. Find the line that shows the ontology title text (inside the `onClick` button for each ontology row) and update it to prefer `o.label` over IRI-derived name.

Find the line that shows the ontology identifier text (currently something like the shortname/IRI). It will be inside an `<onClick>` button. The exact rendering depends on the current card layout. Find a line similar to:

```typescript
          <IriChip iri={o.iri} />
```

Directly before `<IriChip>`, add the label display:

```typescript
          {o.label && (
            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', marginBottom: 2 }}>
              {o.label}
            </div>
          )}
          {o.description && (
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 4, lineClamp: 2 }}>
              {o.description.length > 120 ? o.description.slice(0, 120) + '…' : o.description}
            </div>
          )}
```

- [ ] **Step 2: Update AdminPage.tsx to show resolved title**

In `frontend/src/pages/AdminPage.tsx`, find:

```typescript
                {row.shortname ?? row.iri.split(/[/#]/).pop()}
```

Replace with:

```typescript
                {row.label || row.shortname || row.iri.split(/[/#]/).pop()}
```

- [ ] **Step 3: Type-check**

```bash
cd /path/to/ontoexplorer/frontend && npx tsc --noEmit 2>&1
```
Expected: no output

- [ ] **Step 4: Run all backend tests**

```bash
cd /path/to/ontoexplorer
uv run pytest tests/integration/test_meta_profile.py -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Ontologies.tsx frontend/src/pages/AdminPage.tsx
git commit -m "feat(meta-profile): show resolved title on list page and admin table"
```

---

## Self-Review

**Spec coverage:**
- ✅ `ontology_meta_profiles` table with 18 role JSON columns + `resolved` + `candidates_data` (Task 1)
- ✅ Curated 18-role registry with priority-ordered IRI lists (Task 2)
- ✅ Detector: single SPARQL query, `_resolve_values`, shortname auto-population (Task 3)
- ✅ `detect_meta_profile` Celery task, independent of index chain (Task 4)
- ✅ Pipeline enqueues both `detect_profile` and `detect_meta_profile` (Task 4)
- ✅ GET / PATCH / POST detect / GET candidates / GET bulk `/meta` (Task 5)
- ✅ `/ontologies` list enriched with resolved title/description (Task 6)
- ✅ Frontend types + hooks (Task 7)
- ✅ MetaProfileEditor with 18 role sections (Task 8)
- ✅ OntologyPage: Metadata tab, MetaBanner (Task 9)
- ✅ Ontologies list + Admin show resolved title (Task 10)
- ✅ `PATCH title_props: []` → 422 validation (Task 5)
- ✅ Bulk `/meta?ids=…` silently omits ontologies with no profile (Task 5)

**Type consistency:**
- `OntologyMetaProfile` model (Task 1) → imported in `detector.py` (Task 3), `meta_profile.py` (Task 5), `ontologies.py` (Task 6)
- `_fetch_onto_triples` / `_resolve_values` defined in Task 3 → imported in `meta_profile.py` PATCH handler (Task 5)
- `ALL_META_ROLES` defined in Task 2 → used in Task 3, Task 5, Task 8 (via `ALL_ROLE_COLS`)
- `OntologyMetaProfile` TS type (Task 7) → used in hooks (Task 7), `MetaProfileEditor` (Task 8), `OntologyPage` (Task 9)
- `MetaProfilePatch` TS type (Task 7) → used in `usePatchMeta` (Task 7), `MetaProfileEditor` state (Task 8)
- `useOntologyMeta` hook (Task 7) → used in `MetaBanner` (Task 9)
