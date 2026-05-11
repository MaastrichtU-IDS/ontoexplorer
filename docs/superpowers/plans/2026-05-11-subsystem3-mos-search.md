# Subsystem 3: MOS Search Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Manchester OWL Syntax search engine with Redis entity index, context-sensitive autocomplete, and hybrid ELK/SPARQL expression evaluation.

**Architecture:** A `modules/search/` package handles indexing (Redis sorted-set prefix index built from Oxigraph), parsing (lark grammar → typed AST), autocomplete (cursor-aware state machine), and evaluation (set operations over ELK classification + Oxigraph SPARQL for restrictions). Two FastAPI endpoints expose search and autocomplete. The existing `index_ontology` Celery stub is replaced with the real indexer.

**Tech Stack:** Python 3.12, lark>=1.2 (PEG parser), redis>=6 (sync, already transitive via celery), fakeredis (tests), pyoxigraph (Oxigraph SPARQL), httpx (ELK HTTP client — already present).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `ontoexplorer/modules/search/__init__.py` | Empty package marker |
| Create | `ontoexplorer/modules/search/indexer.py` | Redis entity index: build, lookup, invalidate |
| Create | `ontoexplorer/modules/search/mos_parser.py` | lark grammar, typed AST, `parse()`, `partial_parse()` |
| Create | `ontoexplorer/modules/search/autocomplete.py` | Cursor-aware completion engine |
| Create | `ontoexplorer/modules/search/evaluator.py` | AST→results: ELK set ops + Oxigraph SPARQL |
| Create | `ontoexplorer/api/search.py` | FastAPI router: GET /search, GET /autocomplete |
| Create | `tests/unit/__init__.py` | Package marker |
| Create | `tests/unit/search/__init__.py` | Package marker |
| Create | `tests/unit/search/test_indexer.py` | Unit tests for indexer |
| Create | `tests/unit/search/test_mos_parser.py` | Unit tests for parser |
| Create | `tests/unit/search/test_autocomplete.py` | Unit tests for autocomplete |
| Create | `tests/unit/search/test_evaluator.py` | Unit tests for evaluator |
| Create | `tests/integration/test_search.py` | Integration tests for API endpoints |
| Modify | `pyproject.toml` | Add lark, move redis to main deps |
| Modify | `ontoexplorer/clients/reasoning.py` | Add `get_classification()` |
| Modify | `ontoexplorer/modules/jobs/tasks.py` | Replace `index_ontology` stub |
| Modify | `ontoexplorer/api/ontologies.py` | Add `invalidate_index` to `deprecate_version` |
| Modify | `ontoexplorer/main.py` | Include search router |

---

## Task 1: Dependencies and Module Skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `ontoexplorer/modules/search/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/search/__init__.py`

- [ ] **Step 1: Add lark and redis to main dependencies**

Edit `pyproject.toml` — add `lark` and `redis` to the `dependencies` list and remove `redis` from dev group (it's already a transitive dep via `celery[redis]` but being explicit is correct):

```toml
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]",
    "celery[redis]",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",
    "alembic",
    "pydantic-settings>=2.0",
    "py_horned_owl",
    "rdflib",
    "pyoxigraph",
    "minio",
    "httpx",
    "authlib",
    "python-jose[cryptography]",
    "prometheus-fastapi-instrumentator",
    "python-multipart",
    "structlog>=24.0",
    "prometheus-client",
    "lark>=1.2",
    "redis>=6.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "anyio[trio]",
    "aiosqlite",
    "httpx",
    "ruff>=0.4",
    "mypy>=1.10",
    "fakeredis>=2.35.1",
]
```

- [ ] **Step 2: Install new dependency**

```bash
uv sync
```

Expected: lark installed, no errors.

- [ ] **Step 3: Create package markers**

Create `ontoexplorer/modules/search/__init__.py` (empty file):
```python
```

Create `tests/unit/__init__.py` (empty file):
```python
```

Create `tests/unit/search/__init__.py` (empty file):
```python
```

- [ ] **Step 4: Verify lark imports**

```bash
source .venv/bin/activate && python3 -c "from lark import Lark; print('lark ok')"
```

Expected: `lark ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock ontoexplorer/modules/search/__init__.py tests/unit/__init__.py tests/unit/search/__init__.py
git commit -m "feat(search): add lark dep, create search module skeleton"
```

---

## Task 2: Label Normaliser and Entity Lookup (TDD)

**Files:**
- Create: `tests/unit/search/test_indexer.py`
- Create: `ontoexplorer/modules/search/indexer.py` (partial — normalise + lookup only)

- [ ] **Step 1: Write failing tests**

Create `tests/unit/search/test_indexer.py`:

```python
"""Unit tests for the search indexer."""
import fakeredis
import pytest
from unittest.mock import patch

from ontoexplorer.modules.search.indexer import (
    normalise_label,
    entity_lookup,
    _prefix_key,
    _iri_key,
)


def _make_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_normalise_label_lowercase():
    assert normalise_label("Cell Death") == "cell death"


def test_normalise_label_strips_punctuation():
    assert normalise_label("has-part") == "has part"


def test_normalise_label_collapses_whitespace():
    assert normalise_label("  cell   death  ") == "cell death"


def test_normalise_label_strips_leading_article():
    assert normalise_label("the Cell") == "cell"
    assert normalise_label("a Nucleus") == "nucleus"
    assert normalise_label("an Organelle") == "organelle"


def test_normalise_label_preserves_curie_colon():
    assert normalise_label("GO:0008219") == "go:0008219"


def test_entity_lookup_prefix_match():
    r = _make_redis()
    vid = "v1"
    # Manually insert prefix members
    key = _prefix_key(vid)
    r.zadd(key, {"cell death|class|http://ex.org/CellDeath": 0})
    r.zadd(key, {"cell division|class|http://ex.org/CellDiv": 0})
    r.zadd(key, {"neuron|class|http://ex.org/Neuron": 0})
    # Insert entity hashes
    r.hset(_iri_key(vid, "http://ex.org/CellDeath"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://ex.org/CellDeath", "short": "CellDeath", "synonyms": "",
    })
    r.hset(_iri_key(vid, "http://ex.org/CellDiv"), mapping={
        "label": "cell division", "type": "class",
        "iri": "http://ex.org/CellDiv", "short": "CellDiv", "synonyms": "",
    })

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        results = entity_lookup(vid, "cell", None, limit=10)

    assert len(results) == 2
    iris = {r["iri"] for r in results}
    assert "http://ex.org/CellDeath" in iris
    assert "http://ex.org/CellDiv" in iris
    assert "http://ex.org/Neuron" not in iris


def test_entity_lookup_type_filter():
    r = _make_redis()
    vid = "v1"
    key = _prefix_key(vid)
    r.zadd(key, {"has part|property|http://ex.org/HasPart": 0})
    r.zadd(key, {"has attribute|class|http://ex.org/HasAttr": 0})
    r.hset(_iri_key(vid, "http://ex.org/HasPart"), mapping={
        "label": "has part", "type": "property",
        "iri": "http://ex.org/HasPart", "short": "HasPart", "synonyms": "",
    })
    r.hset(_iri_key(vid, "http://ex.org/HasAttr"), mapping={
        "label": "has attribute", "type": "class",
        "iri": "http://ex.org/HasAttr", "short": "HasAttr", "synonyms": "",
    })

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        results = entity_lookup(vid, "has", "property", limit=10)

    assert len(results) == 1
    assert results[0]["iri"] == "http://ex.org/HasPart"


def test_entity_lookup_empty_prefix():
    r = _make_redis()
    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        results = entity_lookup("v1", "", None, limit=10)
    assert results == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_indexer.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.search.indexer'`

- [ ] **Step 3: Implement normalise_label and entity_lookup**

Create `ontoexplorer/modules/search/indexer.py`:

```python
"""Redis entity search index for ontology versions."""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass

import redis

from ontoexplorer.config import get_settings

_SEARCH_TTL = 30 * 24 * 3600  # 30 days, same as ELK classification TTL

_LABEL_PREDICATES = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://www.w3.org/2004/02/skos/core#altLabel",
    "http://schema.org/name",
]


@dataclass
class IndexStats:
    version_id: str
    class_count: int
    property_count: int
    individual_count: int


def normalise_label(label: str) -> str:
    """Lowercase, strip punctuation (except : for CURIEs), collapse whitespace, strip articles."""
    label = label.lower()
    label = re.sub(r"[^\w\s:<>]", " ", label)
    label = re.sub(r"\s+", " ", label).strip()
    label = re.sub(r"^(the|a|an)\s+", "", label)
    return label


def _prefix_key(version_id: str) -> str:
    return f"search:entities:{version_id}:prefix"


def _iri_key(version_id: str, iri: str) -> str:
    encoded = urllib.parse.quote(iri, safe="")
    return f"search:entities:{version_id}:iri:{encoded}"


def _type_key(version_id: str, entity_type: str) -> str:
    return f"search:entities:{version_id}:type:{entity_type}"


def _meta_key(version_id: str) -> str:
    return f"search:meta:{version_id}"


def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _short_iri(iri: str) -> str:
    if "#" in iri:
        return iri.split("#")[-1]
    return iri.rstrip("/").split("/")[-1]


def entity_lookup(
    version_id: str,
    prefix: str,
    entity_type: str | None,
    limit: int,
) -> list[dict]:
    """Prefix-search entities. Returns list of entity dicts with label/type/iri/short."""
    r = _get_redis()
    norm = normalise_label(prefix)
    if not norm:
        return []

    key = _prefix_key(version_id)
    min_val = f"[{norm}"
    max_val = f"[{norm}\xff"
    members = r.zrangebylex(key, min_val, max_val, start=0, count=limit * 3)

    results: list[dict] = []
    seen_iris: set[str] = set()

    for member in members:
        parts = member.split("|", 2)
        if len(parts) != 3:
            continue
        _, etype, iri = parts
        if entity_type and etype != entity_type:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        detail = r.hgetall(_iri_key(version_id, iri))
        if not detail:
            continue
        results.append(detail)
        if len(results) >= limit:
            break

    return results
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_indexer.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/indexer.py tests/unit/search/test_indexer.py
git commit -m "feat(search): label normaliser and Redis entity lookup"
```

---

## Task 3: Redis Indexer — build_index and invalidate_index (TDD)

**Files:**
- Modify: `tests/unit/search/test_indexer.py` (add tests)
- Modify: `ontoexplorer/modules/search/indexer.py` (add build_index, invalidate_index)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/search/test_indexer.py`:

```python
from ontoexplorer.modules.search.indexer import build_index, invalidate_index


def _make_sparql_rows(rows):
    """Mock pyoxigraph QuerySolutions — each row is a dict of {name: value_str}."""
    class FakeNode:
        def __init__(self, v): self.value = v
    class FakeRow:
        def __init__(self, d): self._d = d
        def __getitem__(self, k): return FakeNode(self._d[k])
        def __iter__(self): return iter(self._d)
    return [FakeRow(r) for r in rows]


def test_build_index_populates_prefix_set():
    r = _make_redis()

    entity_rows = _make_sparql_rows([
        {"entity": "http://ex.org/CellDeath"},
        {"entity": "http://ex.org/Nucleus"},
    ])
    label_rows = _make_sparql_rows([
        {"entity": "http://ex.org/CellDeath", "label": "cell death"},
        {"entity": "http://ex.org/Nucleus", "label": "nucleus"},
    ])

    call_count = 0
    def fake_sparql(q):
        nonlocal call_count
        call_count += 1
        if "owl#Class" in q:
            return entity_rows
        if "label" in q.lower():
            return label_rows
        return []

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.indexer.sparql_query", side_effect=fake_sparql), \
         patch("ontoexplorer.modules.search.indexer.graph_iri", return_value="urn:test"):
        stats = build_index("v1", "o1")

    assert stats.class_count == 2
    members = r.zrangebylex(_prefix_key("v1"), "[cell", "[cell\xff")
    assert any("celldeath" in m or "cell death" in m for m in members)


def test_build_index_writes_entity_hash():
    r = _make_redis()
    entity_rows = _make_sparql_rows([{"entity": "http://ex.org/Cell"}])
    label_rows = _make_sparql_rows([{"entity": "http://ex.org/Cell", "label": "cell"}])

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.indexer.sparql_query",
               side_effect=lambda q: entity_rows if "owl#Class" in q else label_rows if "label" in q.lower() else []), \
         patch("ontoexplorer.modules.search.indexer.graph_iri", return_value="urn:test"):
        build_index("v1", "o1")

    detail = r.hgetall(_iri_key("v1", "http://ex.org/Cell"))
    assert detail["iri"] == "http://ex.org/Cell"
    assert detail["type"] == "class"


def test_invalidate_index_removes_all_keys():
    r = _make_redis()
    vid = "v99"
    r.zadd(_prefix_key(vid), {"cell|class|http://ex.org/C": 0})
    r.hset(_iri_key(vid, "http://ex.org/C"), mapping={"label": "cell"})
    r.set(_meta_key(vid), "{}")

    with patch("ontoexplorer.modules.search.indexer._get_redis", return_value=r):
        invalidate_index(vid)

    assert r.zcard(_prefix_key(vid)) == 0
    assert r.hgetall(_iri_key(vid, "http://ex.org/C")) == {}
    assert r.get(_meta_key(vid)) is None
```

- [ ] **Step 2: Run tests — verify new tests fail**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_indexer.py::test_build_index_populates_prefix_set -v 2>&1 | tail -5
```

Expected: FAILED with `ImportError` or `AttributeError`.

- [ ] **Step 3: Implement build_index and invalidate_index**

Append to `ontoexplorer/modules/search/indexer.py`:

```python
from ontoexplorer.clients.oxigraph import graph_iri, sparql_query


def build_index(version_id: str, ontology_id: str) -> IndexStats:
    """Extract all entities and labels from Oxigraph and write the Redis entity index."""
    from datetime import datetime, timezone

    r = _get_redis()
    named_graph = graph_iri(ontology_id, version_id)

    # Collect entity IRIs with their types
    entities: dict[str, str] = {}  # iri -> "class" | "property"
    for entity_type, owl_type in [
        ("class",    "http://www.w3.org/2002/07/owl#Class"),
        ("property", "http://www.w3.org/2002/07/owl#ObjectProperty"),
        ("property", "http://www.w3.org/2002/07/owl#DatatypeProperty"),
        ("property", "http://www.w3.org/2002/07/owl#AnnotationProperty"),
    ]:
        q = f"""
            SELECT DISTINCT ?entity WHERE {{
                GRAPH <{named_graph}> {{
                    ?entity a <{owl_type}> .
                    FILTER(isIRI(?entity))
                }}
            }}
        """
        for sol in sparql_query(q):
            iri = sol["entity"].value
            if iri not in entities:
                entities[iri] = entity_type

    # Collect labels per entity
    labels_by_iri: dict[str, list[str]] = {iri: [] for iri in entities}
    pred_filter = " ".join(f"<{p}>" for p in _LABEL_PREDICATES)
    q = f"""
        SELECT ?entity ?label WHERE {{
            GRAPH <{named_graph}> {{
                VALUES ?pred {{ {pred_filter} }}
                ?entity ?pred ?label .
                FILTER(isIRI(?entity) && isLiteral(?label))
            }}
        }}
    """
    for sol in sparql_query(q):
        iri = sol["entity"].value
        if iri in labels_by_iri:
            labels_by_iri[iri].append(sol["label"].value)

    # Write to Redis via pipeline
    prefix_key = _prefix_key(version_id)
    r.delete(prefix_key)

    pipe = r.pipeline(transaction=False)
    class_count = property_count = 0

    for iri, entity_type in entities.items():
        labels = labels_by_iri.get(iri, [])
        short = _short_iri(iri)
        primary_label = labels[0] if labels else short
        all_labels = labels + ([short] if short not in labels else [])

        pipe.hset(_iri_key(version_id, iri), mapping={
            "label": primary_label,
            "type":  entity_type,
            "iri":   iri,
            "short": short,
            "synonyms": "|".join(labels[1:]) if len(labels) > 1 else "",
        })
        pipe.expire(_iri_key(version_id, iri), _SEARCH_TTL)
        pipe.sadd(_type_key(version_id, entity_type), iri)

        for label_text in all_labels:
            norm = normalise_label(label_text)
            if norm:
                pipe.zadd(prefix_key, {f"{norm}|{entity_type}|{iri}": 0})

        if entity_type == "class":
            class_count += 1
        else:
            property_count += 1

    pipe.expire(prefix_key, _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "class"),    _SEARCH_TTL)
    pipe.expire(_type_key(version_id, "property"), _SEARCH_TTL)
    pipe.setex(_meta_key(version_id), _SEARCH_TTL, json.dumps({
        "indexed_at":      datetime.now(timezone.utc).isoformat(),
        "class_count":     class_count,
        "property_count":  property_count,
        "individual_count": 0,
    }))
    pipe.execute()

    return IndexStats(
        version_id=version_id,
        class_count=class_count,
        property_count=property_count,
        individual_count=0,
    )


def invalidate_index(version_id: str) -> None:
    """Delete all search index keys for a version."""
    r = _get_redis()
    cursor = 0
    to_delete: list[str] = []
    while True:
        cursor, keys = r.scan(cursor, match=f"search:*:{version_id}:*", count=100)
        to_delete.extend(keys)
        if cursor == 0:
            break
    to_delete.append(_meta_key(version_id))
    keys_present = [k for k in to_delete if r.exists(k)]
    if keys_present:
        r.delete(*keys_present)
```

- [ ] **Step 4: Run all indexer tests**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_indexer.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/indexer.py tests/unit/search/test_indexer.py
git commit -m "feat(search): Redis build_index and invalidate_index"
```

---

## Task 4: MOS Parser — Grammar and parse() (TDD)

**Files:**
- Create: `tests/unit/search/test_mos_parser.py`
- Create: `ontoexplorer/modules/search/mos_parser.py` (parse + AST only)

- [ ] **Step 1: Write failing tests**

Create `tests/unit/search/test_mos_parser.py`:

```python
"""Unit tests for the MOS lark parser."""
import pytest

from ontoexplorer.modules.search.mos_parser import (
    ParseError,
    parse,
    And, Or, Not,
    NamedClass,
    SomeValuesFrom, AllValuesFrom, HasValue, HasSelf,
    MinCardinality, MaxCardinality, ExactCardinality,
)


def test_parse_quoted_label():
    node = parse("'cell death'")
    assert isinstance(node, NamedClass)
    assert node.ref == "cell death"
    assert node.curie is None


def test_parse_quoted_label_with_curie():
    node = parse("'cell death (GO:0008219)'")
    assert isinstance(node, NamedClass)
    assert node.ref == "cell death"
    assert node.curie == "GO:0008219"


def test_parse_curie_direct():
    node = parse("GO:0008219")
    assert isinstance(node, NamedClass)
    assert node.ref == "GO:0008219"
    assert node.curie is None


def test_parse_full_iri():
    node = parse("<http://purl.obolibrary.org/obo/GO_0008219>")
    assert isinstance(node, NamedClass)
    assert node.ref == "http://purl.obolibrary.org/obo/GO_0008219"


def test_parse_and():
    node = parse("'Cell' and 'Nucleus'")
    assert isinstance(node, And)
    assert isinstance(node.left, NamedClass)
    assert isinstance(node.right, NamedClass)


def test_parse_or():
    node = parse("'Disease' or 'Disorder'")
    assert isinstance(node, Or)


def test_parse_not():
    node = parse("not 'Neuron'")
    assert isinstance(node, Not)
    assert isinstance(node.operand, NamedClass)


def test_parse_some_values_from():
    node = parse("'hasPart' some 'Nucleus'")
    assert isinstance(node, SomeValuesFrom)
    assert isinstance(node.property_ref, NamedClass)
    assert isinstance(node.filler, NamedClass)


def test_parse_only():
    node = parse("'hasPart' only 'Cell'")
    assert isinstance(node, AllValuesFrom)


def test_parse_min_cardinality():
    node = parse("'hasPart' min 2 'Protein'")
    assert isinstance(node, MinCardinality)
    assert node.cardinality == 2


def test_parse_max_cardinality():
    node = parse("'hasPart' max 3 'Gene'")
    assert isinstance(node, MaxCardinality)
    assert node.cardinality == 3


def test_parse_exactly_cardinality():
    node = parse("'hasPart' exactly 1 'Nucleus'")
    assert isinstance(node, ExactCardinality)
    assert node.cardinality == 1


def test_parse_has_self():
    node = parse("'loves' Self")
    assert isinstance(node, HasSelf)


def test_parse_has_value():
    node = parse("'hasColor' value GO:0000001")
    assert isinstance(node, HasValue)


def test_parse_nested():
    node = parse("'Cell' and 'hasPart' some ('Nucleus' or 'Mitochondrion')")
    assert isinstance(node, And)
    assert isinstance(node.right, SomeValuesFrom)
    assert isinstance(node.right.filler, Or)


def test_parse_error_raises():
    with pytest.raises(ParseError):
        parse("and and and")


def test_parse_error_unclosed_quote():
    with pytest.raises(ParseError):
        parse("'cell death")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_mos_parser.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.search.mos_parser'`

- [ ] **Step 3: Implement mos_parser.py with grammar and parse()**

Create `ontoexplorer/modules/search/mos_parser.py`:

```python
"""Manchester OWL Syntax parser: lark grammar → typed AST nodes."""
from __future__ import annotations

import re
from dataclasses import dataclass

from lark import Lark, Token, Tree, UnexpectedInput

# ── AST node types ─────────────────────────────────────────────────────────────

@dataclass
class NamedClass:
    ref: str             # label text, CURIE, or full IRI
    curie: str | None    # CURIE hint if disambiguated, else None


@dataclass
class And:
    left: "ASTNode"
    right: "ASTNode"


@dataclass
class Or:
    left: "ASTNode"
    right: "ASTNode"


@dataclass
class Not:
    operand: "ASTNode"


@dataclass
class SomeValuesFrom:
    property_ref: NamedClass
    filler: "ASTNode"


@dataclass
class AllValuesFrom:
    property_ref: NamedClass
    filler: "ASTNode"


@dataclass
class HasValue:
    property_ref: NamedClass
    value_ref: NamedClass


@dataclass
class HasSelf:
    property_ref: NamedClass


@dataclass
class MinCardinality:
    property_ref: NamedClass
    cardinality: int
    filler: "ASTNode"


@dataclass
class MaxCardinality:
    property_ref: NamedClass
    cardinality: int
    filler: "ASTNode"


@dataclass
class ExactCardinality:
    property_ref: NamedClass
    cardinality: int
    filler: "ASTNode"


ASTNode = (
    NamedClass | And | Or | Not
    | SomeValuesFrom | AllValuesFrom | HasValue | HasSelf
    | MinCardinality | MaxCardinality | ExactCardinality
)


class ParseError(ValueError):
    pass


# ── Grammar ────────────────────────────────────────────────────────────────────

_GRAMMAR = r"""
    expression   : or_expr
    or_expr      : and_expr ("or" and_expr)*
    and_expr     : not_expr ("and" not_expr)*
    not_expr     : "not" primary -> not_node
                 | primary
    primary      : "(" expression ")" -> paren
                 | restriction
                 | entity_ref     -> named_class_node

    restriction  : entity_ref "some"    expression     -> some_node
                 | entity_ref "only"    expression     -> only_node
                 | entity_ref "value"   entity_ref     -> value_node
                 | entity_ref "Self"                   -> self_node
                 | entity_ref "min"     INT expression -> min_node
                 | entity_ref "max"     INT expression -> max_node
                 | entity_ref "exactly" INT expression -> exactly_node

    entity_ref   : QUOTED_LABEL
                 | CURIE
                 | FULL_IRI

    QUOTED_LABEL : "'" /[^']+/ "'"
    CURIE        : /[A-Za-z_][A-Za-z0-9_\-]*:[A-Za-z0-9_\-\.]+/
    FULL_IRI     : "<" /[^>]+/ ">"
    INT          : /[0-9]+/

    %ignore /\s+/
"""

_PARSER = Lark(_GRAMMAR, start="expression", parser="earley", ambiguity="resolve")

_DISAMBIG_RE = re.compile(r"^(.+?)\s+\(([A-Za-z_][A-Za-z0-9_\-]*:[A-Za-z0-9_\-\.]+)\)$")


def _entity_ref_to_named_class(tree: Tree) -> NamedClass:
    token = tree.children[0]
    raw = str(token)
    if isinstance(token, Token) and token.type == "QUOTED_LABEL":
        inner = raw[1:-1]  # strip surrounding '...'
        m = _DISAMBIG_RE.match(inner)
        if m:
            return NamedClass(ref=m.group(1), curie=m.group(2))
        return NamedClass(ref=inner, curie=None)
    if isinstance(token, Token) and token.type == "FULL_IRI":
        return NamedClass(ref=raw[1:-1], curie=None)  # strip < >
    return NamedClass(ref=raw, curie=None)  # CURIE


def _build(tree: Tree) -> ASTNode:
    if tree.data == "expression":
        return _build(tree.children[0])

    if tree.data == "or_expr":
        children = [_build(c) for c in tree.children]
        result = children[0]
        for c in children[1:]:
            result = Or(result, c)
        return result

    if tree.data == "and_expr":
        children = [_build(c) for c in tree.children]
        result = children[0]
        for c in children[1:]:
            result = And(result, c)
        return result

    if tree.data == "not_node":
        return Not(_build(tree.children[0]))

    if tree.data == "paren":
        return _build(tree.children[0])

    if tree.data == "named_class_node":
        return _entity_ref_to_named_class(tree.children[0])

    if tree.data == "some_node":
        return SomeValuesFrom(_entity_ref_to_named_class(tree.children[0]), _build(tree.children[1]))

    if tree.data == "only_node":
        return AllValuesFrom(_entity_ref_to_named_class(tree.children[0]), _build(tree.children[1]))

    if tree.data == "value_node":
        return HasValue(_entity_ref_to_named_class(tree.children[0]), _entity_ref_to_named_class(tree.children[1]))

    if tree.data == "self_node":
        return HasSelf(_entity_ref_to_named_class(tree.children[0]))

    if tree.data == "min_node":
        return MinCardinality(_entity_ref_to_named_class(tree.children[0]), int(tree.children[1]), _build(tree.children[2]))

    if tree.data == "max_node":
        return MaxCardinality(_entity_ref_to_named_class(tree.children[0]), int(tree.children[1]), _build(tree.children[2]))

    if tree.data == "exactly_node":
        return ExactCardinality(_entity_ref_to_named_class(tree.children[0]), int(tree.children[1]), _build(tree.children[2]))

    if tree.data == "restriction":
        return _build(tree.children[0])

    if tree.data == "primary":
        return _build(tree.children[0])

    raise ParseError(f"Unknown tree node: {tree.data}")


def parse(text: str) -> ASTNode:
    """Parse a MOS expression string into a typed AST. Raises ParseError on failure."""
    try:
        tree = _PARSER.parse(text)
        return _build(tree)
    except UnexpectedInput as exc:
        raise ParseError(str(exc)) from exc
    except Exception as exc:
        raise ParseError(str(exc)) from exc
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_mos_parser.py -v
```

Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/mos_parser.py tests/unit/search/test_mos_parser.py
git commit -m "feat(search): MOS lark grammar and typed AST parser"
```

---

## Task 5: MOS Parser — partial_parse() (TDD)

**Files:**
- Modify: `tests/unit/search/test_mos_parser.py` (add tests)
- Modify: `ontoexplorer/modules/search/mos_parser.py` (add partial_parse + PartialParseResult)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/search/test_mos_parser.py`:

```python
from ontoexplorer.modules.search.mos_parser import partial_parse, PartialParseResult


def test_partial_parse_open_quote_at_start():
    result = partial_parse("'cell d", 7)
    assert result.token_type == "OPEN_QUOTE"
    assert result.partial == "cell d"


def test_partial_parse_open_quote_mid_expression():
    result = partial_parse("'Cell' and 'nuc", 15)
    assert result.token_type == "OPEN_QUOTE"
    assert result.partial == "nuc"


def test_partial_parse_closed_quote_expect_keyword():
    result = partial_parse("'Cell'", 6)
    assert result.token_type == "EXPECT_KEYWORD"
    assert result.partial == ""


def test_partial_parse_after_some_expect_entity():
    result = partial_parse("'hasPart' some ", 15)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_after_min_expect_int():
    result = partial_parse("'hasPart' min ", 14)
    assert result.token_type == "EXPECT_INT"
    assert result.partial == ""


def test_partial_parse_after_int_expect_entity():
    result = partial_parse("'hasPart' min 2 ", 16)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_after_not_expect_entity():
    result = partial_parse("not ", 4)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_empty_input():
    result = partial_parse("", 0)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""


def test_partial_parse_after_and_expect_entity():
    result = partial_parse("'Cell' and ", 11)
    assert result.token_type == "EXPECT_ENTITY"
    assert result.partial == ""
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_mos_parser.py -k "partial" -v 2>&1 | tail -5
```

Expected: FAILED with ImportError.

- [ ] **Step 3: Implement partial_parse()**

Append to `ontoexplorer/modules/search/mos_parser.py`:

```python
# ── Partial parse for autocomplete ────────────────────────────────────────────

@dataclass
class PartialParseResult:
    token_type: str   # "OPEN_QUOTE" | "EXPECT_ENTITY" | "EXPECT_KEYWORD" | "EXPECT_INT"
    partial: str      # partial text being typed at cursor


_KEYWORD_RESTRICTION = {"some", "only", "value", "Self", "min", "max", "exactly"}
_KEYWORD_BOOLEAN = {"and", "or"}
_CURIE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*:[A-Za-z0-9_\-\.]+")
_FULL_IRI_RE = re.compile(r"<[^>]*>")
_INT_RE = re.compile(r"[0-9]+")


def _tokenize_prefix(text: str) -> list[tuple[str, str]]:
    """Tokenize completed text into (type, value) pairs. Skips open quotes."""
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] == "'":
            end = text.find("'", i + 1)
            if end == -1:
                break  # open quote — stop tokenising
            tokens.append(("QUOTED_LABEL", text[i:end + 1]))
            i = end + 1
            continue
        if text[i] == "<":
            end = text.find(">", i + 1)
            if end == -1:
                break
            tokens.append(("FULL_IRI", text[i:end + 1]))
            i = end + 1
            continue
        if text[i] == "(":
            tokens.append(("OPEN_PAREN", "("))
            i += 1
            continue
        if text[i] == ")":
            tokens.append(("CLOSE_PAREN", ")"))
            i += 1
            continue
        # Try keywords and identifiers
        rest = text[i:]
        word_m = re.match(r"[A-Za-z_][A-Za-z0-9_:\-\.]*", rest)
        if word_m:
            word = word_m.group(0)
            if word in _KEYWORD_RESTRICTION:
                tokens.append(("KW_RESTRICTION", word))
            elif word in _KEYWORD_BOOLEAN:
                tokens.append(("KW_BOOLEAN", word))
            elif word == "not":
                tokens.append(("KW_NOT", word))
            elif _CURIE_RE.fullmatch(word):
                tokens.append(("CURIE", word))
            else:
                tokens.append(("WORD", word))
            i += len(word)
            continue
        int_m = re.match(r"[0-9]+", rest)
        if int_m:
            tokens.append(("INT", int_m.group(0)))
            i += len(int_m.group(0))
            continue
        i += 1
    return tokens


def partial_parse(text: str, cursor: int) -> PartialParseResult:
    """Return the expected token type and partial text at cursor for autocomplete."""
    prefix = text[:cursor]

    # Detect open single quote
    in_quote = False
    quote_start = -1
    for idx, ch in enumerate(prefix):
        if ch == "'":
            if not in_quote:
                in_quote = True
                quote_start = idx
            else:
                in_quote = False
                quote_start = -1

    if in_quote:
        return PartialParseResult(token_type="OPEN_QUOTE", partial=prefix[quote_start + 1:])

    tokens = _tokenize_prefix(prefix)

    if not tokens:
        return PartialParseResult(token_type="EXPECT_ENTITY", partial="")

    last_type, last_val = tokens[-1]

    # After a complete entity reference → expect restriction or boolean keyword
    if last_type in ("QUOTED_LABEL", "CURIE", "FULL_IRI"):
        return PartialParseResult(token_type="EXPECT_KEYWORD", partial="")

    # After min/max/exactly → expect integer
    if last_type == "KW_RESTRICTION" and last_val in ("min", "max", "exactly"):
        return PartialParseResult(token_type="EXPECT_INT", partial="")

    # After integer → expect entity (filler class)
    if last_type == "INT":
        return PartialParseResult(token_type="EXPECT_ENTITY", partial="")

    # After restriction keyword (some/only/value) or boolean (and/or) or not / ( → expect entity
    return PartialParseResult(token_type="EXPECT_ENTITY", partial="")
```

- [ ] **Step 4: Run all parser tests**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_mos_parser.py -v
```

Expected: 26 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/mos_parser.py tests/unit/search/test_mos_parser.py
git commit -m "feat(search): partial_parse for cursor-aware autocomplete context"
```

---

## Task 6: Autocomplete Engine (TDD)

**Files:**
- Create: `tests/unit/search/test_autocomplete.py`
- Create: `ontoexplorer/modules/search/autocomplete.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/search/test_autocomplete.py`:

```python
"""Unit tests for the autocomplete engine."""
import fakeredis
from unittest.mock import patch

from ontoexplorer.modules.search.autocomplete import get_completions, Completion
from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key


def _setup_redis(version_id: str) -> fakeredis.FakeRedis:
    r = fakeredis.FakeRedis(decode_responses=True)
    key = _prefix_key(version_id)
    # Two "cell death" entries with different IRIs (ambiguous)
    r.zadd(key, {"cell death|class|http://go.org/CD": 0})
    r.zadd(key, {"cell death|class|http://mondo.org/CD": 0})
    r.zadd(key, {"cell division|class|http://go.org/CDV": 0})
    r.zadd(key, {"has part|property|http://bfo.org/HP": 0})
    r.hset(_iri_key(version_id, "http://go.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://go.org/CD", "short": "GO:CD", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://mondo.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://mondo.org/CD", "short": "MONDO:CD", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://go.org/CDV"), mapping={
        "label": "cell division", "type": "class",
        "iri": "http://go.org/CDV", "short": "GO:CDV", "synonyms": "",
    })
    r.hset(_iri_key(version_id, "http://bfo.org/HP"), mapping={
        "label": "has part", "type": "property",
        "iri": "http://bfo.org/HP", "short": "BFO:HP", "synonyms": "",
    })
    return r


def test_completions_open_quote_returns_entities():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell d", cursor=7, version_id="v1", limit=10)
    texts = [c.text for c in completions]
    assert any("cell death" in t for t in texts)
    assert any("cell division" in t for t in texts)


def test_completions_disambiguated_label_shown_for_ambiguous():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell death", cursor=11, version_id="v1", limit=10)
    # Should see two completions with CURIE disambiguation
    inserts = [c.insert for c in completions if c.type == "class"]
    assert any("GO:CD" in ins for ins in inserts)
    assert any("MONDO:CD" in ins for ins in inserts)
    # Both inserts should end with closing quote
    assert all(ins.endswith("'") for ins in inserts)


def test_completions_unambiguous_label_no_curie():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'cell div", cursor=9, version_id="v1", limit=10)
    inserts = [c.insert for c in completions]
    assert any(ins == "cell division'" for ins in inserts)


def test_completions_after_entity_returns_restriction_and_boolean_keywords():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'Cell'", cursor=6, version_id="v1", limit=20)
    kw_texts = {c.text for c in completions if c.type == "keyword"}
    assert "some" in kw_texts
    assert "only" in kw_texts
    assert "and" in kw_texts
    assert "or" in kw_texts


def test_completions_after_some_returns_only_classes():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'hasPart' some 'cell", cursor=20, version_id="v1", limit=10)
    types = {c.type for c in completions}
    assert "class" in types
    assert "property" not in types


def test_completions_after_min_returns_int_hint():
    r = _setup_redis("v1")
    with patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=r):
        completions = get_completions("'hasPart' min ", cursor=14, version_id="v1", limit=10)
    types = {c.type for c in completions}
    assert "cardinality" in types
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_autocomplete.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.search.autocomplete'`

- [ ] **Step 3: Implement autocomplete.py**

Create `ontoexplorer/modules/search/autocomplete.py`:

```python
"""Cursor-aware MOS autocomplete engine."""
from __future__ import annotations

from dataclasses import dataclass

from ontoexplorer.modules.search.indexer import _get_redis, _prefix_key, _iri_key, normalise_label
from ontoexplorer.modules.search.mos_parser import partial_parse

_RESTRICTION_KEYWORDS = ["some", "only", "value", "Self", "min", "max", "exactly"]
_BOOLEAN_KEYWORDS = ["and", "or", "not", "(", ")"]


@dataclass
class Completion:
    text: str           # display text
    type: str           # "class" | "property" | "keyword" | "cardinality"
    iri: str | None
    short: str | None
    insert: str         # text to splice at cursor (includes closing ' for labels)


def get_completions(
    q: str,
    cursor: int,
    version_id: str,
    limit: int = 10,
) -> list[Completion]:
    result = partial_parse(q, cursor)
    r = _get_redis()

    if result.token_type == "OPEN_QUOTE":
        return _entity_completions(r, version_id, result.partial, entity_type=None, limit=limit)

    if result.token_type == "EXPECT_ENTITY":
        # After some/only/not/and/or/(  — figure out if we expect class or property
        # Heuristic: after a restriction keyword (some/only/value/min N/max N/exactly N) → class
        # At start / after boolean → either
        kws = _keyword_completions(["'"])  # trigger quote
        return kws

    if result.token_type == "EXPECT_KEYWORD":
        # After a complete entity ref — offer restriction + boolean keywords
        kws = _keyword_completions(_RESTRICTION_KEYWORDS + _BOOLEAN_KEYWORDS)
        return kws

    if result.token_type == "EXPECT_INT":
        return [Completion(text="1", type="cardinality", iri=None, short=None, insert="1 "),
                Completion(text="2", type="cardinality", iri=None, short=None, insert="2 "),
                Completion(text="3", type="cardinality", iri=None, short=None, insert="3 ")]

    return []


def _entity_completions(
    r,
    version_id: str,
    partial: str,
    entity_type: str | None,
    limit: int,
) -> list[Completion]:
    norm = normalise_label(partial) if partial else ""
    key = _prefix_key(version_id)

    if norm:
        min_val = f"[{norm}"
        max_val = f"[{norm}\xff"
        members = r.zrangebylex(key, min_val, max_val, start=0, count=limit * 4)
    else:
        members = r.zrange(key, 0, limit * 4 - 1)

    # Group members by normalised label to detect ambiguity
    by_norm_label: dict[str, list[dict]] = {}
    for member in members:
        parts = member.split("|", 2)
        if len(parts) != 3:
            continue
        norm_lbl, etype, iri = parts
        if entity_type and etype != entity_type:
            continue
        detail = r.hgetall(_iri_key(version_id, iri))
        if not detail:
            continue
        by_norm_label.setdefault(norm_lbl, []).append(detail)

    completions: list[Completion] = []
    for norm_lbl, entities in by_norm_label.items():
        if len(entities) == 1:
            e = entities[0]
            completions.append(Completion(
                text=e["label"],
                type=e["type"],
                iri=e["iri"],
                short=e["short"],
                insert=f"{e['label']}'",
            ))
        else:
            for e in entities:
                completions.append(Completion(
                    text=f"{e['label']} ({e['short']})",
                    type=e["type"],
                    iri=e["iri"],
                    short=e["short"],
                    insert=f"{e['label']} ({e['short']})'",
                ))
        if len(completions) >= limit:
            break

    return completions[:limit]


def _keyword_completions(keywords: list[str]) -> list[Completion]:
    return [
        Completion(
            text=kw,
            type="keyword",
            iri=None,
            short=None,
            insert=f" {kw} " if kw not in ("(", ")", "'") else kw,
        )
        for kw in keywords
    ]
```

- [ ] **Step 4: Run all autocomplete tests**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_autocomplete.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/autocomplete.py tests/unit/search/test_autocomplete.py
git commit -m "feat(search): cursor-aware MOS autocomplete engine"
```

---

## Task 7: ELK Classification Loader (TDD)

**Files:**
- Modify: `ontoexplorer/clients/reasoning.py` (add `get_classification`)
- Modify: `tests/integration/test_reasoning_api.py` (no change needed — existing tests must still pass)

The evaluator needs the full subclass index from ELK. Add a `get_classification(version_id)` function to the existing reasoning client that calls `GET /classify/{version_id}` on the ELK service.

- [ ] **Step 1: Read the current reasoning client to find where to add**

```bash
source .venv/bin/activate && grep -n "^async def\|^def\|^class" ontoexplorer/clients/reasoning.py
```

Note the existing function names and the `_elk_url()` helper used throughout.

- [ ] **Step 2: Add get_classification to reasoning client**

Open `ontoexplorer/clients/reasoning.py` and append the following function (after the existing functions, before the end of file):

```python
async def get_classification(version_id: str) -> dict:
    """Fetch the full ClassificationResult JSON from the ELK service cache.

    Returns the raw dict with keys: superclasses, subclasses, direct_superclasses,
    direct_subclasses, unsatisfiable, class_count, proof_traces, etc.

    Raises ReasoningNotReadyError if the version has not been classified yet.
    """
    url = f"{_elk_url()}/classify/{version_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
    if resp.status_code == 404:
        raise ReasoningNotReadyError(version_id)
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 3: Verify existing reasoning tests still pass**

```bash
source .venv/bin/activate && python3 -m pytest tests/integration/test_reasoning_api.py -v
```

Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/clients/reasoning.py
git commit -m "feat(search): add get_classification to ELK reasoning client"
```

---

## Task 8: Expression Evaluator (TDD)

**Files:**
- Create: `tests/unit/search/test_evaluator.py`
- Create: `ontoexplorer/modules/search/evaluator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/search/test_evaluator.py`:

```python
"""Unit tests for the MOS expression evaluator."""
import fakeredis
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from ontoexplorer.modules.search.mos_parser import (
    NamedClass, And, Or, Not,
    SomeValuesFrom, AllValuesFrom, MinCardinality,
)
from ontoexplorer.modules.search.evaluator import (
    AmbiguousLabelError,
    evaluate,
    SearchResult,
)
from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key


def _make_classification(subclasses: dict) -> dict:
    return {
        "version_id": "v1",
        "classified_at": "2026-01-01T00:00:00+00:00",
        "class_count": len(subclasses),
        "superclasses": {},
        "subclasses": subclasses,
        "direct_superclasses": {},
        "direct_subclasses": {},
        "unsatisfiable": [],
        "proof_traces": {},
        "duration_ms": 1.0,
    }


def _make_redis_with_entity(version_id: str, label: str, iri: str, entity_type: str = "class"):
    r = fakeredis.FakeRedis(decode_responses=True)
    norm = label.lower()
    r.zadd(_prefix_key(version_id), {f"{norm}|{entity_type}|{iri}": 0})
    r.hset(_iri_key(version_id, iri), mapping={
        "label": label, "type": entity_type,
        "iri": iri, "short": iri.split("/")[-1], "synonyms": "",
    })
    return r


@pytest.mark.anyio
async def test_evaluate_named_class_returns_subclasses():
    r = _make_redis_with_entity("v1", "Cell", "http://ex.org/Cell")
    classification = _make_classification({
        "http://ex.org/Cell": ["http://ex.org/EukaryoticCell", "http://ex.org/ProkaryoticCell"],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(NamedClass(ref="Cell", curie=None), "v1")
    iris = {r.iri for r in results}
    assert "http://ex.org/EukaryoticCell" in iris
    assert "http://ex.org/ProkaryoticCell" in iris


@pytest.mark.anyio
async def test_evaluate_and_intersects():
    r = fakeredis.FakeRedis(decode_responses=True)
    # Cell subclasses: A, B; Nucleus subclasses: B, C → and = {B}
    for label, iri in [("Cell", "http://ex.org/Cell"), ("Nucleus", "http://ex.org/Nucleus")]:
        r.zadd(_prefix_key("v1"), {f"{label.lower()}|class|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": label, "type": "class", "iri": iri, "short": label, "synonyms": "",
        })
    classification = _make_classification({
        "http://ex.org/Cell":   ["http://ex.org/A", "http://ex.org/B"],
        "http://ex.org/Nucleus":["http://ex.org/B", "http://ex.org/C"],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(
            And(NamedClass("Cell", None), NamedClass("Nucleus", None)), "v1"
        )
    iris = {r.iri for r in results}
    assert iris == {"http://ex.org/B"}


@pytest.mark.anyio
async def test_evaluate_or_unions():
    r = fakeredis.FakeRedis(decode_responses=True)
    for label, iri in [("Cell", "http://ex.org/Cell"), ("Virus", "http://ex.org/Virus")]:
        r.zadd(_prefix_key("v1"), {f"{label.lower()}|class|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": label, "type": "class", "iri": iri, "short": label, "synonyms": "",
        })
    classification = _make_classification({
        "http://ex.org/Cell":  ["http://ex.org/A"],
        "http://ex.org/Virus": ["http://ex.org/B"],
    })
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        results = await evaluate(
            Or(NamedClass("Cell", None), NamedClass("Virus", None)), "v1"
        )
    iris = {r.iri for r in results}
    assert {"http://ex.org/A", "http://ex.org/B"} <= iris


@pytest.mark.anyio
async def test_evaluate_ambiguous_label_raises():
    r = fakeredis.FakeRedis(decode_responses=True)
    # Two IRIs share label "cell death"
    for iri in ["http://go.org/CD", "http://mondo.org/CD"]:
        r.zadd(_prefix_key("v1"), {f"cell death|class|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": "cell death", "type": "class",
            "iri": iri, "short": iri.split("/")[-1], "synonyms": "",
        })
    classification = _make_classification({})
    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)):
        with pytest.raises(AmbiguousLabelError) as exc_info:
            await evaluate(NamedClass(ref="cell death", curie=None), "v1")
    assert exc_info.value.label == "cell death"
    assert len(exc_info.value.candidates) == 2


@pytest.mark.anyio
async def test_evaluate_some_values_from_calls_sparql():
    r = fakeredis.FakeRedis(decode_responses=True)
    for label, iri, etype in [
        ("hasPart", "http://bfo.org/HP", "property"),
        ("Nucleus",  "http://ex.org/N",   "class"),
    ]:
        r.zadd(_prefix_key("v1"), {f"{label.lower()}|{etype}|{iri}": 0})
        r.hset(_iri_key("v1", iri), mapping={
            "label": label, "type": etype, "iri": iri, "short": label, "synonyms": "",
        })

    mock_sol = MagicMock()
    mock_sol.__getitem__ = lambda self, k: MagicMock(value="http://ex.org/Cell")
    classification = _make_classification({})

    with patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=r), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value=classification)), \
         patch("ontoexplorer.modules.search.evaluator.sparql_query",
               return_value=[mock_sol]) as mock_sparql:
        results = await evaluate(
            SomeValuesFrom(NamedClass("hasPart", None), NamedClass("Nucleus", None)), "v1"
        )
    assert mock_sparql.called
    assert any(r.match_type == "sparql" for r in results)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_evaluator.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.search.evaluator'`

- [ ] **Step 3: Implement evaluator.py**

Create `ontoexplorer/modules/search/evaluator.py`:

```python
"""MOS expression evaluator: AST → matching class IRIs via hybrid ELK + Oxigraph SPARQL."""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from ontoexplorer.clients.oxigraph import graph_iri, sparql_query
from ontoexplorer.clients.reasoning import ReasoningNotReadyError, get_classification
from ontoexplorer.modules.search.indexer import (
    _get_redis,
    _iri_key,
    _prefix_key,
    normalise_label,
)
from ontoexplorer.modules.search.mos_parser import (
    AllValuesFrom,
    And,
    ASTNode,
    ExactCardinality,
    HasSelf,
    HasValue,
    MaxCardinality,
    MinCardinality,
    NamedClass,
    Not,
    Or,
    SomeValuesFrom,
)


@dataclass
class SearchResult:
    iri: str
    label: str
    short: str
    match_type: str   # "elk" | "sparql" | "entity"


class AmbiguousLabelError(ValueError):
    def __init__(self, label: str, candidates: list[dict]):
        super().__init__(f"Ambiguous label: {label!r} matches {len(candidates)} entities")
        self.label = label
        self.candidates = candidates


def _resolve_label(r, version_id: str, node: NamedClass) -> str:
    """Resolve a NamedClass node to a single IRI. Raises AmbiguousLabelError if ambiguous."""
    if node.curie:
        # Disambiguated form: look up by CURIE (stored as `short` field)
        norm = normalise_label(node.curie)
        key = _prefix_key(version_id)
        members = r.zrangebylex(key, f"[{norm}", f"[{norm}\xff")
        for m in members:
            parts = m.split("|", 2)
            if len(parts) == 3:
                _, _, iri = parts
                detail = r.hgetall(_iri_key(version_id, iri))
                if detail.get("short") == node.curie:
                    return iri
        # Fallback: if CURIE is itself an IRI fragment
        return node.ref

    # Check if ref looks like a CURIE or IRI already
    if ":" in node.ref and not node.ref.startswith("'"):
        # Try direct lookup via short/CURIE
        norm = normalise_label(node.ref)
        key = _prefix_key(version_id)
        members = r.zrangebylex(key, f"[{norm}", f"[{norm}\xff")
        for m in members:
            parts = m.split("|", 2)
            if len(parts) == 3:
                _, _, iri = parts
                return iri
        return node.ref  # treat as IRI directly

    # Plain label — look up in prefix index
    norm = normalise_label(node.ref)
    key = _prefix_key(version_id)
    members = r.zrangebylex(key, f"[{norm}|", f"[{norm}|\xff")
    # Exact-label match: members where the norm_label part exactly equals norm
    matched: list[dict] = []
    seen_iris: set[str] = set()
    for m in members:
        parts = m.split("|", 2)
        if len(parts) != 3:
            continue
        norm_lbl, _, iri = parts
        if norm_lbl != norm:
            continue
        if iri in seen_iris:
            continue
        seen_iris.add(iri)
        detail = r.hgetall(_iri_key(version_id, iri))
        if detail:
            matched.append(detail)

    if len(matched) == 0:
        return node.ref  # unknown — pass through, SPARQL may handle it
    if len(matched) == 1:
        return matched[0]["iri"]
    raise AmbiguousLabelError(node.ref, matched)


async def evaluate(node: ASTNode, version_id: str) -> list[SearchResult]:
    """Evaluate a MOS AST node against the given version, returning matching classes."""
    r = _get_redis()
    classification = await get_classification(version_id)
    subclasses_index: dict[str, list[str]] = classification.get("subclasses", {})
    all_class_iris: set[str] = set(subclasses_index.keys()) | {
        iri for subs in subclasses_index.values() for iri in subs
    }

    async def _eval(n: ASTNode) -> set[str]:
        if isinstance(n, NamedClass):
            iri = _resolve_label(r, version_id, n)
            subs = set(subclasses_index.get(iri, []))
            subs.add(iri)
            return subs

        if isinstance(n, And):
            return await _eval(n.left) & await _eval(n.right)

        if isinstance(n, Or):
            return await _eval(n.left) | await _eval(n.right)

        if isinstance(n, Not):
            return all_class_iris - await _eval(n.operand)

        if isinstance(n, (SomeValuesFrom, AllValuesFrom, HasValue, HasSelf,
                          MinCardinality, MaxCardinality, ExactCardinality)):
            return _sparql_eval(n, version_id, r)

        return set()

    iris = await _eval(node)

    # Build results with labels
    results: list[SearchResult] = []
    for iri in iris:
        detail = r.hgetall(_iri_key(version_id, iri))
        label = detail.get("label", iri.split("/")[-1]) if detail else iri.split("/")[-1]
        short = detail.get("short", "") if detail else ""
        match_type = "elk" if not isinstance(node, (SomeValuesFrom, AllValuesFrom, HasValue,
                                                      HasSelf, MinCardinality, MaxCardinality,
                                                      ExactCardinality)) else "sparql"
        results.append(SearchResult(iri=iri, label=label, short=short, match_type=match_type))

    return results


def _sparql_eval(node: ASTNode, version_id: str, r) -> set[str]:
    """Translate restriction AST nodes to SPARQL and query Oxigraph."""
    OWL = "http://www.w3.org/2002/07/owl#"
    RDFS = "http://www.w3.org/2000/01/rdf-schema#"

    if isinstance(node, SomeValuesFrom):
        prop_iri = node.property_ref.ref if node.property_ref.curie is None else node.property_ref.ref
        fill_iri = node.filler.ref if isinstance(node.filler, NamedClass) and node.filler.curie is None else getattr(node.filler, "ref", "")
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}someValuesFrom> <{fill_iri}> .
            }}
        """
    elif isinstance(node, AllValuesFrom):
        prop_iri = node.property_ref.ref
        fill_iri = node.filler.ref if isinstance(node.filler, NamedClass) else ""
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}allValuesFrom> <{fill_iri}> .
            }}
        """
    elif isinstance(node, MinCardinality):
        prop_iri = node.property_ref.ref
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}minCardinality> ?n .
                FILTER(?n >= {node.cardinality})
            }}
        """
    elif isinstance(node, MaxCardinality):
        prop_iri = node.property_ref.ref
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}maxCardinality> ?n .
                FILTER(?n <= {node.cardinality})
            }}
        """
    elif isinstance(node, ExactCardinality):
        prop_iri = node.property_ref.ref
        q = f"""
            SELECT DISTINCT ?cls WHERE {{
                ?cls <{RDFS}subClassOf> ?restr .
                ?restr <{OWL}onProperty> <{prop_iri}> .
                ?restr <{OWL}cardinality> {node.cardinality} .
            }}
        """
    else:
        return set()

    results: set[str] = set()
    for sol in sparql_query(q):
        try:
            results.add(sol["cls"].value)
        except Exception:
            pass
    return results
```

- [ ] **Step 4: Run all evaluator tests**

```bash
source .venv/bin/activate && python3 -m pytest tests/unit/search/test_evaluator.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/evaluator.py tests/unit/search/test_evaluator.py
git commit -m "feat(search): hybrid ELK+SPARQL MOS expression evaluator"
```

---

## Task 9: FastAPI Router and Integration Tests (TDD)

**Files:**
- Create: `tests/integration/test_search.py`
- Create: `ontoexplorer/api/search.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/integration/test_search.py`:

```python
"""Integration tests for the MOS search API endpoints."""
import fakeredis
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ontoexplorer.modules.search.indexer import _prefix_key, _iri_key

_VERSION_MOCK = MagicMock()
_MOCK_VERSION = AsyncMock(return_value=_VERSION_MOCK)

_FAKE_REDIS = fakeredis.FakeRedis(decode_responses=True)

def _seed_redis(version_id: str):
    _FAKE_REDIS.flushall()
    key = _prefix_key(version_id)
    _FAKE_REDIS.zadd(key, {"cell death|class|http://ex.org/CD": 0})
    _FAKE_REDIS.zadd(key, {"nucleus|class|http://ex.org/N": 0})
    _FAKE_REDIS.hset(_iri_key(version_id, "http://ex.org/CD"), mapping={
        "label": "cell death", "type": "class",
        "iri": "http://ex.org/CD", "short": "EX:CD", "synonyms": "",
    })
    _FAKE_REDIS.hset(_iri_key(version_id, "http://ex.org/N"), mapping={
        "label": "nucleus", "type": "class",
        "iri": "http://ex.org/N", "short": "EX:N", "synonyms": "",
    })


@pytest.mark.anyio
async def test_search_entity_mode(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch("ontoexplorer.api.ontologies._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "cell death", "mode": "entity"},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "entity"
    assert any(r["iri"] == "http://ex.org/CD" for r in body["results"])


@pytest.mark.anyio
async def test_search_expression_not_classified(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    from ontoexplorer.clients.reasoning import ReasoningNotReadyError

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(side_effect=ReasoningNotReadyError("fake-vid"))), \
         patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death' and 'nucleus'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 503
    assert resp.json()["error"] == "not_classified"


@pytest.mark.anyio
async def test_search_expression_parse_error(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "and and and", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "parse_error"


@pytest.mark.anyio
async def test_search_ambiguous_label_returns_422(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    from ontoexplorer.modules.search.evaluator import AmbiguousLabelError

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.evaluator.get_classification",
               new=AsyncMock(return_value={"subclasses": {}, "class_count": 0})), \
         patch("ontoexplorer.modules.search.evaluator._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.evaluator._resolve_label",
               side_effect=AmbiguousLabelError("cell death", [
                   {"label": "cell death", "short": "GO:CD", "iri": "http://go.org/CD"},
                   {"label": "cell death", "short": "MONDO:CD", "iri": "http://mondo.org/CD"},
               ])):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/search",
            params={"q": "'cell death'", "mode": "expression"},
            headers=auth,
        )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "ambiguous_label"
    assert len(body["candidates"]) == 2


@pytest.mark.anyio
async def test_autocomplete_open_quote(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}
    _seed_redis("fake-vid")

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.indexer._get_redis", return_value=_FAKE_REDIS), \
         patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/autocomplete",
            params={"q": "'cell", "cursor": 5},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "completions" in body
    assert any("cell death" in c["text"] for c in body["completions"])


@pytest.mark.anyio
async def test_autocomplete_after_entity_returns_keywords(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    with patch("ontoexplorer.api.search._get_version_or_404", new=_MOCK_VERSION), \
         patch("ontoexplorer.modules.search.autocomplete._get_redis", return_value=_FAKE_REDIS):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/autocomplete",
            params={"q": "'Cell'", "cursor": 6},
            headers=auth,
        )
    assert resp.status_code == 200
    texts = [c["text"] for c in resp.json()["completions"]]
    assert "some" in texts
    assert "and" in texts
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
source .venv/bin/activate && python3 -m pytest tests/integration/test_search.py -v 2>&1 | head -15
```

Expected: fails with `404` (router not mounted yet) or `ImportError`.

- [ ] **Step 3: Implement api/search.py**

Create `ontoexplorer/api/search.py`:

```python
"""MOS Search API — GET /search and GET /autocomplete per ontology version."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.api.ontologies import _get_version_or_404
from ontoexplorer.clients.reasoning import ReasoningNotReadyError
from ontoexplorer.database import get_db
from ontoexplorer.modules.auth.dependencies import get_current_user
from ontoexplorer.modules.search.autocomplete import get_completions
from ontoexplorer.modules.search.evaluator import AmbiguousLabelError, evaluate
from ontoexplorer.modules.search.indexer import entity_lookup
from ontoexplorer.modules.search.mos_parser import ParseError, parse, NamedClass, And, Or, Not

router = APIRouter(
    prefix="/api/v1/ontologies/{ontology_id}/{version_id}",
    tags=["search"],
)


def _is_expression(node) -> bool:
    """True if the AST contains any restriction or boolean operator (not just a bare NamedClass)."""
    if isinstance(node, NamedClass):
        return False
    return True


@router.get("/search", summary="MOS entity lookup or expression query")
async def search(
    ontology_id: str,
    version_id: str,
    q: str = Query(..., description="Entity label, CURIE, IRI, or MOS expression"),
    mode: str = Query("auto", description="auto | entity | expression"),
    limit: int = Query(20, ge=1, le=200),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)

    # Determine effective mode
    effective_mode = mode
    ast = None
    if mode in ("auto", "expression"):
        try:
            ast = parse(q)
            if mode == "auto":
                effective_mode = "expression" if _is_expression(ast) else "entity"
        except ParseError as exc:
            if mode == "expression":
                raise HTTPException(400, detail={"error": "parse_error", "message": str(exc)})
            effective_mode = "entity"

    if effective_mode == "entity":
        results = await asyncio.to_thread(entity_lookup, version_id, q, None, limit)
        return {
            "mode": "entity",
            "query": q,
            "results": [
                {"iri": r["iri"], "label": r["label"], "short": r["short"], "match_type": "entity"}
                for r in results
            ],
            "count": len(results),
            "truncated": len(results) >= limit,
        }

    # Expression mode
    try:
        search_results = await evaluate(ast, version_id)
    except AmbiguousLabelError as exc:
        raise HTTPException(422, detail={
            "error": "ambiguous_label",
            "label": exc.label,
            "candidates": exc.candidates,
        })
    except ReasoningNotReadyError:
        raise HTTPException(503, detail={"error": "not_classified"})

    trimmed = search_results[:limit]
    return {
        "mode": "expression",
        "query": q,
        "results": [
            {"iri": r.iri, "label": r.label, "short": r.short, "match_type": r.match_type}
            for r in trimmed
        ],
        "count": len(trimmed),
        "truncated": len(search_results) > limit,
    }


@router.get("/autocomplete", summary="Context-sensitive MOS autocomplete")
async def autocomplete(
    ontology_id: str,
    version_id: str,
    q: str = Query(..., description="Partial MOS expression text"),
    cursor: int = Query(-1, description="Byte offset of cursor (-1 = end of q)"),
    limit: int = Query(10, ge=1, le=50),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    effective_cursor = cursor if cursor >= 0 else len(q)
    completions = await asyncio.to_thread(
        get_completions, q, effective_cursor, version_id, limit
    )
    from ontoexplorer.modules.search.mos_parser import partial_parse
    ctx = partial_parse(q, effective_cursor)
    return {
        "completions": [
            {"text": c.text, "type": c.type, "iri": c.iri, "short": c.short, "insert": c.insert}
            for c in completions
        ],
        "context": ctx.token_type.lower(),
    }
```

- [ ] **Step 4: Mount the search router in main.py**

Edit `ontoexplorer/main.py`. Add the import and `include_router` call:

```python
from ontoexplorer.api.search import router as search_router
```

And inside `create_app()`, after `app.include_router(ontologies_router)`:

```python
    app.include_router(search_router)
```

- [ ] **Step 5: Run integration tests**

```bash
source .venv/bin/activate && python3 -m pytest tests/integration/test_search.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/search.py tests/integration/test_search.py ontoexplorer/main.py
git commit -m "feat(search): FastAPI search and autocomplete endpoints"
```

---

## Task 10: Wire Celery Task and Deprecation Hook

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`
- Modify: `ontoexplorer/api/ontologies.py`

- [ ] **Step 1: Replace the index_ontology stub in tasks.py**

In `ontoexplorer/modules/jobs/tasks.py`, replace:

```python
@celery_app.task(name="ontoexplorer.index_ontology")
def index_ontology(version_id: str) -> dict:
    """Stub: NL search indexing — implemented in Subsystem 3."""
    log.info("index_ontology_stub", version_id=version_id)
    return {"status": "stub", "version_id": version_id}
```

with:

```python
@celery_app.task(name="ontoexplorer.index_ontology", bind=True, max_retries=2)
def index_ontology(self, version_id: str, ontology_id: str = "") -> dict:
    """Build the Redis entity search index for a version."""
    log.info("index_ontology_start", version_id=version_id)
    try:
        from ontoexplorer.modules.search.indexer import build_index
        stats = build_index(version_id, ontology_id)
        log.info("index_ontology_done", version_id=version_id,
                 class_count=stats.class_count, property_count=stats.property_count)
        return {"status": "done", "version_id": version_id,
                "class_count": stats.class_count, "property_count": stats.property_count}
    except Exception as exc:
        log.error("index_ontology_failed", version_id=version_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30)
```

- [ ] **Step 2: Verify the ingestion pipeline passes ontology_id to index_ontology**

In `ontoexplorer/modules/jobs/tasks.py`, find where `index_ontology.delay(version_id)` is called (in the `ingest_ontology` task or pipeline) and update it to also pass `ontology_id`:

```bash
grep -n "index_ontology" ontoexplorer/modules/jobs/tasks.py
```

If the call is `index_ontology.delay(version_id)`, change to `index_ontology.delay(version_id, ontology_id=ontology_id)`. If `ontology_id` is not available at that call site, check how `reason_ontology` receives it and follow the same pattern.

- [ ] **Step 3: Add invalidate_index to deprecate_version in ontologies.py**

In `ontoexplorer/api/ontologies.py`, inside `deprecate_version`, after the existing ELK cache invalidation block, add:

```python
    # Invalidate search entity index for this version
    try:
        import asyncio
        from ontoexplorer.modules.search.indexer import invalidate_index
        await asyncio.to_thread(invalidate_index, version_id)
    except Exception:
        pass  # Non-fatal
```

- [ ] **Step 4: Run the full test suite**

```bash
source .venv/bin/activate && python3 -m pytest tests/ -v --ignore=tests/unit/search/test_evaluator.py 2>&1 | tail -20
```

Note: `test_evaluator.py` uses `anyio` marks and runs fine, but run separately if needed:

```bash
source .venv/bin/activate && python3 -m pytest tests/ -v 2>&1 | tail -30
```

Expected: all existing tests pass plus the new search tests.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py ontoexplorer/api/ontologies.py
git commit -m "feat(search): wire index_ontology Celery task and deprecation invalidation"
```

---

## Self-Review Checklist (completed inline)

**Spec coverage:**
- ✅ Redis entity index (sorted set, hash, type set, meta key) — Tasks 2–3
- ✅ Label normalisation — Task 2
- ✅ MOS lark grammar + all AST nodes — Task 4
- ✅ `parse()` + `partial_parse()` — Tasks 4–5
- ✅ `get_completions()` with `OPEN_QUOTE` / `EXPECT_KEYWORD` / `EXPECT_INT` contexts — Task 6
- ✅ Disambiguated `label (CURIE)'` insert form — Task 6
- ✅ `get_classification()` on reasoning client — Task 7
- ✅ Evaluator: NamedClass, And, Or, Not (ELK), SomeValuesFrom, AllValuesFrom, cardinalities (SPARQL) — Task 8
- ✅ `AmbiguousLabelError` with candidates — Task 8
- ✅ `GET /search` with auto/entity/expression modes, 400/422/503 errors — Task 9
- ✅ `GET /autocomplete` with context field — Task 9
- ✅ `index_ontology` stub replaced — Task 10
- ✅ `invalidate_index` on deprecation — Task 10

**Placeholder scan:** No TBDs found.

**Type consistency:** `NamedClass`, `And`, `Or`, `Not`, `SomeValuesFrom` etc. defined in Task 4 and used consistently in Tasks 6, 8, 9.
