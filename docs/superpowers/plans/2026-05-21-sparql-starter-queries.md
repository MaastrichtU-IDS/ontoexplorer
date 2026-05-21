# SPARQL Starter Query Library + Admin Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a curated starter-query library to the SPARQL page sidebar (anon-readable) and an admin import flow that ingests starter libraries by paste, file, or URL — accepting both JSON-library and `.rq`-with-metadata formats.

**Architecture:** Extend the existing `saved_queries` table with `is_starter` + `category` columns and seed ~10 starters owned by a synthetic `system` user. Two new endpoints: `GET /sparql/starters` (anon) and `POST /sparql/starters/import` (admin-only). A parser module auto-detects JSON-library vs `.rq`-with-metadata. The sidebar grows a Starters tab; the admin page grows a `StarterQueriesPanel` with three import zones.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic + Pydantic + Postgres on the backend; React 18 + TypeScript + Vitest on the frontend.

**Spec:** [`docs/superpowers/specs/2026-05-21-sparql-starter-queries-design.md`](../specs/2026-05-21-sparql-starter-queries-design.md)

---

## File Map

| Path | Role |
|---|---|
| `ontoexplorer/models/db.py` | Add `is_starter` + `category` columns to `SavedQuery`. |
| `alembic/versions/d7e8f9a0b1c2_add_starter_to_saved_queries.py` | Migration: columns + system user + 10 seeded starters. |
| `ontoexplorer/modules/sparql_starters/__init__.py` | Package marker. |
| `ontoexplorer/modules/sparql_starters/parser.py` | `StarterDraft` dataclass + `detect_format`, `parse_json_library`, `parse_rq_with_metadata`. |
| `tests/unit/test_sparql_starters_parser.py` | Unit tests for the parsers. |
| `ontoexplorer/api/sparql_queries.py` | Add `GET /starters` + `POST /starters/import` endpoints; filter `is_starter=false` in `/` and `/public`. |
| `tests/integration/test_sparql_starters.py` | Integration tests for the two new endpoints. |
| `frontend/src/lib/api.ts` | Add `api.savedQueries.listStarters()` + `api.admin.importStarters(payload)` (+ types). |
| `frontend/src/components/QuerySidebar.tsx` | Add `starters` view-mode + segmented tab switch; anon-user handling. |
| `frontend/src/components/QuerySidebar.test.tsx` | New tests for the Starters view. |
| `frontend/src/components/admin/StarterQueriesPanel.tsx` | New admin panel with paste/file/URL zones. |
| `frontend/src/components/admin/StarterQueriesPanel.test.tsx` | Tests for the panel. |
| `frontend/src/pages/AdminPage.tsx` | Mount `<StarterQueriesPanel />`. |

---

## Task 1: Model + migration — `is_starter` + `category` + system user + seeded starters

This task lands all DB plumbing in one shot so subsequent backend tasks have something to query against.

**Files:**
- Modify: `ontoexplorer/models/db.py`
- Create: `alembic/versions/d7e8f9a0b1c2_add_starter_to_saved_queries.py`

- [ ] **Step 1: Extend the `SavedQuery` model**

In `ontoexplorer/models/db.py`, locate `class SavedQuery(Base):` and add the two columns just after `is_public`:

```python
    is_starter: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

- [ ] **Step 2: Create the Alembic migration**

Find the most recent revision id:

```bash
ls -1t alembic/versions/*.py | head -1
```

Use its filename's hex prefix as the `down_revision` value in the new file's `down_revision = "..."` (the engineer should read it and substitute).

Create `alembic/versions/d7e8f9a0b1c2_add_starter_to_saved_queries.py` with this content (replace `<DOWN_REVISION_ID>` with the actual previous revision hex):

```python
"""add is_starter + category to saved_queries; seed starters

Revision ID: d7e8f9a0b1c2
Revises: <DOWN_REVISION_ID>
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d7e8f9a0b1c2"
down_revision = "<DOWN_REVISION_ID>"
branch_labels = None
depends_on = None


SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"
SYSTEM_USER_PROVIDER = "system"
SYSTEM_USER_SUBJECT = "system"

STARTERS: list[dict] = [
    {
        "name": "All classes in scope",
        "description": "Every owl:Class declared in the scoped named graphs, with rdfs:label if any.",
        "category": "Exploration",
        "tags": ["owl", "class"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?cls ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?cls a owl:Class .\n"
            "    OPTIONAL { ?cls rdfs:label ?label }\n"
            "  }\n"
            "}\n"
            "LIMIT 200"
        ),
    },
    {
        "name": "All properties in scope",
        "description": "Every owl:ObjectProperty / owl:DatatypeProperty / owl:AnnotationProperty in the scoped graphs.",
        "category": "Exploration",
        "tags": ["owl", "property"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?p ?type ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    VALUES ?type { owl:ObjectProperty owl:DatatypeProperty owl:AnnotationProperty }\n"
            "    ?p a ?type .\n"
            "    OPTIONAL { ?p rdfs:label ?label }\n"
            "  }\n"
            "}\n"
            "LIMIT 200"
        ),
    },
    {
        "name": "All named individuals in scope",
        "description": "Every owl:NamedIndividual declared in the scoped graphs.",
        "category": "Exploration",
        "tags": ["owl", "individual"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT DISTINCT ?ind ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?ind a owl:NamedIndividual .\n"
            "    OPTIONAL { ?ind rdfs:label ?label }\n"
            "  }\n"
            "}\n"
            "LIMIT 200"
        ),
    },
    {
        "name": "Find term by label",
        "description": 'Replace "search text" with a partial or exact label. Case-insensitive.',
        "category": "Term lookup",
        "tags": ["label", "search"],
        "query_text": (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?term ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?term rdfs:label ?label .\n"
            "    FILTER(CONTAINS(LCASE(STR(?label)), \"search text\"))\n"
            "  }\n"
            "}\n"
            "LIMIT 100"
        ),
    },
    {
        "name": "Subclasses of class",
        "description": "Replace <URI_HERE> with a class IRI. Returns asserted direct subclasses.",
        "category": "Term lookup",
        "tags": ["subclass", "hierarchy"],
        "query_text": (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?sub ?label WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?sub rdfs:subClassOf <URI_HERE> .\n"
            "    OPTIONAL { ?sub rdfs:label ?label }\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "Inferred subClassOf chain",
        "description": "Use the Inferred reasoning mode on the scope toolbar; replace <URI_HERE>.",
        "category": "Reasoning",
        "tags": ["inferred", "subclass"],
        "query_text": (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?ancestor WHERE {\n"
            "  GRAPH ?g {\n"
            "    <URI_HERE> rdfs:subClassOf+ ?ancestor .\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "Equivalents of class",
        "description": "Replace <URI_HERE> with a class IRI.",
        "category": "Reasoning",
        "tags": ["equivalent"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "SELECT ?eq WHERE {\n"
            "  GRAPH ?g {\n"
            "    <URI_HERE> owl:equivalentClass ?eq .\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "OWL 2 DL violations: punning",
        "description": "Entities used as both class and individual (one common DL violation pattern).",
        "category": "Profile",
        "tags": ["dl", "violation", "punning"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "SELECT DISTINCT ?entity WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?entity a owl:Class .\n"
            "    ?entity a owl:NamedIndividual .\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "OWL 2 EL violations: universal restrictions",
        "description": "owl:allValuesFrom restrictions are not permitted in OWL 2 EL.",
        "category": "Profile",
        "tags": ["el", "violation"],
        "query_text": (
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            "SELECT DISTINCT ?restriction ?on ?type WHERE {\n"
            "  GRAPH ?g {\n"
            "    ?restriction a owl:Restriction ;\n"
            "                 owl:onProperty ?on ;\n"
            "                 owl:allValuesFrom ?type .\n"
            "  }\n"
            "}"
        ),
    },
    {
        "name": "Triples in V2 not in V1",
        "description": "Replace <V1_URI_HERE> and <V2_URI_HERE> with the two version graph URIs. Asymmetric diff.",
        "category": "Diff",
        "tags": ["diff", "version"],
        "query_text": (
            "SELECT ?s ?p ?o WHERE {\n"
            "  GRAPH <V2_URI_HERE> { ?s ?p ?o }\n"
            "  FILTER NOT EXISTS { GRAPH <V1_URI_HERE> { ?s ?p ?o } }\n"
            "}\n"
            "LIMIT 200"
        ),
    },
]


def upgrade() -> None:
    op.add_column(
        "saved_queries",
        sa.Column("is_starter", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "saved_queries",
        sa.Column("category", sa.String(length=64), nullable=True),
    )

    # Create the system user (owns all starter rows). Idempotent via ON CONFLICT.
    op.execute(
        sa.text(
            "INSERT INTO users (id, provider, subject, display_name, is_admin) "
            "VALUES (:id, :provider, :subject, 'System', false) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=SYSTEM_USER_ID,
            provider=SYSTEM_USER_PROVIDER,
            subject=SYSTEM_USER_SUBJECT,
        )
    )

    # Seed starters
    sq_table = sa.table(
        "saved_queries",
        sa.column("id", sa.String),
        sa.column("user_id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("query_text", sa.Text),
        sa.column("tags", sa.JSON),
        sa.column("is_public", sa.Boolean),
        sa.column("is_starter", sa.Boolean),
        sa.column("category", sa.String),
    )
    import uuid
    rows = [
        {
            "id": str(uuid.uuid4()),
            "user_id": SYSTEM_USER_ID,
            "name": s["name"],
            "description": s["description"],
            "query_text": s["query_text"],
            "tags": s["tags"],
            "is_public": True,
            "is_starter": True,
            "category": s["category"],
        }
        for s in STARTERS
    ]
    op.bulk_insert(sq_table, rows)


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM saved_queries WHERE is_starter = true AND user_id = :uid"
        ).bindparams(uid=SYSTEM_USER_ID)
    )
    op.execute(
        sa.text("DELETE FROM users WHERE id = :uid").bindparams(uid=SYSTEM_USER_ID)
    )
    op.drop_column("saved_queries", "category")
    op.drop_column("saved_queries", "is_starter")
```

Verify the `users` table has columns `id`, `provider`, `subject`, `display_name`, `is_admin`. If it has additional NOT NULL columns, extend the INSERT statement to satisfy them. Check via `grep "class User" ontoexplorer/models/db.py` and read the field list.

- [ ] **Step 3: Run the migration locally**

```bash
cd /home/micheldumontier/code/ontoexplorer
alembic upgrade head 2>&1 | tail -10
```

Expected: success message with the new revision applied.

- [ ] **Step 4: Verify the seed**

```bash
docker compose exec postgres psql -U postgres -d ontoexplorer -c "SELECT COUNT(*) FROM saved_queries WHERE is_starter = true;"
```

Expected: `10` rows.

```bash
docker compose exec postgres psql -U postgres -d ontoexplorer -c "SELECT id, display_name FROM users WHERE id = '00000000-0000-0000-0000-000000000000';"
```

Expected: one row showing the system user.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add ontoexplorer/models/db.py alembic/versions/d7e8f9a0b1c2_add_starter_to_saved_queries.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): add is_starter + category columns and seed 10 starter queries

Extends the saved_queries table with two columns, creates a synthetic
system user (UUID 00000000-...0000) to own starter rows, and seeds an
initial library spanning Exploration / Term lookup / Reasoning /
Profile / Diff categories.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Parser module — JSON library + .rq with metadata

Pure Python. No FastAPI, no DB. Easy to test first.

**Files:**
- Create: `ontoexplorer/modules/sparql_starters/__init__.py` (empty)
- Create: `ontoexplorer/modules/sparql_starters/parser.py`
- Create: `tests/unit/test_sparql_starters_parser.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sparql_starters_parser.py`:

```python
import pytest

from ontoexplorer.modules.sparql_starters.parser import (
    StarterDraft,
    detect_format,
    parse_json_library,
    parse_rq_with_metadata,
)


# ── detect_format ──────────────────────────────────────────────────────────

def test_detect_format_json_object():
    assert detect_format('{"starters": []}') == "json"


def test_detect_format_json_with_leading_whitespace():
    assert detect_format('\n  {"starters": []}') == "json"


def test_detect_format_rq_with_comment():
    assert detect_format("# @name foo\nSELECT * WHERE { ?s ?p ?o }") == "rq"


def test_detect_format_bare_sparql():
    assert detect_format("SELECT * WHERE { ?s ?p ?o }") == "rq"


def test_detect_format_empty_string_treated_as_rq():
    assert detect_format("") == "rq"


# ── parse_json_library ─────────────────────────────────────────────────────

def test_parse_json_library_minimal():
    text = '{"starters": [{"name": "n", "query_text": "SELECT *"}]}'
    drafts = parse_json_library(text)
    assert drafts == [StarterDraft(name="n", description=None, category=None, tags=[], query_text="SELECT *")]


def test_parse_json_library_full_fields():
    text = (
        '{"starters": [{'
        '"name": "All classes", "description": "desc", '
        '"category": "Exploration", "tags": ["owl", "class"], '
        '"query_text": "SELECT *"}]}'
    )
    drafts = parse_json_library(text)
    assert drafts == [StarterDraft(
        name="All classes",
        description="desc",
        category="Exploration",
        tags=["owl", "class"],
        query_text="SELECT *",
    )]


def test_parse_json_library_rejects_missing_starters_key():
    with pytest.raises(ValueError, match="starters"):
        parse_json_library('{"items": []}')


def test_parse_json_library_rejects_non_array_starters():
    with pytest.raises(ValueError, match="array"):
        parse_json_library('{"starters": "nope"}')


def test_parse_json_library_skips_entries_missing_name():
    text = '{"starters": [{"query_text": "X"}, {"name": "ok", "query_text": "Y"}]}'
    drafts = parse_json_library(text)
    # The first entry is dropped silently; the second is kept.
    assert len(drafts) == 1
    assert drafts[0].name == "ok"


def test_parse_json_library_skips_entries_missing_query_text():
    text = '{"starters": [{"name": "no query"}]}'
    assert parse_json_library(text) == []


def test_parse_json_library_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_json_library("not json")


# ── parse_rq_with_metadata ─────────────────────────────────────────────────

def test_parse_rq_with_only_name():
    text = "# @name Hello\nSELECT * WHERE { ?s ?p ?o }"
    draft = parse_rq_with_metadata(text)
    assert draft == StarterDraft(
        name="Hello", description=None, category=None, tags=[],
        query_text="SELECT * WHERE { ?s ?p ?o }",
    )


def test_parse_rq_with_full_metadata():
    text = (
        "# @name Subclasses\n"
        "# @description Replace <URI_HERE>.\n"
        "# @category Term lookup\n"
        "# @tags subclass, hierarchy\n"
        "\n"
        "SELECT ?s WHERE { ?s rdfs:subClassOf <URI_HERE> }"
    )
    draft = parse_rq_with_metadata(text)
    assert draft.name == "Subclasses"
    assert draft.description == "Replace <URI_HERE>."
    assert draft.category == "Term lookup"
    assert draft.tags == ["subclass", "hierarchy"]
    assert draft.query_text == "SELECT ?s WHERE { ?s rdfs:subClassOf <URI_HERE> }"


def test_parse_rq_tolerates_blank_lines_between_metadata():
    text = "# @name X\n\n# @category C\n\nSELECT *"
    draft = parse_rq_with_metadata(text)
    assert draft.name == "X"
    assert draft.category == "C"
    assert draft.query_text == "SELECT *"


def test_parse_rq_rejects_missing_name():
    with pytest.raises(ValueError, match="name"):
        parse_rq_with_metadata("# @category Foo\nSELECT *")


def test_parse_rq_ignores_unknown_metadata_keys():
    text = "# @name X\n# @author Bob\nSELECT *"
    draft = parse_rq_with_metadata(text)
    assert draft.name == "X"
    # @author is ignored — no field on StarterDraft for it.
    assert draft.query_text == "SELECT *"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/micheldumontier/code/ontoexplorer
python -m pytest tests/unit/test_sparql_starters_parser.py -q
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write the implementation**

Create `ontoexplorer/modules/sparql_starters/__init__.py`:

```python
```

(empty file)

Create `ontoexplorer/modules/sparql_starters/parser.py`:

```python
"""Parsers for the two starter-library intake formats."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class StarterDraft:
    """A parsed starter ready to be inserted as a saved_queries row."""
    name: str
    description: str | None
    category: str | None
    tags: list[str] = field(default_factory=list)
    query_text: str = ""


def detect_format(text: str) -> Literal["json", "rq"]:
    """Return 'json' if the content begins with { or [ (after whitespace); else 'rq'."""
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return "json"
    return "rq"


def parse_json_library(text: str) -> list[StarterDraft]:
    """Parse a `{ starters: [...] }` document.

    Entries missing required fields (`name`, `query_text`) are silently skipped.
    Malformed JSON or missing top-level shape raises ValueError.
    """
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc

    if not isinstance(doc, dict) or "starters" not in doc:
        raise ValueError("JSON library must be an object with a 'starters' key")
    starters = doc["starters"]
    if not isinstance(starters, list):
        raise ValueError("'starters' must be an array")

    out: list[StarterDraft] = []
    for entry in starters:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        query_text = entry.get("query_text")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(query_text, str) or not query_text.strip():
            continue
        tags = entry.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        out.append(StarterDraft(
            name=name.strip(),
            description=entry.get("description"),
            category=entry.get("category"),
            tags=[str(t) for t in tags],
            query_text=query_text,
        ))
    return out


_META_LINE = re.compile(r"^\s*#\s*@(\w+)\s+(.*)$")


def parse_rq_with_metadata(text: str) -> StarterDraft:
    """Parse a single `.rq` file with leading `# @key value` metadata comments.

    Required: `# @name`. Recognised keys: name, description, category, tags
    (comma-separated). Unknown keys are silently ignored. Body after the
    leading metadata block is `query_text` (verbatim).
    """
    lines = text.splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            # Blank lines inside the metadata block are tolerated.
            body_start = i + 1
            continue
        m = _META_LINE.match(line)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
            body_start = i + 1
        else:
            # First non-comment, non-blank line begins the body.
            break

    name = meta.get("name")
    if not name:
        raise ValueError("Missing '# @name ...' metadata line")

    tags: list[str] = []
    if "tags" in meta:
        tags = [t.strip() for t in meta["tags"].split(",") if t.strip()]

    query_text = "\n".join(lines[body_start:]).lstrip("\n").rstrip()

    return StarterDraft(
        name=name,
        description=meta.get("description"),
        category=meta.get("category"),
        tags=tags,
        query_text=query_text,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_sparql_starters_parser.py -q
```

Expected: PASS, all parser tests green.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add ontoexplorer/modules/sparql_starters/__init__.py ontoexplorer/modules/sparql_starters/parser.py tests/unit/test_sparql_starters_parser.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): parsers for starter-library intake (JSON + .rq)

Pure helpers: detect_format distinguishes JSON-library from .rq-
with-metadata; parse_json_library validates the {starters: [...]}
shape and silently skips entries missing required fields;
parse_rq_with_metadata extracts # @name / # @description / @category
/ @tags from the leading comment block of an .rq file.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Read API — `GET /sparql/starters` + filter starters out of existing listings

**Files:**
- Modify: `ontoexplorer/api/sparql_queries.py`
- Create: `tests/integration/test_sparql_starters.py`

- [ ] **Step 1: Add the failing tests**

Create `tests/integration/test_sparql_starters.py`:

```python
"""Integration tests for the starter-queries endpoints."""
import pytest


@pytest.mark.anyio
async def test_starters_list_returns_seeded_rows(client):
    resp = await client.get("/api/v1/sparql/starters")
    assert resp.status_code == 200
    data = resp.json()
    assert "starters" in data
    # We seeded 10 starters in the migration.
    assert len(data["starters"]) >= 10
    names = [s["name"] for s in data["starters"]]
    assert "All classes in scope" in names


@pytest.mark.anyio
async def test_starters_list_ordered_by_category_then_name(client):
    resp = await client.get("/api/v1/sparql/starters")
    starters = resp.json()["starters"]
    sortable = [(s.get("category") or "", s["name"]) for s in starters]
    assert sortable == sorted(sortable)


@pytest.mark.anyio
async def test_starters_not_in_public_listing(client):
    public = await client.get("/api/v1/sparql/queries/public")
    public_names = {q["name"] for q in public.json()["queries"]}
    starters = await client.get("/api/v1/sparql/starters")
    starter_names = {s["name"] for s in starters.json()["starters"]}
    # Disjoint sets — starters must not bleed into /public.
    assert public_names.isdisjoint(starter_names)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/micheldumontier/code/ontoexplorer
python -m pytest tests/integration/test_sparql_starters.py -q
```

Expected: FAIL — `/api/v1/sparql/starters` returns 404.

- [ ] **Step 3: Add the read endpoint + filter starters out of existing listings**

Open `ontoexplorer/api/sparql_queries.py`. Three edits:

1. **Update `_serialize`** to include `is_starter` and `category` so consumers can distinguish:

```python
def _serialize(sq: SavedQuery, user_display_name: Optional[str] = None) -> dict:
    d = {
        "id": sq.id,
        "user_id": sq.user_id,
        "name": sq.name,
        "description": sq.description,
        "query_text": sq.query_text,
        "tags": sq.tags or [],
        "is_public": sq.is_public,
        "is_starter": sq.is_starter,
        "category": sq.category,
        "created_at": sq.created_at.isoformat() if sq.created_at else None,
        "updated_at": sq.updated_at.isoformat() if sq.updated_at else None,
    }
    if user_display_name is not None:
        d["user_display_name"] = user_display_name
    return d
```

2. **Modify `list_saved_queries`** (the `/` GET) — filter out starters:

```python
@router.get("")
async def list_saved_queries(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SavedQuery)
        .where(SavedQuery.user_id == user.id)
        .where(SavedQuery.is_starter == False)  # noqa: E712
        .order_by(SavedQuery.updated_at.desc())
    )
    return {"queries": [_serialize(q) for q in result.scalars().all()]}
```

3. **Modify `list_public_queries`** (the `/public` GET) — filter out starters. Inside the existing function, change the `stmt` definition:

```python
    stmt = (
        select(SavedQuery, User.display_name)
        .join(User, SavedQuery.user_id == User.id)
        .where(SavedQuery.is_public == True)  # noqa: E712
        .where(SavedQuery.is_starter == False)  # noqa: E712
    )
```

4. **Add the new starters listing endpoint.** Place it after `list_public_queries`:

```python
@router.get("/starters")
async def list_starters(db: AsyncSession = Depends(get_db)):
    """Return the curated starter-query library. No authentication required."""
    result = await db.execute(
        select(SavedQuery)
        .where(SavedQuery.is_starter == True)  # noqa: E712
        .order_by(SavedQuery.category, SavedQuery.name)
    )
    return {"starters": [_serialize(q) for q in result.scalars().all()]}
```

**Important routing detail:** the new endpoint must be declared BEFORE `/api/v1/sparql/queries/{query_id}` (the existing single-row endpoint), otherwise FastAPI matches `/starters` as a `query_id` path parameter. Place it right after the `/public` handler — well before the `/{query_id}` handler.

Wait — the router prefix is `/api/v1/sparql/queries`, so the new endpoint sits at `/api/v1/sparql/queries/starters`. Update the spec usage accordingly in the test file:

```python
# In tests/integration/test_sparql_starters.py, change all paths from
# /api/v1/sparql/starters → /api/v1/sparql/queries/starters
```

Or — cleaner — create a SEPARATE router with prefix `/api/v1/sparql` and mount the `/starters` endpoint on it. Use this approach:

5. **Create a separate router for `/starters`** (avoids the path-param collision and matches the spec's URL exactly). In `ontoexplorer/api/sparql_queries.py`, just below the existing `router = APIRouter(...)`:

```python
starters_router = APIRouter(prefix="/api/v1/sparql", tags=["sparql-starters"])


@starters_router.get("/starters")
async def list_starters(db: AsyncSession = Depends(get_db)):
    """Return the curated starter-query library. No authentication required."""
    result = await db.execute(
        select(SavedQuery)
        .where(SavedQuery.is_starter == True)  # noqa: E712
        .order_by(SavedQuery.category, SavedQuery.name)
    )
    return {"starters": [_serialize(q) for q in result.scalars().all()]}
```

6. **Register the new router** in the FastAPI app. Find where `router` from `sparql_queries` is mounted. Look in `ontoexplorer/main.py`:

```bash
grep -n "sparql_queries" /home/micheldumontier/code/ontoexplorer/ontoexplorer/main.py
```

Add a parallel line for `starters_router`. Example pattern: if you see `app.include_router(sparql_queries_router)`, add `app.include_router(sparql_queries_starters_router)` with appropriate import. Specifically, in `main.py`:

```python
from ontoexplorer.api.sparql_queries import router as sparql_queries_router, starters_router as sparql_starters_router
...
app.include_router(sparql_queries_router)
app.include_router(sparql_starters_router)
```

(If the existing import is just `from ontoexplorer.api.sparql_queries import router as sparql_queries_router`, extend it to also import `starters_router`.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/integration/test_sparql_starters.py -q
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Run the full sparql_queries integration suite to confirm no regression**

```bash
python -m pytest tests/integration/test_sparql_queries.py -q 2>&1 | tail -10
```

Expected: all pre-existing tests still pass (or at most are skipping due to environment, which is pre-existing).

- [ ] **Step 6: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add ontoexplorer/api/sparql_queries.py ontoexplorer/main.py tests/integration/test_sparql_starters.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): GET /sparql/starters; exclude starters from /queries and /queries/public

Anonymous GET returns the curated starter library ordered by
category then name. The existing my-queries (/) and public-gallery
(/public) endpoints now WHERE is_starter = false so seeded starters
don't pollute either listing. _serialize emits is_starter and
category so clients can distinguish.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Import API — `POST /sparql/starters/import` (admin-only)

**Files:**
- Modify: `ontoexplorer/api/sparql_queries.py`
- Modify: `tests/integration/test_sparql_starters.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/integration/test_sparql_starters.py`:

```python
@pytest.mark.anyio
async def test_import_requires_admin(client):
    resp = await client.post(
        "/api/v1/sparql/starters/import",
        json={"text": '{"starters": []}'},
    )
    # Non-admin: 401 (no auth) or 403 (auth but not admin). Either is correct;
    # the integration fixture has no admin user by default.
    assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_import_paste_json_creates_starters(admin_client):
    body = {
        "text": (
            '{"starters": [{"name": "Test starter", "category": "Test", '
            '"query_text": "SELECT * WHERE { ?s ?p ?o }"}]}'
        ),
    }
    resp = await admin_client.post("/api/v1/sparql/starters/import", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 1
    assert data["skipped"] == 0


@pytest.mark.anyio
async def test_import_paste_rq_creates_one_starter(admin_client):
    body = {
        "text": (
            "# @name Test rq\n# @category Test\n\n"
            "SELECT * WHERE { ?s ?p ?o }"
        ),
    }
    resp = await admin_client.post("/api/v1/sparql/starters/import", json=body)
    assert resp.status_code == 200
    assert resp.json()["created"] == 1


@pytest.mark.anyio
async def test_import_duplicate_name_is_skipped(admin_client):
    body = {
        "text": (
            '{"starters": [{"name": "All classes in scope", '
            '"query_text": "SELECT *"}]}'
        ),
    }
    resp = await admin_client.post("/api/v1/sparql/starters/import", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 0
    assert data["skipped"] == 1
    assert data["errors"] and data["errors"][0]["reason"] == "duplicate name"


@pytest.mark.anyio
async def test_import_url_rejects_non_https(admin_client):
    resp = await admin_client.post(
        "/api/v1/sparql/starters/import",
        json={"source_url": "http://example.com/starters.json"},
    )
    assert resp.status_code == 400
    assert "https" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_import_url_allows_localhost_http(admin_client, monkeypatch):
    # Stub the fetcher so we don't actually open a socket
    async def fake_fetch(url: str) -> str:
        return '{"starters": [{"name": "Local test", "query_text": "SELECT *"}]}'
    monkeypatch.setattr(
        "ontoexplorer.api.sparql_queries._fetch_starter_url",
        fake_fetch,
    )
    resp = await admin_client.post(
        "/api/v1/sparql/starters/import",
        json={"source_url": "http://localhost:9999/lib.json"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1
```

The `admin_client` fixture must exist in `tests/conftest.py`. Check it:

```bash
grep -n "admin_client\|fixture.*admin" /home/micheldumontier/code/ontoexplorer/tests/conftest.py | head
```

If `admin_client` doesn't exist, create it. Open `tests/conftest.py` and append:

```python
@pytest.fixture
async def admin_client(client, db_session):
    """Yields a test client authenticated as a freshly-created admin user."""
    from ontoexplorer.models.db import User
    from ontoexplorer.modules.auth.tokens import create_access_token
    admin = User(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        provider="test",
        subject="admin-test",
        display_name="Admin Test",
        is_admin=True,
    )
    db_session.add(admin)
    await db_session.commit()
    token = create_access_token(admin.id)
    client.headers.update({"Authorization": f"Bearer {token}"})
    yield client
```

**The exact shape of the fixture depends on the conftest setup.** Read `tests/conftest.py` first; pattern-match its existing `client` fixture and add an `admin_client` that follows the same async pattern. If the project uses a different auth-injection method (e.g., session cookies, custom Depends override), adapt accordingly.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/integration/test_sparql_starters.py -q
```

Expected: FAIL on the new tests — endpoint doesn't exist yet.

- [ ] **Step 3: Add import-helper functions**

In `ontoexplorer/api/sparql_queries.py`, add these helpers near the top of the file (after the imports, before the existing models):

```python
import asyncio
import uuid
from urllib.parse import urlparse

import httpx

from ontoexplorer.api.admin._common import _require_admin
from ontoexplorer.modules.sparql_starters.parser import (
    StarterDraft,
    detect_format,
    parse_json_library,
    parse_rq_with_metadata,
)


SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"
_MAX_URL_BYTES = 1_048_576  # 1 MB
_URL_TIMEOUT_SECONDS = 5.0


async def _fetch_starter_url(url: str) -> str:
    """Fetch the body of `url` with a size cap, timeout, and scheme guard.

    Allowed schemes: https://, plus http:// for localhost only.
    Returns the response body as a string (UTF-8 decoded).
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    is_local_http = parsed.scheme == "http" and host in ("localhost", "127.0.0.1")
    if parsed.scheme != "https" and not is_local_http:
        raise ValueError("Only https:// URLs are allowed (localhost http allowed for dev)")

    async with httpx.AsyncClient(timeout=_URL_TIMEOUT_SECONDS, follow_redirects=True, max_redirects=3) as http:
        resp = await http.get(url)
    if resp.status_code != 200:
        raise ValueError(f"Upstream returned HTTP {resp.status_code}")
    if len(resp.content) > _MAX_URL_BYTES:
        raise ValueError(f"Response exceeded {_MAX_URL_BYTES} byte cap")
    return resp.content.decode("utf-8", errors="replace")
```

- [ ] **Step 4: Add the import endpoint**

In the same file, after the `list_starters` endpoint on `starters_router`, add:

```python
class StarterImportPaste(BaseModel):
    text: Optional[str] = None
    source_url: Optional[str] = None


@starters_router.post("/starters/import")
async def import_starters(
    body: Optional[StarterImportPaste] = None,
    file: Optional[bytes] = None,  # populated by FastAPI for multipart; see note
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only import. Accepts a JSON body with `text` or `source_url`, OR
    a multipart upload with `file`. Auto-detects JSON-library vs .rq format.
    """
    # Resolve the source text
    if file is not None:
        text = file.decode("utf-8", errors="replace")
    elif body is None:
        raise HTTPException(status_code=400, detail="No text, source_url, or file provided")
    elif body.text:
        text = body.text
    elif body.source_url:
        try:
            text = await _fetch_starter_url(body.source_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        raise HTTPException(status_code=400, detail="No text, source_url, or file provided")

    fmt = detect_format(text)
    drafts: list[StarterDraft]
    errors: list[dict] = []
    if fmt == "json":
        try:
            drafts = parse_json_library(text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"JSON parse error: {exc}")
    else:
        try:
            drafts = [parse_rq_with_metadata(text)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"rq parse error: {exc}")

    # Look up which names already exist
    existing_names_q = await db.execute(
        select(SavedQuery.name).where(SavedQuery.is_starter == True)  # noqa: E712
    )
    existing_names = {row for (row,) in existing_names_q.all()}

    created = 0
    skipped = 0
    for i, draft in enumerate(drafts):
        if draft.name in existing_names:
            skipped += 1
            errors.append({"index": i, "name": draft.name, "reason": "duplicate name"})
            continue
        sq = SavedQuery(
            id=str(uuid.uuid4()),
            user_id=SYSTEM_USER_ID,
            name=draft.name,
            description=draft.description,
            query_text=draft.query_text,
            tags=draft.tags,
            is_public=True,
            is_starter=True,
            category=draft.category,
        )
        db.add(sq)
        existing_names.add(draft.name)  # in-flight dedup for the same batch
        created += 1
    await db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}
```

**Note on multipart**: FastAPI doesn't auto-bind bytes to a multipart field. To support actual file upload, change the signature to use `UploadFile`:

```python
from fastapi import UploadFile, File, Form

@starters_router.post("/starters/import")
async def import_starters(
    text: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    if file is not None:
        text_content = (await file.read()).decode("utf-8", errors="replace")
    elif source_url:
        try:
            text_content = await _fetch_starter_url(source_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    elif text:
        text_content = text
    else:
        raise HTTPException(status_code=400, detail="No text, source_url, or file provided")
    # ... (rest of body, using `text_content` in place of `text`)
```

Choose this `Form`/`File` variant — it handles both JSON-body and multipart cleanly with FastAPI's content-type negotiation. **Use this signature, not the `body: BaseModel` one above.**

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/integration/test_sparql_starters.py -q
```

Expected: PASS.

If tests fail because the `admin_client` fixture doesn't work as drafted, debug by reading `tests/conftest.py` and adapting. The fixture's signature MUST match the project's existing auth-injection style.

- [ ] **Step 6: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add ontoexplorer/api/sparql_queries.py tests/integration/test_sparql_starters.py tests/conftest.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): admin-only POST /sparql/starters/import (paste, file, URL)

Three intake modes — text body, multipart file, or source_url —
all funnel through detect_format + parse_json_library /
parse_rq_with_metadata. URL fetcher rejects non-https (except
localhost) and caps responses at 1 MB with a 5s timeout.
Duplicate-name imports are skipped and recorded in the errors list;
the response shape is { created, skipped, errors }.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Frontend API client — `listStarters` + `importStarters`

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the API methods**

Open `frontend/src/lib/api.ts`. Find the `savedQueries` object (search for `savedQueries:`). Add:

```ts
  savedQueries: {
    // ... existing methods unchanged ...
    listStarters: () =>
      request<{ starters: StarterQuery[] }>('/sparql/starters'),
  },
```

Find the `admin` object. Add:

```ts
  admin: {
    // ... existing methods unchanged ...
    importStarters: (payload: ImportStartersPayload) => {
      if ('file' in payload) {
        const form = new FormData()
        form.append('file', payload.file)
        return fetch('/api/v1/sparql/starters/import', { method: 'POST', body: form })
          .then(r => r.json() as Promise<ImportStartersResponse>)
      }
      if ('source_url' in payload) {
        const form = new FormData()
        form.append('source_url', payload.source_url)
        return fetch('/api/v1/sparql/starters/import', { method: 'POST', body: form })
          .then(r => r.json() as Promise<ImportStartersResponse>)
      }
      const form = new FormData()
      form.append('text', payload.text)
      return fetch('/api/v1/sparql/starters/import', { method: 'POST', body: form })
        .then(r => r.json() as Promise<ImportStartersResponse>)
    },
  },
```

Add types — near the other interfaces at the top of the file:

```ts
export interface StarterQuery {
  id: string
  name: string
  description: string | null
  category: string | null
  tags: string[]
  query_text: string
  is_starter: boolean
  is_public: boolean
  created_at: string | null
  updated_at: string | null
}

export type ImportStartersPayload =
  | { text: string }
  | { source_url: string }
  | { file: File }

export interface ImportStartersResponse {
  created: number
  skipped: number
  errors: Array<{ index: number; name?: string; reason: string }>
}
```

- [ ] **Step 2: TS check**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend && npx tsc --noEmit 2>&1 | grep "api\.ts" | grep -v node_modules
```

Expected: empty.

- [ ] **Step 3: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/lib/api.ts
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): api client methods for starter listing + admin import

api.savedQueries.listStarters() returns the read-only library.
api.admin.importStarters(payload) accepts {text}/{source_url}/{file}
and POSTs via FormData. Adds StarterQuery / ImportStartersPayload /
ImportStartersResponse types.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: QuerySidebar — Starters view + tab switch

**Files:**
- Modify: `frontend/src/components/QuerySidebar.tsx`
- Create: `frontend/src/components/QuerySidebar.starters.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/QuerySidebar.starters.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import QuerySidebar from './QuerySidebar'

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: null }) }))

vi.mock('../lib/api', () => ({
  api: {
    savedQueries: {
      list: vi.fn().mockResolvedValue({ queries: [] }),
      listStarters: vi.fn().mockResolvedValue({
        starters: [
          { id: 's1', name: 'All classes', description: 'desc 1', category: 'Exploration',
            tags: [], query_text: 'SELECT * WHERE { ?s ?p ?o }',
            is_starter: true, is_public: true, created_at: null, updated_at: null },
          { id: 's2', name: 'Subclasses', description: 'desc 2', category: 'Term lookup',
            tags: [], query_text: 'SELECT ?sub WHERE {}',
            is_starter: true, is_public: true, created_at: null, updated_at: null },
        ],
      }),
    },
    ontologies: { list: vi.fn().mockResolvedValue({ ontologies: [] }) },
  },
}))

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('QuerySidebar — Starters', () => {
  it('shows starters for anonymous users', async () => {
    const yasgui = { getTab: () => ({ getYasqe: () => ({ setValue: vi.fn() }) }) } as any
    render(wrap(<QuerySidebar yasguiRef={{ current: yasgui }} />))
    await waitFor(() => {
      expect(screen.getByText('All classes')).toBeInTheDocument()
      expect(screen.getByText('Subclasses')).toBeInTheDocument()
    })
  })

  it('clicking a starter calls setValue with its query_text', async () => {
    const setValueMock = vi.fn()
    const yasgui = { getTab: () => ({ getYasqe: () => ({ setValue: setValueMock }) }) } as any
    render(wrap(<QuerySidebar yasguiRef={{ current: yasgui }} />))
    await waitFor(() => screen.getByText('All classes'))
    fireEvent.click(screen.getByText('All classes'))
    expect(setValueMock).toHaveBeenCalledWith('SELECT * WHERE { ?s ?p ?o }')
  })

  it('groups starters by category', async () => {
    const yasgui = { getTab: () => ({ getYasqe: () => ({ setValue: vi.fn() }) }) } as any
    render(wrap(<QuerySidebar yasguiRef={{ current: yasgui }} />))
    await waitFor(() => screen.getByText('All classes'))
    expect(screen.getByText('Exploration')).toBeInTheDocument()
    expect(screen.getByText('Term lookup')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx vitest run src/components/QuerySidebar.starters.test.tsx --reporter=basic
```

Expected: FAIL — anonymous users currently see "Sign in to save queries", no starters.

- [ ] **Step 3: Refactor QuerySidebar to support Starters view**

Open `frontend/src/components/QuerySidebar.tsx`. Make these changes:

1. **Import the starter API** at the top:

```tsx
import { api, SavedQuery, StarterQuery } from '../lib/api'
```

2. **Add state** for starters and the active tab. Add near the other useState calls (after `tagInputRef`):

```tsx
const [starters, setStarters] = useState<StarterQuery[]>([])
type SidebarTab = 'my' | 'starters'
const [tab, setTab] = useState<SidebarTab>(user ? 'my' : 'starters')
```

3. **Fetch starters on mount.** Add an effect after the existing `user` and `ontologies` effects:

```tsx
useEffect(() => {
  api.savedQueries.listStarters()
    .then(r => setStarters(r.starters))
    .catch(() => {})
}, [])
```

4. **Group starters by category** (a memo near `filteredQueries`):

```tsx
const startersByCategory = useMemo(() => {
  const m = new Map<string, StarterQuery[]>()
  for (const s of starters) {
    const cat = s.category ?? 'Other'
    if (!m.has(cat)) m.set(cat, [])
    m.get(cat)!.push(s)
  }
  return Array.from(m.entries()).sort(([a], [b]) => a.localeCompare(b))
}, [starters])
```

(Add `useMemo` to the React import if missing.)

5. **Replace the early-return for anonymous users** with a version that still shows the Starters tab. Locate:

```tsx
if (!user) {
  return (
    <div style={{ ...base, alignItems: 'center', justifyContent: 'center', padding: '1rem', textAlign: 'center' }}>
      <span style={{ color: 'var(--text-dim)', fontSize: '0.7rem', lineHeight: 1.5 }}>
        Sign in to save queries
      </span>
    </div>
  )
}
```

Delete it. The component now always renders the main JSX; anonymous handling is done by hiding/showing tabs.

6. **Add a tab strip at the top** (right after the existing header `<div>` that shows "MY QUERIES"). Replace the existing header `<div>` with:

```tsx
{/* Header + tabs */}
<div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 4, flexShrink: 0 }}>
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
    <div style={{ display: 'flex', gap: 8 }}>
      {user && (
        <button
          onClick={() => { setTab('my'); setView('list') }}
          style={{
            background: 'none', border: 'none', cursor: 'pointer', padding: 0,
            color: tab === 'my' && view !== 'form' ? 'var(--text)' : 'var(--text-dim)',
            fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.05em',
            textDecoration: tab === 'my' && view !== 'form' ? 'underline' : 'none',
          }}
        >MINE</button>
      )}
      <button
        onClick={() => { setTab('starters'); setView('list') }}
        style={{
          background: 'none', border: 'none', cursor: 'pointer', padding: 0,
          color: tab === 'starters' && view !== 'form' ? 'var(--text)' : 'var(--text-dim)',
          fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.05em',
          textDecoration: tab === 'starters' && view !== 'form' ? 'underline' : 'none',
        }}
      >STARTERS</button>
    </div>
    {user && (
      view === 'list' ? (
        <button
          onClick={openSaveForm}
          style={{ background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 3, padding: '2px 7px', fontSize: '0.65rem', fontWeight: 700, cursor: 'pointer' }}
        >＋ Save</button>
      ) : (
        <span onClick={cancelForm} style={{ color: 'var(--text-dim)', cursor: 'pointer', fontSize: '0.7rem' }}>✕ cancel</span>
      )
    )}
  </div>
</div>
```

7. **Render the Starters tab content** in place of the existing my-queries list when `tab === 'starters'`. Wrap the existing `view === 'list'` block in a conditional and add a starters block. Find the line `{view === 'list' && (` and change it to handle both tabs:

```tsx
{view === 'list' && tab === 'my' && user && (
  <>
    {/* existing my-queries list JSX unchanged */}
  </>
)}
{view === 'list' && tab === 'starters' && (
  <div style={{ flex: 1, overflowY: 'auto' }}>
    {startersByCategory.length === 0 && (
      <div style={{ padding: '10px', color: 'var(--text-dim)', fontSize: '0.65rem', textAlign: 'center' }}>
        No starters available
      </div>
    )}
    {startersByCategory.map(([category, items]) => (
      <div key={category} style={{ borderBottom: '1px solid rgba(51,65,85,0.4)' }}>
        <div style={{ padding: '4px 10px', color: 'var(--text-dim)', fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.05em', background: 'rgba(51,65,85,0.2)' }}>
          {category}
        </div>
        {items.map(s => (
          <div
            key={s.id}
            onClick={() => yasguiRef.current?.getTab()?.getYasqe()?.setValue(s.query_text)}
            style={{ padding: '5px 10px', cursor: 'pointer', borderLeft: '2px solid transparent' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(34,197,94,0.05)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {s.name}
            </div>
            {s.description && (
              <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginTop: 1, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                {s.description}
              </div>
            )}
          </div>
        ))}
      </div>
    ))}
  </div>
)}
```

8. **Hide the "Search my queries" input and footer "Browse Gallery" link** when the Starters tab is active. These are inside the existing `{view === 'list' && (...)}` block — keep them only for `tab === 'my'`. Move them inside the `tab === 'my'` branch.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx vitest run src/components/QuerySidebar.starters.test.tsx --reporter=basic
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Re-run any existing QuerySidebar tests**

```bash
npx vitest run src/components/QuerySidebar --reporter=basic
```

Expected: pre-existing tests (if any) still pass; if they break because of the tab-switch refactor, update them minimally to match the new behaviour.

- [ ] **Step 6: TS check**

```bash
npx tsc --noEmit 2>&1 | grep "QuerySidebar" | grep -v "\.test\."
```

Expected: empty.

- [ ] **Step 7: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/QuerySidebar.tsx frontend/src/components/QuerySidebar.starters.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(sparql): Starters tab in QuerySidebar, visible to anon users

A new STARTERS tab sits next to MINE in the sidebar header.
Starters are fetched on mount, grouped by category, and clicking
one loads its query_text into the Yasgui editor. The MINE tab
hides for anonymous users; the STARTERS tab works without auth.
The Save button still requires sign-in.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `StarterQueriesPanel` admin component

**Files:**
- Create: `frontend/src/components/admin/StarterQueriesPanel.tsx`
- Create: `frontend/src/components/admin/StarterQueriesPanel.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/admin/StarterQueriesPanel.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi } from 'vitest'
import { StarterQueriesPanel } from './StarterQueriesPanel'

vi.mock('../../lib/api', () => ({
  api: {
    admin: { importStarters: vi.fn() },
  },
}))
import { api } from '../../lib/api'
const mockImport = api.admin.importStarters as ReturnType<typeof vi.fn>

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('StarterQueriesPanel', () => {
  it('renders three input zones', () => {
    render(wrap(<StarterQueriesPanel />))
    expect(screen.getByLabelText(/paste/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/upload/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/url/i)).toBeInTheDocument()
  })

  it('paste import calls api with the typed text', async () => {
    mockImport.mockResolvedValue({ created: 2, skipped: 0, errors: [] })
    render(wrap(<StarterQueriesPanel />))
    fireEvent.change(screen.getByLabelText(/paste/i), { target: { value: '{"starters":[]}' } })
    fireEvent.click(screen.getByRole('button', { name: /import paste/i }))
    await waitFor(() => expect(mockImport).toHaveBeenCalledWith({ text: '{"starters":[]}' }))
    expect(screen.getByText(/imported 2/i)).toBeInTheDocument()
  })

  it('url import calls api with the typed URL', async () => {
    mockImport.mockResolvedValue({ created: 1, skipped: 0, errors: [] })
    render(wrap(<StarterQueriesPanel />))
    fireEvent.change(screen.getByLabelText(/url/i), { target: { value: 'https://example.com/lib.json' } })
    fireEvent.click(screen.getByRole('button', { name: /import url/i }))
    await waitFor(() => expect(mockImport).toHaveBeenCalledWith({ source_url: 'https://example.com/lib.json' }))
  })

  it('shows error count when import returns errors', async () => {
    mockImport.mockResolvedValue({ created: 0, skipped: 1, errors: [{ index: 0, reason: 'duplicate name' }] })
    render(wrap(<StarterQueriesPanel />))
    fireEvent.change(screen.getByLabelText(/paste/i), { target: { value: '{"starters":[{"name":"x","query_text":"y"}]}' } })
    fireEvent.click(screen.getByRole('button', { name: /import paste/i }))
    await waitFor(() => expect(screen.getByText(/1 error/i)).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npx vitest run src/components/admin/StarterQueriesPanel.test.tsx --reporter=basic
```

Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement the panel**

Create `frontend/src/components/admin/StarterQueriesPanel.tsx`:

```tsx
import { useState, useRef } from 'react'
import { api, ImportStartersResponse } from '../../lib/api'

export function StarterQueriesPanel() {
  const [pasteText, setPasteText] = useState('')
  const [urlText, setUrlText] = useState('')
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [result, setResult] = useState<ImportStartersResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run<T extends () => Promise<ImportStartersResponse>>(fn: T) {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const r = await fn()
      setResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setBusy(false)
    }
  }

  function handlePaste() {
    if (!pasteText.trim()) return
    run(() => api.admin.importStarters({ text: pasteText }))
  }

  function handleUpload() {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    run(() => api.admin.importStarters({ file }))
  }

  function handleUrl() {
    if (!urlText.trim()) return
    run(() => api.admin.importStarters({ source_url: urlText.trim() }))
  }

  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>Starter Queries — Import</div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <label htmlFor="starter-paste" style={{ fontSize: 11, color: 'var(--text-dim)' }}>Paste (JSON library or .rq)</label>
        <textarea
          id="starter-paste"
          aria-label="Paste"
          value={pasteText}
          onChange={e => setPasteText(e.target.value)}
          rows={4}
          placeholder='{ "starters": [...] }  OR  # @name …'
          style={{ width: '100%', boxSizing: 'border-box', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '6px 8px', fontSize: 11, color: 'var(--text)', fontFamily: 'monospace' }}
        />
        <button
          onClick={handlePaste}
          disabled={busy || !pasteText.trim()}
          style={{ alignSelf: 'flex-start', background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 4, padding: '4px 10px', fontSize: 11, fontWeight: 600, cursor: busy ? 'default' : 'pointer', opacity: busy || !pasteText.trim() ? 0.5 : 1 }}
        >Import paste</button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <label htmlFor="starter-upload" style={{ fontSize: 11, color: 'var(--text-dim)' }}>Upload (.json or .rq)</label>
        <input
          id="starter-upload"
          aria-label="Upload"
          type="file"
          ref={fileRef}
          accept=".json,.rq"
          style={{ fontSize: 11, color: 'var(--text-dim)' }}
        />
        <button
          onClick={handleUpload}
          disabled={busy}
          style={{ alignSelf: 'flex-start', background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 4, padding: '4px 10px', fontSize: 11, fontWeight: 600, cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.5 : 1 }}
        >Import file</button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <label htmlFor="starter-url" style={{ fontSize: 11, color: 'var(--text-dim)' }}>URL (https://… or http://localhost)</label>
        <input
          id="starter-url"
          aria-label="URL"
          type="text"
          value={urlText}
          onChange={e => setUrlText(e.target.value)}
          placeholder="https://example.org/starters.json"
          style={{ width: '100%', boxSizing: 'border-box', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '4px 8px', fontSize: 11, color: 'var(--text)' }}
        />
        <button
          onClick={handleUrl}
          disabled={busy || !urlText.trim()}
          style={{ alignSelf: 'flex-start', background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 4, padding: '4px 10px', fontSize: 11, fontWeight: 600, cursor: busy ? 'default' : 'pointer', opacity: busy || !urlText.trim() ? 0.5 : 1 }}
        >Import URL</button>
      </div>

      {result && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Imported {result.created} · Skipped {result.skipped}
          {result.errors.length > 0 && (
            <> · {result.errors.length} error{result.errors.length === 1 ? '' : 's'}</>
          )}
          {result.errors.length > 0 && (
            <details style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer' }}>Errors</summary>
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {result.errors.map((e, i) => (
                  <li key={i}>{e.name ? `${e.name}: ` : ''}{e.reason}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {error && (
        <div style={{ fontSize: 11, color: '#f87171' }}>{error}</div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npx vitest run src/components/admin/StarterQueriesPanel.test.tsx --reporter=basic
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/components/admin/StarterQueriesPanel.tsx frontend/src/components/admin/StarterQueriesPanel.test.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(admin): StarterQueriesPanel with paste/upload/URL import zones

Three input methods funnel into api.admin.importStarters, which
dispatches multipart FormData to the backend. Result panel shows
created/skipped counts plus an expandable errors list. No edit/
delete affordances — admins manage via SQL.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Mount `StarterQueriesPanel` on `AdminPage`

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`

- [ ] **Step 1: Add the import + mount**

Open `frontend/src/pages/AdminPage.tsx`. Add the import at the top with the other admin-component imports:

```tsx
import { StarterQueriesPanel } from '../components/admin/StarterQueriesPanel'
```

Locate the JSX section that lists admin panels. Add a new section near the bottom (before the existing "Recent Jobs" / "Workers" section, or at the end — wherever fits the page's section order). Use the same `SectionLabel` helper that the other sections use:

```tsx
<SectionLabel>Starter Queries</SectionLabel>
<div style={{ marginBottom: 24 }}>
  <StarterQueriesPanel />
</div>
```

- [ ] **Step 2: Run all the relevant tests**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx vitest run src/pages/AdminPage src/components/admin/StarterQueriesPanel --reporter=basic
```

Expected: PASS.

- [ ] **Step 3: TS check**

```bash
npx tsc --noEmit 2>&1 | grep "AdminPage\.tsx\|StarterQueriesPanel" | grep -v "\.test\."
```

Expected: empty.

- [ ] **Step 4: Commit**

```bash
cd /home/micheldumontier/code/ontoexplorer
git add frontend/src/pages/AdminPage.tsx
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(admin): mount StarterQueriesPanel on AdminPage

Adds a 'Starter Queries' section to the admin page using the
existing SectionLabel pattern.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: End-to-end sweep

- [ ] **Step 1: Full frontend test run**

```bash
cd /home/micheldumontier/code/ontoexplorer/frontend
npx vitest run --reporter=basic 2>&1 | tail -25
```

Expected: all tests pass. Pre-existing failures in unrelated files (`OwlProfileSection`) are not blockers.

- [ ] **Step 2: Backend test run**

```bash
cd /home/micheldumontier/code/ontoexplorer
python -m pytest tests/unit/test_sparql_starters_parser.py tests/integration/test_sparql_starters.py -q 2>&1 | tail -10
```

Expected: PASS for both parser and integration suites.

- [ ] **Step 3: Full project TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "(StarterQueriesPanel|QuerySidebar|sparql_starters|api\.ts)" | grep -v "\.test\." | grep -v node_modules
```

Expected: empty.

- [ ] **Step 4: File inventory**

```bash
cd /home/micheldumontier/code/ontoexplorer
git log --since="3 hours ago" --stat | head -100
```

Confirm only the expected files were touched (~13 files across this feature's tasks).

- [ ] **Step 5: Manual smoke test (optional)**

1. Open `/sparql` while signed out. Confirm the Starters tab is visible with the 10 seeded starters grouped by category.
2. Click a starter — confirm it loads into the editor.
3. Sign in as admin. Open `/admin`. Confirm the Starter Queries panel appears.
4. Paste a JSON library with one starter and click "Import paste". Confirm the result line shows `Imported 1`.
5. Try the same starter again — confirm `Skipped 1 · 1 error · duplicate name`.
6. Try a `.rq` paste with `# @name Foo\nSELECT *`. Confirm `Imported 1`.
7. Try a URL pointing to a public JSON gist. Confirm `Imported N`.
8. Return to `/sparql`. Sign out. Confirm the new starters appear in the sidebar.

- [ ] **Step 6: Optional post-merge cleanup commit**

If anything was tweaked during the sweep:

```bash
git add -A
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
chore(sparql): post-merge cleanup for starter queries

Fix-ups discovered during the end-to-end sweep.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

If nothing changed, no commit.

---

## Out of scope

Per the spec:

- Admin UI for editing/deleting individual starters (SQL only).
- Per-starter usage analytics.
- Parameterization engine (placeholders are literal tokens).
- Git-repo URL imports.
- Nested categories.
- Syntax-validating SPARQL at import time.
- Localised starter names/descriptions.
