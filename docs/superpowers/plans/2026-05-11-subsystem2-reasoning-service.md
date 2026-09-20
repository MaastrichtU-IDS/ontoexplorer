# Subsystem 2: OWL-EL Reasoning Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the ELK reasoning stub into a fully capable OWL-EL reasoning service with a Redis-backed classification cache, complete CR-rule coverage, superclass/subclass hierarchy queries, consistency checking, and async multi-justification computation.

**Architecture:** The ELK service (`docker/elk-service/`) is refactored into four focused modules (classifier, cache, justification, main) and gains a Redis connection. The main OntoExplorer API gains proxy endpoints for hierarchy queries and async justification jobs. A new `compute_justification` Celery task handles async justification work.

**Tech Stack:** Python 3.12, FastAPI, rdflib, redis-py, httpx, Celery, Postgres (SQLAlchemy async), pytest

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `docker/elk-service/classifier.py` | OWL-EL CR rules + proof trace recording |
| Create | `docker/elk-service/cache.py` | Redis read/write + key helpers |
| Create | `docker/elk-service/justification.py` | Justification backtracking + multiple minimal sets |
| Rewrite | `docker/elk-service/main.py` | FastAPI app wiring all three modules; all endpoints |
| Modify | `docker/elk-service/Dockerfile` | Add `redis>=5.0` dependency |
| Modify | `docker-compose.yml` | Add `REDIS_URL` + `JUSTIFICATION_TIME_LIMIT_SECONDS` to elk-service |
| Rewrite | `ontoexplorer/clients/reasoning.py` | Add `classify_v2()`, `superclasses()`, `subclasses()`, `consistency()`, `request_justification()` |
| Modify | `ontoexplorer/modules/jobs/tasks.py` | Add `compute_justification` Celery task |
| Modify | `ontoexplorer/api/ontologies.py` | Add superclasses, subclasses, consistency, justification proxy endpoints |
| Modify | `ontoexplorer/modules/webhooks/registry.py` | Add `justification.completed`, `justification.failed` to `VALID_EVENTS` |
| Modify | `tests/integration/test_reasoning.py` | Add CR3/CR4/CR5/CR6, proof-trace, multi-justification tests |
| Create | `tests/integration/test_reasoning_api.py` | Integration tests for new proxy endpoints |

---

## Task 1: OWL-EL Classifier with Full CR Rules and Proof Traces

**Files:**
- Create: `docker/elk-service/classifier.py`
- Test (inline, no Docker): `docker/elk-service/test_classifier.py`

- [ ] **Step 1.1: Write failing tests for classifier.py**

Create `docker/elk-service/test_classifier.py`:

```python
"""Unit tests for the enhanced OWL-EL classifier."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import io
import rdflib
from rdflib.namespace import OWL, RDFS, RDF
from rdflib import URIRef

EX = "http://example.org/"

def g(ttl: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(io.StringIO(ttl), format="turtle")
    return graph


def test_cr2_transitivity():
    """A ⊑ B, B ⊑ C → infer A ⊑ C."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    result = classify(g(ttl), "v1")
    sups = result.superclasses[f"{EX}A"]
    assert f"{EX}C" in sups
    assert str(OWL.Thing) in sups
    assert f"{EX}B" not in sups  # asserted, not inferred


def test_cr3_conjunction():
    """A ⊑ B ⊓ C → infer A ⊑ B and A ⊑ C."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:BC a owl:Class ;
          owl:intersectionOf ( ex:B ex:C ) .
    ex:A rdfs:subClassOf ex:BC .
    """
    result = classify(g(ttl), "v1")
    sups = result.superclasses[f"{EX}A"]
    assert f"{EX}B" in sups
    assert f"{EX}C" in sups


def test_cr4_existential_propagation():
    """If ∃r.B ⊑ D and A ⊑ ∃r.B, then A ⊑ D."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:D a owl:Class .
    ex:r a owl:ObjectProperty .
    ex:A rdfs:subClassOf [
        a owl:Restriction ;
        owl:onProperty ex:r ;
        owl:someValuesFrom ex:B
    ] .
    [ a owl:Restriction ;
      owl:onProperty ex:r ;
      owl:someValuesFrom ex:B ] rdfs:subClassOf ex:D .
    """
    result = classify(g(ttl), "v1")
    sups = result.superclasses.get(f"{EX}A", [])
    assert f"{EX}D" in sups


def test_cr5_role_hierarchy():
    """r ⊑ s: ∃r.A ⊑ ∃s.A — propagate existentials up role hierarchy."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:r a owl:ObjectProperty ; rdfs:subPropertyOf ex:s .
    ex:s a owl:ObjectProperty .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:A rdfs:subClassOf [
        a owl:Restriction ; owl:onProperty ex:r ; owl:someValuesFrom ex:B
    ] .
    [ a owl:Restriction ; owl:onProperty ex:s ; owl:someValuesFrom ex:B ]
        rdfs:subClassOf ex:C .
    """
    result = classify(g(ttl), "v1")
    sups = result.superclasses.get(f"{EX}A", [])
    assert f"{EX}C" in sups


def test_cr6_unsatisfiable():
    """A ⊑ B and A ⊑ ¬B (DisjointWith) → A is unsatisfiable."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:C .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:B owl:disjointWith ex:C .
    """
    result = classify(g(ttl), "v1")
    assert f"{EX}A" in result.unsatisfiable


def test_proof_trace_recorded():
    """Every inferred axiom has an entry in proof_traces."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    result = classify(g(ttl), "v1")
    key = f"{EX}A|{EX}C"
    assert key in result.proof_traces
    step = result.proof_traces[key][0]
    assert step["rule"] == "CR2"
    assert "axioms" in step
    assert len(step["axioms"]) >= 2


def test_direct_superclasses_only_one_hop():
    """direct_superclasses contains only immediately asserted parents."""
    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    result = classify(g(ttl), "v1")
    assert result.direct_superclasses[f"{EX}A"] == [f"{EX}B"]
    assert f"{EX}C" not in result.direct_superclasses[f"{EX}A"]
```

- [ ] **Step 1.2: Run tests — confirm they fail**

```bash
cd docker/elk-service && python -m pytest test_classifier.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'classifier'`

- [ ] **Step 1.3: Create `docker/elk-service/classifier.py`**

```python
"""OWL-EL classifier implementing CR1–CR6 with proof trace recording."""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

OWL_THING    = str(OWL.Thing)
OWL_NOTHING  = str(OWL.Nothing)


@dataclass
class ClassificationResult:
    version_id: str
    classified_at: str
    class_count: int
    superclasses: dict[str, list[str]]         # all inferred (not asserted)
    subclasses: dict[str, list[str]]            # inverse of superclasses
    direct_superclasses: dict[str, list[str]]   # asserted only
    direct_subclasses: dict[str, list[str]]     # asserted only (inverted)
    unsatisfiable: list[str]
    proof_traces: dict[str, list[dict]]         # "sub|sup" -> steps
    duration_ms: float


def classify(graph: rdflib.Graph, version_id: str) -> ClassificationResult:
    """Run OWL-EL classification and return a ClassificationResult."""
    from datetime import datetime, timezone
    t0 = time.monotonic()

    classes: set[str] = _collect_classes(graph)
    asserted_sub = _collect_asserted_subclass(graph, classes)  # cls -> set of direct supers
    equiv_pairs  = _collect_equiv(graph, classes)
    exists_sups  = _collect_existential_supers(graph)   # (role, filler) -> set of named sups
    role_hier    = _collect_role_hierarchy(graph)        # role -> set of super-roles
    disjoints    = _collect_disjointness(graph, classes) # cls -> set of disjoint classes

    # Forward index: cls -> set of all inferred supers (starts with asserted + reflexive + Thing)
    inferred: dict[str, set[str]] = defaultdict(set)
    for cls in classes:
        inferred[cls].add(OWL_THING)
        inferred[cls].update(asserted_sub.get(cls, set()))
        for equiv in equiv_pairs.get(cls, set()):
            inferred[cls].add(equiv)
            inferred[equiv].add(cls)

    # Proof trace: "sub|sup" -> list of steps
    traces: dict[str, list[dict]] = {}

    def _record(sub: str, sup: str, rule: str, premises: list[str], axioms: list[str]) -> None:
        key = f"{sub}|{sup}"
        if key not in traces:
            traces[key] = []
        traces[key].append({"rule": rule, "premises": premises,
                             "conclusion": f"{_short(sub)} ⊑ {_short(sup)}", "axioms": axioms})

    # ── CR3: conjunction left — A ⊑ B ⊓ C → A ⊑ B, A ⊑ C ────────────────────
    for node, _, lst in graph.triples((None, OWL.intersectionOf, None)):
        operands = _rdf_list(graph, lst)
        for cls in list(classes):
            if str(node) in inferred.get(cls, set()) or str(node) in asserted_sub.get(cls, set()):
                for op in operands:
                    op_str = str(op)
                    if isinstance(op, rdflib.URIRef) and op_str not in inferred[cls]:
                        inferred[cls].add(op_str)
                        _record(cls, op_str, "CR3",
                                [f"{_short(cls)} ⊑ {_short(str(node))}", f"{_short(str(node))} = {' ⊓ '.join(_short(str(o)) for o in operands if isinstance(o, rdflib.URIRef))}"],
                                [f"<{cls}> <{RDFS.subClassOf}> <{node}> .",
                                 f"<{node}> <{OWL.intersectionOf}> _:list ."])

    # ── CR4: existential propagation — A ⊑ ∃r.B and ∃r.B ⊑ D → A ⊑ D ────────
    # Collect A → [(role, filler)] from owl:someValuesFrom restrictions
    a_exists: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for restr, _, _ in graph.triples((None, RDF.type, OWL.Restriction)):
        role = graph.value(restr, OWL.onProperty)
        filler = graph.value(restr, OWL.someValuesFrom)
        if role is None or filler is None:
            continue
        role_str   = str(role)
        filler_str = str(filler)
        restr_str  = str(restr)
        # Which classes have this restriction as a superclass?
        for cls in classes:
            if restr_str in asserted_sub.get(cls, set()) or restr_str in inferred.get(cls, set()):
                a_exists[cls].append((role_str, filler_str))
        # Also collect ∃r.B ⊑ D GCIs
        for _, _, gci_sup in graph.triples((restr, RDFS.subClassOf, None)):
            if isinstance(gci_sup, rdflib.URIRef):
                exists_sups.setdefault((role_str, filler_str), set()).add(str(gci_sup))

    for cls, exist_list in a_exists.items():
        for (role, filler) in exist_list:
            # Direct GCIs on this existential
            for sup in exists_sups.get((role, filler), set()):
                if sup not in inferred[cls]:
                    inferred[cls].add(sup)
                    _record(cls, sup, "CR4",
                            [f"{_short(cls)} ⊑ ∃{_short(role)}.{_short(filler)}",
                             f"∃{_short(role)}.{_short(filler)} ⊑ {_short(sup)}"],
                            [f"<{cls}> <{RDFS.subClassOf}> _:restr .",
                             f"_:restr <{OWL.onProperty}> <{role}> ; <{OWL.someValuesFrom}> <{filler}> .",
                             f"_:restr <{RDFS.subClassOf}> <{sup}> ."])

            # ── CR5: role hierarchy — r ⊑ s means ∃r.B ⊑ ∃s.B ───────────────
            for super_role in role_hier.get(role, set()):
                for sup in exists_sups.get((super_role, filler), set()):
                    if sup not in inferred[cls]:
                        inferred[cls].add(sup)
                        _record(cls, sup, "CR5",
                                [f"{_short(role)} ⊑ {_short(super_role)}",
                                 f"{_short(cls)} ⊑ ∃{_short(role)}.{_short(filler)}",
                                 f"∃{_short(super_role)}.{_short(filler)} ⊑ {_short(sup)}"],
                                [f"<{role}> <{RDFS.subPropertyOf}> <{super_role}> .",
                                 f"<{cls}> <{RDFS.subClassOf}> _:restr .",
                                 f"_:restr2 <{RDFS.subClassOf}> <{sup}> ."])

    # ── CR2: transitivity fixed-point ─────────────────────────────────────────
    changed = True
    while changed:
        changed = False
        for cls in classes:
            new_sups: set[str] = set()
            for sup in list(inferred[cls]):
                for sup2 in inferred.get(sup, set()):
                    if sup2 not in inferred[cls] and sup2 != cls:
                        new_sups.add(sup2)
                        _record(cls, sup2, "CR2",
                                [f"{_short(cls)} ⊑ {_short(sup)}", f"{_short(sup)} ⊑ {_short(sup2)}"],
                                [f"<{cls}> <{RDFS.subClassOf}> <{sup}> .",
                                 f"<{sup}> <{RDFS.subClassOf}> <{sup2}> ."])
            if new_sups:
                inferred[cls].update(new_sups)
                changed = True

    # ── CR6: unsatisfiability — A ⊑ B and A ⊑ C and B disjointWith C ─────────
    unsatisfiable: list[str] = []
    for cls in classes:
        sups = inferred[cls]
        for b in list(sups):
            for c in disjoints.get(b, set()):
                if c in sups and cls not in unsatisfiable:
                    unsatisfiable.append(cls)
                    inferred[cls].add(OWL_NOTHING)
                    _record(cls, OWL_NOTHING, "CR6",
                            [f"{_short(cls)} ⊑ {_short(b)}", f"{_short(cls)} ⊑ {_short(c)}",
                             f"{_short(b)} disjointWith {_short(c)}"],
                            [f"<{cls}> <{RDFS.subClassOf}> <{b}> .",
                             f"<{cls}> <{RDFS.subClassOf}> <{c}> .",
                             f"<{b}> <{OWL.disjointWith}> <{c}> ."])

    # Build result — superclasses contains only inferred (not directly asserted)
    asserted_all: set[tuple[str, str]] = set()
    for cls, sups in asserted_sub.items():
        for sup in sups:
            asserted_all.add((cls, sup))
    for cls, eqs in equiv_pairs.items():
        for eq in eqs:
            asserted_all.add((cls, eq))
            asserted_all.add((eq, cls))

    superclasses: dict[str, list[str]] = {}
    subclasses:   dict[str, list[str]] = defaultdict(list)
    for cls in classes:
        inf_sups = [s for s in inferred[cls] if s != cls and (cls, s) not in asserted_all]
        superclasses[cls] = inf_sups
        for sup in inf_sups:
            subclasses[sup].append(cls)

    direct_subs: dict[str, list[str]] = defaultdict(list)
    for cls, sups in asserted_sub.items():
        for sup in sups:
            direct_subs[sup].append(cls)

    from datetime import datetime, timezone
    return ClassificationResult(
        version_id=version_id,
        classified_at=datetime.now(timezone.utc).isoformat(),
        class_count=len(classes),
        superclasses=superclasses,
        subclasses=dict(subclasses),
        direct_superclasses={cls: list(sups) for cls, sups in asserted_sub.items()},
        direct_subclasses=dict(direct_subs),
        unsatisfiable=unsatisfiable,
        proof_traces=traces,
        duration_ms=round((time.monotonic() - t0) * 1000, 1),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_classes(g: rdflib.Graph) -> set[str]:
    classes: set[str] = set()
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, rdflib.URIRef):
            classes.add(str(s))
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        if isinstance(s, rdflib.URIRef):
            classes.add(str(s))
        if isinstance(o, rdflib.URIRef):
            classes.add(str(o))
    classes.discard(str(OWL.Thing))
    classes.discard(str(OWL.Nothing))
    return classes


def _collect_asserted_subclass(g: rdflib.Graph, classes: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            if str(s) in classes and str(o) != str(s):
                result[str(s)].add(str(o))
    return result


def _collect_equiv(g: rdflib.Graph, classes: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, OWL.equivalentClass, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            if str(s) in classes and str(o) in classes:
                result[str(s)].add(str(o))
    return result


def _collect_existential_supers(g: rdflib.Graph) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    for restr, _, _ in g.triples((None, RDF.type, OWL.Restriction)):
        role   = g.value(restr, OWL.onProperty)
        filler = g.value(restr, OWL.someValuesFrom)
        if role is None or filler is None:
            continue
        for _, _, sup in g.triples((restr, RDFS.subClassOf, None)):
            if isinstance(sup, rdflib.URIRef):
                result[(str(role), str(filler))].add(str(sup))
    return result


def _collect_role_hierarchy(g: rdflib.Graph) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, RDFS.subPropertyOf, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            result[str(s)].add(str(o))
    return result


def _collect_disjointness(g: rdflib.Graph, classes: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for s, _, o in g.triples((None, OWL.disjointWith, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            result[str(s)].add(str(o))
            result[str(o)].add(str(s))
    return result


def _rdf_list(g: rdflib.Graph, node) -> list:
    items = []
    current = node
    while current and current != RDF.nil:
        first = g.value(current, RDF.first)
        if first is not None:
            items.append(first)
        current = g.value(current, RDF.rest)
    return items


def _short(iri: str) -> str:
    if "#" in iri:
        return iri.split("#")[-1]
    return iri.rstrip("/").split("/")[-1]
```

- [ ] **Step 1.4: Run tests — confirm they pass**

```bash
cd docker/elk-service && pip install rdflib pytest --quiet && python -m pytest test_classifier.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add docker/elk-service/classifier.py docker/elk-service/test_classifier.py
git commit -m "feat: OWL-EL classifier with full CR rules and proof traces"
```

---

## Task 2: Redis Cache Module

**Files:**
- Create: `docker/elk-service/cache.py`

- [ ] **Step 2.1: Write failing test for cache.py**

Append to `docker/elk-service/test_classifier.py`:

```python
def test_cache_round_trip(tmp_path, monkeypatch):
    """ClassificationResult serialises to/from Redis correctly."""
    import fakeredis
    import cache as cache_mod
    r = fakeredis.FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)

    from classifier import classify
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class .
    """
    result = classify(g(ttl), "test-version")
    cache_mod.store_classification(result)
    loaded = cache_mod.load_classification("test-version")
    assert loaded is not None
    assert loaded.class_count == result.class_count
    assert loaded.superclasses == result.superclasses


def test_cache_miss_returns_none(monkeypatch):
    import fakeredis
    import cache as cache_mod
    r = fakeredis.FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)
    assert cache_mod.load_classification("no-such-version") is None
```

- [ ] **Step 2.2: Run tests — confirm they fail**

```bash
cd docker/elk-service && pip install fakeredis --quiet && python -m pytest test_classifier.py::test_cache_round_trip test_classifier.py::test_cache_miss_returns_none -v
```

Expected: `ModuleNotFoundError: No module named 'cache'`

- [ ] **Step 2.3: Create `docker/elk-service/cache.py`**

```python
"""Redis-backed classification result cache."""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import asdict
from typing import Any

import redis

from classifier import ClassificationResult

_CLASSIFICATION_TTL = int(os.getenv("CLASSIFICATION_TTL_SECONDS", str(30 * 24 * 3600)))
_JUSTIFICATION_TTL  = int(os.getenv("JUSTIFICATION_TTL_SECONDS",  str(7  * 24 * 3600)))
_REDIS_URL          = os.getenv("REDIS_URL", "redis://localhost:6379/2")

_redis: redis.Redis = redis.from_url(_REDIS_URL, decode_responses=False)


def _classification_key(version_id: str) -> str:
    return f"classification:{version_id}"


def _justification_key(version_id: str, sub: str, sup: str | None, max_j: int) -> str:
    import hashlib
    raw = f"{sub}|{sup}|{max_j}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"justification:{version_id}:{h}"


def store_classification(result: ClassificationResult) -> None:
    key = _classification_key(result.version_id)
    data = json.dumps(asdict(result)).encode()
    compressed = gzip.compress(data)
    _redis.setex(key, _CLASSIFICATION_TTL, compressed)


def load_classification(version_id: str) -> ClassificationResult | None:
    key = _classification_key(version_id)
    raw = _redis.get(key)
    if raw is None:
        return None
    data = json.loads(gzip.decompress(raw))
    return ClassificationResult(**data)


def store_justification(version_id: str, sub: str, sup: str | None, max_j: int, result: dict) -> None:
    key = _justification_key(version_id, sub, sup, max_j)
    _redis.setex(key, _JUSTIFICATION_TTL, json.dumps(result).encode())


def load_justification(version_id: str, sub: str, sup: str | None, max_j: int) -> dict | None:
    key = _justification_key(version_id, sub, sup, max_j)
    raw = _redis.get(key)
    return json.loads(raw) if raw else None


def invalidate_version(version_id: str) -> None:
    """Remove all cache entries for a version (called on deprecation)."""
    pattern = f"*:{version_id}:*"
    keys = list(_redis.scan_iter(pattern))
    keys.append(_classification_key(version_id).encode())
    if keys:
        _redis.delete(*keys)
```

- [ ] **Step 2.4: Run tests — confirm they pass**

```bash
cd docker/elk-service && python -m pytest test_classifier.py::test_cache_round_trip test_classifier.py::test_cache_miss_returns_none -v
```

Expected: 2 passed.

- [ ] **Step 2.5: Commit**

```bash
git add docker/elk-service/cache.py
git commit -m "feat: Redis classification cache module"
```

---

## Task 3: Justification Computation

**Files:**
- Create: `docker/elk-service/justification.py`

- [ ] **Step 3.1: Write failing tests for justification.py**

Append to `docker/elk-service/test_classifier.py`:

```python
def test_justification_simple():
    """Justification for A ⊑ C (via A ⊑ B, B ⊑ C) is exactly those two axioms."""
    from classifier import classify
    from justification import compute_justifications
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class ; rdfs:subClassOf ex:D .
    ex:D a owl:Class .
    """
    graph = g(ttl)
    result = classify(graph, "v1")
    justs = compute_justifications(graph, result, f"{EX}A", f"{EX}C", max_justifications=1)
    assert len(justs) == 1
    j = justs[0]
    # Must contain A ⊑ B and B ⊑ C; must NOT contain B ⊑ D or C ⊑ D
    axiom_strs = " ".join(j)
    assert f"{EX}A" in axiom_strs
    assert f"{EX}B" in axiom_strs
    assert f"{EX}C" in axiom_strs
    # Minimality: exactly 2 axioms
    assert len(j) == 2


def test_justification_minimality():
    """Removing any axiom from a justification breaks the inference."""
    from classifier import classify
    from justification import compute_justifications
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    graph = g(ttl)
    result = classify(graph, "v1")
    justs = compute_justifications(graph, result, f"{EX}A", f"{EX}C", max_justifications=1)
    assert len(justs) == 1
    j = justs[0]
    for i in range(len(j)):
        reduced = j[:i] + j[i+1:]
        reduced_g = rdflib.Graph()
        for ax in reduced:
            try:
                reduced_g.parse(data=ax, format="nt")
            except Exception:
                pass
        reduced_result = classify(reduced_g, "v1")
        sups = reduced_result.superclasses.get(f"{EX}A", [])
        assert f"{EX}C" not in sups, f"Axiom {i} was not load-bearing"


def test_multiple_justifications():
    """Two independent paths yield two distinct justifications."""
    from classifier import classify
    from justification import compute_justifications
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:X .
    ex:B a owl:Class ; rdfs:subClassOf ex:C .
    ex:X a owl:Class ; rdfs:subClassOf ex:C .
    ex:C a owl:Class .
    """
    graph = g(ttl)
    result = classify(graph, "v1")
    justs = compute_justifications(graph, result, f"{EX}A", f"{EX}C", max_justifications=0)
    assert len(justs) == 2
    # Justifications should be different sets
    assert set(justs[0]) != set(justs[1])


def test_justification_unsatisfiable():
    """Justification for unsatisfiability contains the disjointness axiom."""
    from classifier import classify
    from justification import compute_justifications
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:C .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:B owl:disjointWith ex:C .
    """
    graph = g(ttl)
    result = classify(graph, "v1")
    justs = compute_justifications(graph, result, f"{EX}A", str(OWL.Nothing), max_justifications=1)
    assert len(justs) >= 1
    axiom_strs = " ".join(justs[0])
    assert "disjointWith" in axiom_strs
```

- [ ] **Step 3.2: Run tests — confirm they fail**

```bash
cd docker/elk-service && python -m pytest test_classifier.py::test_justification_simple test_classifier.py::test_justification_minimality test_classifier.py::test_multiple_justifications test_classifier.py::test_justification_unsatisfiable -v
```

Expected: `ModuleNotFoundError: No module named 'justification'`

- [ ] **Step 3.3: Create `docker/elk-service/justification.py`**

```python
"""
Justification computation for OWL-EL inferences.

Algorithm:
1. Find all input axioms (N-Triple strings) that are used anywhere in
   the proof trace for the target inference.
2. Greedily shrink the set (remove axioms that are not load-bearing)
   by re-running classification on the reduced graph.
3. For multiple justifications, use the hitting-set approach:
   after finding one justification J, add a blocking constraint
   (exclude at least one axiom from J) and search again.
"""
from __future__ import annotations

import io
import itertools
from typing import Sequence

import rdflib

from classifier import ClassificationResult, classify


def compute_justifications(
    graph: rdflib.Graph,
    result: ClassificationResult,
    sub: str,
    sup: str,
    max_justifications: int = 1,
) -> list[list[str]]:
    """
    Return a list of minimal justifications for the inference sub ⊑ sup.

    Each justification is a list of N-Triple strings (original axioms).
    max_justifications=0 means find all (may be expensive).
    Returns [] if the inference is not present in result.
    """
    # Verify inference is present
    if sup == str(rdflib.OWL.Nothing):
        if sub not in result.unsatisfiable:
            return []
    else:
        if sup not in result.superclasses.get(sub, []) and sup not in result.direct_superclasses.get(sub, []):
            # Also allow asserted
            return []

    all_axioms = _extract_all_axioms(graph)
    if not all_axioms:
        return []

    justifications: list[list[str]] = []
    excluded: list[frozenset[str]] = []  # hitting sets to block

    limit = max_justifications if max_justifications > 0 else 999

    while len(justifications) < limit:
        candidate = _find_one_justification(all_axioms, sub, sup, excluded)
        if candidate is None:
            break
        justifications.append(candidate)
        excluded.append(frozenset(candidate))

    return justifications


def _find_one_justification(
    all_axioms: list[str],
    sub: str,
    sup: str,
    excluded: list[frozenset[str]],
) -> list[str] | None:
    """Find one minimal justification not blocked by any set in excluded."""
    # Start with all axioms and greedily remove non-load-bearing ones
    candidate = list(all_axioms)

    # Apply exclusion: must contain at least one axiom NOT in each excluded set.
    # Filter out any candidate that is a subset of an excluded justification.
    for ex_set in excluded:
        # Remove one axiom from ex_set so the candidate diverges
        for ax in list(ex_set):
            if ax in candidate:
                candidate = [a for a in candidate if a != ax]
                break

    if not _entails(candidate, sub, sup):
        return None

    # Greedy minimisation: try removing each axiom
    minimal = list(candidate)
    for ax in list(candidate):
        reduced = [a for a in minimal if a != ax]
        if _entails(reduced, sub, sup):
            minimal = reduced

    return minimal if minimal else None


def _entails(axioms: list[str], sub: str, sup: str) -> bool:
    """Return True if the given axiom set entails sub ⊑ sup."""
    g = rdflib.Graph()
    for ax in axioms:
        try:
            g.parse(data=ax, format="nt")
        except Exception:
            pass
    if len(g) == 0:
        return False
    try:
        r = classify(g, "_check")
    except Exception:
        return False
    if sup == str(rdflib.OWL.Nothing):
        return sub in r.unsatisfiable
    return (sup in r.superclasses.get(sub, []) or
            sup in r.direct_superclasses.get(sub, []))


def _extract_all_axioms(graph: rdflib.Graph) -> list[str]:
    """Serialise every triple in the graph as a separate N-Triple string."""
    axioms = []
    for triple in graph:
        g = rdflib.Graph()
        g.add(triple)
        nt = g.serialize(format="nt").strip()
        if nt:
            axioms.append(nt)
    return axioms
```

- [ ] **Step 3.4: Run tests — confirm they pass**

```bash
cd docker/elk-service && python -m pytest test_classifier.py::test_justification_simple test_classifier.py::test_justification_minimality test_classifier.py::test_multiple_justifications test_classifier.py::test_justification_unsatisfiable -v
```

Expected: 4 passed.

- [ ] **Step 3.5: Commit**

```bash
git add docker/elk-service/justification.py
git commit -m "feat: justification computation with minimality and multiple justifications"
```

---

## Task 4: Refactor ELK Service main.py

**Files:**
- Rewrite: `docker/elk-service/main.py`

- [ ] **Step 4.1: Rewrite `docker/elk-service/main.py`**

Replace the entire file:

```python
"""ELK OWL-EL Reasoning Service — FastAPI application."""
from __future__ import annotations

import io
import logging
import os
import uuid
from typing import Any

import rdflib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from cache import (
    invalidate_version,
    load_classification,
    load_justification,
    store_classification,
    store_justification,
)
from classifier import classify
from justification import compute_justifications

log = logging.getLogger("elk-service")
logging.basicConfig(level=logging.INFO)

_JUSTIFICATION_TIME_LIMIT = int(os.getenv("JUSTIFICATION_TIME_LIMIT_SECONDS", "300"))

app = FastAPI(title="ELK Reasoning Service", version="2.0.0")


# ── Request / Response models ─────────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    ntriples: str
    version_id: str


class JustificationRequest(BaseModel):
    sub: str
    sup: str | None = None
    type: str | None = None          # "unsatisfiable" when sup is omitted
    max_justifications: int = 1      # 0 = find all


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        from cache import _redis
        _redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"status": "ok", "redis": "ok" if redis_ok else "error"}


@app.post("/classify")
def run_classify(req: ClassifyRequest):
    """Run OWL-EL classification and persist result in Redis."""
    try:
        g = rdflib.Graph()
        g.parse(io.StringIO(req.ntriples), format="nt")
    except Exception as exc:
        raise HTTPException(422, f"Failed to parse N-Triples: {exc}")

    result = classify(g, req.version_id)
    store_classification(result)

    return {
        "version_id": result.version_id,
        "class_count": result.class_count,
        "unsatisfiable_count": len(result.unsatisfiable),
        "duration_ms": result.duration_ms,
        "cached": True,
    }


@app.get("/classify/{version_id}")
def get_classification(version_id: str):
    result = _load_or_404(version_id)
    from dataclasses import asdict
    return asdict(result)


@app.get("/classify/{version_id}/superclasses")
def get_superclasses(version_id: str, cls: str, direct: bool = False):
    result = _load_or_404(version_id)
    if cls not in result.superclasses and cls not in result.direct_superclasses:
        raise HTTPException(404, "Class not found in classification index")
    if direct:
        return {"class": cls, "superclasses": result.direct_superclasses.get(cls, []), "direct": True}
    return {"class": cls, "superclasses": result.superclasses.get(cls, []), "direct": False}


@app.get("/classify/{version_id}/subclasses")
def get_subclasses(version_id: str, cls: str, direct: bool = False):
    result = _load_or_404(version_id)
    if cls not in result.subclasses and cls not in result.direct_subclasses:
        raise HTTPException(404, "Class not found in classification index")
    if direct:
        return {"class": cls, "subclasses": result.direct_subclasses.get(cls, []), "direct": True}
    return {"class": cls, "subclasses": result.subclasses.get(cls, []), "direct": False}


@app.get("/classify/{version_id}/consistency")
def get_consistency(version_id: str):
    result = _load_or_404(version_id)
    return {
        "version_id": version_id,
        "consistent": len(result.unsatisfiable) == 0,
        "unsatisfiable_classes": result.unsatisfiable,
        "unsatisfiable_count": len(result.unsatisfiable),
    }


@app.post("/classify/{version_id}/justification")
def compute_justification_endpoint(version_id: str, req: JustificationRequest):
    """
    Synchronously compute justification(s) and cache result.
    Long-running; called by the compute_justification Celery task.
    """
    import time
    result = _load_or_404(version_id)

    sup = req.sup if req.sup else str(rdflib.OWL.Nothing)

    # Check cache first
    cached = load_justification(version_id, req.sub, sup, req.max_justifications)
    if cached:
        return cached

    # Reconstruct graph from inferred + direct axioms stored in proof traces
    g = _reconstruct_graph_from_traces(result)

    t0 = time.monotonic()
    timed_out = False
    try:
        import signal

        def _handler(signum, frame):
            raise TimeoutError("justification time limit exceeded")

        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(_JUSTIFICATION_TIME_LIMIT)
        try:
            justs = compute_justifications(g, result, req.sub, sup, req.max_justifications)
        finally:
            signal.alarm(0)
    except TimeoutError:
        timed_out = True
        justs = []

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    justification_id = str(uuid.uuid4())

    response = {
        "justification_id": justification_id,
        "version_id": version_id,
        "sub": req.sub,
        "sup": sup,
        "justifications_requested": req.max_justifications,
        "justifications_found": len(justs),
        "minimal": not timed_out,
        "timed_out": timed_out,
        "justifications": justs,
        "proof_traces": [result.proof_traces.get(f"{req.sub}|{sup}", [])],
        "duration_ms": elapsed_ms,
    }

    store_justification(version_id, req.sub, sup, req.max_justifications, response)
    return response


@app.get("/classify/{version_id}/justification/{justification_id}")
def get_justification(version_id: str, justification_id: str):
    # Justifications are stored by sub/sup/max, not by ID.
    # This endpoint is a convenience lookup — scan for matching ID.
    # In practice the Celery task stores the full response and the
    # main API caches the job_id → justification_id mapping.
    raise HTTPException(501, "Use GET /classify/{version_id}?sub=...&sup=... to retrieve justifications")


@app.delete("/classify/{version_id}")
def invalidate(version_id: str):
    invalidate_version(version_id)
    return {"detail": f"Cache invalidated for version {version_id}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_or_404(version_id: str):
    result = load_classification(version_id)
    if result is None:
        raise HTTPException(409, "Reasoning not yet completed for this version — submit via POST /classify")
    return result


def _reconstruct_graph_from_traces(result) -> rdflib.Graph:
    """Reconstruct input axioms from the recorded proof traces."""
    g = rdflib.Graph()
    seen: set[str] = set()
    for steps in result.proof_traces.values():
        for step in steps:
            for ax in step.get("axioms", []):
                if ax not in seen and not ax.startswith("_:"):
                    seen.add(ax)
                    try:
                        g.parse(data=ax, format="nt")
                    except Exception:
                        pass
    return g
```

- [ ] **Step 4.2: Run all ELK service tests**

```bash
cd docker/elk-service && python -m pytest test_classifier.py -v
```

Expected: all tests pass.

- [ ] **Step 4.3: Commit**

```bash
git add docker/elk-service/main.py
git commit -m "feat: ELK service main.py refactored with classify/superclasses/subclasses/consistency/justification endpoints"
```

---

## Task 5: Docker Updates

**Files:**
- Modify: `docker/elk-service/Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 5.1: Update `docker/elk-service/Dockerfile`**

Replace the `pip install` line:

```dockerfile
RUN pip install --no-cache-dir \
    "fastapi==0.111.*" \
    "uvicorn[standard]" \
    "py_horned_owl" \
    "rdflib" \
    "redis>=5.0"
```

- [ ] **Step 5.2: Update `docker-compose.yml` elk-service block**

Replace the `elk-service` service definition:

```yaml
  elk-service:
    build: docker/elk-service
    ports:
      - "8001:8001"
    environment:
      REDIS_URL: redis://redis:6379/2
      CLASSIFICATION_TTL_SECONDS: "2592000"
      JUSTIFICATION_TTL_SECONDS: "604800"
      JUSTIFICATION_TIME_LIMIT_SECONDS: "300"
    depends_on:
      - redis
```

- [ ] **Step 5.3: Commit**

```bash
git add docker/elk-service/Dockerfile docker-compose.yml
git commit -m "chore: ELK service gains Redis dependency and env config"
```

---

## Task 6: Update Reasoning Client

**Files:**
- Rewrite: `ontoexplorer/clients/reasoning.py`

- [ ] **Step 6.1: Rewrite `ontoexplorer/clients/reasoning.py`**

```python
"""HTTP client for the ELK reasoning service (v2)."""
from __future__ import annotations

import httpx
import rdflib

from ontoexplorer.config import get_settings


def _elk_url(path: str) -> str:
    return f"{get_settings().elk_service_url}{path}"


async def classify_v2(graph: rdflib.Graph, version_id: str) -> dict:
    """
    Run full OWL-EL classification and cache in ELK service.
    Returns the summary dict from POST /classify.
    """
    ntriples = graph.serialize(format="nt")
    async with httpx.AsyncClient(timeout=get_settings().elk_service_timeout) as client:
        resp = await client.post(_elk_url("/classify"),
                                 json={"ntriples": ntriples, "version_id": version_id})
        resp.raise_for_status()
    return resp.json()


async def superclasses(version_id: str, class_iri: str, direct: bool = False) -> dict:
    """Return all (or direct-only) inferred superclasses of class_iri."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _elk_url(f"/classify/{version_id}/superclasses"),
            params={"cls": class_iri, "direct": str(direct).lower()},
        )
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        if resp.status_code == 404:
            raise ClassNotFoundError(class_iri)
        resp.raise_for_status()
    return resp.json()


async def subclasses(version_id: str, class_iri: str, direct: bool = False) -> dict:
    """Return all (or direct-only) inferred subclasses of class_iri."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _elk_url(f"/classify/{version_id}/subclasses"),
            params={"cls": class_iri, "direct": str(direct).lower()},
        )
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        if resp.status_code == 404:
            raise ClassNotFoundError(class_iri)
        resp.raise_for_status()
    return resp.json()


async def consistency(version_id: str) -> dict:
    """Return consistency check result including unsatisfiable classes."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_elk_url(f"/classify/{version_id}/consistency"))
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        resp.raise_for_status()
    return resp.json()


async def request_justification(
    version_id: str,
    sub: str,
    sup: str | None,
    max_justifications: int = 1,
) -> dict:
    """
    Synchronously request justification computation from ELK service.
    Long-running — always called from a Celery task, not an HTTP handler.
    """
    body: dict = {"sub": sub, "max_justifications": max_justifications}
    if sup:
        body["sup"] = sup
    else:
        body["type"] = "unsatisfiable"

    timeout = get_settings().elk_service_timeout + 60  # extra buffer over time limit
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            _elk_url(f"/classify/{version_id}/justification"),
            json=body,
        )
        if resp.status_code == 409:
            raise ReasoningNotReadyError(version_id)
        resp.raise_for_status()
    return resp.json()


async def invalidate_cache(version_id: str) -> None:
    """Invalidate ELK Redis cache for a version (called on deprecation)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.delete(_elk_url(f"/classify/{version_id}"))


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(_elk_url("/health"))
            return resp.status_code == 200 and resp.json().get("redis") == "ok"
    except Exception:
        return False


class ReasoningNotReadyError(Exception):
    def __init__(self, version_id: str):
        super().__init__(f"Reasoning not yet completed for version {version_id}")
        self.version_id = version_id


class ClassNotFoundError(Exception):
    def __init__(self, class_iri: str):
        super().__init__(f"Class {class_iri} not found in classification index")
        self.class_iri = class_iri
```

- [ ] **Step 6.2: Commit**

```bash
git add ontoexplorer/clients/reasoning.py
git commit -m "feat: reasoning client v2 with superclasses/subclasses/consistency/justification"
```

---

## Task 7: `compute_justification` Celery Task

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`

- [ ] **Step 7.1: Update `ontoexplorer/modules/jobs/tasks.py`**

Append after the `index_ontology` task (keep all existing tasks unchanged):

```python
@celery_app.task(bind=True, name="ontoexplorer.compute_justification", max_retries=1,
                 time_limit=660)  # 11 min hard limit (matches ELK 300s + buffer)
def compute_justification(
    self,
    *,
    version_id: str,
    ontology_id: str,
    sub: str,
    sup: str | None,
    max_justifications: int = 1,
) -> dict:
    """
    Compute justification(s) for a subclass inference or unsatisfiability.

    Calls ELK service synchronously (ELK does the work), stores the result,
    updates job status, and fires justification.completed / justification.failed.
    """
    import asyncio

    async def _run():
        from ontoexplorer.clients import reasoning as reasoning_client
        from ontoexplorer.database import AsyncSessionLocal
        from ontoexplorer.modules.jobs import tracker
        from ontoexplorer.modules.webhooks.delivery import broadcast_event

        async with AsyncSessionLocal() as db:
            job = await tracker.create_job(db, version_id=version_id, job_type="justification")
            await tracker.mark_running(db, job.id)
            try:
                result = await reasoning_client.request_justification(
                    version_id, sub, sup, max_justifications
                )
                await tracker.mark_done(db, job.id)
                await broadcast_event(db, "justification.completed", {
                    "version_id": version_id,
                    "ontology_id": ontology_id,
                    "sub": sub,
                    "sup": sup,
                    "justifications_found": result.get("justifications_found", 0),
                })
                return result
            except Exception as exc:
                await tracker.mark_failed(db, job.id, str(exc))
                await broadcast_event(db, "justification.failed", {
                    "version_id": version_id,
                    "ontology_id": ontology_id,
                    "sub": sub,
                    "sup": sup,
                    "error": str(exc),
                })
                raise

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.error("justification_task_failed", version_id=version_id, sub=sub, error=str(exc))
        raise self.retry(exc=exc, countdown=30) from exc
```

- [ ] **Step 7.2: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py
git commit -m "feat: compute_justification Celery task"
```

---

## Task 8: Add Justification Webhook Events

**Files:**
- Modify: `ontoexplorer/modules/webhooks/registry.py`

- [ ] **Step 8.1: Add new events to `VALID_EVENTS`**

In `ontoexplorer/modules/webhooks/registry.py`, replace the `VALID_EVENTS` frozenset:

```python
VALID_EVENTS = frozenset({
    "ontology.ingested",
    "version.deprecated",
    "reasoning.completed",
    "reasoning.failed",
    "indexing.completed",
    "justification.completed",
    "justification.failed",
})
```

- [ ] **Step 8.2: Commit**

```bash
git add ontoexplorer/modules/webhooks/registry.py
git commit -m "feat: add justification.completed and justification.failed webhook events"
```

---

## Task 9: Main API Proxy Endpoints

**Files:**
- Modify: `ontoexplorer/api/ontologies.py`

- [ ] **Step 9.1: Add five new endpoints to `ontoexplorer/api/ontologies.py`**

Add the following imports at the top of the file (after existing imports):

```python
from ontoexplorer.clients.reasoning import (
    ClassNotFoundError,
    ReasoningNotReadyError,
    consistency as elk_consistency,
    subclasses as elk_subclasses,
    superclasses as elk_superclasses,
)
```

Add the following endpoints before the `# ── Deprecate` section:

```python
# ── Reasoning query endpoints ──────────────────────────────────────────────────

@router.get("/{ontology_id}/{version_id}/superclasses", summary="Inferred superclasses of a class")
async def get_superclasses(
    ontology_id: str,
    version_id: str,
    cls: str = Query(..., description="Class IRI to look up"),
    direct: bool = Query(False, description="Return only directly asserted superclasses"),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    try:
        return await elk_superclasses(version_id, cls, direct=direct)
    except ReasoningNotReadyError:
        raise HTTPException(409, "Reasoning not yet completed — trigger via POST .../reason")
    except ClassNotFoundError:
        raise HTTPException(404, f"Class {cls!r} not found in classification index")
    except Exception:
        raise HTTPException(503, "Reasoning service unavailable")


@router.get("/{ontology_id}/{version_id}/subclasses", summary="Inferred subclasses of a class")
async def get_subclasses(
    ontology_id: str,
    version_id: str,
    cls: str = Query(..., description="Class IRI to look up"),
    direct: bool = Query(False, description="Return only directly asserted subclasses"),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    try:
        return await elk_subclasses(version_id, cls, direct=direct)
    except ReasoningNotReadyError:
        raise HTTPException(409, "Reasoning not yet completed — trigger via POST .../reason")
    except ClassNotFoundError:
        raise HTTPException(404, f"Class {cls!r} not found in classification index")
    except Exception:
        raise HTTPException(503, "Reasoning service unavailable")


@router.get("/{ontology_id}/{version_id}/consistency", summary="Consistency check for a version")
async def get_consistency(
    ontology_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    try:
        return await elk_consistency(version_id)
    except ReasoningNotReadyError:
        raise HTTPException(409, "Reasoning not yet completed — trigger via POST .../reason")
    except Exception:
        raise HTTPException(503, "Reasoning service unavailable")


class JustificationRequest(BaseModel):
    sub: str
    sup: str | None = None
    type: str | None = None         # "unsatisfiable" when sup is omitted
    max_justifications: int = 1     # 0 = find all


@router.post("/{ontology_id}/{version_id}/justification", summary="Request async justification computation")
async def request_justification(
    ontology_id: str,
    version_id: str,
    body: JustificationRequest,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await _get_version_or_404(db, ontology_id, version_id)
    from ontoexplorer.modules.jobs.tasks import compute_justification
    task = compute_justification.delay(
        version_id=version_id,
        ontology_id=ontology_id,
        sub=body.sub,
        sup=body.sup,
        max_justifications=body.max_justifications,
    )
    return {"job_id": task.id, "status": "queued", "sub": body.sub, "sup": body.sup}


@router.get("/{ontology_id}/{version_id}/justification/{job_id}", summary="Retrieve justification result")
async def get_justification_result(
    ontology_id: str,
    version_id: str,
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    from ontoexplorer.modules.jobs.tracker import get_job
    job = await get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status in ("pending", "running"):
        return {"job_id": job_id, "status": job.status}
    if job.status == "failed":
        raise HTTPException(500, f"Justification job failed: {job.error}")
    # Job done — result is stored in ELK Redis; retrieve via Celery result backend
    from ontoexplorer.modules.jobs.tasks import celery_app
    result = celery_app.AsyncResult(job_id)
    if result.ready():
        return result.get()
    raise HTTPException(202, "Job complete but result not yet available — retry shortly")
```

- [ ] **Step 9.2: Commit**

```bash
git add ontoexplorer/api/ontologies.py
git commit -m "feat: superclasses/subclasses/consistency/justification proxy endpoints on main API"
```

---

## Task 10: Update `reason_ontology` Task to Use `classify_v2`

**Files:**
- Modify: `ontoexplorer/modules/jobs/tasks.py`

- [ ] **Step 10.1: Update `_run_reasoning` to call `classify_v2` instead of old `/reason`**

In `ontoexplorer/modules/jobs/tasks.py`, replace the `_run_reasoning` function's ELK call:

```python
    # Call ELK service — classify_v2 POSTs to /classify and caches in Redis
    inferred_summary = await reasoning_client.classify_v2(asserted_graph, version_id)
```

Replace the lines that load inferred triples into Oxigraph with:

```python
    # Fetch the full inferred graph from ELK classification result for Oxigraph persistence
    from ontoexplorer.clients.reasoning import _elk_url
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{get_settings().elk_service_url}/classify/{version_id}")
        resp.raise_for_status()
    classification = resp.json()

    # Build inferred N-Triples from superclasses index
    inferred_nt_lines = []
    for sub, supers in classification.get("superclasses", {}).items():
        for sup in supers:
            inferred_nt_lines.append(f"<{sub}> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{sup}> .")
    inferred_nt = "\n".join(inferred_nt_lines).encode()
    inferred_count = len(inferred_nt_lines)
```

Also add `import httpx` at the top of `tasks.py` if not already present, and add this import inside `_run_reasoning`:

```python
    from ontoexplorer.config import get_settings
```

- [ ] **Step 10.2: Commit**

```bash
git add ontoexplorer/modules/jobs/tasks.py
git commit -m "feat: reason_ontology uses classify_v2 endpoint, persists inferred hierarchy to Oxigraph"
```

---

## Task 11: Update `version.deprecated` Webhook Handler to Invalidate ELK Cache

**Files:**
- Modify: `ontoexplorer/api/ontologies.py`

- [ ] **Step 11.1: Add cache invalidation on version deprecation**

In the `deprecate_version` endpoint in `ontoexplorer/api/ontologies.py`, add invalidation after the commit:

```python
@router.delete("/{ontology_id}/{version_id}", summary="Deprecate a version (soft delete)")
async def deprecate_version(
    ontology_id: str,
    version_id: str,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    version = await _get_version_or_404(db, ontology_id, version_id)
    if version.status == "deprecated":
        raise HTTPException(status_code=409, detail="Version is already deprecated")

    await db.execute(
        update(OntologyVersion)
        .where(OntologyVersion.id == version_id)
        .values(status="deprecated")
    )
    await db.commit()

    # Invalidate ELK classification cache for this version
    try:
        from ontoexplorer.clients.reasoning import invalidate_cache
        await invalidate_cache(version_id)
    except Exception:
        pass  # Non-fatal — TTL will expire anyway

    return {"detail": f"Version {version_id} deprecated"}
```

- [ ] **Step 11.2: Commit**

```bash
git add ontoexplorer/api/ontologies.py
git commit -m "feat: invalidate ELK cache on version deprecation"
```

---

## Task 12: Integration Tests

**Files:**
- Modify: `tests/integration/test_reasoning.py` (add CR rule tests)
- Create: `tests/integration/test_reasoning_api.py`

- [ ] **Step 12.1: Add CR rule tests to `tests/integration/test_reasoning.py`**

Append to `tests/integration/test_reasoning.py`:

```python
def test_cr3_conjunction_via_service():
    """CR3: A ⊑ intersectionOf(B, C) → infer A ⊑ B and A ⊑ C."""
    from main import classify  # type: ignore[import]
    from rdflib import URIRef
    from rdflib.namespace import RDFS, OWL, RDF
    import rdflib, io

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:BC a owl:Class ; owl:intersectionOf ( ex:B ex:C ) .
    ex:A rdfs:subClassOf ex:BC .
    """
    g = rdflib.Graph()
    g.parse(io.StringIO(ttl), format="turtle")
    result = classify(g, "v-cr3")
    a = "http://example.org/A"
    assert "http://example.org/B" in result.superclasses.get(a, [])
    assert "http://example.org/C" in result.superclasses.get(a, [])


def test_cr6_unsatisfiable_via_service():
    """CR6: disjointWith creates unsatisfiable class."""
    from main import classify  # type: ignore[import]
    import rdflib, io

    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .
    ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:subClassOf ex:C .
    ex:B a owl:Class .
    ex:C a owl:Class .
    ex:B owl:disjointWith ex:C .
    """
    g = rdflib.Graph()
    g.parse(io.StringIO(ttl), format="turtle")
    result = classify(g, "v-cr6")
    assert "http://example.org/A" in result.unsatisfiable
```

- [ ] **Step 12.2: Create `tests/integration/test_reasoning_api.py`**

```python
"""Integration tests for the Subsystem 2 reasoning API proxy endpoints."""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.anyio
async def test_superclasses_not_ready(client, user_and_key):
    """Returns 409 when reasoning not yet completed."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    from ontoexplorer.clients.reasoning import ReasoningNotReadyError

    with patch("ontoexplorer.api.ontologies.elk_superclasses",
               new=AsyncMock(side_effect=ReasoningNotReadyError("v1"))):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/superclasses",
            params={"cls": "http://example.org/A"},
            headers=auth,
        )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_superclasses_class_not_found(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    from ontoexplorer.clients.reasoning import ClassNotFoundError

    with patch("ontoexplorer.api.ontologies.elk_superclasses",
               new=AsyncMock(side_effect=ClassNotFoundError("http://example.org/Unknown"))):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/superclasses",
            params={"cls": "http://example.org/Unknown"},
            headers=auth,
        )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_superclasses_success(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    mock_result = {"class": "http://example.org/A",
                   "superclasses": ["http://example.org/B", "http://www.w3.org/2002/07/owl#Thing"],
                   "direct": False}

    with patch("ontoexplorer.api.ontologies.elk_superclasses",
               new=AsyncMock(return_value=mock_result)):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/superclasses",
            params={"cls": "http://example.org/A"},
            headers=auth,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "http://example.org/B" in body["superclasses"]


@pytest.mark.anyio
async def test_consistency_success(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    mock_result = {"version_id": "v1", "consistent": True,
                   "unsatisfiable_classes": [], "unsatisfiable_count": 0}

    with patch("ontoexplorer.api.ontologies.elk_consistency",
               new=AsyncMock(return_value=mock_result)):
        resp = await client.get(
            "/api/v1/ontologies/fake-oid/fake-vid/consistency",
            headers=auth,
        )
    assert resp.status_code == 200
    assert resp.json()["consistent"] is True


@pytest.mark.anyio
async def test_justification_queues_job(client, user_and_key):
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    mock_task = type("Task", (), {"id": "mock-task-id"})()

    with patch("ontoexplorer.api.ontologies.compute_justification") as mock_celery:
        mock_celery.delay.return_value = mock_task
        resp = await client.post(
            "/api/v1/ontologies/fake-oid/fake-vid/justification",
            json={"sub": "http://example.org/A", "sup": "http://example.org/C",
                  "max_justifications": 2},
            headers=auth,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "mock-task-id"
    assert body["status"] == "queued"


@pytest.mark.anyio
async def test_webhook_justification_events_valid(client, user_and_key):
    """justification.completed and justification.failed are valid webhook events."""
    _, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    for event in ("justification.completed", "justification.failed"):
        resp = await client.post(
            "/api/v1/webhooks",
            json={"url": "http://example.com/hook", "events": [event]},
            headers=auth,
        )
        assert resp.status_code == 200, f"Event {event} rejected: {resp.json()}"
```

- [ ] **Step 12.3: Run all new tests**

```bash
cd /path/to/ontoexplorer && python -m pytest tests/integration/test_reasoning.py tests/integration/test_reasoning_api.py -v
```

Expected: all tests pass (test_reasoning_api.py tests use mocks so no Docker needed).

- [ ] **Step 12.4: Run ELK service tests**

```bash
cd docker/elk-service && python -m pytest test_classifier.py -v
```

Expected: all tests pass.

- [ ] **Step 12.5: Final commit**

```bash
git add tests/integration/test_reasoning.py tests/integration/test_reasoning_api.py
git commit -m "test: Subsystem 2 integration tests — CR rules, justification, proxy endpoints"
```
