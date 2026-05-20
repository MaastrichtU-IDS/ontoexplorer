# Ontology Reuse Analysis (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a per-ontology and fleet-level reuse-analysis surface inside OntoExplorer that captures four reuse signals (owl:imports closure, term-IRI reuse, MIREOT-pattern, mapping predicates) with bioregistry-normalized IRIs, plus a parallel BioPortal-scale population rerun.

**Architecture:** New module `ontoexplorer/modules/reuse/` mirrors the `owl_profile` module shape — pure functions over a pyoxigraph `Store`, results cached in Redis at indexing time (`_populate_reuse_cache` hook in `indexer.py`), refreshable via a Celery task, served read-only by a FastAPI router. Frontend adds a per-ontology `ReuseSection` (cards) and a fleet-level `Reuse` tab (sortable table) under the existing `/ontologies?tab=` dispatcher. A separate `scripts/bioportal_reuse/` runner reuses the same `bioregistry.py` wrapper to publish updated population numbers to the user's existing GitHub Pages site.

**Tech Stack:** Python 3.10+, pyoxigraph (in-process SPARQL), SQLAlchemy async + Postgres (existing `OntologyImport`/`OntologyVersion` tables), Redis (cache, 30-day TTL), Celery (refresh task), FastAPI (routes), React + TanStack Query (frontend), `bioregistry>=0.11` (new dependency, ships offline prefix data).

---

## File Structure (locked-in decomposition)

Each Python file has one clear responsibility; signal modules are small and independently testable.

```
ontoexplorer/modules/reuse/
    __init__.py                # re-exports public types
    cache.py                   # Redis key helper:  reuse_cache_key(version_id) -> str
    bioregistry.py             # iri_to_prefix(), prefix_to_canonical_iri() + Redis-cached lookups
    detector.py                # detect_reuse(store, version_id, host_iri, db_imports) -> ReuseReport
    signals/
        __init__.py            # exports the four signal entry-points
        imports.py             # build_closure(db_imports) -> list[ImportEdge]
        term_iri.py            # classify_terms(entities, host_prefix, host_namespaces) -> dict[str, TermIRIReuseEntry]
        mireot.py              # detect_mireot(store, graph_iri, host_prefix, host_namespaces, import_prefix_set) -> list[MireotTerm]
        mappings.py            # extract_mappings(store, graph_iri, host_prefix) -> dict[str, list[MappingEntry]]

ontoexplorer/api/
    reuse.py                   # GET /api/v1/ontologies/{id}/{vid}/reuse + /api/v1/reuse/fleet

scripts/bioportal_reuse/
    README.md
    run.py                     # CLI entry: orchestrates the three steps
    normalize.py               # apply bioregistry to preliminary-work CSVs
    mireot_heuristic.py        # weaker-signal MIREOT estimator (no axioms)
    publish.py                 # write CSV/JSON to the bioportal-ontology-analysis site dir

frontend/src/components/
    ReuseSection.tsx           # four cards for per-ontology view

frontend/src/pages/
    Reuse.tsx                  # fleet table + summary cards

tests/unit/reuse/
    __init__.py
    test_bioregistry.py
    test_signal_imports.py
    test_signal_term_iri.py
    test_signal_mireot.py
    test_signal_mappings.py
    test_detector.py
tests/integration/
    test_reuse_api.py
```

Files modified (not created):
- `pyproject.toml` — add `bioregistry>=0.11`
- `ontoexplorer/modules/search/indexer.py` — add `_populate_reuse_cache` next to `_populate_owl_profile_cache` (around L485), add invalidate (around L799)
- `ontoexplorer/modules/jobs/tasks.py` — add `refresh_reuse` task
- `ontoexplorer/main.py` — `app.include_router(reuse_router)` after owl_profile router
- `ontoexplorer/api/ontologies.py` — add `?reuses=<prefix>` filter alongside the existing `?profile=` filter
- `frontend/src/lib/api.ts` — add `getReuse(versionId)`, `getReuseFleet()` + types
- `frontend/src/pages/Ontologies.tsx` — register `reuse` tab in `TAB_VALUES` and dispatcher
- `frontend/src/pages/OntologyPage.tsx` — embed `<ReuseSection />` near OwlProfileSection

---

## Sequencing and dependencies

Tasks 1-7 build the analysis engine bottom-up (cache helper → bioregistry → four signals → aggregator). Each is independently testable. Task 8 wires the engine into the indexer; Task 9 adds the Celery refresh task (independent of Task 8 — the spec rebuild path doesn't need the indexer hook). Tasks 10-12 are the API + frontend. Task 13 is the BioPortal-scale rerun, which depends only on Task 2 (`bioregistry.py`).

The subagent executing each task should:
1. Run `pytest tests/unit/reuse/<file>.py -v` and confirm green after writing each step's code.
2. Commit at the end of each task with the message shown.
3. Never skip the "run failing test first" step — that proves the test actually exercises the new code path.

---

## Task 1: Module scaffold + Redis cache-key helper

**Files:**
- Create: `ontoexplorer/modules/reuse/__init__.py`
- Create: `ontoexplorer/modules/reuse/cache.py`
- Create: `tests/unit/reuse/__init__.py`
- Create: `tests/unit/reuse/test_cache.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/reuse/test_cache.py`:
```python
from ontoexplorer.modules.reuse.cache import reuse_cache_key


def test_reuse_cache_key_format():
    assert reuse_cache_key("abc-123") == "reuse:abc-123"


def test_reuse_cache_key_handles_uuid():
    vid = "550e8400-e29b-41d4-a716-446655440000"
    assert reuse_cache_key(vid) == f"reuse:{vid}"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/reuse/test_cache.py -v
```
Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.reuse'`.

- [ ] **Step 3: Create empty package files**

`ontoexplorer/modules/reuse/__init__.py`:
```python
"""Ontology reuse analysis: signals, bioregistry-normalized prefixes, caching."""
```

`tests/unit/reuse/__init__.py`:
```python
```
(empty)

`ontoexplorer/modules/reuse/cache.py`:
```python
"""Redis cache-key helper for reuse analysis (mirrors owl_profile.cache)."""


def reuse_cache_key(version_id: str) -> str:
    return f"reuse:{version_id}"
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/reuse/test_cache.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/reuse/ tests/unit/reuse/
git commit -m "feat(reuse): scaffold module + redis cache key helper"
```

---

## Task 2: Bioregistry wrapper

**Files:**
- Modify: `pyproject.toml` (add `bioregistry>=0.11` to `dependencies`)
- Create: `ontoexplorer/modules/reuse/bioregistry.py`
- Create: `tests/unit/reuse/test_bioregistry.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/reuse/test_bioregistry.py`:
```python
from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix, prefix_to_canonical_iri


def test_obo_purl_iri_resolves_to_prefix():
    # The OBO Foundry canonical pattern: bioregistry resolves these
    prefix, resolved = iri_to_prefix("http://purl.obolibrary.org/obo/RO_0002211")
    assert prefix == "ro"
    assert resolved is True


def test_iao_term_resolves():
    prefix, resolved = iri_to_prefix("http://purl.obolibrary.org/obo/IAO_0000412")
    assert prefix == "iao"
    assert resolved is True


def test_bfo_term_resolves():
    prefix, resolved = iri_to_prefix("http://purl.obolibrary.org/obo/BFO_0000001")
    assert prefix == "bfo"
    assert resolved is True


def test_unknown_iri_returns_unresolved():
    prefix, resolved = iri_to_prefix("http://example.com/made-up/X_001")
    assert resolved is False
    # prefix is either None or the raw namespace — caller decides; we just guarantee the flag


def test_prefix_back_to_canonical_iri():
    # round-trip: prefix produces an IRI we can resolve back
    canonical = prefix_to_canonical_iri("ro")
    assert canonical is not None
    assert "obolibrary.org" in canonical or "ro" in canonical.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/reuse/test_bioregistry.py -v
```
Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.reuse.bioregistry'` (or `bioregistry` itself if not installed).

- [ ] **Step 3: Add the dependency**

Edit `pyproject.toml` — under the `[project]` `dependencies` array, add the line `"bioregistry>=0.11",` alphabetically. Then:
```
pip install -e .
```
or whatever the project's standard install command is (check `Dockerfile` / `Makefile` if unsure).

- [ ] **Step 4: Implement the wrapper**

`ontoexplorer/modules/reuse/bioregistry.py`:
```python
"""Thin wrapper over the `bioregistry` PyPI package.

`bioregistry` ships an offline-curated map of biomedical-ontology prefixes
to canonical IRIs. We normalize entity IRIs to a stable prefix so reuse
counts collapse variant forms (e.g. purl.obolibrary.org/obo/RO_ and
purl.org/obo/RO_ both resolve to `ro`).

Unresolved IRIs are flagged so the UI can surface them; callers should fall
back to the raw namespace as a stand-in key.
"""
from __future__ import annotations

import bioregistry


def iri_to_prefix(iri: str) -> tuple[str | None, bool]:
    """Resolve an IRI to a canonical bioregistry prefix.

    Returns (prefix, resolved). When `resolved` is False, `prefix` is either
    `None` (no match at all) or the raw namespace (best-effort fallback).
    """
    parsed = bioregistry.parse_iri(iri)
    if parsed is None:
        return _raw_namespace(iri), False
    prefix, _identifier = parsed
    if prefix is None:
        return _raw_namespace(iri), False
    return prefix, True


def prefix_to_canonical_iri(prefix: str) -> str | None:
    """Return the canonical URI-prefix for a bioregistry prefix, or None."""
    return bioregistry.get_uri_prefix(prefix)


def _raw_namespace(iri: str) -> str | None:
    """Best-effort namespace stripping when bioregistry doesn't recognize the IRI."""
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[0] + sep
    return None
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/unit/reuse/test_bioregistry.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml ontoexplorer/modules/reuse/bioregistry.py tests/unit/reuse/test_bioregistry.py
git commit -m "feat(reuse): bioregistry wrapper for IRI→prefix normalization"
```

---

## Task 3: imports signal

**Files:**
- Create: `ontoexplorer/modules/reuse/signals/__init__.py`
- Create: `ontoexplorer/modules/reuse/signals/imports.py`
- Create: `tests/unit/reuse/test_signal_imports.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/reuse/test_signal_imports.py`:
```python
from dataclasses import asdict

from ontoexplorer.modules.reuse.signals.imports import ImportEdge, build_closure


def test_single_import_resolves_prefix():
    # A version V imports BFO directly
    rows = [
        {"version_id": "v1", "import_iri": "http://purl.obolibrary.org/obo/bfo.owl", "depth": 1},
    ]
    edges = build_closure(rows)
    assert len(edges) == 1
    assert edges[0].target_iri == "http://purl.obolibrary.org/obo/bfo.owl"
    assert edges[0].target_prefix == "bfo"
    assert edges[0].depth == 1
    assert edges[0].resolved is True


def test_unresolved_import_flagged():
    rows = [{"version_id": "v1", "import_iri": "http://example.com/x.owl", "depth": 1}]
    edges = build_closure(rows)
    assert len(edges) == 1
    assert edges[0].resolved is False


def test_multiple_imports_at_same_depth():
    rows = [
        {"version_id": "v1", "import_iri": "http://purl.obolibrary.org/obo/bfo.owl", "depth": 1},
        {"version_id": "v1", "import_iri": "http://purl.obolibrary.org/obo/ro.owl", "depth": 1},
    ]
    edges = build_closure(rows)
    prefixes = {e.target_prefix for e in edges}
    assert prefixes == {"bfo", "ro"}


def test_import_edge_serializes_to_dict():
    rows = [{"version_id": "v1", "import_iri": "http://purl.obolibrary.org/obo/bfo.owl", "depth": 1}]
    edges = build_closure(rows)
    d = asdict(edges[0])
    assert "target_prefix" in d and "target_iri" in d
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/reuse/test_signal_imports.py -v
```
Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.reuse.signals'`.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/reuse/signals/__init__.py`:
```python
"""Reuse-signal modules — each computes one dimension of reuse."""
```

`ontoexplorer/modules/reuse/signals/imports.py`:
```python
"""owl:imports closure signal.

Inputs are pre-fetched rows from the OntologyImport table (depth pre-computed
during ingestion by the recursive resolver). We normalize the target IRI via
bioregistry into a stable prefix and emit one ImportEdge per row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


@dataclass(frozen=True)
class ImportEdge:
    target_iri: str
    target_prefix: str | None
    depth: int
    resolved: bool


def build_closure(rows: Iterable[dict]) -> list[ImportEdge]:
    """Map OntologyImport rows to ImportEdges with bioregistry-resolved prefixes.

    `rows` is an iterable of dicts with keys: `import_iri`, `depth`.
    (The caller — typically `detector.detect_reuse` — fetches these from the
    `OntologyImport` SQLAlchemy model.)
    """
    edges: list[ImportEdge] = []
    for row in rows:
        prefix, resolved = iri_to_prefix(row["import_iri"])
        edges.append(ImportEdge(
            target_iri=row["import_iri"],
            target_prefix=prefix,
            depth=int(row.get("depth", 1)),
            resolved=resolved,
        ))
    return edges
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/reuse/test_signal_imports.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/reuse/signals/ tests/unit/reuse/test_signal_imports.py
git commit -m "feat(reuse): imports signal — closure with bioregistry-resolved prefixes"
```

---

## Task 4: term_iri signal

**Files:**
- Create: `ontoexplorer/modules/reuse/signals/term_iri.py`
- Create: `tests/unit/reuse/test_signal_term_iri.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/reuse/test_signal_term_iri.py`:
```python
from ontoexplorer.modules.reuse.signals.term_iri import (
    TermIRIReuseEntry,
    classify_terms,
)


def test_native_terms_excluded_from_reuse_counts():
    entities = [
        ("http://example.org/myonto#ClassA", "class"),
        ("http://example.org/myonto#ClassB", "class"),
    ]
    out = classify_terms(entities, host_prefix=None, host_namespaces=["http://example.org/myonto#"])
    # All entities are native — no reused-from buckets
    assert out == {}


def test_foreign_terms_bucketed_by_prefix():
    entities = [
        ("http://purl.obolibrary.org/obo/BFO_0000001", "class"),
        ("http://purl.obolibrary.org/obo/BFO_0000002", "class"),
        ("http://purl.obolibrary.org/obo/RO_0002211", "object_property"),
    ]
    out = classify_terms(entities, host_prefix="myonto",
                         host_namespaces=["http://example.org/myonto#"])
    assert "bfo" in out
    assert out["bfo"].class_count == 2
    assert out["bfo"].property_count == 0
    assert "ro" in out
    assert out["ro"].property_count == 1
    assert out["ro"].class_count == 0


def test_samples_capped_at_five():
    entities = [
        (f"http://purl.obolibrary.org/obo/BFO_{i:07d}", "class") for i in range(20)
    ]
    out = classify_terms(entities, host_prefix="myonto",
                         host_namespaces=["http://example.org/myonto#"])
    assert len(out["bfo"].sample_iris) == 5


def test_term_iri_reuse_entry_is_serializable():
    from dataclasses import asdict
    entry = TermIRIReuseEntry(class_count=1, property_count=0, sample_iris=["foo"])
    assert asdict(entry)["class_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/reuse/test_signal_term_iri.py -v
```
Expected: `ImportError: cannot import name 'classify_terms'`.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/reuse/signals/term_iri.py`:
```python
"""Term-IRI reuse signal.

For each indexed entity in a version, classify the IRI's namespace as
native (matches the host ontology's base IRI) or reused-from-X (resolves
to a different bioregistry prefix). Counts are aggregated per source
prefix; sample IRIs are capped to keep the cache payload small.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


_SAMPLE_CAP = 5


@dataclass
class TermIRIReuseEntry:
    class_count: int = 0
    property_count: int = 0
    sample_iris: list[str] = field(default_factory=list)
    resolved: bool = True


def classify_terms(
    entities: Iterable[tuple[str, str]],
    host_prefix: str | None,
    host_namespaces: list[str],
) -> dict[str, TermIRIReuseEntry]:
    """Bucket entity IRIs by reused-from prefix.

    Args:
        entities: iterable of (iri, entity_type) where entity_type is one of
            "class", "object_property", "data_property", "annotation_property",
            "individual".
        host_prefix: bioregistry prefix of the host ontology (for skip-self).
        host_namespaces: raw namespaces declared as the host's own (skip-native).

    Returns:
        dict keyed by source bioregistry prefix → TermIRIReuseEntry. Native
        terms are dropped (we report reuse, not totals).
    """
    out: dict[str, TermIRIReuseEntry] = {}
    for iri, etype in entities:
        if any(iri.startswith(ns) for ns in host_namespaces):
            continue  # native
        prefix, resolved = iri_to_prefix(iri)
        if prefix is None:
            continue
        if prefix == host_prefix:
            continue  # also native (host's own prefix used in mixed-namespace form)
        entry = out.setdefault(prefix, TermIRIReuseEntry(resolved=resolved))
        if etype == "class":
            entry.class_count += 1
        elif etype in ("object_property", "data_property", "annotation_property"):
            entry.property_count += 1
        if len(entry.sample_iris) < _SAMPLE_CAP:
            entry.sample_iris.append(iri)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/reuse/test_signal_term_iri.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/reuse/signals/term_iri.py tests/unit/reuse/test_signal_term_iri.py
git commit -m "feat(reuse): term-IRI reuse signal — bucket per source prefix"
```

---

## Task 5: mireot signal

**Files:**
- Create: `ontoexplorer/modules/reuse/signals/mireot.py`
- Create: `tests/unit/reuse/test_signal_mireot.py`

The detection rule (from spec): a class C in version V is MIREOT-imported when ALL hold:
1. `iri_to_prefix(C)` returns a `target_prefix` that is foreign (≠ host_prefix).
2. `target_prefix` is NOT in V's import closure.
3. V's axiom signature for C is minimal: at most one `rdfs:subClassOf`/`rdfs:subPropertyOf`, plus only allowed annotation predicates.
4. C has no equivalentClass / disjointWith / domain / range / Restriction blank node / property characteristic axioms.

Implementation: one SPARQL query enumerates foreign-prefix terms with minimal signatures. The list of allowed annotation predicates is hard-coded.

- [ ] **Step 1: Write the failing test**

`tests/unit/reuse/test_signal_mireot.py`:
```python
import pyoxigraph

from ontoexplorer.modules.reuse.signals.mireot import MireotTerm, detect_mireot


GRAPH = "urn:test:graph"
HOST_NS = "http://example.org/host#"


def _make_store(turtle: str) -> pyoxigraph.Store:
    store = pyoxigraph.Store()
    store.load(turtle.encode(), "text/turtle",
               to_graph=pyoxigraph.NamedNode(GRAPH))
    return store


def test_mireot_term_detected_when_minimally_axiomatized():
    # IAO_0000115 (definition) brought in as MIREOT: a label + one parent, no imports
    store = _make_store(f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        <{HOST_NS}LocalClass> a owl:Class ; rdfs:label "Local" .
        <http://purl.obolibrary.org/obo/IAO_0000115> a owl:AnnotationProperty ;
            rdfs:label "definition" ;
            rdfs:subPropertyOf <http://www.w3.org/2000/01/rdf-schema#comment> .
    """)
    found = detect_mireot(
        store, graph_iri=GRAPH, host_prefix="host",
        host_namespaces=[HOST_NS],
        import_prefix_set=set(),  # no imports — IAO must be MIREOT
    )
    assert len(found) == 1
    assert isinstance(found[0], MireotTerm)
    assert found[0].source_prefix == "iao"
    assert found[0].iri == "http://purl.obolibrary.org/obo/IAO_0000115"


def test_no_mireot_when_source_is_imported():
    store = _make_store(f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        <http://purl.obolibrary.org/obo/IAO_0000115> a owl:AnnotationProperty ;
            rdfs:label "definition" .
    """)
    found = detect_mireot(
        store, graph_iri=GRAPH, host_prefix="host",
        host_namespaces=[HOST_NS],
        import_prefix_set={"iao"},  # IAO imported — not MIREOT
    )
    assert found == []


def test_no_mireot_when_term_has_rich_axiomatization():
    # IAO term with an equivalentClass axiom → NOT minimal → not MIREOT
    store = _make_store(f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        <http://purl.obolibrary.org/obo/IAO_0000115> a owl:Class ;
            owl:equivalentClass <{HOST_NS}OtherClass> .
    """)
    found = detect_mireot(
        store, graph_iri=GRAPH, host_prefix="host",
        host_namespaces=[HOST_NS],
        import_prefix_set=set(),
    )
    assert found == []


def test_native_terms_never_flagged():
    store = _make_store(f"""
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix owl:  <http://www.w3.org/2002/07/owl#> .
        <{HOST_NS}LocalClass> a owl:Class ; rdfs:label "Local" .
    """)
    found = detect_mireot(
        store, graph_iri=GRAPH, host_prefix="host",
        host_namespaces=[HOST_NS],
        import_prefix_set=set(),
    )
    assert found == []
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/reuse/test_signal_mireot.py -v
```
Expected: `ImportError: cannot import name 'detect_mireot'`.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/reuse/signals/mireot.py`:
```python
"""MIREOT-pattern detection.

A term is MIREOT'd into the host ontology when:
  1. its IRI namespace is foreign (not the host's own),
  2. the source ontology is NOT in the host's owl:imports closure, and
  3. the term carries only minimal axiomatization in the host
     (label + at most one subClassOf/subPropertyOf, plus a known set of
     metadata annotation predicates, and no equivalentClass / disjointWith /
     domain / range / restriction / property-characteristic axioms).
"""
from __future__ import annotations

from dataclasses import dataclass

import pyoxigraph

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


# Allowed predicates that DON'T disqualify a term from being minimal.
_ALLOWED_ANNOTATION_PREDS = {
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://www.w3.org/2000/01/rdf-schema#isDefinedBy",
    "http://www.w3.org/2000/01/rdf-schema#seeAlso",
    "http://purl.obolibrary.org/obo/IAO_0000412",  # imported from
    "http://purl.obolibrary.org/obo/IAO_0000115",  # definition (allowed as predicate)
    "http://purl.obolibrary.org/obo/IAO_0000118",  # alternative term
    "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasDbXref",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
}

# Predicates whose presence disqualifies a term from being minimal.
_DISQUALIFYING_PREDS = (
    "http://www.w3.org/2002/07/owl#equivalentClass",
    "http://www.w3.org/2002/07/owl#disjointWith",
    "http://www.w3.org/2000/01/rdf-schema#domain",
    "http://www.w3.org/2000/01/rdf-schema#range",
    "http://www.w3.org/2002/07/owl#inverseOf",
    "http://www.w3.org/2002/07/owl#equivalentProperty",
)


@dataclass(frozen=True)
class MireotTerm:
    iri: str
    source_prefix: str
    has_imported_from: bool  # whether IAO:0000412 is present (strong MIREOT signal)


def detect_mireot(
    store: pyoxigraph.Store,
    graph_iri: str,
    host_prefix: str | None,
    host_namespaces: list[str],
    import_prefix_set: set[str],
) -> list[MireotTerm]:
    """Find foreign-namespace terms with minimal axiomatization and no covering import.

    `host_namespaces` is the authoritative native-skip — bioregistry may not
    recognize a custom host base IRI, so we can't rely on host_prefix matching
    alone. Subjects whose IRI starts with any of these namespaces are native
    and skipped.
    """
    found: list[MireotTerm] = []

    # Step 1: enumerate distinct foreign subjects.
    # Use a SPARQL ASK-style enumeration constrained to the named graph.
    subjects_q = f"""
        SELECT DISTINCT ?s WHERE {{
            GRAPH <{graph_iri}> {{
                ?s ?p ?o .
                FILTER(isIRI(?s))
            }}
        }}
    """
    subject_iris = [
        sol["s"].value for sol in store.query(subjects_q)
    ]

    for s in subject_iris:
        if any(s.startswith(ns) for ns in host_namespaces):
            continue  # native — host's own namespace
        prefix, _ = iri_to_prefix(s)
        if prefix is None:
            continue
        if prefix == host_prefix:
            continue  # also native (mixed-namespace forms of the host prefix)
        if prefix in import_prefix_set:
            continue  # source IS imported → not MIREOT

        # Step 2: fetch all predicates with this subject in this graph.
        preds_q = f"""
            SELECT ?p (COUNT(*) AS ?n) WHERE {{
                GRAPH <{graph_iri}> {{
                    <{s}> ?p ?o .
                }}
            }} GROUP BY ?p
        """
        pred_counts: dict[str, int] = {}
        for sol in store.query(preds_q):
            pred_counts[sol["p"].value] = int(sol["n"].value)

        # Step 3: check minimal-axiomatization rules.
        if any(p in pred_counts for p in _DISQUALIFYING_PREDS):
            continue
        sub_class_count = pred_counts.get(
            "http://www.w3.org/2000/01/rdf-schema#subClassOf", 0
        )
        sub_prop_count = pred_counts.get(
            "http://www.w3.org/2000/01/rdf-schema#subPropertyOf", 0
        )
        if sub_class_count > 1 or sub_prop_count > 1:
            continue
        # Any unknown predicate (not in allowed set, not the structural ones we just counted)?
        for p in pred_counts:
            if p in _ALLOWED_ANNOTATION_PREDS:
                continue
            if p == "http://www.w3.org/2000/01/rdf-schema#subClassOf":
                continue
            if p == "http://www.w3.org/2000/01/rdf-schema#subPropertyOf":
                continue
            # Unknown predicate → not minimal; bail.
            break
        else:
            has_imp = "http://purl.obolibrary.org/obo/IAO_0000412" in pred_counts
            found.append(MireotTerm(iri=s, source_prefix=prefix, has_imported_from=has_imp))

    return found
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/reuse/test_signal_mireot.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/reuse/signals/mireot.py tests/unit/reuse/test_signal_mireot.py
git commit -m "feat(reuse): MIREOT-pattern detection via minimal-axiomatization SPARQL"
```

---

## Task 6: mappings signal

**Files:**
- Create: `ontoexplorer/modules/reuse/signals/mappings.py`
- Create: `tests/unit/reuse/test_signal_mappings.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/reuse/test_signal_mappings.py`:
```python
import pyoxigraph

from ontoexplorer.modules.reuse.signals.mappings import MappingEntry, extract_mappings


GRAPH = "urn:test:graph"


def _make_store(turtle: str) -> pyoxigraph.Store:
    store = pyoxigraph.Store()
    store.load(turtle.encode(), "text/turtle",
               to_graph=pyoxigraph.NamedNode(GRAPH))
    return store


def test_skos_close_match_extracted():
    store = _make_store("""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        <http://example.org/host#A> skos:closeMatch
            <http://purl.obolibrary.org/obo/CHEBI_12345> .
    """)
    out = extract_mappings(store, graph_iri=GRAPH, host_prefix="host")
    assert "skos:closeMatch" in out
    assert len(out["skos:closeMatch"]) == 1
    entry = out["skos:closeMatch"][0]
    assert entry.target_prefix == "chebi"


def test_obo_xref_extracted():
    store = _make_store("""
        @prefix oboInOwl: <http://www.geneontology.org/formats/oboInOwl#> .
        <http://example.org/host#A> oboInOwl:hasDbXref
            <http://purl.obolibrary.org/obo/MESH_D123> .
    """)
    out = extract_mappings(store, graph_iri=GRAPH, host_prefix="host")
    assert "oboInOwl:hasDbXref" in out


def test_no_mappings_returns_empty_dict():
    store = _make_store("""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://example.org/host#A> a owl:Class .
    """)
    out = extract_mappings(store, graph_iri=GRAPH, host_prefix="host")
    assert out == {}


def test_samples_capped_at_five_per_predicate_prefix():
    triples = "\n".join(
        f"<http://example.org/host#A{i}> skos:closeMatch "
        f"<http://purl.obolibrary.org/obo/CHEBI_{i:05d}> ."
        for i in range(10)
    )
    store = _make_store(f"""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        {triples}
    """)
    out = extract_mappings(store, graph_iri=GRAPH, host_prefix="host")
    # 10 mappings, but samples capped at 5
    entries = out["skos:closeMatch"]
    chebi_entries = [e for e in entries if e.target_prefix == "chebi"]
    assert len(chebi_entries) == 1
    assert chebi_entries[0].count == 10
    assert len(chebi_entries[0].sample_pairs) == 5
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/reuse/test_signal_mappings.py -v
```
Expected: `ImportError: cannot import name 'extract_mappings'`.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/reuse/signals/mappings.py`:
```python
"""Mapping-predicate extraction.

Enumerates cross-ontology mapping assertions (skos:*Match, oboInOwl:hasDbXref,
owl:sameAs) and groups them by (predicate, target_prefix). Counts every
mapping; caps sample (subject, object) pairs to keep payloads small.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pyoxigraph

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


_SAMPLE_CAP = 5

# Mapping predicates we extract, with CURIE-style keys for the response.
_MAPPING_PREDICATES = {
    "http://www.w3.org/2004/02/skos/core#closeMatch":   "skos:closeMatch",
    "http://www.w3.org/2004/02/skos/core#exactMatch":   "skos:exactMatch",
    "http://www.w3.org/2004/02/skos/core#relatedMatch": "skos:relatedMatch",
    "http://www.w3.org/2004/02/skos/core#broadMatch":   "skos:broadMatch",
    "http://www.w3.org/2004/02/skos/core#narrowMatch":  "skos:narrowMatch",
    "http://www.geneontology.org/formats/oboInOwl#hasDbXref": "oboInOwl:hasDbXref",
    "http://www.w3.org/2002/07/owl#sameAs":             "owl:sameAs",
}


@dataclass
class MappingEntry:
    target_prefix: str | None
    count: int = 0
    sample_pairs: list[tuple[str, str]] = field(default_factory=list)


def extract_mappings(
    store: pyoxigraph.Store,
    graph_iri: str,
    host_prefix: str | None,
) -> dict[str, list[MappingEntry]]:
    """Return mapping assertions per predicate, grouped by target prefix."""
    out: dict[str, list[MappingEntry]] = {}

    values_clause = " ".join(f"<{iri}>" for iri in _MAPPING_PREDICATES)

    q = f"""
        SELECT ?s ?p ?o WHERE {{
            VALUES ?p {{ {values_clause} }}
            GRAPH <{graph_iri}> {{
                ?s ?p ?o .
                FILTER(isIRI(?s) && isIRI(?o))
            }}
        }}
    """
    # buckets[(curie, target_prefix)] -> MappingEntry
    buckets: dict[tuple[str, str | None], MappingEntry] = {}
    for sol in store.query(q):
        pred_iri = sol["p"].value
        curie = _MAPPING_PREDICATES[pred_iri]
        target_iri = sol["o"].value
        target_prefix, _ = iri_to_prefix(target_iri)
        key = (curie, target_prefix)
        entry = buckets.setdefault(key, MappingEntry(target_prefix=target_prefix))
        entry.count += 1
        if len(entry.sample_pairs) < _SAMPLE_CAP:
            entry.sample_pairs.append((sol["s"].value, target_iri))

    for (curie, _tp), entry in buckets.items():
        out.setdefault(curie, []).append(entry)

    return out
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/reuse/test_signal_mappings.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/reuse/signals/mappings.py tests/unit/reuse/test_signal_mappings.py
git commit -m "feat(reuse): mappings signal — SKOS/OBO xref/sameAs extraction"
```

---

## Task 7: detector aggregator

**Files:**
- Create: `ontoexplorer/modules/reuse/detector.py`
- Modify: `ontoexplorer/modules/reuse/__init__.py` (re-export public types)
- Create: `tests/unit/reuse/test_detector.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/reuse/test_detector.py`:
```python
import pyoxigraph

from ontoexplorer.modules.reuse.detector import ReuseReport, detect_reuse


GRAPH = "urn:test:graph"


def _make_store(turtle: str) -> pyoxigraph.Store:
    store = pyoxigraph.Store()
    store.load(turtle.encode(), "text/turtle",
               to_graph=pyoxigraph.NamedNode(GRAPH))
    return store


def test_report_has_all_four_signal_sections():
    store = _make_store(f"""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <http://example.org/host#A> a owl:Class .
        <http://purl.obolibrary.org/obo/BFO_0000001> a owl:Class ; rdfs:label "entity" .
    """)
    report = detect_reuse(
        store,
        graph_iri=GRAPH,
        version_id="v1",
        host_iri="http://example.org/host",
        host_namespaces=["http://example.org/host#"],
        db_imports=[],
        entities=[
            ("http://example.org/host#A", "class"),
            ("http://purl.obolibrary.org/obo/BFO_0000001", "class"),
        ],
    )
    assert isinstance(report, ReuseReport)
    assert hasattr(report, "imports")
    assert hasattr(report, "term_iri_reuse")
    assert hasattr(report, "mireot_terms")
    assert hasattr(report, "mappings")
    assert report.version_id == "v1"
    assert report.host_iri == "http://example.org/host"


def test_term_iri_section_populated_from_entities():
    store = _make_store("""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://purl.obolibrary.org/obo/BFO_0000001> a owl:Class .
    """)
    report = detect_reuse(
        store, graph_iri=GRAPH, version_id="v1",
        host_iri="http://example.org/host",
        host_namespaces=["http://example.org/host#"],
        db_imports=[],
        entities=[("http://purl.obolibrary.org/obo/BFO_0000001", "class")],
    )
    assert "bfo" in report.term_iri_reuse
    assert report.term_iri_reuse["bfo"].class_count == 1


def test_report_has_indexed_at_iso_timestamp():
    store = _make_store("""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        <http://example.org/host#A> a owl:Class .
    """)
    report = detect_reuse(
        store, graph_iri=GRAPH, version_id="v1",
        host_iri="http://example.org/host",
        host_namespaces=["http://example.org/host#"],
        db_imports=[], entities=[],
    )
    # ISO-8601 with TZ
    assert "T" in report.indexed_at
    assert report.indexed_at.endswith("+00:00") or report.indexed_at.endswith("Z")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit/reuse/test_detector.py -v
```
Expected: `ImportError: cannot import name 'detect_reuse'`.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/reuse/detector.py`:
```python
"""Reuse-analysis aggregator: runs all four signals and returns a ReuseReport."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pyoxigraph

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix
from ontoexplorer.modules.reuse.signals.imports import ImportEdge, build_closure
from ontoexplorer.modules.reuse.signals.mappings import MappingEntry, extract_mappings
from ontoexplorer.modules.reuse.signals.mireot import MireotTerm, detect_mireot
from ontoexplorer.modules.reuse.signals.term_iri import (
    TermIRIReuseEntry,
    classify_terms,
)


@dataclass
class ReuseReport:
    version_id: str
    host_prefix: str | None
    host_iri: str
    imports: list[ImportEdge] = field(default_factory=list)
    term_iri_reuse: dict[str, TermIRIReuseEntry] = field(default_factory=dict)
    mireot_terms: list[MireotTerm] = field(default_factory=list)
    mappings: dict[str, list[MappingEntry]] = field(default_factory=dict)
    indexed_at: str = ""


def detect_reuse(
    store: pyoxigraph.Store,
    *,
    graph_iri: str,
    version_id: str,
    host_iri: str,
    host_namespaces: list[str],
    db_imports: list[dict],
    entities: list[tuple[str, str]],
) -> ReuseReport:
    """Run all four signals and aggregate into a ReuseReport.

    Args:
        store: in-process pyoxigraph store with the version's graph loaded.
        graph_iri: named graph IRI for the version.
        version_id: UUID of the version (for the report and cache key).
        host_iri: ontology IRI (display only; not used for classification).
        host_namespaces: namespaces declared as the host's own — terms whose
            IRI starts with any of these are treated as native.
        db_imports: list of dicts with keys `import_iri`, `depth`, fetched
            from the OntologyImport table by the caller.
        entities: list of (iri, entity_type) from the existing search index;
            the indexer passes this in to avoid a second store traversal.
    """
    host_prefix, _ = iri_to_prefix(host_iri)
    imports = build_closure(db_imports)
    import_prefix_set = {e.target_prefix for e in imports if e.target_prefix}

    term_iri_reuse = classify_terms(entities, host_prefix=host_prefix,
                                    host_namespaces=host_namespaces)
    mireot_terms = detect_mireot(store, graph_iri=graph_iri,
                                 host_prefix=host_prefix,
                                 host_namespaces=host_namespaces,
                                 import_prefix_set=import_prefix_set)
    mappings = extract_mappings(store, graph_iri=graph_iri, host_prefix=host_prefix)

    return ReuseReport(
        version_id=version_id,
        host_prefix=host_prefix,
        host_iri=host_iri,
        imports=imports,
        term_iri_reuse=term_iri_reuse,
        mireot_terms=mireot_terms,
        mappings=mappings,
        indexed_at=datetime.now(timezone.utc).isoformat(),
    )
```

Edit `ontoexplorer/modules/reuse/__init__.py` to re-export the public types:
```python
"""Ontology reuse analysis: signals, bioregistry-normalized prefixes, caching."""

from ontoexplorer.modules.reuse.detector import ReuseReport, detect_reuse  # noqa: F401
from ontoexplorer.modules.reuse.signals.imports import ImportEdge  # noqa: F401
from ontoexplorer.modules.reuse.signals.mappings import MappingEntry  # noqa: F401
from ontoexplorer.modules.reuse.signals.mireot import MireotTerm  # noqa: F401
from ontoexplorer.modules.reuse.signals.term_iri import TermIRIReuseEntry  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/reuse/test_detector.py tests/unit/reuse/ -v
```
Expected: all tests pass (3 new + earlier tasks still green).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/reuse/detector.py ontoexplorer/modules/reuse/__init__.py tests/unit/reuse/test_detector.py
git commit -m "feat(reuse): aggregator returns ReuseReport from all four signals"
```

---

## Task 8: Indexer hook — `_populate_reuse_cache`

**Files:**
- Modify: `ontoexplorer/modules/search/indexer.py`

This task has no new unit tests of its own — the integration test in Task 10 exercises the hook end-to-end. We do a quick syntax-check after the edit.

- [ ] **Step 1: Add the populator function**

Open `ontoexplorer/modules/search/indexer.py`. After the existing `_populate_owl_profile_cache` function (around line 773), add:

```python
def _populate_reuse_cache(
    version_id: str,
    ontology_id: str,
    entities: dict[str, str],
    r: "redis.Redis",
) -> None:
    """Compute the reuse report for this version and cache it in Redis.

    Mirrors `_populate_owl_profile_cache` — runs at the end of indexing so
    the data is ready before any API call.
    """
    import asyncio as _asyncio
    import json as _json

    from sqlalchemy import select

    from ontoexplorer.clients.oxigraph import get_store, graph_iri as _graph_iri
    from ontoexplorer.database import make_celery_db_session
    from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
    from ontoexplorer.modules.reuse.cache import reuse_cache_key
    from ontoexplorer.modules.reuse.detector import detect_reuse

    async def _gather():
        async with make_celery_db_session()() as db:
            ver = (await db.execute(
                select(OntologyVersion).where(OntologyVersion.id == version_id)
            )).scalar_one_or_none()
            if ver is None:
                return None, [], []
            ont = (await db.execute(
                select(Ontology).where(Ontology.id == ver.ontology_id)
            )).scalar_one_or_none()
            imp_rows = (await db.execute(
                select(OntologyImport).where(OntologyImport.version_id == version_id)
            )).scalars().all()
            db_imports = [
                {"import_iri": row.import_iri, "depth": 1} for row in imp_rows
            ]
            host_iri = ont.iri if ont else ""
            host_namespaces = [host_iri + sep for sep in ("#", "/") if host_iri]
            return host_iri, host_namespaces, db_imports

    host_iri, host_namespaces, db_imports = _asyncio.run(_gather())
    if host_iri is None:
        return  # version disappeared mid-index — skip silently

    g = _graph_iri(ontology_id, version_id)
    entity_pairs = list(entities.items())
    report = detect_reuse(
        get_store(),
        graph_iri=g,
        version_id=version_id,
        host_iri=host_iri,
        host_namespaces=host_namespaces,
        db_imports=db_imports,
        entities=entity_pairs,
    )
    # Convert dataclasses to dicts via asdict — preserves the nested structure.
    from dataclasses import asdict as _asdict
    payload = _asdict(report)
    r.setex(reuse_cache_key(version_id), _SEARCH_TTL, _json.dumps(payload))
```

- [ ] **Step 2: Invoke the populator from `build_index`**

Find the existing line `_populate_owl_profile_cache(version_id, ontology_id, r)` (around line 485). Add directly below it:

```python
    _populate_reuse_cache(version_id, ontology_id, entities, r)
```

- [ ] **Step 3: Add cache invalidation**

Find `invalidate_index` (around line 785). After the line `to_delete.append(owl_profile_cache_key(version_id))`, add:

```python
    from ontoexplorer.modules.reuse.cache import reuse_cache_key
    to_delete.append(reuse_cache_key(version_id))
```

- [ ] **Step 4: Verify the module still loads**

```
python -c "from ontoexplorer.modules.search.indexer import build_index, _populate_reuse_cache, invalidate_index; print('ok')"
```
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/search/indexer.py
git commit -m "feat(reuse): indexer hook populates reuse cache at index time"
```

---

## Task 9: Celery refresh task

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`

- [ ] **Step 1: Add the task**

At the end of `ontoexplorer/modules/jobs/tasks.py`, add:

```python
@celery_app.task(name="ontoexplorer.refresh_reuse", time_limit=300)
def refresh_reuse(version_id: str, ontology_id: str) -> dict:
    """Rebuild ONLY the reuse:{version_id} Redis cache.

    Cheaper alternative to a full index_ontology when only the reuse report
    needs updating (e.g. after a detector bug fix). Does NOT touch the
    search index, OWL profile cache, or queue embeddings.
    """
    import json as _json
    from dataclasses import asdict as _asdict

    from sqlalchemy import select

    from ontoexplorer.clients.oxigraph import get_store, graph_iri
    from ontoexplorer.database import make_celery_db_session
    from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
    from ontoexplorer.modules.reuse.cache import reuse_cache_key
    from ontoexplorer.modules.reuse.detector import detect_reuse
    from ontoexplorer.modules.search.indexer import (
        _get_redis,
        _SEARCH_TTL,
        _iri_key,
        _type_key,
    )

    async def _gather():
        async with make_celery_db_session()() as db:
            ont = (await db.execute(
                select(Ontology).where(Ontology.id == ontology_id)
            )).scalar_one_or_none()
            imp_rows = (await db.execute(
                select(OntologyImport).where(OntologyImport.version_id == version_id)
            )).scalars().all()
            db_imports = [
                {"import_iri": row.import_iri, "depth": 1} for row in imp_rows
            ]
            return ont.iri if ont else "", db_imports

    host_iri, db_imports = asyncio.run(_gather())
    host_namespaces = [host_iri + sep for sep in ("#", "/")] if host_iri else []

    # Re-collect entities from the existing search index in Redis
    r = _get_redis()
    entities: list[tuple[str, str]] = []
    for etype in ("class", "object_property", "data_property",
                  "annotation_property", "individual"):
        for iri in r.smembers(_type_key(version_id, etype)):
            entities.append((iri, etype))

    g = graph_iri(ontology_id, version_id)
    report = detect_reuse(
        get_store(),
        graph_iri=g,
        version_id=version_id,
        host_iri=host_iri,
        host_namespaces=host_namespaces,
        db_imports=db_imports,
        entities=entities,
    )
    r.setex(reuse_cache_key(version_id), _SEARCH_TTL,
            _json.dumps(_asdict(report)))
    log.info("reuse_refresh_done", version_id=version_id)
    return {
        "status": "done",
        "version_id": version_id,
        "imports_count": len(report.imports),
        "mireot_terms_count": len(report.mireot_terms),
        "sources_reused": len(report.term_iri_reuse),
    }
```

- [ ] **Step 2: Verify Celery can import the task**

```
python -c "from ontoexplorer.modules.jobs.tasks import celery_app, refresh_reuse; print(refresh_reuse.name)"
```
Expected: `ontoexplorer.refresh_reuse`.

- [ ] **Step 3: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py
git commit -m "feat(reuse): celery refresh_reuse task (cache-only rebuild)"
```

---

## Task 10: API routes + ontologies filter + integration test

**Files:**
- Create: `ontoexplorer/api/reuse.py`
- Modify: `ontoexplorer/main.py` (add `app.include_router(reuse_router)` before `ontologies_router`)
- Modify: `ontoexplorer/api/ontologies.py` (add `?reuses=` filter)
- Create: `tests/integration/test_reuse_api.py`

- [ ] **Step 1: Write the failing integration test**

`tests/integration/test_reuse_api.py`:
```python
import json

import pytest
from httpx import AsyncClient

from ontoexplorer.modules.reuse.cache import reuse_cache_key
from ontoexplorer.modules.search.indexer import _get_redis


@pytest.mark.asyncio
async def test_get_reuse_404_when_not_cached(test_client: AsyncClient):
    r = await test_client.get(
        "/api/v1/ontologies/missing-onto/missing-vid/reuse"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_reuse_returns_cached_payload(test_client: AsyncClient):
    vid = "test-vid-reuse-1"
    payload = {
        "version_id": vid,
        "host_prefix": "host",
        "host_iri": "http://example.org/host",
        "imports": [
            {"target_iri": "http://purl.obolibrary.org/obo/bfo.owl",
             "target_prefix": "bfo", "depth": 1, "resolved": True}
        ],
        "term_iri_reuse": {
            "bfo": {"class_count": 3, "property_count": 0,
                    "sample_iris": ["http://purl.obolibrary.org/obo/BFO_0000001"],
                    "resolved": True}
        },
        "mireot_terms": [],
        "mappings": {},
        "indexed_at": "2026-05-20T00:00:00+00:00",
    }
    _get_redis().set(reuse_cache_key(vid), json.dumps(payload))

    r = await test_client.get(f"/api/v1/ontologies/dummy/{vid}/reuse")
    assert r.status_code == 200
    body = r.json()
    assert body["imports"][0]["target_prefix"] == "bfo"
    assert body["term_iri_reuse"]["bfo"]["class_count"] == 3


@pytest.mark.asyncio
async def test_reuse_fleet_aggregates_across_versions(test_client: AsyncClient):
    # Caller is responsible for setting up versions via fixtures; this test
    # smoke-checks the endpoint returns shape, not content.
    r = await test_client.get("/api/v1/reuse/fleet")
    assert r.status_code == 200
    body = r.json()
    assert "ontologies" in body
    assert "totals" in body
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/integration/test_reuse_api.py -v
```
Expected: 404s and import errors (the router doesn't exist yet).

- [ ] **Step 3: Implement the router**

`ontoexplorer/api/reuse.py`:
```python
"""Reuse-analysis endpoints — read-only views over the Redis reuse cache."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.reuse.cache import reuse_cache_key
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["reuse"])


@router.get(
    "/ontologies/{ontology_id}/{version_id}/reuse",
    summary="Per-version reuse report",
)
async def get_version_reuse(ontology_id: str, version_id: str):
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, reuse_cache_key(version_id))
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="Reuse report not computed — reindex pending",
        )
    return json.loads(raw)


@router.get("/reuse/fleet", summary="Fleet reuse rollup (no auth)")
async def get_fleet_reuse(db: AsyncSession = Depends(get_db)):
    """Aggregate per-ontology reuse reports across the fleet.

    Mirrors the `/owl-profile/public` fleet rollup pattern: subquery for the
    latest ready version per ontology, mget the reuse cache payloads, then
    compute summary counts.
    """
    subq = (
        select(
            OntologyVersion.ontology_id,
            func.max(OntologyVersion.created_at).label("max_created"),
        )
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                OntologyVersion.id,
                OntologyVersion.ontology_id,
                Ontology.shortname,
                Ontology.title,
            )
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
            .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        )
    ).all()

    r = _get_redis()
    keys = [reuse_cache_key(str(row.id)) for row in rows]
    payloads = await asyncio.to_thread(r.mget, keys) if keys else []

    ontologies: list[dict] = []
    totals = {
        "fleet_size": 0,
        "total_import_edges": 0,
        "total_mireot_terms": 0,
        "ontologies_with_mireot": 0,
    }
    source_prefix_uses: dict[str, int] = {}

    for row, raw in zip(rows, payloads):
        if not raw:
            continue
        data = json.loads(raw)
        totals["fleet_size"] += 1
        totals["total_import_edges"] += len(data.get("imports", []))
        mireot_count = len(data.get("mireot_terms", []))
        totals["total_mireot_terms"] += mireot_count
        if mireot_count > 0:
            totals["ontologies_with_mireot"] += 1
        for prefix in data.get("term_iri_reuse", {}):
            source_prefix_uses[prefix] = source_prefix_uses.get(prefix, 0) + 1
        ontologies.append({
            "id": row.ontology_id,
            "shortname": row.shortname,
            "title": row.title,
            "version_id": str(row.id),
            "imports_count": len(data.get("imports", [])),
            "mireot_terms_count": mireot_count,
            "term_iri_reused_count": sum(
                e["class_count"] + e["property_count"]
                for e in data.get("term_iri_reuse", {}).values()
            ),
            "mappings_count": sum(
                len(v) for v in data.get("mappings", {}).values()
            ),
            "source_prefixes": list(data.get("term_iri_reuse", {}).keys()),
        })

    top_sources = sorted(source_prefix_uses.items(), key=lambda x: -x[1])[:10]

    return {
        "ontologies": ontologies,
        "totals": totals,
        "top_reused_sources": [
            {"prefix": p, "reusers_count": n} for p, n in top_sources
        ],
    }


async def filter_ontology_ids_by_reuse(
    db: AsyncSession,
    ontology_ids: list[str],
    target_prefix: str,
) -> set[str]:
    """Subset of ontology_ids whose latest ready version reuses target_prefix."""
    if not ontology_ids:
        return set()

    subq = (
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
    version_rows = (
        await db.execute(
            select(OntologyVersion.id, OntologyVersion.ontology_id)
            .join(
                subq,
                (OntologyVersion.ontology_id == subq.c.ontology_id)
                & (OntologyVersion.created_at == subq.c.max_created),
            )
        )
    ).all()
    if not version_rows:
        return set()

    r = _get_redis()
    keys = [reuse_cache_key(str(vr.id)) for vr in version_rows]
    raws = await asyncio.to_thread(r.mget, keys)

    matching: set[str] = set()
    for vr, raw in zip(version_rows, raws):
        if not raw:
            continue
        data = json.loads(raw)
        if target_prefix in data.get("term_iri_reuse", {}):
            matching.add(vr.ontology_id)
        else:
            for edge in data.get("imports", []):
                if edge.get("target_prefix") == target_prefix:
                    matching.add(vr.ontology_id)
                    break
    return matching
```

- [ ] **Step 4: Mount the router**

In `ontoexplorer/main.py`:

After the import block, add:
```python
from ontoexplorer.api.reuse import router as reuse_router
```

After `app.include_router(owl_profile_router)`, add:
```python
    # reuse_router before ontologies_router: /{id}/{vid}/reuse static segment must
    # match before ontologies_router's parameterized sub-routes
    app.include_router(reuse_router)
```

- [ ] **Step 5: Add the `?reuses=` filter to the list endpoint**

In `ontoexplorer/api/ontologies.py`:

Add a new query parameter to `list_ontologies` (around L320, alphabetically next to `profile`):
```python
    reuses: str | None = Query(None, description="Filter: latest version reuses this prefix"),
```

Update the early-return guard (around L348) to include `reuses`:
```python
    if not q and not profile and not reuses:
        stmt = stmt.offset(offset).limit(limit)
```

After the existing `profile` filter block (around L479), add:
```python
    # Reuse filter: keep only ontologies whose latest ready version reuses target_prefix
    if reuses:
        from ontoexplorer.api.reuse import filter_ontology_ids_by_reuse
        all_ids = [r["id"] for r in rows]
        matching_ids = await filter_ontology_ids_by_reuse(db, all_ids, reuses.lower())
        rows = [r for r in rows if r["id"] in matching_ids]
```

Also extend the pagination guard at L512 so `reuses` triggers it:
```python
    elif profile or reuses:
        # Profile or reuse filter already applied above; now apply pagination
        rows = rows[offset: offset + limit]
```

- [ ] **Step 6: Run integration test**

```
pytest tests/integration/test_reuse_api.py -v
```
Expected: 3 passed.

Also run a sanity check that other ontology endpoints still pass:
```
pytest tests/integration/test_ontologies.py tests/integration/test_owl_profile_api.py -v
```
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add ontoexplorer/api/reuse.py ontoexplorer/main.py ontoexplorer/api/ontologies.py tests/integration/test_reuse_api.py
git commit -m "feat(reuse): API routes (/reuse, /reuse/fleet, ?reuses= filter)"
```

---

## Task 11: Frontend — per-ontology `ReuseSection`

**Files:**
- Modify: `frontend/src/lib/api.ts` (add types + fetchers)
- Create: `frontend/src/components/ReuseSection.tsx`
- Modify: `frontend/src/pages/OntologyPage.tsx`

- [ ] **Step 1: Add types and fetchers to `api.ts`**

Open `frontend/src/lib/api.ts`. Add near the other type exports:

```typescript
export type ImportEdge = {
  target_iri: string
  target_prefix: string | null
  depth: number
  resolved: boolean
}

export type TermIRIReuseEntry = {
  class_count: number
  property_count: number
  sample_iris: string[]
  resolved: boolean
}

export type MireotTerm = {
  iri: string
  source_prefix: string
  has_imported_from: boolean
}

export type MappingEntry = {
  target_prefix: string | null
  count: number
  sample_pairs: [string, string][]
}

export type ReuseReport = {
  version_id: string
  host_prefix: string | null
  host_iri: string
  imports: ImportEdge[]
  term_iri_reuse: Record<string, TermIRIReuseEntry>
  mireot_terms: MireotTerm[]
  mappings: Record<string, MappingEntry[]>
  indexed_at: string
}

export type ReuseFleetEntry = {
  id: string
  shortname: string
  title: string
  version_id: string
  imports_count: number
  mireot_terms_count: number
  term_iri_reused_count: number
  mappings_count: number
  source_prefixes: string[]
}

export type ReuseFleet = {
  ontologies: ReuseFleetEntry[]
  totals: {
    fleet_size: number
    total_import_edges: number
    total_mireot_terms: number
    ontologies_with_mireot: number
  }
  top_reused_sources: { prefix: string; reusers_count: number }[]
}
```

Then add the fetcher methods to the existing `api` object:

```typescript
  async getReuse(ontologyId: string, versionId: string): Promise<ReuseReport> {
    const r = await fetch(`${BASE_URL}/api/v1/ontologies/${ontologyId}/${versionId}/reuse`)
    if (!r.ok) throw new Error(`reuse ${r.status}`)
    return r.json()
  },
  async getReuseFleet(): Promise<ReuseFleet> {
    const r = await fetch(`${BASE_URL}/api/v1/reuse/fleet`)
    if (!r.ok) throw new Error(`reuse fleet ${r.status}`)
    return r.json()
  },
```

(Use the existing project conventions for `BASE_URL`, error-handling, etc. — copy the pattern of the existing `getOwlProfile` method in the same file.)

- [ ] **Step 2: Create the ReuseSection component**

`frontend/src/components/ReuseSection.tsx`:
```typescript
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ReuseReport } from '../lib/api'


function Card({
  title,
  count,
  testId,
  children,
}: {
  title: string
  count: number
  testId: string
  children: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div
      data-testid={testId}
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '0.75rem',
      }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--text)',
          fontWeight: 600,
          fontSize: 'var(--font-size-sm)',
          cursor: 'pointer',
          padding: 0,
          width: '100%',
          display: 'flex',
          justifyContent: 'space-between',
        }}
      >
        <span>{title}</span>
        <span style={{ color: 'var(--text-dim)' }}>
          {count.toLocaleString()} {expanded ? '▲' : '▼'}
        </span>
      </button>
      {expanded && <div style={{ marginTop: 8 }}>{children}</div>}
    </div>
  )
}


export function ReuseSection({
  ontologyId,
  versionId,
}: {
  ontologyId: string
  versionId: string
}) {
  const { data, isLoading, error } = useQuery<ReuseReport>({
    queryKey: ['reuse', ontologyId, versionId],
    queryFn: () => api.getReuse(ontologyId, versionId),
    retry: false,
  })

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading reuse…</div>
  if (error) return <div style={{ color: 'var(--text-dim)' }}>No reuse report yet (reindex pending)</div>
  if (!data) return null

  const termIRIPairs = Object.entries(data.term_iri_reuse).sort(
    (a, b) => (b[1].class_count + b[1].property_count) - (a[1].class_count + a[1].property_count)
  )

  return (
    <div style={{ display: 'grid', gap: '0.5rem' }}>
      <Card title="owl:imports" count={data.imports.length} testId="reuse-card-imports">
        <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
          {data.imports.map((edge, i) => (
            <li key={i}>
              <code style={{ color: 'var(--accent-blue)' }}>{edge.target_prefix ?? '(unresolved)'}</code>
              {' — '}
              <span style={{ color: 'var(--text-dim)', wordBreak: 'break-all' }}>
                {edge.target_iri}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card
        title="Term-IRI reuse"
        count={termIRIPairs.reduce((acc, [, v]) => acc + v.class_count + v.property_count, 0)}
        testId="reuse-card-term-iri"
      >
        <table style={{ width: '100%', fontSize: 11 }}>
          <thead>
            <tr style={{ color: 'var(--text-dim)' }}>
              <th style={{ textAlign: 'left' }}>Source</th>
              <th style={{ textAlign: 'right' }}>Classes</th>
              <th style={{ textAlign: 'right' }}>Properties</th>
            </tr>
          </thead>
          <tbody>
            {termIRIPairs.map(([prefix, entry]) => (
              <tr key={prefix}>
                <td>
                  <code style={{ color: 'var(--accent-blue)' }}>{prefix}</code>
                </td>
                <td style={{ textAlign: 'right' }}>{entry.class_count}</td>
                <td style={{ textAlign: 'right' }}>{entry.property_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="MIREOT-style terms"
        count={data.mireot_terms.length}
        testId="reuse-card-mireot"
      >
        {data.mireot_terms.length === 0 ? (
          <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>
            No MIREOT-pattern terms detected.
          </div>
        ) : (
          <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
            {data.mireot_terms.slice(0, 20).map((term, i) => (
              <li key={i}>
                <code style={{ color: 'var(--accent-blue)' }}>{term.source_prefix}</code>
                {' '}
                <span style={{ color: 'var(--text-dim)', wordBreak: 'break-all' }}>
                  {term.iri}
                </span>
                {term.has_imported_from && (
                  <span style={{ color: '#3fb950', marginLeft: 4 }}>★</span>
                )}
              </li>
            ))}
            {data.mireot_terms.length > 20 && (
              <li style={{ color: 'var(--text-dim)' }}>
                … {data.mireot_terms.length - 20} more
              </li>
            )}
          </ul>
        )}
      </Card>

      <Card
        title="Cross-ontology mappings"
        count={Object.values(data.mappings).reduce(
          (acc, entries) => acc + entries.reduce((a, e) => a + e.count, 0), 0,
        )}
        testId="reuse-card-mappings"
      >
        {Object.entries(data.mappings).map(([predicate, entries]) => (
          <div key={predicate} style={{ marginBottom: 4 }}>
            <strong style={{ fontSize: 11 }}>{predicate}</strong>
            <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
              {entries.map((e, i) => (
                <li key={i}>
                  <code style={{ color: 'var(--accent-blue)' }}>
                    {e.target_prefix ?? '(unresolved)'}
                  </code>
                  : {e.count}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Card>
    </div>
  )
}
```

- [ ] **Step 3: Embed in OntologyPage**

Open `frontend/src/pages/OntologyPage.tsx`. Add the import near the other component imports:
```typescript
import { ReuseSection } from '../components/ReuseSection'
```

Find the spot where `<OwlProfileSection ontologyId={...} versionId={...} />` is rendered. Add directly below it:
```typescript
<section data-testid="reuse-section" style={{ marginTop: '1rem' }}>
  <h3 style={{ fontSize: 'var(--font-size-sm)', marginBottom: 8 }}>Reuse</h3>
  <ReuseSection ontologyId={ontologyId} versionId={versionId} />
</section>
```

- [ ] **Step 4: Build and smoke-test**

```
cd frontend && bun run build
```
Expected: build succeeds with no TypeScript errors.

(Manual visual check happens in Task 13's end-to-end verification.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/components/ReuseSection.tsx frontend/src/pages/OntologyPage.tsx
git commit -m "feat(reuse): per-ontology ReuseSection (four cards)"
```

---

## Task 12: Frontend — fleet `Reuse` page + tab wiring

**Files:**
- Create: `frontend/src/pages/Reuse.tsx`
- Modify: `frontend/src/pages/Ontologies.tsx`

- [ ] **Step 1: Create the Reuse page**

`frontend/src/pages/Reuse.tsx`:
```typescript
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, ReuseFleet, ReuseFleetEntry } from '../lib/api'


type SortKey = 'name' | 'imports' | 'mireot' | 'reused' | 'mappings'


function sortValue(e: ReuseFleetEntry, key: SortKey): string | number {
  switch (key) {
    case 'name':    return (e.shortname || e.id).toLowerCase()
    case 'imports': return e.imports_count
    case 'mireot':  return e.mireot_terms_count
    case 'reused':  return e.term_iri_reused_count
    case 'mappings':return e.mappings_count
  }
}


function Th({
  children, onClick, active, dir, testId,
}: {
  children: React.ReactNode
  onClick: () => void
  active: boolean
  dir: 'asc' | 'desc'
  testId?: string
}) {
  return (
    <th style={{ padding: '4px 8px', textAlign: 'left' }}>
      <button
        data-testid={testId}
        onClick={onClick}
        style={{
          background: 'none', border: 'none',
          color: active ? 'var(--text)' : 'var(--text-dim)',
          fontSize: 10, textTransform: 'uppercase', fontWeight: 500,
          cursor: 'pointer', padding: 0,
        }}
      >
        {children}{active ? (dir === 'asc' ? ' ▲' : ' ▼') : ''}
      </button>
    </th>
  )
}


function SummaryCard({ label, value, testId }: { label: string; value: number; testId: string }) {
  return (
    <div data-testid={testId} style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '0.75rem',
    }}>
      <p style={{ fontSize: 10, color: 'var(--text-dim)', margin: 0,
                  textTransform: 'uppercase' }}>{label}</p>
      <p style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)',
                  margin: '4px 0 0' }}>
        {value.toLocaleString()}
      </p>
    </div>
  )
}


export function Reuse() {
  const { data, isLoading, error } = useQuery<ReuseFleet>({
    queryKey: ['reuse-fleet'],
    queryFn: () => api.getReuseFleet(),
  })
  const [sortKey, setSortKey] = useState<SortKey>('reused')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  function clickHeader(k: SortKey) {
    if (k === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir('desc') }
  }

  const sorted = useMemo(() => {
    if (!data) return []
    const arr = [...data.ontologies]
    arr.sort((a, b) => {
      const va = sortValue(a, sortKey)
      const vb = sortValue(b, sortKey)
      if (va < vb) return sortDir === 'asc' ? -1 : 1
      if (va > vb) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return arr
  }, [data, sortKey, sortDir])

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div>Failed to load fleet reuse data.</div>

  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <div style={{ display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                    gap: '0.5rem' }}>
        <SummaryCard label="Ontologies" value={data.totals.fleet_size} testId="reuse-fleet-size" />
        <SummaryCard label="Import edges" value={data.totals.total_import_edges} testId="reuse-import-edges" />
        <SummaryCard label="MIREOT terms" value={data.totals.total_mireot_terms} testId="reuse-mireot-total" />
        <SummaryCard label="With MIREOT" value={data.totals.ontologies_with_mireot} testId="reuse-mireot-onts" />
      </div>

      {data.top_reused_sources.length > 0 && (
        <div style={{ background: 'var(--bg-secondary)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius)', padding: '0.75rem' }}>
          <h4 style={{ fontSize: 'var(--font-size-sm)', margin: '0 0 8px' }}>
            Top reused sources
          </h4>
          <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
            {data.top_reused_sources.map(s => (
              <li key={s.prefix}>
                <Link to={`/ontologies?reuses=${s.prefix}`}
                      style={{ color: 'var(--accent-blue)' }}>
                  <code>{s.prefix}</code>
                </Link>
                {' — '}
                <span style={{ color: 'var(--text-dim)' }}>
                  {s.reusers_count} ontolog{s.reusers_count === 1 ? 'y' : 'ies'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            <Th onClick={() => clickHeader('name')}
                active={sortKey === 'name'} dir={sortDir}
                testId="reuse-th-name">Ontology</Th>
            <Th onClick={() => clickHeader('imports')}
                active={sortKey === 'imports'} dir={sortDir}
                testId="reuse-th-imports">Imports</Th>
            <Th onClick={() => clickHeader('mireot')}
                active={sortKey === 'mireot'} dir={sortDir}
                testId="reuse-th-mireot">MIREOT</Th>
            <Th onClick={() => clickHeader('reused')}
                active={sortKey === 'reused'} dir={sortDir}
                testId="reuse-th-reused">Reused terms</Th>
            <Th onClick={() => clickHeader('mappings')}
                active={sortKey === 'mappings'} dir={sortDir}
                testId="reuse-th-mappings">Mappings</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(e => (
            <tr key={e.id} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '4px 8px' }}>
                <Link to={`/ontologies/${e.shortname || e.id}`}
                      style={{ color: 'var(--accent-blue)' }}>
                  {e.shortname || e.id}
                </Link>
              </td>
              <td style={{ padding: '4px 8px' }}>{e.imports_count}</td>
              <td style={{ padding: '4px 8px' }}>{e.mireot_terms_count}</td>
              <td style={{ padding: '4px 8px' }}>{e.term_iri_reused_count}</td>
              <td style={{ padding: '4px 8px' }}>{e.mappings_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 2: Register the tab in Ontologies.tsx**

Open `frontend/src/pages/Ontologies.tsx`.

Change line 12 from:
```typescript
type Tab = 'list' | 'coverage' | 'profiles' | 'compare'
```
to:
```typescript
type Tab = 'list' | 'coverage' | 'profiles' | 'compare' | 'reuse'
```

Change line 13:
```typescript
const TAB_VALUES: Tab[] = ['list', 'coverage', 'profiles', 'compare', 'reuse']
```

Add an entry to `TAB_LABELS`:
```typescript
const TAB_LABELS: Record<Tab, string> = {
  list: 'List',
  coverage: 'Coverage',
  profiles: 'OWL Profile',
  compare: 'Compare',
  reuse: 'Reuse',
}
```

Add the import near the top:
```typescript
import { Reuse } from './Reuse'
```

Add the dispatch line below `{tab === 'compare' && <Compare />}` (around L358):
```typescript
{tab === 'reuse' && <Reuse />}
```

- [ ] **Step 3: Build**

```
cd frontend && bun run build
```
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Reuse.tsx frontend/src/pages/Ontologies.tsx
git commit -m "feat(reuse): fleet Reuse tab under /ontologies?tab=reuse"
```

---

## Task 13: BioPortal-scale rerun script

**Files:**
- Create: `scripts/bioportal_reuse/README.md`
- Create: `scripts/bioportal_reuse/normalize.py`
- Create: `scripts/bioportal_reuse/mireot_heuristic.py`
- Create: `scripts/bioportal_reuse/publish.py`
- Create: `scripts/bioportal_reuse/run.py`

This script is intentionally separate from the OntoExplorer runtime — it consumes the user's existing preliminary-work CSVs from [bioportal-ontology-analysis](https://github.com/micheldumontier/bioportal-ontology-analysis) and overlays the same bioregistry normalization. No tests are required (this is a one-off analysis tool); a smoke check on a small sample validates end-to-end.

- [ ] **Step 1: README**

`scripts/bioportal_reuse/README.md`:
```markdown
# BioPortal Reuse Rerun

Re-runs the user's preliminary [bioportal-ontology-analysis](https://github.com/micheldumontier/bioportal-ontology-analysis)
work with two additions:

1. **Bioregistry-normalized IRIs** — variant URI forms (e.g. `purl.obolibrary.org/obo/RO_*` vs `purl.org/obo/RO_*`) collapse to the same target prefix, producing higher (more accurate) reuse counts.
2. **MIREOT heuristic** — without ontology bodies (BioPortal API gives metadata only at scale), we estimate MIREOT usage from the mapping table: a term that appears in `oboInOwl:hasDbXref` to ontology X but whose host does NOT declare `owl:imports` of X is a MIREOT *candidate*. Counts are upper-bound estimates and labelled as such.

## Inputs

Expects the preliminary work's CSV outputs to be available locally. Clone the
companion repo and pass its path:

```
git clone https://github.com/micheldumontier/bioportal-ontology-analysis.git ~/bpoa
python -m scripts.bioportal_reuse.run --input-dir ~/bpoa/results/tables --output-dir ~/bpoa/results/tables/v2-normalized
```

## Outputs

- `upper_level_adoption_normalized.csv` — adoption rate before/after normalization
- `hub_ontologies_normalized.csv` — mapping hubs with collapsed prefixes
- `mireot_candidates.csv` — terms that LOOK like MIREOT under the heuristic
- `summary.json` — single-file rollup for the GitHub Pages site

The publish step copies these into a `v2/` subdirectory of the
companion repo's `docs/` folder, ready for git commit + push.

## Caveat

This pipeline does NOT run the precise MIREOT detector — that requires
parsing ontology bodies and lives in OntoExplorer's `signals/mireot.py`.
The fleet-scale numbers from BioPortal are upper bounds. Use OntoExplorer's
per-ontology Reuse tab for ground-truth analysis.
```

- [ ] **Step 2: normalize.py**

`scripts/bioportal_reuse/normalize.py`:
```python
"""Apply bioregistry normalization to the preliminary work's CSV tables."""
from __future__ import annotations

import csv
from pathlib import Path

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


def normalize_upper_level_adoption(input_csv: Path, output_csv: Path) -> dict:
    """Reduces variant IRIs to canonical bioregistry prefixes.

    Preliminary work CSV schema (`upper_level_adoption.csv`):
        acronym, name, imports_iri, upper_level_detected, ...

    We re-key the `imports_iri` column through bioregistry. Variants that
    previously did not match (because the upstream code checked literal IRI
    equality) now collapse to the same prefix and DO match.
    """
    summary = {"rows_in": 0, "rows_out": 0, "newly_resolved": 0}
    seen_resolved: set[tuple[str, str]] = set()

    with input_csv.open() as f_in, output_csv.open("w") as f_out:
        reader = csv.DictReader(f_in)
        fieldnames = list(reader.fieldnames or []) + ["normalized_prefix", "resolved"]
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            summary["rows_in"] += 1
            iri = row.get("imports_iri", "")
            prefix, resolved = iri_to_prefix(iri)
            if resolved:
                key = (row["acronym"], prefix or "")
                if key not in seen_resolved:
                    seen_resolved.add(key)
                    summary["newly_resolved"] += 1
            row["normalized_prefix"] = prefix or ""
            row["resolved"] = "true" if resolved else "false"
            writer.writerow(row)
            summary["rows_out"] += 1

    return summary


def normalize_hub_ontologies(input_csv: Path, output_csv: Path) -> dict:
    """Collapse mapping-hub counts by bioregistry prefix (instead of raw IRI base)."""
    summary = {"rows_in": 0, "rows_out": 0}
    counts: dict[str, int] = {}

    with input_csv.open() as f_in:
        reader = csv.DictReader(f_in)
        for row in reader:
            summary["rows_in"] += 1
            iri = row.get("target_iri") or row.get("ontology_iri") or ""
            prefix, _ = iri_to_prefix(iri)
            key = prefix or iri
            n = int(row.get("mapping_count", row.get("count", 0)))
            counts[key] = counts.get(key, 0) + n

    with output_csv.open("w") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=["target_prefix", "mapping_count"])
        writer.writeheader()
        for prefix, count in sorted(counts.items(), key=lambda x: -x[1]):
            writer.writerow({"target_prefix": prefix, "mapping_count": count})
            summary["rows_out"] += 1

    return summary
```

- [ ] **Step 3: mireot_heuristic.py**

`scripts/bioportal_reuse/mireot_heuristic.py`:
```python
"""Heuristic MIREOT candidate estimator for BioPortal scale.

Without ontology bodies, the best we can do is: a term in ontology H
points (via mapping table) to ontology X, but H does not declare
owl:imports X. That's a MIREOT *candidate* — upper bound only.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


def estimate_mireot_candidates(
    mappings_csv: Path,
    imports_csv: Path,
    output_csv: Path,
) -> dict:
    """Cross-reference mapping targets vs declared imports per ontology."""
    declared: dict[str, set[str]] = {}
    with imports_csv.open() as f:
        for row in csv.DictReader(f):
            acronym = row.get("acronym", "")
            iri = row.get("imports_iri", "")
            prefix, _ = iri_to_prefix(iri)
            if prefix:
                declared.setdefault(acronym, set()).add(prefix)

    summary = {"rows_in": 0, "candidates": 0, "ontologies_with_candidates": 0}
    onts_with_candidates: set[str] = set()

    with mappings_csv.open() as f_in, output_csv.open("w") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=[
            "acronym", "target_prefix", "mapping_count", "is_candidate",
        ])
        writer.writeheader()
        # Group by (acronym, target_prefix)
        buckets: dict[tuple[str, str], int] = {}
        for row in csv.DictReader(f_in):
            summary["rows_in"] += 1
            acronym = row.get("acronym", "")
            target_iri = row.get("target_iri") or row.get("ontology_iri") or ""
            prefix, _ = iri_to_prefix(target_iri)
            if not prefix:
                continue
            buckets[(acronym, prefix)] = buckets.get((acronym, prefix), 0) + 1

        for (acronym, prefix), n in buckets.items():
            is_candidate = prefix not in declared.get(acronym, set())
            if is_candidate:
                summary["candidates"] += 1
                onts_with_candidates.add(acronym)
            writer.writerow({
                "acronym": acronym,
                "target_prefix": prefix,
                "mapping_count": n,
                "is_candidate": "true" if is_candidate else "false",
            })

    summary["ontologies_with_candidates"] = len(onts_with_candidates)
    return summary
```

- [ ] **Step 4: publish.py**

`scripts/bioportal_reuse/publish.py`:
```python
"""Package output CSVs + summary into the bioportal-ontology-analysis docs/v2/ dir."""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def publish(output_dir: Path, summary: dict, companion_repo: Path | None) -> Path:
    """Write summary.json alongside CSVs; optionally copy into companion repo."""
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    if companion_repo is not None:
        target = companion_repo / "docs" / "v2"
        target.mkdir(parents=True, exist_ok=True)
        for f in output_dir.iterdir():
            if f.is_file():
                shutil.copy(f, target / f.name)
        print(f"Copied {len(list(output_dir.iterdir()))} files to {target}")

    return summary_path
```

- [ ] **Step 5: run.py (orchestrator)**

`scripts/bioportal_reuse/run.py`:
```python
"""CLI entry: load preliminary CSVs, normalize, write outputs.

Usage:
  python -m scripts.bioportal_reuse.run \\
      --input-dir ~/bpoa/results/tables \\
      --output-dir ~/bpoa/results/tables/v2-normalized \\
      [--companion-repo ~/bpoa]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.bioportal_reuse.mireot_heuristic import estimate_mireot_candidates
from scripts.bioportal_reuse.normalize import (
    normalize_hub_ontologies,
    normalize_upper_level_adoption,
)
from scripts.bioportal_reuse.publish import publish


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--companion-repo", type=Path, default=None)
    args = p.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    upper_summary = normalize_upper_level_adoption(
        args.input_dir / "upper_level_adoption.csv",
        args.output_dir / "upper_level_adoption_normalized.csv",
    )
    hub_summary = normalize_hub_ontologies(
        args.input_dir / "hub_ontologies.csv",
        args.output_dir / "hub_ontologies_normalized.csv",
    )
    mireot_summary = estimate_mireot_candidates(
        args.input_dir / "hub_ontologies.csv",  # serves as mapping source
        args.input_dir / "upper_level_adoption.csv",  # imports source
        args.output_dir / "mireot_candidates.csv",
    )

    summary = {
        "upper_level": upper_summary,
        "hubs": hub_summary,
        "mireot": mireot_summary,
    }
    print(json.dumps(summary, indent=2))
    summary_path = publish(args.output_dir, summary, args.companion_repo)
    print(f"Wrote summary to {summary_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Smoke-test on a small input**

Create a 5-row fixture:
```
mkdir -p /tmp/bpoa-smoke/input /tmp/bpoa-smoke/output
cat > /tmp/bpoa-smoke/input/upper_level_adoption.csv <<'EOF'
acronym,name,imports_iri,upper_level_detected
RO,Relations Ontology,http://purl.obolibrary.org/obo/bfo.owl,true
GO,Gene Ontology,http://purl.obolibrary.org/obo/ro.owl,true
HP,Human Phenotype,http://purl.obolibrary.org/obo/iao.owl,true
PIZZA,Pizza Ontology,http://example.com/missing.owl,false
DOID,Disease Ontology,http://purl.obolibrary.org/obo/iao.owl,true
EOF
cat > /tmp/bpoa-smoke/input/hub_ontologies.csv <<'EOF'
acronym,target_iri,mapping_count
RO,http://purl.obolibrary.org/obo/CHEBI_0000001,42
GO,http://purl.obolibrary.org/obo/CHEBI_0000002,7
EOF
python -m scripts.bioportal_reuse.run \
    --input-dir /tmp/bpoa-smoke/input \
    --output-dir /tmp/bpoa-smoke/output
```
Expected: produces `upper_level_adoption_normalized.csv`, `hub_ontologies_normalized.csv`, `mireot_candidates.csv`, and `summary.json` in `/tmp/bpoa-smoke/output`. The summary JSON should report `newly_resolved >= 4` (BFO, RO, IAO, IAO again all resolve via bioregistry where the raw-IRI baseline might have missed variants).

- [ ] **Step 7: Commit**

```bash
git add scripts/bioportal_reuse/
git commit -m "feat(reuse): BioPortal-scale rerun with bioregistry + MIREOT heuristic"
```

---

## End-to-end verification

After all 13 tasks land, run the full verification listed in the spec:

```bash
# 1. Backend unit + integration tests
pytest tests/unit/reuse/ tests/integration/test_reuse_api.py -v

# 2. Reindex a fleet ontology with known imports (e.g. RO imports BFO + IAO)
#    via the existing OntoExplorer admin UI or API. Confirm:
curl -s http://localhost:8000/api/v1/ontologies/ro/<vid>/reuse | jq .
#   - .imports lists target_prefix "bfo", "iao"
#   - .term_iri_reuse has "bfo", "iao" keys with non-zero counts
#   - .mireot_terms is empty for RO (uses imports, not MIREOT)

# 3. Hit the fleet endpoint
curl -s http://localhost:8000/api/v1/reuse/fleet | jq '.totals'

# 4. Open the frontend
#    http://localhost:5173/ontologies?tab=reuse — table sorted by reused-term count desc
#    Click an ontology → ReuseSection appears below the OWL Profile section
#    Click a "top reused source" link → /ontologies?reuses=<prefix> filters the list

# 5. BioPortal rerun on real data (one-shot, not in CI)
git clone https://github.com/micheldumontier/bioportal-ontology-analysis.git ~/bpoa
python -m scripts.bioportal_reuse.run --input-dir ~/bpoa/results/tables \
    --output-dir ~/bpoa/results/tables/v2-normalized --companion-repo ~/bpoa
# Confirm: summary.json reports newly_resolved > 0 (bioregistry catches IRI variants)
```

If any verification step fails, the bug is in the most recent task and is reproducible — fix in place, do not skip to the next task.
