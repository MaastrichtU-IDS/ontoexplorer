# Consistency Analysis (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every ontology version in the OntoExplorer fleet, compute and cache three consistency verdicts — host alone, host + `owl:imports` closure, host + closure + fetched MIREOT-source ontologies — each with the list of unsatisfiable classes and a ROBOT-explain justification per class.

**Architecture:** New module `ontoexplorer/modules/consistency/` with focused files for each pipeline stage (merger → konclude wrapper → robot_explain wrapper → mireot_source_resolver → detector aggregator). Async Celery task `check_consistency` enqueued by the indexer post-index (mirrors the existing `reason_ontology` ELK task pattern). Frontend adds a per-ontology Consistency tab + fleet rollup tab (mirrors the shipped Phase 1 Reuse shape). HermiT cross-check ships as `scripts/consistency_bench/`. Konclude binary added to the runtime Docker image.

**Tech Stack:** Python 3.10+, Konclude C++ binary (CLI shell-out), ROBOT 1.9.10 (already in the image, used by `scripts/owl_profile_bench/`), pyoxigraph (graph extraction), SQLAlchemy async + Postgres, Redis (cache, 30-day TTL), Celery (async job), FastAPI (routes), React + TanStack Query.

---

## File Structure

```
ontoexplorer/modules/consistency/
    __init__.py                       # re-exports public types
    cache.py                          # consistency_cache_key(version_id) -> str
    merger.py                         # build_merge(version_id, ontology_id, scope, fetched_mireot_paths) -> Path
    konclude.py                       # run_konclude_consistency(nt_path) -> KoncludeResult
    robot_explain.py                  # explain_unsatisfiability(nt_path, iri) -> list[ManchesterToken]
    mireot_source_resolver.py         # fetch_mireot_sources(version_id) -> dict[prefix, Path]
    detector.py                       # detect_consistency(version_id, ontology_id) -> ConsistencyReport

ontoexplorer/api/
    consistency.py                    # /consistency endpoints + filter helper

scripts/consistency_bench/
    README.md
    run.py                            # run HermiT/ROBOT consistency over fleet
    compare.py                        # diff Konclude (cache) vs HermiT verdicts
    publish.py                        # render CSV/JSON results

frontend/src/components/
    ConsistencySection.tsx            # per-onto: three scope cards + expandable justifications

frontend/src/pages/
    Consistency.tsx                   # fleet table + summary cards + filter pill

tests/unit/consistency/
    __init__.py
    test_cache.py
    test_konclude.py
    test_robot_explain.py
    test_merger.py
    test_mireot_source_resolver.py
    test_detector.py
tests/integration/
    test_consistency_api.py
```

Files modified:
- `ontoexplorer/modules/search/indexer.py` — enqueue `check_consistency.delay(...)` post-index, write `pending` placeholder to cache; add invalidate
- `ontoexplorer/modules/jobs/tasks.py` — add `check_consistency` task
- `ontoexplorer/main.py` — `app.include_router(consistency_router)`
- `ontoexplorer/api/ontologies.py` — add `?consistency=<value>` filter
- `frontend/src/lib/api.ts` — types + fetchers
- `frontend/src/pages/Ontologies.tsx` — register `consistency` tab
- `frontend/src/pages/OntologyPage.tsx` — add `consistency` detailTab branch
- `Dockerfile` (or `docker/runtime.Dockerfile`) — add Konclude binary install step

---

## Sequencing

Tasks 1-7 build the consistency engine bottom-up (cache → konclude wrapper → robot_explain → merger → mireot resolver → detector). Each is independently testable. Task 8 is the Celery task that orchestrates the three-scope run. Task 9 hooks the indexer. Tasks 10-12 are the API + frontend. Task 13 is the HermiT cross-check bench script. Task 14 is the Dockerfile change for Konclude packaging — listed last because it can be parallelized with frontend work but blocks production deployment.

---

## Task 1: Module scaffold + Redis cache-key helper

**Files:**
- Create: `ontoexplorer/modules/consistency/__init__.py`
- Create: `ontoexplorer/modules/consistency/cache.py`
- Create: `tests/unit/consistency/__init__.py`
- Create: `tests/unit/consistency/test_cache.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/consistency/test_cache.py`:
```python
from ontoexplorer.modules.consistency.cache import consistency_cache_key


def test_consistency_cache_key_format():
    assert consistency_cache_key("abc-123") == "consistency:abc-123"


def test_consistency_cache_key_handles_uuid():
    vid = "550e8400-e29b-41d4-a716-446655440000"
    assert consistency_cache_key(vid) == f"consistency:{vid}"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /path/to/ontoexplorer && /path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_cache.py -v
```
Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.consistency'`.

- [ ] **Step 3: Create files**

`ontoexplorer/modules/consistency/__init__.py`:
```python
"""Joint-reasoning consistency analysis (Konclude + ROBOT explain)."""
```

`tests/unit/consistency/__init__.py`:
```python
```
(empty)

`ontoexplorer/modules/consistency/cache.py`:
```python
"""Redis cache-key helper for consistency reports (mirrors reuse.cache)."""


def consistency_cache_key(version_id: str) -> str:
    return f"consistency:{version_id}"
```

- [ ] **Step 4: Run test to verify it passes**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_cache.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/consistency/ tests/unit/consistency/
git commit -m "feat(consistency): scaffold module + redis cache key helper"
```

---

## Task 2: Konclude wrapper

**Files:**
- Create: `ontoexplorer/modules/consistency/konclude.py`
- Create: `tests/unit/consistency/test_konclude.py`

Konclude's CLI:
- `Konclude consistency -i <ontology.owl>` → exits 0 if consistent, non-zero if inconsistent. Prints `Ontology is consistent.` / `Ontology is inconsistent.` to stdout.
- `Konclude classify -i <ontology.owl> -o <out.owl>` → writes inferred class hierarchy to `out.owl`. To find unsatisfiable classes, query the output for `EquivalentClasses(<X>, owl:Nothing)` axioms.

We wrap both. The CLI is invoked via `subprocess.run`. The wrapper is a pure function — caller provides the input file path; we return parsed results.

- [ ] **Step 1: Write the failing test**

`tests/unit/consistency/test_konclude.py`:
```python
from pathlib import Path

import pytest

from ontoexplorer.modules.consistency.konclude import (
    KoncludeResult,
    KoncludeUnavailable,
    run_konclude_consistency,
)


# Trivial consistent fixture: empty ontology
CONSISTENT_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xml:base="http://example.org/ok">
  <owl:Ontology rdf:about="http://example.org/ok"/>
  <owl:Class rdf:about="http://example.org/ok#A"/>
</rdf:RDF>
"""

# Inconsistent fixture: A and B are disjoint, but C is both A and B
INCONSISTENT_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xml:base="http://example.org/bad">
  <owl:Ontology rdf:about="http://example.org/bad"/>
  <owl:Class rdf:about="http://example.org/bad#A">
    <owl:disjointWith rdf:resource="http://example.org/bad#B"/>
  </owl:Class>
  <owl:Class rdf:about="http://example.org/bad#B"/>
  <owl:Class rdf:about="http://example.org/bad#C">
    <rdfs:subClassOf rdf:resource="http://example.org/bad#A"/>
    <rdfs:subClassOf rdf:resource="http://example.org/bad#B"/>
  </owl:Class>
</rdf:RDF>
"""


def _write_fixture(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def test_consistent_ontology_classified_as_consistent(tmp_path):
    fixture = _write_fixture(tmp_path, "ok.owl", CONSISTENT_OWL)
    try:
        result = run_konclude_consistency(fixture, timeout_seconds=60)
    except KoncludeUnavailable:
        pytest.skip("Konclude binary not installed in this environment")
    assert isinstance(result, KoncludeResult)
    assert result.consistent is True
    assert result.unsatisfiable_class_iris == []


def test_inconsistent_ontology_yields_unsatisfiable_classes(tmp_path):
    fixture = _write_fixture(tmp_path, "bad.owl", INCONSISTENT_OWL)
    try:
        result = run_konclude_consistency(fixture, timeout_seconds=60)
    except KoncludeUnavailable:
        pytest.skip("Konclude binary not installed in this environment")
    # `C` is unsatisfiable because it's subClass of two disjoint classes.
    # Konclude flags this either as global inconsistency OR as `C subClassOf owl:Nothing`.
    assert (result.consistent is False) or (
        "http://example.org/bad#C" in result.unsatisfiable_class_iris
    )


def test_missing_binary_raises_konclude_unavailable(tmp_path, monkeypatch):
    fixture = _write_fixture(tmp_path, "ok.owl", CONSISTENT_OWL)
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(KoncludeUnavailable):
        run_konclude_consistency(fixture, timeout_seconds=10, konclude_cmd="this-binary-does-not-exist-xyz")
```

- [ ] **Step 2: Run test to verify it fails**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_konclude.py -v
```
Expected: `ImportError: cannot import name 'KoncludeResult'`.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/consistency/konclude.py`:
```python
"""Konclude reasoner shell-out wrapper.

Konclude is a native C++ OWL 2 DL reasoner (no JVM). We invoke its CLI
twice per consistency check: once for the boolean (`consistency`) and
once for classification (to extract unsatisfiable classes).

The wrapper is a pure function over a file path on disk; the caller is
responsible for materializing the merge.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


class KoncludeUnavailable(RuntimeError):
    """Raised when the Konclude binary cannot be found on PATH."""


class KoncludeTimeout(RuntimeError):
    """Raised when Konclude exceeds the timeout."""


@dataclass
class KoncludeResult:
    consistent: bool
    unsatisfiable_class_iris: list[str] = field(default_factory=list)
    classification_output_path: Path | None = None  # for downstream robot_explain
    stdout: str = ""
    stderr: str = ""


def run_konclude_consistency(
    ontology_path: Path,
    *,
    timeout_seconds: int = 600,
    konclude_cmd: str = "Konclude",
) -> KoncludeResult:
    """Run Konclude consistency + classification on the merged ontology file.

    Args:
        ontology_path: Path to an OWL/Turtle/N-Triples file Konclude can load.
        timeout_seconds: Hard cutoff per Konclude invocation (consistency + classify combined wall time).
        konclude_cmd: Binary name on PATH.

    Returns:
        KoncludeResult with consistent flag + unsatisfiable class IRIs.

    Raises:
        KoncludeUnavailable: if the binary is not on PATH.
        KoncludeTimeout: if either invocation exceeds the timeout.
    """
    if shutil.which(konclude_cmd) is None:
        raise KoncludeUnavailable(f"{konclude_cmd!r} not found on PATH")

    # Step 1: consistency check
    try:
        cons_proc = subprocess.run(
            [konclude_cmd, "consistency", "-i", str(ontology_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise KoncludeTimeout(f"Konclude consistency timed out after {timeout_seconds}s") from e

    stdout = cons_proc.stdout
    stderr = cons_proc.stderr
    consistent = _parse_consistency_verdict(stdout)

    # Step 2: classification (only needed to find unsatisfiable classes; skip if globally inconsistent)
    unsat_iris: list[str] = []
    classify_out_path: Path | None = None
    if consistent:
        classify_out_path = ontology_path.with_suffix(".classified.owl")
        try:
            classify_proc = subprocess.run(
                [konclude_cmd, "classify", "-i", str(ontology_path), "-o", str(classify_out_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise KoncludeTimeout(f"Konclude classify timed out after {timeout_seconds}s") from e
        stdout += "\n" + classify_proc.stdout
        stderr += "\n" + classify_proc.stderr
        if classify_out_path.exists():
            unsat_iris = _parse_unsatisfiable_classes(classify_out_path)

    return KoncludeResult(
        consistent=consistent,
        unsatisfiable_class_iris=unsat_iris,
        classification_output_path=classify_out_path,
        stdout=stdout,
        stderr=stderr,
    )


def _parse_consistency_verdict(stdout: str) -> bool:
    """Konclude prints 'Ontology is consistent.' or 'Ontology is inconsistent.' to stdout."""
    lowered = stdout.lower()
    if "inconsistent" in lowered:
        return False
    if "consistent" in lowered:
        return True
    # Konclude exited 0 but didn't print the expected verdict — treat as inconsistent (conservative).
    return False


_OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"


def _parse_unsatisfiable_classes(classified_path: Path) -> list[str]:
    """Extract IRIs of classes equivalent to owl:Nothing from Konclude's classify output.

    Konclude emits the inferred classification as OWL/XML. An unsatisfiable named
    class C appears as `<owl:Class rdf:about="C"> <owl:equivalentClass rdf:resource="owl:Nothing"/> </owl:Class>`
    OR as `<owl:EquivalentClasses>` with two children, one of which is owl:Nothing.

    We tolerate both forms.
    """
    try:
        tree = ET.parse(classified_path)
    except ET.ParseError:
        return []
    root = tree.getroot()
    ns = {
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    }
    unsat: set[str] = set()
    # Form 1: owl:Class with owl:equivalentClass pointing at owl:Nothing
    for cls in root.iter(f"{{{ns['owl']}}}Class"):
        about = cls.get(f"{{{ns['rdf']}}}about")
        if about is None:
            continue
        for eq in cls.findall(f"{{{ns['owl']}}}equivalentClass"):
            ref = eq.get(f"{{{ns['rdf']}}}resource")
            if ref == _OWL_NOTHING:
                unsat.add(about)
    return sorted(unsat)
```

- [ ] **Step 4: Run test to verify it passes**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_konclude.py -v
```
Expected: 3 passed (the two real-Konclude tests will SKIP cleanly if Konclude isn't installed in the dev environment; only `test_missing_binary_raises_konclude_unavailable` always runs).

If Konclude IS installed and the Konclude-version test output format differs from our parser, adjust `_parse_consistency_verdict` and `_parse_unsatisfiable_classes` based on the actual stdout/output XML. The wrapper's contract is stable; only the parsing internals may need tuning.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/consistency/konclude.py tests/unit/consistency/test_konclude.py
git commit -m "feat(consistency): Konclude CLI wrapper (consistency + unsat extraction)"
```

---

## Task 3: ROBOT explain wrapper

**Files:**
- Create: `ontoexplorer/modules/consistency/robot_explain.py`
- Create: `tests/unit/consistency/test_robot_explain.py`

ROBOT's `explain` subcommand: `robot explain --input <ontology.owl> --reasoner hermit --axiom "<class_iri> SubClassOf: owl:Nothing" --explanation explanation.txt`. The output is plain-text Manchester syntax with each axiom on its own line.

We parse that into our existing `ManchesterToken[]` shape (from `pyowl2_profiles.manchester`).

- [ ] **Step 1: Write the failing test**

`tests/unit/consistency/test_robot_explain.py`:
```python
from pathlib import Path

import pytest

from ontoexplorer.modules.consistency.robot_explain import (
    RobotExplainUnavailable,
    explain_unsatisfiability,
)


# Same inconsistent fixture as Task 2: A and B disjoint, C subclass of both
INCONSISTENT_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xml:base="http://example.org/bad">
  <owl:Ontology rdf:about="http://example.org/bad"/>
  <owl:Class rdf:about="http://example.org/bad#A">
    <owl:disjointWith rdf:resource="http://example.org/bad#B"/>
  </owl:Class>
  <owl:Class rdf:about="http://example.org/bad#B"/>
  <owl:Class rdf:about="http://example.org/bad#C">
    <rdfs:subClassOf rdf:resource="http://example.org/bad#A"/>
    <rdfs:subClassOf rdf:resource="http://example.org/bad#B"/>
  </owl:Class>
</rdf:RDF>
"""


def test_explain_returns_axiom_list(tmp_path):
    fixture = tmp_path / "bad.owl"
    fixture.write_text(INCONSISTENT_OWL)
    try:
        tokens = explain_unsatisfiability(
            fixture,
            class_iri="http://example.org/bad#C",
            timeout_seconds=60,
        )
    except RobotExplainUnavailable:
        pytest.skip("ROBOT not installed in this environment")
    assert isinstance(tokens, list)
    assert len(tokens) >= 1
    # Each item is a list of ManchesterTokens (one per axiom in the justification)


def test_missing_robot_raises(tmp_path):
    fixture = tmp_path / "bad.owl"
    fixture.write_text(INCONSISTENT_OWL)
    with pytest.raises(RobotExplainUnavailable):
        explain_unsatisfiability(
            fixture,
            class_iri="http://example.org/bad#C",
            timeout_seconds=10,
            robot_cmd="this-binary-does-not-exist-xyz",
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_robot_explain.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/consistency/robot_explain.py`:
```python
"""ROBOT explain wrapper for per-class unsatisfiability justifications.

For each unsatisfiable class IRI, ROBOT computes a MINIMUM-MODULE
justification (the smallest axiom subset that proves the unsatisfiability)
via HermiT. We parse the Manchester-syntax output into our existing
ManchesterToken shape so the frontend can render it inline.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pyowl2_profiles.manchester import ManchesterToken, parse_manchester_axiom


class RobotExplainUnavailable(RuntimeError):
    """Raised when the ROBOT binary cannot be found on PATH."""


class RobotExplainTimeout(RuntimeError):
    """Raised when ROBOT explain exceeds the timeout."""


def explain_unsatisfiability(
    ontology_path: Path,
    *,
    class_iri: str,
    timeout_seconds: int = 300,
    robot_cmd: str = "robot",
) -> list[list[ManchesterToken]]:
    """Run ROBOT explain to extract a justification for `class_iri SubClassOf owl:Nothing`.

    Args:
        ontology_path: Path to the merged ontology file (the same one Konclude reasoned over).
        class_iri: The unsatisfiable class to explain.
        timeout_seconds: Hard cutoff for ROBOT.
        robot_cmd: Binary name on PATH.

    Returns:
        A list of axioms (each axiom is a list of ManchesterTokens).

    Raises:
        RobotExplainUnavailable: if ROBOT is missing.
        RobotExplainTimeout: if the command exceeds the timeout.
    """
    if shutil.which(robot_cmd) is None:
        raise RobotExplainUnavailable(f"{robot_cmd!r} not found on PATH")

    explanation_path = ontology_path.with_suffix(f".explain.{_safe(class_iri)}.txt")
    try:
        proc = subprocess.run(
            [
                robot_cmd, "explain",
                "--input", str(ontology_path),
                "--reasoner", "hermit",
                "--axiom", f"<{class_iri}> SubClassOf: owl:Nothing",
                "--explanation", str(explanation_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RobotExplainTimeout(f"ROBOT explain timed out after {timeout_seconds}s") from e

    if not explanation_path.exists():
        # ROBOT may have failed (no justification found, error, etc.)
        return []

    raw = explanation_path.read_text()
    axioms: list[list[ManchesterToken]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("Explanation"):
            continue
        try:
            axioms.append(parse_manchester_axiom(line))
        except Exception:
            # Fall back to a single text token if parsing fails
            axioms.append([ManchesterToken(t="text", v=line)])
    return axioms


def _safe(iri: str) -> str:
    """Make an IRI safe for use as a filename component."""
    return iri.replace("://", "_").replace("/", "_").replace("#", "_")[-80:]
```

Note: the `pyowl2_profiles.manchester` import assumes the library is installed (Phase 1 already added it as a dependency). The `parse_manchester_axiom` function is from the library; if its signature differs, adapt — but the function exists per Phase 1's manchester rendering work. If parsing falls back to a text-only token for one line, the frontend will display that line as plain text rather than as styled tokens — acceptable degradation.

- [ ] **Step 4: Run test to verify it passes**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_robot_explain.py -v
```
Expected: 2 passed (the ROBOT test skips if ROBOT isn't installed; the missing-binary test always runs).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/consistency/robot_explain.py tests/unit/consistency/test_robot_explain.py
git commit -m "feat(consistency): ROBOT explain wrapper for unsat-class justifications"
```

---

## Task 4: Merger — build N-Triples blob per scope

**Files:**
- Create: `ontoexplorer/modules/consistency/merger.py`
- Create: `tests/unit/consistency/test_merger.py`

The merger materializes a single file Konclude can load. For each scope:
- `host_only`: serialize just the host's named graph from Oxigraph
- `host_plus_imports`: include all transitively-imported named graphs (already loaded in Oxigraph by `import_resolver` at ingestion time)
- `host_plus_imports_plus_mireot`: additionally append fetched-source Turtle bytes from `mireot_source_resolver` (resolved into a list of paths passed in)

We serialize as N-Triples (Konclude reads N-Triples; simplest to concatenate).

- [ ] **Step 1: Write the failing test**

`tests/unit/consistency/test_merger.py`:
```python
from pathlib import Path

import pyoxigraph
import pytest

from ontoexplorer.modules.consistency.merger import build_merge


HOST_GRAPH = "urn:test:host"
IMPORT_GRAPH = "urn:test:import"


@pytest.fixture
def populated_store(monkeypatch):
    """A pyoxigraph store with two named graphs: host + an import."""
    store = pyoxigraph.Store()
    store.load(
        b"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
            <http://example.org/host#A> a owl:Class .""",
        "text/turtle",
        to_graph=pyoxigraph.NamedNode(HOST_GRAPH),
    )
    store.load(
        b"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
            <http://purl.obolibrary.org/obo/BFO_0000001> a owl:Class .""",
        "text/turtle",
        to_graph=pyoxigraph.NamedNode(IMPORT_GRAPH),
    )
    # Patch get_store so build_merge uses our test store
    monkeypatch.setattr(
        "ontoexplorer.modules.consistency.merger.get_store",
        lambda: store,
    )
    return store


def test_host_only_scope_contains_only_host(populated_store, tmp_path):
    out = build_merge(
        out_dir=tmp_path,
        host_graph_iri=HOST_GRAPH,
        import_graph_iris=[IMPORT_GRAPH],
        mireot_source_paths=[],
        scope="host_only",
    )
    content = out.read_text()
    assert "host#A" in content
    assert "BFO_0000001" not in content


def test_host_plus_imports_includes_imports(populated_store, tmp_path):
    out = build_merge(
        out_dir=tmp_path,
        host_graph_iri=HOST_GRAPH,
        import_graph_iris=[IMPORT_GRAPH],
        mireot_source_paths=[],
        scope="host_plus_imports",
    )
    content = out.read_text()
    assert "host#A" in content
    assert "BFO_0000001" in content


def test_host_plus_imports_plus_mireot_appends_source_bytes(populated_store, tmp_path):
    mireot_src = tmp_path / "mireot_iao.nt"
    mireot_src.write_text(
        "<http://purl.obolibrary.org/obo/IAO_0000115> "
        "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
        "<http://www.w3.org/2002/07/owl#AnnotationProperty> .\n"
    )
    out = build_merge(
        out_dir=tmp_path,
        host_graph_iri=HOST_GRAPH,
        import_graph_iris=[IMPORT_GRAPH],
        mireot_source_paths=[mireot_src],
        scope="host_plus_imports_plus_mireot",
    )
    content = out.read_text()
    assert "host#A" in content
    assert "BFO_0000001" in content
    assert "IAO_0000115" in content


def test_invalid_scope_raises(populated_store, tmp_path):
    with pytest.raises(ValueError, match="unknown scope"):
        build_merge(
            out_dir=tmp_path,
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            mireot_source_paths=[],
            scope="invalid",
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_merger.py -v
```
Expected: ImportError on `build_merge`.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/consistency/merger.py`:
```python
"""Materialize a single N-Triples file per reasoning scope.

For each scope we extract the relevant subset of the OntoExplorer pyoxigraph
store + optionally append fetched MIREOT-source bytes, and write to disk so
Konclude / ROBOT can read it.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

import pyoxigraph

from ontoexplorer.clients.oxigraph import get_store


_VALID_SCOPES = {
    "host_only",
    "host_plus_imports",
    "host_plus_imports_plus_mireot",
}


def build_merge(
    *,
    out_dir: Path,
    host_graph_iri: str,
    import_graph_iris: list[str],
    mireot_source_paths: list[Path],
    scope: str,
) -> Path:
    """Build a single .nt file representing the merged ontology for the given scope.

    Returns the path to the written file.
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(f"unknown scope: {scope!r} (must be one of {_VALID_SCOPES})")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"merge_{scope}.nt"

    graphs_to_dump = [host_graph_iri]
    if scope in ("host_plus_imports", "host_plus_imports_plus_mireot"):
        graphs_to_dump.extend(import_graph_iris)

    store = get_store()
    with out_path.open("wb") as out_f:
        for g_iri in graphs_to_dump:
            _dump_graph_as_nt(store, g_iri, out_f)
        if scope == "host_plus_imports_plus_mireot":
            for src_path in mireot_source_paths:
                # Append the MIREOT source bytes verbatim — they're already N-Triples
                # (the resolver converts whatever format the source ships in to N-Triples).
                out_f.write(src_path.read_bytes())
                if not src_path.read_bytes().endswith(b"\n"):
                    out_f.write(b"\n")

    return out_path


def _dump_graph_as_nt(store: pyoxigraph.Store, graph_iri: str, out: io.BufferedWriter) -> None:
    """Serialize all quads in `graph_iri` as N-Triples (dropping the graph component)."""
    g = pyoxigraph.NamedNode(graph_iri)
    for quad in store.quads_for_pattern(None, None, None, g):
        triple = pyoxigraph.Triple(quad.subject, quad.predicate, quad.object)
        out.write(_serialize_triple_nt(triple).encode())
        out.write(b"\n")


def _serialize_triple_nt(triple: pyoxigraph.Triple) -> str:
    """Render a single triple as N-Triples line (no trailing newline)."""
    return f"{_term_nt(triple.subject)} {_term_nt(triple.predicate)} {_term_nt(triple.object)} ."


def _term_nt(term) -> str:
    """N-Triples serialization of a single term."""
    if isinstance(term, pyoxigraph.NamedNode):
        return f"<{term.value}>"
    if isinstance(term, pyoxigraph.BlankNode):
        return f"_:{term.value}"
    if isinstance(term, pyoxigraph.Literal):
        # Best-effort literal serialization. pyoxigraph's Literal has .value, .language, .datatype
        escaped = term.value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        s = f'"{escaped}"'
        if term.language:
            s += f"@{term.language}"
        elif term.datatype is not None and term.datatype.value != "http://www.w3.org/2001/XMLSchema#string":
            s += f"^^<{term.datatype.value}>"
        return s
    raise TypeError(f"Unsupported term type: {type(term)}")
```

- [ ] **Step 4: Run test to verify it passes**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_merger.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/consistency/merger.py tests/unit/consistency/test_merger.py
git commit -m "feat(consistency): per-scope N-Triples merger"
```

---

## Task 5: MIREOT source resolver

**Files:**
- Create: `ontoexplorer/modules/consistency/mireot_source_resolver.py`
- Create: `tests/unit/consistency/test_mireot_source_resolver.py`

For each MIREOT'd term flagged by Phase 1's reuse cache, derive the source ontology IRI via bioregistry, then use the existing import_resolver to fetch + MinIO-cache it, returning paths to N-Triples-converted files.

- [ ] **Step 1: Write the failing test**

`tests/unit/consistency/test_mireot_source_resolver.py`:
```python
from pathlib import Path
from unittest.mock import patch

import pytest

from ontoexplorer.modules.consistency.mireot_source_resolver import (
    MireotSourceResolveResult,
    fetch_mireot_sources,
)


def test_resolves_known_prefix_to_canonical_iri(tmp_path):
    """Given a Phase 1 reuse cache with a MIREOT'd prefix, derive the source IRI."""
    fake_reuse = {
        "mireot_terms": [
            {"iri": "http://purl.obolibrary.org/obo/IAO_0000115",
             "source_prefix": "iao", "has_imported_from": True},
            {"iri": "http://purl.obolibrary.org/obo/IAO_0000118",
             "source_prefix": "iao", "has_imported_from": False},
        ],
        "imports": [],
    }
    # Mock the actual fetch — we test the dedup + IRI-derivation logic, not the network
    fetched_path = tmp_path / "iao.nt"
    fetched_path.write_text(
        "<http://purl.obolibrary.org/obo/IAO_0000115> "
        "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
        "<http://www.w3.org/2002/07/owl#AnnotationProperty> .\n"
    )
    with patch("ontoexplorer.modules.consistency.mireot_source_resolver._fetch_and_convert_to_nt",
               return_value=fetched_path):
        result = fetch_mireot_sources(reuse_payload=fake_reuse, out_dir=tmp_path)
    assert isinstance(result, MireotSourceResolveResult)
    assert "iao" in result.fetched
    assert "iao" not in result.skipped
    # IAO appears twice in mireot_terms but is fetched once (dedup'd)
    assert len(result.fetched) == 1


def test_skips_imported_prefixes(tmp_path):
    """If a MIREOT'd term's source IS in the imports closure, don't re-fetch it."""
    fake_reuse = {
        "mireot_terms": [
            {"iri": "http://purl.obolibrary.org/obo/IAO_0000115",
             "source_prefix": "iao", "has_imported_from": True},
        ],
        "imports": [
            {"target_iri": "http://purl.obolibrary.org/obo/iao.owl",
             "target_prefix": "iao", "depth": 1, "resolved": True},
        ],
    }
    result = fetch_mireot_sources(reuse_payload=fake_reuse, out_dir=tmp_path)
    # iao is already imported, so no fetch was needed
    assert "iao" not in result.fetched
    assert "iao" not in result.skipped


def test_unreachable_source_recorded_in_skipped(tmp_path):
    """When fetch fails, prefix moves to `skipped` not `fetched`."""
    fake_reuse = {
        "mireot_terms": [
            {"iri": "http://example.org/obscure/Foo_001",
             "source_prefix": "obscure", "has_imported_from": False},
        ],
        "imports": [],
    }
    with patch("ontoexplorer.modules.consistency.mireot_source_resolver._fetch_and_convert_to_nt",
               side_effect=RuntimeError("network unreachable")):
        result = fetch_mireot_sources(reuse_payload=fake_reuse, out_dir=tmp_path)
    assert "obscure" in result.skipped
    assert "obscure" not in result.fetched
```

- [ ] **Step 2: Run test to verify it fails**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_mireot_source_resolver.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/consistency/mireot_source_resolver.py`:
```python
"""Fetch MIREOT source ontologies for the host+imports+MIREOT reasoning scope.

The resolver reads Phase 1's reuse cache payload to know which source-prefixes
are MIREOT'd (foreign-IRI + minimal-axiomatization + NOT in imports closure).
For each such prefix it:
  1. Derives the canonical source IRI via bioregistry
  2. Calls the existing OntoExplorer import_resolver to fetch + MinIO-cache it
  3. Converts the fetched bytes to N-Triples format
  4. Writes to `out_dir` so the merger can include it

Fails soft per source: a single unreachable source goes into `skipped`, the
overall result still includes whatever WAS fetched.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import rdflib

from ontoexplorer.modules.reuse.bioregistry import prefix_to_canonical_iri


log = logging.getLogger(__name__)


@dataclass
class MireotSourceResolveResult:
    fetched: dict[str, Path] = field(default_factory=dict)  # prefix -> path to .nt file
    skipped: list[str] = field(default_factory=list)        # prefixes that failed to fetch


def fetch_mireot_sources(
    *,
    reuse_payload: dict,
    out_dir: Path,
) -> MireotSourceResolveResult:
    """Resolve all MIREOT source prefixes for one version.

    Args:
        reuse_payload: the JSON dict from `reuse:{version_id}` Redis cache (Phase 1).
        out_dir: where to write the fetched N-Triples files.

    Returns:
        MireotSourceResolveResult mapping prefixes to .nt paths (success) and
        a list of skipped prefixes (failure or no canonical IRI).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result = MireotSourceResolveResult()

    imported_prefixes = {
        edge.get("target_prefix")
        for edge in reuse_payload.get("imports", [])
        if edge.get("target_prefix")
    }

    needed_prefixes: set[str] = set()
    for term in reuse_payload.get("mireot_terms", []):
        prefix = term.get("source_prefix")
        if not prefix:
            continue
        if prefix in imported_prefixes:
            continue  # already in import closure — covered by host_plus_imports scope
        needed_prefixes.add(prefix)

    for prefix in sorted(needed_prefixes):
        canonical_iri = prefix_to_canonical_iri(prefix)
        if not canonical_iri:
            result.skipped.append(prefix)
            log.warning("mireot_source_no_canonical_iri prefix=%s", prefix)
            continue
        # bioregistry's URI-prefix is the namespace, not the ontology file. For OBO
        # Foundry, we conventionally fetch `<canonical_iri>.owl` or use the ontology IRI.
        # For non-OBO sources this won't work uniformly; treat as best-effort.
        source_url = _derive_ontology_url(prefix, canonical_iri)
        try:
            nt_path = _fetch_and_convert_to_nt(prefix, source_url, out_dir)
            result.fetched[prefix] = nt_path
        except Exception as exc:
            log.warning("mireot_source_fetch_failed prefix=%s url=%s err=%s",
                        prefix, source_url, exc)
            result.skipped.append(prefix)
    return result


def _derive_ontology_url(prefix: str, canonical_iri: str) -> str:
    """Best-effort derivation of an ontology document URL from a bioregistry prefix.

    Convention for OBO Foundry: http://purl.obolibrary.org/obo/{prefix}.owl
    Falls back to the canonical bioregistry URI prefix for non-OBO sources.
    """
    if "purl.obolibrary.org/obo/" in canonical_iri:
        return f"http://purl.obolibrary.org/obo/{prefix}.owl"
    return canonical_iri


def _fetch_and_convert_to_nt(prefix: str, source_url: str, out_dir: Path) -> Path:
    """Fetch the ontology bytes (via import_resolver) and write as N-Triples to out_dir.

    Returns the path to the .nt file.
    Raises RuntimeError on fetch failure.
    """
    from ontoexplorer.modules.ingestion.import_resolver import _fetch_import

    data, ext = _fetch_import(source_url)
    if not data:
        raise RuntimeError(f"empty body fetching {source_url}")

    # Parse via rdflib (handles owl/turtle/rdf/xml/obo), re-serialize as N-Triples
    g = rdflib.Graph()
    rdflib_format = _ext_to_rdflib_format(ext)
    g.parse(data=data, format=rdflib_format)

    nt_path = out_dir / f"mireot_{prefix}.nt"
    nt_path.write_bytes(g.serialize(format="nt").encode("utf-8"))
    return nt_path


def _ext_to_rdflib_format(ext: str) -> str:
    return {
        "owl": "xml",
        "rdf": "xml",
        "ttl": "turtle",
        "nt": "nt",
        "obo": "obo",   # rdflib may not handle .obo natively; fall back to xml on failure
    }.get(ext.lstrip("."), "xml")
```

- [ ] **Step 4: Run test to verify it passes**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_mireot_source_resolver.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/consistency/mireot_source_resolver.py tests/unit/consistency/test_mireot_source_resolver.py
git commit -m "feat(consistency): MIREOT-source resolver via bioregistry + import_resolver"
```

---

## Task 6: Detector aggregator

**Files:**
- Create: `ontoexplorer/modules/consistency/detector.py`
- Modify: `ontoexplorer/modules/consistency/__init__.py`
- Create: `tests/unit/consistency/test_detector.py`

The aggregator orchestrates: load reuse cache → for each scope { build merge → run konclude → for top-10 unsat call robot_explain } → assemble ConsistencyReport.

For testability, we inject the Konclude runner and ROBOT-explain runner as callables (default: the real wrappers; in tests: stubs returning canned results).

- [ ] **Step 1: Write the failing test**

`tests/unit/consistency/test_detector.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch

import pyoxigraph
import pytest

from ontoexplorer.modules.consistency.detector import (
    ConsistencyReport,
    ScopeResult,
    detect_consistency,
)
from ontoexplorer.modules.consistency.konclude import KoncludeResult


HOST_GRAPH = "urn:test:host"


@pytest.fixture
def populated_store(monkeypatch):
    store = pyoxigraph.Store()
    store.load(
        b'@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
        b'<http://example.org/host#A> a owl:Class .\n',
        "text/turtle",
        to_graph=pyoxigraph.NamedNode(HOST_GRAPH),
    )
    monkeypatch.setattr(
        "ontoexplorer.modules.consistency.merger.get_store",
        lambda: store,
    )
    return store


def test_report_has_three_scope_sections(populated_store, tmp_path):
    fake_reuse = {"mireot_terms": [], "imports": []}
    with patch("ontoexplorer.modules.consistency.detector._load_reuse_payload",
               return_value=fake_reuse), \
         patch("ontoexplorer.modules.consistency.detector.run_konclude_consistency",
               return_value=KoncludeResult(consistent=True)), \
         patch("ontoexplorer.modules.consistency.detector.explain_unsatisfiability",
               return_value=[]):
        report = detect_consistency(
            version_id="v1",
            ontology_id="o1",
            host_iri="http://example.org/host",
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            work_dir=tmp_path,
        )
    assert isinstance(report, ConsistencyReport)
    assert set(report.scopes.keys()) == {
        "host_only", "host_plus_imports", "host_plus_imports_plus_mireot"
    }
    for scope in report.scopes.values():
        assert isinstance(scope, ScopeResult)
        assert scope.status == "consistent"


def test_inconsistent_konclude_result_propagates_to_scope(populated_store, tmp_path):
    fake_reuse = {"mireot_terms": [], "imports": []}
    bad_result = KoncludeResult(
        consistent=False,
        unsatisfiable_class_iris=["http://example.org/bad#X"],
    )
    with patch("ontoexplorer.modules.consistency.detector._load_reuse_payload",
               return_value=fake_reuse), \
         patch("ontoexplorer.modules.consistency.detector.run_konclude_consistency",
               return_value=bad_result), \
         patch("ontoexplorer.modules.consistency.detector.explain_unsatisfiability",
               return_value=[]):
        report = detect_consistency(
            version_id="v1",
            ontology_id="o1",
            host_iri="http://example.org/host",
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            work_dir=tmp_path,
        )
    assert report.scopes["host_only"].status == "inconsistent"
    assert len(report.scopes["host_only"].unsatisfiable_classes) == 1
    assert report.scopes["host_only"].unsatisfiable_classes[0].iri == "http://example.org/bad#X"


def test_explain_called_only_for_first_10_unsat(populated_store, tmp_path):
    iris = [f"http://example.org/bad#{i}" for i in range(15)]
    bad_result = KoncludeResult(consistent=False, unsatisfiable_class_iris=iris)
    call_count = [0]
    def fake_explain(*_args, **_kwargs):
        call_count[0] += 1
        return []
    with patch("ontoexplorer.modules.consistency.detector._load_reuse_payload",
               return_value={"mireot_terms": [], "imports": []}), \
         patch("ontoexplorer.modules.consistency.detector.run_konclude_consistency",
               return_value=bad_result), \
         patch("ontoexplorer.modules.consistency.detector.explain_unsatisfiability",
               side_effect=fake_explain):
        report = detect_consistency(
            version_id="v1", ontology_id="o1",
            host_iri="http://example.org/host",
            host_graph_iri=HOST_GRAPH,
            import_graph_iris=[],
            work_dir=tmp_path,
        )
    # 10 unsat per scope x 3 scopes = 30 explain calls
    assert call_count[0] == 30
    # First 10 should have justification slots; the rest stored without justifications
    host_only = report.scopes["host_only"]
    assert len(host_only.unsatisfiable_classes) == 15
```

- [ ] **Step 2: Run test to verify it fails**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/test_detector.py -v
```
Expected: ImportError on detector imports.

- [ ] **Step 3: Implement**

`ontoexplorer/modules/consistency/detector.py`:
```python
"""Consistency aggregator: runs all three scopes and assembles a ConsistencyReport."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ontoexplorer.modules.consistency.konclude import (
    KoncludeResult,
    KoncludeTimeout,
    KoncludeUnavailable,
    run_konclude_consistency,
)
from ontoexplorer.modules.consistency.merger import build_merge
from ontoexplorer.modules.consistency.mireot_source_resolver import fetch_mireot_sources
from ontoexplorer.modules.consistency.robot_explain import (
    RobotExplainUnavailable,
    explain_unsatisfiability,
)


_MAX_EXPLAINED_PER_SCOPE = 10
_SCOPES = ("host_only", "host_plus_imports", "host_plus_imports_plus_mireot")


@dataclass(frozen=True)
class JustificationAxiom:
    manchester: list                   # list[ManchesterToken] — typed via the library
    source_ontology_iri: str | None = None


@dataclass(frozen=True)
class UnsatisfiableClass:
    iri: str
    label: str | None = None
    justification: list[JustificationAxiom] = field(default_factory=list)


@dataclass
class ScopeResult:
    scope: str
    status: str  # consistent | inconsistent | partial | timeout | error
    unsatisfiable_classes: list[UnsatisfiableClass] = field(default_factory=list)
    mireot_sources_fetched: list[str] = field(default_factory=list)
    mireot_sources_skipped: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error_message: str | None = None


@dataclass
class ConsistencyReport:
    version_id: str
    host_iri: str
    scopes: dict[str, ScopeResult] = field(default_factory=dict)
    job_status: str = "done"
    started_at: str | None = None
    finished_at: str | None = None


def detect_consistency(
    *,
    version_id: str,
    ontology_id: str,
    host_iri: str,
    host_graph_iri: str,
    import_graph_iris: list[str],
    work_dir: Path,
) -> ConsistencyReport:
    """Run all three scopes; return the assembled report."""
    started_at = datetime.now(timezone.utc).isoformat()
    reuse_payload = _load_reuse_payload(version_id)

    # MIREOT sources fetched ONCE (shared between scopes that need them)
    mireot_result = fetch_mireot_sources(
        reuse_payload=reuse_payload,
        out_dir=work_dir / "mireot",
    )

    report = ConsistencyReport(version_id=version_id, host_iri=host_iri)
    for scope in _SCOPES:
        report.scopes[scope] = _run_one_scope(
            scope=scope,
            work_dir=work_dir,
            host_graph_iri=host_graph_iri,
            import_graph_iris=import_graph_iris,
            mireot_paths=list(mireot_result.fetched.values()),
            mireot_fetched_prefixes=list(mireot_result.fetched.keys()),
            mireot_skipped_prefixes=mireot_result.skipped,
        )

    report.finished_at = datetime.now(timezone.utc).isoformat()
    report.started_at = started_at
    return report


def _run_one_scope(
    *,
    scope: str,
    work_dir: Path,
    host_graph_iri: str,
    import_graph_iris: list[str],
    mireot_paths: list[Path],
    mireot_fetched_prefixes: list[str],
    mireot_skipped_prefixes: list[str],
) -> ScopeResult:
    t0 = time.monotonic()
    result = ScopeResult(scope=scope, status="error")
    try:
        merge_path = build_merge(
            out_dir=work_dir / scope,
            host_graph_iri=host_graph_iri,
            import_graph_iris=import_graph_iris,
            mireot_source_paths=mireot_paths,
            scope=scope,
        )
    except Exception as exc:
        result.status = "error"
        result.error_message = f"merge failed: {exc}"
        result.elapsed_seconds = time.monotonic() - t0
        return result

    try:
        konclude_result = run_konclude_consistency(merge_path)
    except KoncludeUnavailable as exc:
        result.status = "error"
        result.error_message = str(exc)
        result.elapsed_seconds = time.monotonic() - t0
        return result
    except KoncludeTimeout as exc:
        result.status = "timeout"
        result.error_message = str(exc)
        result.elapsed_seconds = time.monotonic() - t0
        return result

    if konclude_result.consistent and not konclude_result.unsatisfiable_class_iris:
        result.status = "consistent"
    else:
        result.status = "inconsistent"

    # Build UnsatisfiableClass entries; explain top N
    for i, iri in enumerate(konclude_result.unsatisfiable_class_iris):
        justification: list[JustificationAxiom] = []
        if i < _MAX_EXPLAINED_PER_SCOPE:
            try:
                axioms = explain_unsatisfiability(merge_path, class_iri=iri)
                justification = [JustificationAxiom(manchester=a) for a in axioms]
            except RobotExplainUnavailable:
                # ROBOT missing — no justifications, but the unsat result still recorded
                justification = []
            except Exception:
                justification = []
        result.unsatisfiable_classes.append(UnsatisfiableClass(
            iri=iri,
            justification=justification,
        ))

    # Annotate scope with MIREOT bookkeeping
    if scope == "host_plus_imports_plus_mireot":
        result.mireot_sources_fetched = mireot_fetched_prefixes
        result.mireot_sources_skipped = mireot_skipped_prefixes
        if result.status == "consistent" and mireot_skipped_prefixes:
            result.status = "partial"  # partial coverage of MIREOT sources

    result.elapsed_seconds = time.monotonic() - t0
    return result


def _load_reuse_payload(version_id: str) -> dict:
    """Load the Phase 1 reuse cache for this version."""
    from ontoexplorer.modules.reuse.cache import reuse_cache_key
    from ontoexplorer.modules.search.indexer import _get_redis

    raw = _get_redis().get(reuse_cache_key(version_id))
    if raw is None:
        return {"mireot_terms": [], "imports": []}
    return json.loads(raw)
```

Update `ontoexplorer/modules/consistency/__init__.py`:
```python
"""Joint-reasoning consistency analysis (Konclude + ROBOT explain)."""

from ontoexplorer.modules.consistency.cache import consistency_cache_key  # noqa: F401
from ontoexplorer.modules.consistency.detector import (  # noqa: F401
    ConsistencyReport,
    JustificationAxiom,
    ScopeResult,
    UnsatisfiableClass,
    detect_consistency,
)
```

- [ ] **Step 4: Run test to verify it passes**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/ -v
```
Expected: all tests pass (3 new + earlier tasks still green).

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/consistency/detector.py ontoexplorer/modules/consistency/__init__.py tests/unit/consistency/test_detector.py
git commit -m "feat(consistency): detector aggregator runs three scopes"
```

---

## Task 7: Celery task `check_consistency`

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`

Mirrors the existing `reason_ontology` ELK task: sync wrapper around `asyncio.run(_run())`, retry semantics, job-tracker integration, metrics.

- [ ] **Step 1: Add the task**

Append to `ontoexplorer/modules/jobs/tasks.py`:

```python
@celery_app.task(name="ontoexplorer.check_consistency", time_limit=3600, max_retries=1)
def check_consistency(version_id: str, ontology_id: str) -> dict:
    """Run all three consistency scopes for a version; cache the result in Redis.

    Mirrors the existing ELK `reason_ontology` async-task pattern. Long-running
    (up to 1h hard limit); retries once on failure.
    """
    import json as _json
    import tempfile
    import time as _time
    from dataclasses import asdict as _asdict
    from pathlib import Path

    from sqlalchemy import select

    from ontoexplorer.clients.oxigraph import graph_iri as _graph_iri
    from ontoexplorer.database import make_celery_db_session
    from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
    from ontoexplorer.modules.consistency.cache import consistency_cache_key
    from ontoexplorer.modules.consistency.detector import detect_consistency
    from ontoexplorer.modules.search.indexer import _SEARCH_TTL, _get_redis

    async def _gather() -> tuple[str, str, list[str]]:
        async with make_celery_db_session()() as db:
            ver = (await db.execute(
                select(OntologyVersion).where(OntologyVersion.id == version_id)
            )).scalar_one_or_none()
            if ver is None:
                return "", "", []
            ont = (await db.execute(
                select(Ontology).where(Ontology.id == ver.ontology_id)
            )).scalar_one_or_none()
            imp_rows = (await db.execute(
                select(OntologyImport).where(OntologyImport.version_id == version_id)
            )).scalars().all()
            import_iris = [
                _graph_iri(ver.ontology_id, version_id, inferred=False, import_iri=row.import_iri)
                if hasattr(_graph_iri, "__call__") and False
                else f"urn:ontoexplorer:import:{row.import_iri}"
                for row in imp_rows
            ]
            # NOTE: the import_iri-to-graph_iri mapping depends on how import_resolver
            # registers imported graphs. Inspect the existing convention and adapt.
            return (ont.iri if ont else ""), _graph_iri(ver.ontology_id, version_id), import_iris

    t0 = _time.monotonic()
    host_iri, host_graph_iri, import_graph_iris = asyncio.run(_gather())
    if not host_iri:
        log.warning("consistency_skipped_no_version", version_id=version_id)
        return {"status": "skipped", "version_id": version_id}

    with tempfile.TemporaryDirectory(prefix=f"consistency_{version_id}_") as tmp:
        report = detect_consistency(
            version_id=version_id,
            ontology_id=ontology_id,
            host_iri=host_iri,
            host_graph_iri=host_graph_iri,
            import_graph_iris=import_graph_iris,
            work_dir=Path(tmp),
        )

    r = _get_redis()
    r.setex(consistency_cache_key(version_id), _SEARCH_TTL, _json.dumps(_asdict(report)))
    elapsed = _time.monotonic() - t0
    log.info("consistency_done", version_id=version_id, elapsed_s=round(elapsed, 2),
             scopes={k: v["status"] for k, v in _asdict(report)["scopes"].items()})
    return {
        "status": "done",
        "version_id": version_id,
        "elapsed_seconds": elapsed,
        "scopes": {k: v.status for k, v in report.scopes.items()},
    }
```

Note: The exact `graph_iri(...)` call for imported graphs depends on OntoExplorer's existing import-graph naming convention. **Before this task is implemented, the implementer must check how `import_resolver` registers imported graphs into Oxigraph** — `grep -n "store.load\|named_node\|named_graph" ontoexplorer/modules/ingestion/import_resolver.py` — and replace the placeholder import-graph-IRI derivation above with the actual convention. The detector accepts a list of named-graph IRIs; the Celery task must produce the right ones.

- [ ] **Step 2: Inspect import_resolver to find the correct graph-IRI convention**

```
grep -n "store.load\|named_graph\|graph_iri\|NamedNode" ontoexplorer/modules/ingestion/import_resolver.py
grep -n "graph_iri" ontoexplorer/clients/oxigraph.py
```

Update the `import_iris = [...]` block in `check_consistency` to use the correct call. Most likely it's `graph_iri(ontology_id, version_id, import_iri=row.import_iri)` or similar — adapt to the actual signature.

- [ ] **Step 3: Verify Celery can import the task**

```
/path/to/ontoexplorer/.venv/bin/python -c "from ontoexplorer.modules.jobs.tasks import celery_app, check_consistency; print(check_consistency.name)"
```
Expected: `ontoexplorer.check_consistency`.

Run the existing test suite to confirm nothing broke:
```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/ -v
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py
git commit -m "feat(consistency): celery check_consistency task (async post-index)"
```

---

## Task 8: Indexer hook — enqueue check_consistency

**Files:**
- Modify: `ontoexplorer/modules/search/indexer.py`

Enqueue the Celery task after the existing `_populate_reuse_cache(...)` call. Write a `pending` placeholder to the consistency cache so the API doesn't 404 in the window between index-complete and Celery-pickup.

- [ ] **Step 1: Add the enqueue + placeholder**

Find the existing call sequence in `build_index`:
```python
_populate_owl_profile_cache(version_id, ontology_id, r)
_populate_reuse_cache(version_id, ontology_id, entities, r)
```

Add directly after:
```python
_enqueue_consistency_check(version_id, ontology_id, r)
```

Add the helper function near the other populators (around line 800):
```python
def _enqueue_consistency_check(
    version_id: str,
    ontology_id: str,
    r: "redis.Redis",
) -> None:
    """Enqueue the async consistency check and write a pending placeholder to Redis."""
    import json as _json

    from ontoexplorer.modules.consistency.cache import consistency_cache_key

    # Placeholder so the API returns pending instead of 404 while Celery picks up
    placeholder = {
        "version_id": version_id,
        "host_iri": "",
        "scopes": {},
        "job_status": "pending",
        "started_at": None,
        "finished_at": None,
    }
    r.setex(consistency_cache_key(version_id), _SEARCH_TTL, _json.dumps(placeholder))

    # Enqueue Celery task (don't await — runs async)
    try:
        from ontoexplorer.modules.jobs.tasks import check_consistency
        check_consistency.delay(version_id, ontology_id)
    except Exception as exc:
        # Don't fail indexing if the broker is unreachable; the user can retry later via
        # POST /api/v1/ontologies/{id}/{vid}/consistency/refresh
        import structlog
        structlog.get_logger(__name__).warning(
            "consistency_enqueue_failed", version_id=version_id, error=str(exc)
        )
```

- [ ] **Step 2: Add cache invalidation**

In `invalidate_index`, after the existing `to_delete.append(reuse_cache_key(version_id))` line:
```python
    from ontoexplorer.modules.consistency.cache import consistency_cache_key
    to_delete.append(consistency_cache_key(version_id))
```

- [ ] **Step 3: Verify the module still loads**

```
/path/to/ontoexplorer/.venv/bin/python -c "from ontoexplorer.modules.search.indexer import build_index, _enqueue_consistency_check, invalidate_index; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/modules/search/indexer.py
git commit -m "feat(consistency): indexer enqueues async check_consistency post-index"
```

---

## Task 9: API routes + filter + integration test

**Files:**
- Create: `ontoexplorer/api/consistency.py`
- Modify: `ontoexplorer/main.py` (mount router before `ontologies_router`)
- Modify: `ontoexplorer/api/ontologies.py` (add `?consistency=` filter)
- Create: `tests/integration/test_consistency_api.py`

- [ ] **Step 1: Write the integration test**

`tests/integration/test_consistency_api.py`:
```python
"""Integration tests for the consistency-analysis endpoints."""
import json
from unittest.mock import patch

import fakeredis
import pytest

from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.consistency.cache import consistency_cache_key


def _report_payload(version_id: str, *, status: str = "done", host_only="consistent",
                    host_plus_imports="consistent",
                    host_plus_imports_plus_mireot="consistent") -> dict:
    def _scope(name, st):
        return {
            "scope": name,
            "status": st,
            "unsatisfiable_classes": [],
            "mireot_sources_fetched": [],
            "mireot_sources_skipped": [],
            "elapsed_seconds": 1.23,
            "error_message": None,
        }
    return {
        "version_id": version_id,
        "host_iri": "http://example.org/host",
        "scopes": {
            "host_only": _scope("host_only", host_only),
            "host_plus_imports": _scope("host_plus_imports", host_plus_imports),
            "host_plus_imports_plus_mireot": _scope(
                "host_plus_imports_plus_mireot", host_plus_imports_plus_mireot
            ),
        },
        "job_status": status,
        "started_at": "2026-05-21T00:00:00+00:00",
        "finished_at": "2026-05-21T00:00:01+00:00",
    }


@pytest.mark.anyio
async def test_get_consistency_404_when_not_cached(client, db_session):
    ont = Ontology(iri="http://example.org/c1.owl", shortname="c1", title="Cons Test 1")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id, minio_key="c1.ttl", sha256="c1_001",
        format="turtle", status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.api.consistency._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/consistency")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_consistency_returns_pending_placeholder(client, db_session):
    ont = Ontology(iri="http://example.org/c2.owl", shortname="c2", title="Cons Test 2")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id, minio_key="c2.ttl", sha256="c2_001",
        format="turtle", status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    pending = _report_payload(str(ver.id), status="pending",
                              host_only="", host_plus_imports="",
                              host_plus_imports_plus_mireot="")
    # The placeholder has empty scopes dict in the indexer hook; replicate that
    pending["scopes"] = {}
    r.set(consistency_cache_key(str(ver.id)), json.dumps(pending))

    with patch("ontoexplorer.api.consistency._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/consistency")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_status"] == "pending"


@pytest.mark.anyio
async def test_get_consistency_returns_full_report(client, db_session):
    ont = Ontology(iri="http://example.org/c3.owl", shortname="c3", title="Cons Test 3")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id, minio_key="c3.ttl", sha256="c3_001",
        format="turtle", status="ready",
    )
    db_session.add(ver)
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(consistency_cache_key(str(ver.id)),
          json.dumps(_report_payload(str(ver.id))))

    with patch("ontoexplorer.api.consistency._get_redis", return_value=r):
        resp = await client.get(f"/api/v1/ontologies/{ont.id}/{ver.id}/consistency")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_status"] == "done"
    assert body["scopes"]["host_only"]["status"] == "consistent"


@pytest.mark.anyio
async def test_consistency_fleet_aggregates(client, db_session):
    ont_a = Ontology(iri="http://example.org/fc-a.owl", shortname="fca", title="Fleet C A")
    ont_b = Ontology(iri="http://example.org/fc-b.owl", shortname="fcb", title="Fleet C B")
    db_session.add_all([ont_a, ont_b])
    await db_session.flush()
    ver_a = OntologyVersion(ontology_id=ont_a.id, minio_key="fca.ttl",
                            sha256="fca001", format="turtle", status="ready")
    ver_b = OntologyVersion(ontology_id=ont_b.id, minio_key="fcb.ttl",
                            sha256="fcb001", format="turtle", status="ready")
    db_session.add_all([ver_a, ver_b])
    await db_session.commit()

    r = fakeredis.FakeRedis(decode_responses=True)
    r.set(consistency_cache_key(str(ver_a.id)),
          json.dumps(_report_payload(str(ver_a.id))))
    r.set(consistency_cache_key(str(ver_b.id)),
          json.dumps(_report_payload(str(ver_b.id),
                                     host_plus_imports="inconsistent")))

    with patch("ontoexplorer.api.consistency._get_redis", return_value=r):
        resp = await client.get("/api/v1/consistency/fleet")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["fleet_size"] == 2
    assert body["totals"]["inconsistent_any_scope"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/integration/test_consistency_api.py -v
```
Expected: 4 failures (router doesn't exist yet).

- [ ] **Step 3: Implement the router**

`ontoexplorer/api/consistency.py`:
```python
"""Consistency-analysis endpoints — read-only views over the Redis consistency cache."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.consistency.cache import consistency_cache_key
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["consistency"])


@router.get(
    "/ontologies/{ontology_id}/{version_id}/consistency",
    summary="Per-version consistency report",
)
async def get_version_consistency(ontology_id: str, version_id: str):
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, consistency_cache_key(version_id))
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="Consistency report not computed — reindex pending",
        )
    return json.loads(raw)


@router.post(
    "/ontologies/{ontology_id}/{version_id}/consistency/refresh",
    summary="Re-enqueue consistency check (admin/owner only)",
)
async def refresh_consistency(ontology_id: str, version_id: str):
    """Re-run the Celery check_consistency task without re-indexing."""
    from ontoexplorer.modules.jobs.tasks import check_consistency
    check_consistency.delay(version_id, ontology_id)
    return {"status": "enqueued", "version_id": version_id}


@router.get("/consistency/fleet", summary="Fleet consistency rollup (no auth)")
async def get_fleet_consistency(db: AsyncSession = Depends(get_db)):
    """Aggregate per-ontology consistency reports across the fleet."""
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
    keys = [consistency_cache_key(str(row.id)) for row in rows]
    payloads = await asyncio.to_thread(r.mget, keys) if keys else []

    ontologies: list[dict] = []
    totals = {
        "fleet_size": 0,
        "pending_or_running": 0,
        "consistent_all_scopes": 0,
        "inconsistent_any_scope": 0,
    }

    for row, raw in zip(rows, payloads):
        if not raw:
            continue
        data = json.loads(raw)
        totals["fleet_size"] += 1
        if data.get("job_status") in ("pending", "running"):
            totals["pending_or_running"] += 1
            entry = {
                "id": row.ontology_id,
                "shortname": row.shortname,
                "title": row.title,
                "version_id": str(row.id),
                "job_status": data.get("job_status"),
                "host_only": None,
                "host_plus_imports": None,
                "host_plus_imports_plus_mireot": None,
            }
            ontologies.append(entry)
            continue

        scopes = data.get("scopes", {})
        host_only = scopes.get("host_only", {}).get("status")
        host_plus_imports = scopes.get("host_plus_imports", {}).get("status")
        host_plus_imports_plus_mireot = scopes.get(
            "host_plus_imports_plus_mireot", {}
        ).get("status")

        all_consistent = (
            host_only == "consistent"
            and host_plus_imports == "consistent"
            and host_plus_imports_plus_mireot in ("consistent", "partial")
        )
        any_inconsistent = "inconsistent" in {
            host_only, host_plus_imports, host_plus_imports_plus_mireot
        }
        if all_consistent:
            totals["consistent_all_scopes"] += 1
        if any_inconsistent:
            totals["inconsistent_any_scope"] += 1

        ontologies.append({
            "id": row.ontology_id,
            "shortname": row.shortname,
            "title": row.title,
            "version_id": str(row.id),
            "job_status": data.get("job_status"),
            "host_only": host_only,
            "host_plus_imports": host_plus_imports,
            "host_plus_imports_plus_mireot": host_plus_imports_plus_mireot,
            "total_unsat": sum(
                len(scopes.get(s, {}).get("unsatisfiable_classes", []))
                for s in ("host_only", "host_plus_imports", "host_plus_imports_plus_mireot")
            ),
        })

    return {"ontologies": ontologies, "totals": totals}


async def filter_ontology_ids_by_consistency(
    db: AsyncSession,
    ontology_ids: list[str],
    value: str,
) -> set[str]:
    """Subset of ontology_ids whose latest ready version matches the consistency filter.

    Supported values: 'inconsistent' (inconsistent in any scope), 'consistent' (consistent
    in all three scopes, allowing 'partial' on the MIREOT scope).
    """
    if not ontology_ids or value not in ("inconsistent", "consistent"):
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
    keys = [consistency_cache_key(str(vr.id)) for vr in version_rows]
    raws = await asyncio.to_thread(r.mget, keys)

    matching: set[str] = set()
    for vr, raw in zip(version_rows, raws):
        if not raw:
            continue
        data = json.loads(raw)
        if data.get("job_status") != "done":
            continue
        scopes = data.get("scopes", {})
        statuses = {scopes.get(s, {}).get("status")
                    for s in ("host_only", "host_plus_imports", "host_plus_imports_plus_mireot")}
        if value == "inconsistent" and "inconsistent" in statuses:
            matching.add(vr.ontology_id)
        elif value == "consistent":
            ok_set = {"consistent", "partial"}
            if statuses <= ok_set:
                matching.add(vr.ontology_id)
    return matching
```

- [ ] **Step 4: Mount router + extend ontologies filter**

In `ontoexplorer/main.py`, after `from ontoexplorer.api.reuse import router as reuse_router`:
```python
from ontoexplorer.api.consistency import router as consistency_router
```

After `app.include_router(reuse_router)`:
```python
    app.include_router(consistency_router)
```

In `ontoexplorer/api/ontologies.py::list_ontologies`, add a new query param near `reuses`:
```python
    consistency: str | None = Query(None, description="Filter: consistent | inconsistent"),
```

Update the early-return guard:
```python
    if not q and not profile and not reuses and not consistency:
        stmt = stmt.offset(offset).limit(limit)
```

After the existing `if reuses:` block, add:
```python
    if consistency:
        from ontoexplorer.api.consistency import filter_ontology_ids_by_consistency
        all_ids = [r["id"] for r in rows]
        matching_ids = await filter_ontology_ids_by_consistency(db, all_ids, consistency.lower())
        rows = [r for r in rows if r["id"] in matching_ids]
```

Update the pagination guard at the end of the q-filter block:
```python
    elif profile or reuses or consistency:
        rows = rows[offset: offset + limit]
```

- [ ] **Step 5: Run integration tests**

```
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/integration/test_consistency_api.py tests/integration/test_reuse_api.py tests/integration/test_ontologies.py -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add ontoexplorer/api/consistency.py ontoexplorer/main.py ontoexplorer/api/ontologies.py tests/integration/test_consistency_api.py
git commit -m "feat(consistency): API routes + ?consistency= filter + integration tests"
```

---

## Task 10: Frontend per-ontology ConsistencySection

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/ConsistencySection.tsx`
- Modify: `frontend/src/pages/OntologyPage.tsx`

- [ ] **Step 1: Add types and fetchers to api.ts**

Find the Phase 1 reuse types near the bottom of `api.ts`. Add nearby:

```typescript
export type JustificationAxiom = {
  manchester: ManchesterToken[]
  source_ontology_iri: string | null
}

export type UnsatisfiableClass = {
  iri: string
  label: string | null
  justification: JustificationAxiom[]
}

export type ConsistencyScopeName =
  | 'host_only'
  | 'host_plus_imports'
  | 'host_plus_imports_plus_mireot'

export type ConsistencyScopeStatus =
  | 'consistent' | 'inconsistent' | 'partial' | 'timeout' | 'error'

export type ScopeResult = {
  scope: ConsistencyScopeName
  status: ConsistencyScopeStatus
  unsatisfiable_classes: UnsatisfiableClass[]
  mireot_sources_fetched: string[]
  mireot_sources_skipped: string[]
  elapsed_seconds: number
  error_message: string | null
}

export type ConsistencyReport = {
  version_id: string
  host_iri: string
  scopes: Partial<Record<ConsistencyScopeName, ScopeResult>>
  job_status: 'pending' | 'running' | 'done' | 'failed'
  started_at: string | null
  finished_at: string | null
}

export type ConsistencyFleetEntry = {
  id: string
  shortname: string
  title: string
  version_id: string
  job_status: string
  host_only: ConsistencyScopeStatus | null
  host_plus_imports: ConsistencyScopeStatus | null
  host_plus_imports_plus_mireot: ConsistencyScopeStatus | null
  total_unsat?: number
}

export type ConsistencyFleet = {
  ontologies: ConsistencyFleetEntry[]
  totals: {
    fleet_size: number
    pending_or_running: number
    consistent_all_scopes: number
    inconsistent_any_scope: number
  }
}
```

Add fetchers to the `api` object — inside `api.ontologies`:
```typescript
    consistency: (ontologyId: string, versionId: string) =>
      request<ConsistencyReport>(`/ontologies/${ontologyId}/${versionId}/consistency`),
    refreshConsistency: (ontologyId: string, versionId: string) =>
      request<{ status: string; version_id: string }>(
        `/ontologies/${ontologyId}/${versionId}/consistency/refresh`,
        { method: 'POST' },
      ),
```

And at the top level:
```typescript
  consistency: {
    fleet: () => request<ConsistencyFleet>('/consistency/fleet'),
  },
```

- [ ] **Step 2: Create the component**

`frontend/src/components/ConsistencySection.tsx`:
```typescript
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ConsistencyReport, ConsistencyScopeName, ScopeResult } from '../lib/api'


const SCOPE_LABELS: Record<ConsistencyScopeName, string> = {
  host_only: 'Host only',
  host_plus_imports: 'Host + imports',
  host_plus_imports_plus_mireot: 'Host + imports + MIREOT sources',
}

const STATUS_COLOR: Record<string, string> = {
  consistent: '#3fb950',
  inconsistent: '#e06c75',
  partial: '#e5c07b',
  timeout: '#c678dd',
  error: '#e06c75',
}

function StatusBadge({ status }: { status: string }) {
  const symbol =
    status === 'consistent' ? '✓' :
    status === 'inconsistent' ? '✗' :
    status === 'partial' ? '⚠' :
    status === 'timeout' ? '⏱' : '!'
  return (
    <span style={{ color: STATUS_COLOR[status] ?? 'var(--text)', fontWeight: 700 }}>
      {symbol} {status}
    </span>
  )
}

function ScopeCard({ scope, result }: { scope: ConsistencyScopeName; result: ScopeResult }) {
  const [expanded, setExpanded] = useState(false)
  const top10 = result.unsatisfiable_classes.slice(0, 10)
  return (
    <div data-testid={`consistency-card-${scope}`} style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '0.75rem',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ fontSize: 'var(--font-size-sm)' }}>{SCOPE_LABELS[scope]}</strong>
        <StatusBadge status={result.status} />
      </div>
      <p style={{ fontSize: 10, color: 'var(--text-dim)', margin: '4px 0 0' }}>
        {result.unsatisfiable_classes.length} unsat
        {result.mireot_sources_skipped.length > 0 && (
          <> · {result.mireot_sources_skipped.length} MIREOT sources skipped</>
        )}
        {result.error_message && <> · {result.error_message}</>}
      </p>
      {top10.length > 0 && (
        <button onClick={() => setExpanded(!expanded)} style={{
          background: 'none', border: 'none', color: 'var(--accent-blue)',
          cursor: 'pointer', padding: '4px 0', fontSize: 11,
        }}>
          {expanded ? '▲ Hide' : '▼ Show'} justifications
        </button>
      )}
      {expanded && (
        <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: 11 }}>
          {top10.map(uc => (
            <li key={uc.iri} style={{ marginBottom: 6 }}>
              <code style={{ color: 'var(--accent-blue)' }}>{uc.label || uc.iri}</code>
              {uc.justification.length > 0 && (
                <ul style={{ margin: '2px 0 0', paddingLeft: '1rem' }}>
                  {uc.justification.map((ax, i) => (
                    <li key={i} style={{ fontFamily: 'monospace', fontSize: 10 }}>
                      {ax.manchester.map((tok, j) =>
                        tok.t === 'iri'
                          ? <span key={j} style={{ color: 'var(--accent-blue)' }}>
                              {tok.label ?? tok.iri}
                            </span>
                          : <span key={j}>{tok.v}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}


export function ConsistencySection({
  ontologyId,
  versionId,
}: {
  ontologyId: string
  versionId: string
}) {
  const { data, isLoading, error } = useQuery<ConsistencyReport>({
    queryKey: ['consistency', ontologyId, versionId],
    queryFn: () => api.ontologies.consistency(ontologyId, versionId),
    retry: false,
    // Poll while pending/running
    refetchInterval: (q) => {
      const s = (q.state.data as ConsistencyReport | undefined)?.job_status
      return s === 'pending' || s === 'running' ? 5000 : false
    },
  })

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading consistency…</div>
  if (error) return <div style={{ color: 'var(--text-dim)' }}>No consistency report yet (reindex pending)</div>
  if (!data) return null

  if (data.job_status === 'pending' || data.job_status === 'running') {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>
        <p>⏳ Consistency analysis running…</p>
        <p style={{ fontSize: 11 }}>
          Three reasoning scopes (host-only, host+imports, host+imports+MIREOT sources).
          This can take a few minutes for large ontologies. The page updates automatically.
        </p>
      </div>
    )
  }

  if (data.job_status === 'failed') {
    return <div style={{ padding: '1rem', color: '#e06c75' }}>
      ✗ Analysis failed. Click refresh in admin to re-enqueue.
    </div>
  }

  return (
    <div style={{ display: 'grid', gap: '0.5rem', padding: '0.75rem' }}>
      {(['host_only', 'host_plus_imports', 'host_plus_imports_plus_mireot'] as const).map(s => {
        const sr = data.scopes[s]
        if (!sr) return null
        return <ScopeCard key={s} scope={s} result={sr} />
      })}
    </div>
  )
}
```

- [ ] **Step 3: Wire into OntologyPage as a new tab**

Edit `frontend/src/pages/OntologyPage.tsx`:

Add import near line 17:
```typescript
import { ConsistencySection } from '../components/ConsistencySection'
```

Extend `detailTab` union (around line 882):
```typescript
const [detailTab, setDetailTab] = useState<'info' | 'profile' | 'history' | 'coverage' | 'owl-profile' | 'reuse' | 'consistency'>('info')
```

Add hash-routing branch (around line 884):
```typescript
} else if (location.hash === '#consistency') {
  setDetailTab('consistency')
```

Extend tab list (around line 1203):
```typescript
{(['info', 'profile', 'history', 'coverage', 'owl-profile', 'reuse', 'consistency'] as const).map(tab => (
```

Extend label override:
```typescript
{tab === 'owl-profile' ? 'OWL Profile' : tab === 'reuse' ? 'Reuse' : tab === 'consistency' ? 'Consistency' : tab}
```

Add dispatcher branch (between `'reuse'` and the fall-through `: (...)`):
```typescript
) : detailTab === 'consistency' ? (
  oid && activeVid
    ? <ConsistencySection ontologyId={oid} versionId={activeVid} />
    : <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
        No version available.
      </div>
```

- [ ] **Step 4: Build and verify**

```
cd /path/to/ontoexplorer/frontend && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E '(Consistency|api.ts)' | head -10
```
Expected: no errors in the changed files.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/components/ConsistencySection.tsx frontend/src/pages/OntologyPage.tsx
git commit -m "feat(consistency): per-ontology ConsistencySection (3 scope cards + polling)"
```

---

## Task 11: Frontend fleet Consistency tab

**Files:**
- Create: `frontend/src/pages/Consistency.tsx`
- Modify: `frontend/src/pages/Ontologies.tsx`

- [ ] **Step 1: Create the page**

`frontend/src/pages/Consistency.tsx`:
```typescript
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, ConsistencyFleet, ConsistencyFleetEntry, ConsistencyScopeStatus } from '../lib/api'


type SortKey = 'name' | 'host_only' | 'host_plus_imports' | 'host_plus_imports_plus_mireot' | 'total_unsat'


function rank(status: ConsistencyScopeStatus | null | undefined): number {
  switch (status) {
    case 'consistent':   return 0
    case 'partial':      return 1
    case 'timeout':      return 2
    case 'error':        return 3
    case 'inconsistent': return 4
    default:             return -1
  }
}

function StatusCell({ status }: { status: ConsistencyScopeStatus | null }) {
  if (!status) return <span style={{ color: 'var(--text-dim)' }}>—</span>
  const color =
    status === 'consistent' ? '#3fb950' :
    status === 'inconsistent' ? '#e06c75' :
    status === 'partial' ? '#e5c07b' :
    status === 'timeout' ? '#c678dd' : '#e06c75'
  const symbol =
    status === 'consistent' ? '✓' :
    status === 'inconsistent' ? '✗' :
    status === 'partial' ? '⚠' :
    status === 'timeout' ? '⏱' : '!'
  return <span style={{ color, fontWeight: 700 }}>{symbol}</span>
}

function Th({
  children, onClick, active, dir,
}: {
  children: React.ReactNode
  onClick: () => void
  active: boolean
  dir: 'asc' | 'desc'
}) {
  return (
    <th style={{ padding: '4px 8px', textAlign: 'left' }}>
      <button onClick={onClick} style={{
        background: 'none', border: 'none',
        color: active ? 'var(--text)' : 'var(--text-dim)',
        fontSize: 10, textTransform: 'uppercase', fontWeight: 500,
        cursor: 'pointer', padding: 0,
      }}>
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
                  margin: '4px 0 0' }}>{value.toLocaleString()}</p>
    </div>
  )
}


export function Consistency() {
  const { data, isLoading, error } = useQuery<ConsistencyFleet>({
    queryKey: ['consistency-fleet'],
    queryFn: () => api.consistency.fleet(),
    refetchInterval: 10000,  // auto-refresh while jobs are pending
  })
  const [sortKey, setSortKey] = useState<SortKey>('total_unsat')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  function click(k: SortKey) {
    if (k === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(k); setSortDir('desc') }
  }

  const sorted = useMemo(() => {
    if (!data) return []
    const arr = [...data.ontologies]
    arr.sort((a, b) => {
      let va: string | number
      let vb: string | number
      if (sortKey === 'name') {
        va = (a.shortname || a.id).toLowerCase()
        vb = (b.shortname || b.id).toLowerCase()
      } else if (sortKey === 'total_unsat') {
        va = a.total_unsat ?? 0
        vb = b.total_unsat ?? 0
      } else {
        va = rank(a[sortKey] as ConsistencyScopeStatus | null)
        vb = rank(b[sortKey] as ConsistencyScopeStatus | null)
      }
      if (va < vb) return sortDir === 'asc' ? -1 : 1
      if (va > vb) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return arr
  }, [data, sortKey, sortDir])

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div>Failed to load fleet consistency data.</div>

  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <div style={{ display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                    gap: '0.5rem' }}>
        <SummaryCard label="Ontologies" value={data.totals.fleet_size} testId="consistency-fleet-size" />
        <SummaryCard label="Consistent (all scopes)" value={data.totals.consistent_all_scopes} testId="consistency-all-ok" />
        <SummaryCard label="Inconsistent (any scope)" value={data.totals.inconsistent_any_scope} testId="consistency-inconsistent" />
        <SummaryCard label="Pending / Running" value={data.totals.pending_or_running} testId="consistency-pending" />
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            <Th onClick={() => click('name')} active={sortKey === 'name'} dir={sortDir}>Ontology</Th>
            <Th onClick={() => click('host_only')} active={sortKey === 'host_only'} dir={sortDir}>Host</Th>
            <Th onClick={() => click('host_plus_imports')} active={sortKey === 'host_plus_imports'} dir={sortDir}>Host + imports</Th>
            <Th onClick={() => click('host_plus_imports_plus_mireot')} active={sortKey === 'host_plus_imports_plus_mireot'} dir={sortDir}>+ MIREOT sources</Th>
            <Th onClick={() => click('total_unsat')} active={sortKey === 'total_unsat'} dir={sortDir}>Total unsat</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(e => (
            <tr key={e.id} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '4px 8px' }}>
                <Link to={`/ontologies/${e.shortname || e.id}#consistency`}
                      style={{ color: 'var(--accent-blue)' }}>
                  {e.shortname || e.id}
                </Link>
              </td>
              <td style={{ padding: '4px 8px' }}><StatusCell status={e.host_only} /></td>
              <td style={{ padding: '4px 8px' }}><StatusCell status={e.host_plus_imports} /></td>
              <td style={{ padding: '4px 8px' }}><StatusCell status={e.host_plus_imports_plus_mireot} /></td>
              <td style={{ padding: '4px 8px' }}>{e.total_unsat ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 2: Register the tab in Ontologies.tsx**

Extend `Tab` type (line ~12):
```typescript
type Tab = 'list' | 'coverage' | 'profiles' | 'compare' | 'reuse' | 'consistency'
```

Extend `TAB_VALUES`:
```typescript
const TAB_VALUES: Tab[] = ['list', 'coverage', 'profiles', 'compare', 'reuse', 'consistency']
```

Add to `TAB_LABELS`:
```typescript
  consistency: 'Consistency',
```

Add import:
```typescript
import { Consistency } from './Consistency'
```

Add dispatch (after `{tab === 'reuse' && <Reuse />}`):
```typescript
{tab === 'consistency' && <Consistency />}
```

- [ ] **Step 3: Build**

```
cd /path/to/ontoexplorer/frontend && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E '(Consistency|Ontologies)' | head -10
```
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Consistency.tsx frontend/src/pages/Ontologies.tsx
git commit -m "feat(consistency): fleet Consistency tab under /ontologies?tab=consistency"
```

---

## Task 12: HermiT cross-check bench script

**Files:**
- Create: `scripts/consistency_bench/README.md`
- Create: `scripts/consistency_bench/run.py`
- Create: `scripts/consistency_bench/compare.py`
- Create: `scripts/consistency_bench/publish.py`
- Create: `scripts/consistency_bench/__init__.py`

This is a standalone publication-comparability tool — runs ROBOT/HermiT consistency across the fleet, then compares Konclude's verdicts (from the production cache) against HermiT's. No new runtime dependencies; same shell-out pattern as `scripts/owl_profile_bench/benchmark.py`.

- [ ] **Step 1: README**

`scripts/consistency_bench/README.md`:
```markdown
# Consistency Bench (Konclude vs HermiT/ROBOT)

Standalone tool to validate Konclude's per-scope consistency verdicts against ROBOT/HermiT (the OBO Foundry community standard) across the OntoExplorer fleet. Produces verdict-agreement numbers comparable to Matentzoglu 2020.

## Inputs

- OntoExplorer's production consistency cache (Redis) for Konclude verdicts
- ROBOT 1.9.10 on PATH (already in the runtime container; uses `--reasoner hermit`)

## Usage

```
# Run HermiT on every fleet version, write per-version verdicts to a CSV
python -m scripts.consistency_bench.run --output-dir /tmp/cbench/

# Compare Konclude (production cache) vs HermiT (just produced)
python -m scripts.consistency_bench.compare \\
    --hermit-csv /tmp/cbench/hermit_verdicts.csv \\
    --output-dir /tmp/cbench/

# Publish summary CSV/JSON
python -m scripts.consistency_bench.publish --output-dir /tmp/cbench/
```

## Caveat

ROBOT/HermiT reasons over `host + owl:imports closure` natively. It does NOT support the host+imports+MIREOT-sources scope without pre-merging — so the bench compares only the first two scopes (`host_only`, `host_plus_imports`). The MIREOT scope's verdict is Konclude-only; trust requires manual review for now.
```

- [ ] **Step 2: `__init__.py`**

Create empty `scripts/consistency_bench/__init__.py`.

- [ ] **Step 3: `run.py`**

`scripts/consistency_bench/run.py`:
```python
"""Run ROBOT/HermiT consistency across the OntoExplorer fleet.

For each (ontology, version), serialize host + imports closure to a single OWL/XML
file via OntoExplorer's existing merger, then invoke `robot reason --reasoner hermit`
and record consistent/inconsistent + any unsatisfiable class IRIs.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import subprocess
import tempfile
import time
from pathlib import Path

from sqlalchemy import select

from ontoexplorer.clients.oxigraph import graph_iri
from ontoexplorer.database import make_celery_db_session
from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
from ontoexplorer.modules.consistency.merger import build_merge


async def _enumerate_fleet() -> list[tuple[str, str, str, list[str]]]:
    """Return list of (ontology_id, version_id, host_iri, import_graph_iris) for latest-ready versions."""
    async with make_celery_db_session()() as db:
        # Latest ready version per ontology
        from sqlalchemy import func
        subq = (
            select(
                OntologyVersion.ontology_id,
                func.max(OntologyVersion.created_at).label("max_created"),
            )
            .where(OntologyVersion.status == "ready")
            .group_by(OntologyVersion.ontology_id)
            .subquery()
        )
        rows = (await db.execute(
            select(OntologyVersion.id, OntologyVersion.ontology_id, Ontology.iri)
            .join(subq, (OntologyVersion.ontology_id == subq.c.ontology_id)
                  & (OntologyVersion.created_at == subq.c.max_created))
            .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        )).all()
        out = []
        for vid, oid, host_iri in rows:
            imps = (await db.execute(
                select(OntologyImport.import_iri)
                .where(OntologyImport.version_id == vid)
            )).scalars().all()
            # Adapt this to the project's actual import-graph naming
            import_graphs = [f"urn:ontoexplorer:import:{imp}" for imp in imps]
            out.append((str(oid), str(vid), str(host_iri), import_graphs))
        return out


def run_hermit(merge_path: Path, robot_cmd: str = "robot") -> tuple[bool, list[str], float]:
    """Run `robot reason --reasoner hermit` and parse the verdict."""
    t0 = time.monotonic()
    proc = subprocess.run(
        [robot_cmd, "reason", "--input", str(merge_path),
         "--reasoner", "hermit",
         "--output", str(merge_path.with_suffix(".reasoned.owl"))],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    elapsed = time.monotonic() - t0
    out = (proc.stdout + proc.stderr).lower()
    consistent = "inconsistent" not in out and proc.returncode == 0
    unsat: list[str] = []
    # ROBOT prints unsatisfiable class IRIs to stderr in a known format; parse minimally
    for line in (proc.stdout + proc.stderr).splitlines():
        if "unsatisfiable" in line.lower() and "http://" in line:
            iri = line.split("http://", 1)[1].split()[0]
            unsat.append("http://" + iri.rstrip(",.;:"))
    return consistent, sorted(set(unsat)), elapsed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--robot-cmd", default="robot")
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = asyncio.run(_enumerate_fleet())
    out_csv = args.output_dir / "hermit_verdicts.csv"
    with out_csv.open("w") as f:
        w = csv.DictWriter(f, fieldnames=[
            "ontology_id", "version_id", "host_iri", "scope",
            "consistent", "unsatisfiable_count", "elapsed_seconds",
        ])
        w.writeheader()
        with tempfile.TemporaryDirectory(prefix="cbench_") as tmp:
            for oid, vid, host_iri, import_graphs in rows:
                for scope in ("host_only", "host_plus_imports"):
                    merge_path = build_merge(
                        out_dir=Path(tmp) / vid,
                        host_graph_iri=graph_iri(oid, vid),
                        import_graph_iris=import_graphs,
                        mireot_source_paths=[],
                        scope=scope,
                    )
                    try:
                        consistent, unsat, elapsed = run_hermit(merge_path, args.robot_cmd)
                    except Exception as exc:
                        print(f"FAIL {vid} {scope}: {exc}")
                        continue
                    w.writerow({
                        "ontology_id": oid, "version_id": vid,
                        "host_iri": host_iri, "scope": scope,
                        "consistent": "true" if consistent else "false",
                        "unsatisfiable_count": len(unsat),
                        "elapsed_seconds": round(elapsed, 2),
                    })
                    print(f"OK {vid} {scope}: consistent={consistent} unsat={len(unsat)} {elapsed:.1f}s")
    print(f"Wrote {out_csv}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: `compare.py`**

`scripts/consistency_bench/compare.py`:
```python
"""Diff Konclude (production cache) vs HermiT (bench output) verdicts."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from ontoexplorer.modules.consistency.cache import consistency_cache_key
from ontoexplorer.modules.search.indexer import _get_redis


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--hermit-csv", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    r = _get_redis()
    hermit_rows = list(csv.DictReader(args.hermit_csv.open()))

    out_rows = []
    agreement = {"host_only": 0, "host_plus_imports": 0}
    total = {"host_only": 0, "host_plus_imports": 0}

    for h in hermit_rows:
        vid = h["version_id"]
        scope = h["scope"]
        raw = r.get(consistency_cache_key(vid))
        if not raw:
            continue
        konclude_data = json.loads(raw)
        konclude_status = konclude_data.get("scopes", {}).get(scope, {}).get("status")
        konclude_consistent = konclude_status == "consistent"
        hermit_consistent = h["consistent"] == "true"
        agree = (konclude_consistent == hermit_consistent)
        agreement[scope] += int(agree)
        total[scope] += 1
        out_rows.append({
            "version_id": vid,
            "scope": scope,
            "konclude_status": konclude_status,
            "hermit_consistent": h["consistent"],
            "agree": "true" if agree else "false",
        })

    comp_csv = args.output_dir / "konclude_vs_hermit.csv"
    with comp_csv.open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else
                           ["version_id", "scope", "konclude_status", "hermit_consistent", "agree"])
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        scope: {
            "agreed": agreement[scope],
            "total": total[scope],
            "agreement_pct": round(100 * agreement[scope] / total[scope], 1) if total[scope] else 0,
        }
        for scope in ("host_only", "host_plus_imports")
    }
    (args.output_dir / "agreement_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: `publish.py`**

`scripts/consistency_bench/publish.py`:
```python
"""Bundle CSVs + summary into a v2/ subdirectory of the companion docs repo."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--companion-repo", type=Path, default=None)
    args = p.parse_args()

    if args.companion_repo is None:
        print(f"Outputs left in {args.output_dir}")
        return

    target = args.companion_repo / "docs" / "consistency_v2"
    target.mkdir(parents=True, exist_ok=True)
    for f in args.output_dir.iterdir():
        if f.is_file():
            shutil.copy(f, target / f.name)
    print(f"Copied {len(list(args.output_dir.iterdir()))} files to {target}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Smoke-test (skip if ROBOT not on PATH)**

```
which robot && /path/to/ontoexplorer/.venv/bin/python -c "from scripts.consistency_bench.run import _enumerate_fleet; print('importable')"
```
Expected: `importable` (full bench run is too slow for the implementer to execute; just verify the module loads).

- [ ] **Step 7: Commit**

```bash
git add scripts/consistency_bench/
git commit -m "feat(consistency): HermiT cross-check bench script"
```

---

## Task 13: Konclude binary in Docker image

**Files:**
- Modify: `Dockerfile` (or whichever runtime Dockerfile the project uses — check via `find . -maxdepth 3 -name "Dockerfile*"`)

Konclude is distributed as a static Linux x86_64 binary from <https://www.derivo.de/en/produkte/konclude/>. We pin to a specific release and verify by checksum.

- [ ] **Step 1: Find the runtime Dockerfile**

```
find /path/to/ontoexplorer -maxdepth 4 -name "Dockerfile*" -not -path "*/node_modules/*" -not -path "*/.venv/*"
```

Identify which Dockerfile builds the API + Celery worker image. Most projects use one (`Dockerfile` at the root) or a directory like `docker/runtime.Dockerfile`.

- [ ] **Step 2: Verify Konclude download URL and checksum**

Konclude releases are hosted at GitHub: <https://github.com/konclude/Konclude/releases>. Pick the latest stable Linux x86_64 release. Visit the release page in a browser, copy the download URL of the `Konclude-vX.Y.Z-x64-linux-gcc-static-qt-...tar.gz` asset, and compute its sha256:

```
KONCLUDE_VERSION=v0.7.0-1135
KONCLUDE_URL="https://github.com/konclude/Konclude/releases/download/${KONCLUDE_VERSION}/Konclude-${KONCLUDE_VERSION}-Linux-x64-GCC-static-qt-...tar.gz"
curl -fsSL "$KONCLUDE_URL" -o /tmp/konclude.tar.gz
sha256sum /tmp/konclude.tar.gz
```

Record the sha256 for the Dockerfile pin. **If the URL is no longer valid, browse the releases page and update — Konclude release naming may have shifted.**

- [ ] **Step 3: Add Konclude install layer to the Dockerfile**

In the runtime Dockerfile, before the `COPY . /app` step (so the Konclude layer is cached separately from the app code), add:

```dockerfile
# Konclude OWL 2 DL reasoner (used by Phase 2 consistency analysis)
ARG KONCLUDE_VERSION=v0.7.0-1135
ARG KONCLUDE_SHA256=<the-sha256-from-step-2>
RUN curl -fsSL "https://github.com/konclude/Konclude/releases/download/${KONCLUDE_VERSION}/Konclude-${KONCLUDE_VERSION}-Linux-x64-GCC-static-qt.tar.gz" \
        -o /tmp/konclude.tar.gz \
 && echo "${KONCLUDE_SHA256}  /tmp/konclude.tar.gz" | sha256sum -c - \
 && tar -xzf /tmp/konclude.tar.gz -C /tmp \
 && find /tmp -name "Konclude" -type f -executable -exec install -Dm755 {} /usr/local/bin/Konclude \; \
 && rm -rf /tmp/konclude.tar.gz /tmp/Konclude-*
```

Adapt the URL and tarball path to match the actual release asset structure.

- [ ] **Step 4: Verify the binary is callable from the image**

After rebuilding the image (`docker build -t ontoexplorer-test .` from the repo root):
```
docker run --rm ontoexplorer-test Konclude --help 2>&1 | head -5
```
Expected: Konclude usage banner.

- [ ] **Step 5: Run the consistency tests inside the image to confirm**

```
docker run --rm ontoexplorer-test /opt/venv/bin/python -m pytest tests/unit/consistency/ -v
```
(Adapt the venv path to the actual image layout.) Expected: all green, with the Konclude tests now actually running rather than skipping.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile  # or whichever path
git commit -m "build(consistency): bundle Konclude binary in runtime image"
```

---

## End-to-end verification

After all 13 tasks land:

```bash
# 1. Backend tests
/path/to/ontoexplorer/.venv/bin/python -m pytest tests/unit/consistency/ tests/integration/test_consistency_api.py -v

# 2. Reindex a known-consistent fleet ontology (e.g. RO)
#    via the admin UI or API. Wait ~30s for the Celery task.
curl -s http://localhost:8000/api/v1/ontologies/ro/<vid>/consistency | jq '.scopes | map_values(.status)'
# Expected: {"host_only": "consistent", "host_plus_imports": "consistent", "host_plus_imports_plus_mireot": "consistent"}

# 3. Reindex a fixture ontology that MIREOTs a class with a contradicting host constraint.
#    Confirm: host_only consistent; host_plus_imports consistent; host_plus_imports_plus_mireot INCONSISTENT.
#    Confirm the unsat list contains the contradicting class with non-empty justification.

# 4. Fleet rollup
curl -s http://localhost:8000/api/v1/consistency/fleet | jq '.totals'

# 5. Frontend
#    http://localhost:5173/ontologies?tab=consistency  — table sorts by total unsat desc
#    Click any ontology link → opens at the Consistency tab with the three scope cards
#    Click "Show justifications" on the inconsistent scope → expands Manchester-tokenized axioms

# 6. HermiT cross-check (one-shot)
python -m scripts.consistency_bench.run --output-dir /tmp/cbench/
python -m scripts.consistency_bench.compare --hermit-csv /tmp/cbench/hermit_verdicts.csv --output-dir /tmp/cbench/
cat /tmp/cbench/agreement_summary.json
# Target: 100% agreement on host_only and host_plus_imports (MIREOT scope is Konclude-only)
```

If any step fails, debug in the most recent task — do not skip ahead.
