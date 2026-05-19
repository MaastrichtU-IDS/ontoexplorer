# OWL 2 Profile Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect OWL 2 profile membership (EL / RL / QL / DL) for every indexed ontology version via SPARQL ASK/COUNT queries against Oxigraph in-process. Cache results in Redis at indexing time; expose via API, per-ontology page tab, fleet page, and `?profile=` search filter. See spec at `docs/superpowers/specs/2026-05-19-owl-profile-detection-design.md`.

**Architecture:** New `ontoexplorer/modules/owl_profile/` module with per-profile pattern catalogs, a structural-checks layer (for DL), and a Redis-cached detector hooked into the existing indexer pipeline. New API surface at `/api/v1/owl-profile/*`. Frontend mirrors the Coverage tab/page pattern.

**Tech Stack:** Pyoxigraph (in-process SPARQL), Redis (cache), FastAPI, React + TanStack Query, Vitest, pytest + pyoxigraph.Store for unit tests.

---

## File structure (created across tasks)

```
ontoexplorer/modules/owl_profile/
    __init__.py
    registry.py             # ProfileName, ProfileViolation, axiom-type constants
    cache.py                # owl_profile_cache_key, profile-name list
    patterns.py             # Per-profile SPARQL pattern catalogs (EL, RL, QL)
    structural.py           # DL structural checks (punning, role hierarchy, etc.)
    detector.py             # detect_profiles() — aggregates all checks

ontoexplorer/api/owl_profile.py          # /api/v1/owl-profile/* routes

ontoexplorer/modules/search/indexer.py   # MODIFY: hook _populate_owl_profile_cache
ontoexplorer/api/ontologies.py           # MODIFY: ?profile= filter on list endpoint
ontoexplorer/api/ols/ontologies.py       # MODIFY: ?profile= filter on OLS list endpoints
ontoexplorer/main.py                     # MODIFY: register router

tests/fixtures/owl_profile/              # Curated test ontologies
    pizza-minimal.ttl                    # known DL, not EL/RL/QL
    el-only.ttl                          # known EL/RL/QL/DL
    disjoint-classes.ttl                 # known DL, not EL
    ql-conformant.ttl                    # known QL
    rl-conformant.ttl                    # known RL
    *.expected.json                      # ROBOT outputs for each

tests/unit/owl_profile/
    test_patterns_el.py
    test_patterns_rl.py
    test_patterns_ql.py
    test_structural_dl.py
    test_detector.py
    test_robot_regression.py

tests/integration/test_owl_profile_api.py

frontend/src/lib/api.ts                  # MODIFY: owl_profile namespace
frontend/src/pages/OwlProfile.tsx        # Fleet page
frontend/src/components/OwlProfileSection.tsx  # Per-version tab content
frontend/src/pages/OntologyPage.tsx      # MODIFY: add owl-profile tab
frontend/src/components/NavBar.tsx       # MODIFY: add link
frontend/src/App.tsx                     # MODIFY: route
frontend/src/components/OwlProfileSection.test.tsx
frontend/src/pages/OwlProfile.test.tsx
```

---

## Task 1: Foundation — module skeleton, cache key, dataclass, ROBOT fixtures

**Files:**
- Create: `ontoexplorer/modules/owl_profile/__init__.py`
- Create: `ontoexplorer/modules/owl_profile/registry.py`
- Create: `ontoexplorer/modules/owl_profile/cache.py`
- Create: `tests/unit/owl_profile/__init__.py`
- Create: `tests/unit/owl_profile/test_registry.py`
- Create: `tests/fixtures/owl_profile/el-only.ttl`
- Create: `tests/fixtures/owl_profile/disjoint-classes.ttl`
- Create: `tests/fixtures/owl_profile/el-only.expected.json`
- Create: `tests/fixtures/owl_profile/disjoint-classes.expected.json`

- [ ] **Step 1: Write failing test for registry constants** (`tests/unit/owl_profile/test_registry.py`):

```python
from ontoexplorer.modules.owl_profile.registry import (
    ProfileName, PROFILE_NAMES, ProfileViolation,
)


def test_profile_names_are_lowercase():
    assert PROFILE_NAMES == ("el", "rl", "ql", "dl")


def test_profile_violation_dataclass():
    v = ProfileViolation(profile="el", axiom_type="owl:DisjointClasses",
                          subject_iri="http://example.org/A", details="A disjoint with B")
    assert v.profile == "el"
    assert v.axiom_type == "owl:DisjointClasses"
    assert v.subject_iri == "http://example.org/A"


def test_profile_violation_subject_iri_optional():
    v = ProfileViolation(profile="dl", axiom_type="punning",
                         subject_iri=None, details="IRI used as both class and obj prop")
    assert v.subject_iri is None
```

- [ ] **Step 2: Run test, confirm fail** (`ModuleNotFoundError`). `uv run pytest tests/unit/owl_profile/test_registry.py -v`

- [ ] **Step 3: Implement `registry.py`**:

```python
"""Constants and dataclasses for OWL 2 profile detection."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

ProfileName = Literal["el", "rl", "ql", "dl"]
PROFILE_NAMES: tuple[ProfileName, ...] = ("el", "rl", "ql", "dl")


@dataclass(frozen=True)
class ProfileViolation:
    """One axiom that violates a profile."""
    profile: ProfileName
    axiom_type: str       # e.g. "owl:DisjointClasses", "punning", "role-hierarchy-cycle"
    subject_iri: str | None
    details: str          # human-readable
```

- [ ] **Step 4: Write failing test for cache helper** (`tests/unit/owl_profile/test_cache.py`):

```python
from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key

def test_cache_key_format():
    assert owl_profile_cache_key("abc-123") == "owl_profile:abc-123"
```

- [ ] **Step 5: Implement `cache.py`**:

```python
"""Redis cache key helpers for OWL profile detection."""

def owl_profile_cache_key(version_id: str) -> str:
    return f"owl_profile:{version_id}"
```

- [ ] **Step 6: Create empty `__init__.py`** for the module (just `from ontoexplorer.modules.owl_profile.registry import *`).

- [ ] **Step 7: Create ROBOT fixture files.** These are small `.ttl` files with `.expected.json` siblings recording what ROBOT would say. Two fixtures to start:

`tests/fixtures/owl_profile/el-only.ttl` (an ontology in all four profiles):

```turtle
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://example.org/elonly#> .

: a owl:Ontology .

:A a owl:Class .
:B a owl:Class ; rdfs:subClassOf :A .
:C a owl:Class ; rdfs:subClassOf :A .
:p a owl:ObjectProperty .
```

`tests/fixtures/owl_profile/el-only.expected.json`:

```json
{
  "el": {"in_profile": true, "total_violations": 0},
  "rl": {"in_profile": true, "total_violations": 0},
  "ql": {"in_profile": true, "total_violations": 0},
  "dl": {"in_profile": true, "total_violations": 0}
}
```

`tests/fixtures/owl_profile/disjoint-classes.ttl`:

```turtle
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://example.org/disjoint#> .

: a owl:Ontology .

:A a owl:Class .
:B a owl:Class .
:C a owl:Class .

[] a owl:AllDisjointClasses ; owl:members ( :A :B :C ) .
```

`tests/fixtures/owl_profile/disjoint-classes.expected.json`:

```json
{
  "el": {"in_profile": false, "violations_by_axiom_type": {"owl:AllDisjointClasses": 1}},
  "ql": {"in_profile": false, "violations_by_axiom_type": {"owl:AllDisjointClasses": 1}},
  "rl": {"in_profile": true},
  "dl": {"in_profile": true}
}
```

(Tasks 2-5 will add more fixtures as they implement each profile's patterns.)

- [ ] **Step 8: Run all unit tests, confirm pass.**

- [ ] **Step 9: Commit.**

```bash
git add ontoexplorer/modules/owl_profile/ tests/unit/owl_profile/ tests/fixtures/owl_profile/
git commit -m "feat(owl-profile): foundation — registry, cache key, ROBOT fixtures"
```

---

## Task 2: OWL 2 EL pattern set

**Files:**
- Create: `ontoexplorer/modules/owl_profile/patterns.py`
- Create: `tests/unit/owl_profile/test_patterns_el.py`

**Forbidden patterns for EL** (W3C OWL 2 Profiles §4.2):

The EL pattern catalog must detect axioms using these constructs (each is one SPARQL pattern):

| Axiom type | What to detect |
|---|---|
| `owl:DisjointClasses` (pairwise) | Triple `?x owl:disjointWith ?y` |
| `owl:AllDisjointClasses` | Triple `?x a owl:AllDisjointClasses` |
| `owl:disjointUnionOf` | Triple `?x owl:disjointUnionOf ?y` |
| `owl:complementOf` | Triple `?x owl:complementOf ?y` |
| `owl:unionOf` | Triple `?x owl:unionOf ?y` |
| `owl:allValuesFrom` | Triple `?x owl:allValuesFrom ?y` |
| `owl:oneOf` (with >1 individual) | `?x owl:oneOf (a b c)` where the list has 2+ items |
| `owl:hasValue` (object-property form) | `?x owl:hasValue ?ind` where `?ind` is an individual |
| `owl:hasSelf` | `?x owl:hasSelf true` |
| `owl:inverseOf` | `?p owl:inverseOf ?q` |
| `owl:FunctionalProperty` on object property | `?p a owl:FunctionalProperty, owl:ObjectProperty` |
| `owl:InverseFunctionalProperty` | `?p a owl:InverseFunctionalProperty` |
| `owl:IrreflexiveProperty` | `?p a owl:IrreflexiveProperty` |
| `owl:AsymmetricProperty` | `?p a owl:AsymmetricProperty` |
| `owl:SymmetricProperty` | `?p a owl:SymmetricProperty` |
| `owl:maxCardinality`/`owl:cardinality` | Any cardinality restriction (EL allows only existential) |
| `owl:minCardinality` | Same |
| `owl:NegativeObjectPropertyAssertion`/`owl:NegativeDataPropertyAssertion` | Negative-assertion axioms |

~17 patterns.

- [ ] **Step 1: Write failing test for one EL pattern** (each pattern follows the same shape — show one, then the rest mirror):

```python
import pyoxigraph
import pytest
from ontoexplorer.modules.owl_profile.patterns import EL_PATTERNS, run_pattern_count


def _store_from_turtle(ttl: str) -> pyoxigraph.Store:
    s = pyoxigraph.Store()
    s.load(ttl.encode("utf-8"), "text/turtle")
    return s


def test_el_disjoint_with_detected():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <http://example.org/> .
    :A a owl:Class ; owl:disjointWith :B .
    :B a owl:Class .
    """
    store = _store_from_turtle(ttl)
    p = next(pat for pat in EL_PATTERNS if pat.axiom_type == "owl:disjointWith")
    count, samples = run_pattern_count(store, None, p)
    assert count == 1
    assert samples and samples[0]["subject_iri"] == "http://example.org/A"


def test_el_pure_subclass_no_violations():
    ttl = """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix : <http://example.org/> .
    :A a owl:Class . :B a owl:Class ; rdfs:subClassOf :A .
    """
    store = _store_from_turtle(ttl)
    for p in EL_PATTERNS:
        count, _ = run_pattern_count(store, None, p)
        assert count == 0, f"{p.axiom_type} should not match on pure EL ontology"
```

- [ ] **Step 2: Run test, confirm fail.** `uv run pytest tests/unit/owl_profile/test_patterns_el.py -v`

- [ ] **Step 3: Implement `patterns.py`** with the EL pattern list:

```python
"""SPARQL pattern catalogs for OWL 2 profile detection."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import pyoxigraph

from ontoexplorer.modules.owl_profile.registry import ProfileName

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

_PREFIXES = f"""
PREFIX owl: <{_OWL}>
PREFIX rdf: <{_RDF}>
PREFIX rdfs: <{_RDFS}>
"""


@dataclass(frozen=True)
class Pattern:
    profile: ProfileName
    axiom_type: str
    count_sparql: str      # COUNT query, returns ?n
    sample_sparql: str     # SELECT ?subject LIMIT 10


def _make_basic_predicate_pattern(profile: ProfileName, axiom_type: str, predicate: str,
                                  graph_clause: str = "") -> Pattern:
    """Detect axioms of shape `?s <predicate> ?o`."""
    return Pattern(
        profile=profile, axiom_type=axiom_type,
        count_sparql=f"""{_PREFIXES}
            SELECT (COUNT(*) AS ?n) WHERE {{ {graph_clause}
                ?s <{predicate}> ?o .
            }}""",
        sample_sparql=f"""{_PREFIXES}
            SELECT ?s WHERE {{ {graph_clause}
                ?s <{predicate}> ?o .
            }} LIMIT 10""",
    )


def _make_basic_type_pattern(profile: ProfileName, axiom_type: str, rdf_class: str,
                             graph_clause: str = "") -> Pattern:
    """Detect axioms of shape `?s a <class>`."""
    return Pattern(
        profile=profile, axiom_type=axiom_type,
        count_sparql=f"""{_PREFIXES}
            SELECT (COUNT(*) AS ?n) WHERE {{ {graph_clause}
                ?s a <{rdf_class}> .
            }}""",
        sample_sparql=f"""{_PREFIXES}
            SELECT ?s WHERE {{ {graph_clause}
                ?s a <{rdf_class}> .
            }} LIMIT 10""",
    )


def _el_patterns(graph_clause: str = "") -> list[Pattern]:
    g = graph_clause
    p = lambda at, pred: _make_basic_predicate_pattern("el", at, pred, g)
    t = lambda at, cls: _make_basic_type_pattern("el", at, cls, g)
    cardinality_count = f"""{_PREFIXES}
        SELECT (COUNT(*) AS ?n) WHERE {{ {g}
            ?s ?card ?o .
            FILTER(?card IN (
                <{_OWL}cardinality>, <{_OWL}maxCardinality>, <{_OWL}minCardinality>,
                <{_OWL}qualifiedCardinality>, <{_OWL}maxQualifiedCardinality>,
                <{_OWL}minQualifiedCardinality>
            ))
        }}"""
    cardinality_sample = cardinality_count.replace("(COUNT(*) AS ?n)", "?s").replace("WHERE", "WHERE", 1) + " LIMIT 10"
    return [
        p("owl:disjointWith",          f"{_OWL}disjointWith"),
        t("owl:AllDisjointClasses",    f"{_OWL}AllDisjointClasses"),
        p("owl:disjointUnionOf",       f"{_OWL}disjointUnionOf"),
        p("owl:complementOf",          f"{_OWL}complementOf"),
        p("owl:unionOf",               f"{_OWL}unionOf"),
        p("owl:allValuesFrom",         f"{_OWL}allValuesFrom"),
        p("owl:hasValue",              f"{_OWL}hasValue"),
        p("owl:hasSelf",               f"{_OWL}hasSelf"),
        p("owl:inverseOf",             f"{_OWL}inverseOf"),
        t("owl:FunctionalProperty",        f"{_OWL}FunctionalProperty"),
        t("owl:InverseFunctionalProperty", f"{_OWL}InverseFunctionalProperty"),
        t("owl:IrreflexiveProperty",       f"{_OWL}IrreflexiveProperty"),
        t("owl:AsymmetricProperty",        f"{_OWL}AsymmetricProperty"),
        t("owl:SymmetricProperty",         f"{_OWL}SymmetricProperty"),
        Pattern(profile="el", axiom_type="owl:cardinality-restriction",
                count_sparql=cardinality_count, sample_sparql=cardinality_sample),
        t("owl:NegativeObjectPropertyAssertion", f"{_OWL}NegativeObjectPropertyAssertion"),
        t("owl:NegativeDataPropertyAssertion",   f"{_OWL}NegativeDataPropertyAssertion"),
        # owl:oneOf with >1 individual: detect any owl:oneOf usage (over-approximate; refine later)
        p("owl:oneOf",                 f"{_OWL}oneOf"),
    ]


EL_PATTERNS: list[Pattern] = _el_patterns()


def run_pattern_count(store: pyoxigraph.Store, graph_iri: str | None,
                       pattern: Pattern) -> tuple[int, list[dict]]:
    """Execute one pattern. Returns (violation_count, sample_subjects)."""
    # If graph_iri provided, the SPARQL templates need wrapping in GRAPH clauses.
    # For v1, we either include the GRAPH wrap at template construction time (per indexer call)
    # or assume the default graph if graph_iri is None (unit tests).
    count_result = list(store.query(pattern.count_sparql))
    count = int(count_result[0]["n"].value) if count_result else 0
    samples: list[dict] = []
    if count > 0:
        sample_result = store.query(pattern.sample_sparql)
        samples = [{"subject_iri": s["s"].value if hasattr(s["s"], "value") else str(s["s"])}
                  for s in sample_result]
    return count, samples
```

- [ ] **Step 4: Run EL pattern tests, confirm pass.**

- [ ] **Step 5: Add ROBOT regression fixture for EL.** Add `tests/fixtures/owl_profile/el-with-disjoint.ttl` containing a `disjointWith` axiom; add expected JSON saying not in EL with 1 violation.

- [ ] **Step 6: Add a `make_patterns(graph_iri)` factory** that wraps each pattern's SPARQL in a `GRAPH <{g}> { ... }` clause when a named graph is given. Tests use no graph; production uses a graph.

```python
def make_el_patterns(graph_iri: str | None) -> list[Pattern]:
    return _el_patterns(graph_clause=f"GRAPH <{graph_iri}> {{" if graph_iri else "")
    # ... close braces appropriately. Refine the template helpers to handle both cases.
```

Refine the template helpers so the `WHERE {{ {graph_clause} ...}}` produces valid SPARQL whether `graph_clause` is empty (default graph) or `GRAPH <g> {{ ... }}` (named graph). Test both cases.

- [ ] **Step 7: Commit.**

```bash
git commit -m "feat(owl-profile): OWL 2 EL forbidden-pattern detection"
```

---

## Task 3: OWL 2 RL pattern set

**Files:**
- Modify: `ontoexplorer/modules/owl_profile/patterns.py`
- Create: `tests/unit/owl_profile/test_patterns_rl.py`

**RL forbidden patterns** (W3C OWL 2 Profiles §5.2). RL has *positional* restrictions — different rules for subclass position (LHS of `rdfs:subClassOf`) vs superclass position (RHS). The simplest, most-impactful checks:

- `owl:oneOf` (forbidden anywhere except in subclass restricted forms)
- `owl:hasValue` of an individual (allowed on LHS, forbidden on RHS)
- Class union (`owl:unionOf`) — allowed only on LHS
- Existential (`owl:someValuesFrom`) — allowed only on LHS
- Cardinality with N > 1 — forbidden
- `owl:hasSelf` — forbidden
- `owl:disjointWith`, `owl:AllDisjointClasses` — RL allows pairwise disjoint (binary) but restricts
- `owl:propertyChainAxiom` — restricted forms

For v1, use the most conservative interpretation: detect occurrence of forbidden constructs anywhere. False positives on positional rules acceptable as long as they err on the side of "not in RL" rather than "in RL". Add a comment in `patterns.py` noting this; refine if user feedback comes in.

~8-10 RL patterns to add.

- [ ] **Step 1: Failing tests** for 3-4 representative RL patterns (oneOf, cardinality > 1, hasSelf).

- [ ] **Step 2: Implement** `_rl_patterns(graph_clause)` in `patterns.py` mirroring `_el_patterns`.

- [ ] **Step 3: Add ROBOT regression fixture** `rl-conformant.ttl` (pure SubClassOf chain; no forbidden constructs) and `not-rl.ttl` (uses `owl:hasSelf`).

- [ ] **Step 4: Run tests, commit.** `feat(owl-profile): OWL 2 RL forbidden-pattern detection`

---

## Task 4: OWL 2 QL pattern set

**Files:**
- Modify: `ontoexplorer/modules/owl_profile/patterns.py`
- Create: `tests/unit/owl_profile/test_patterns_ql.py`

**QL forbidden patterns** (W3C OWL 2 Profiles §6.2). QL is the most restrictive:
- LHS restrictions: only named classes and existentials over named properties allowed
- No class intersection on LHS
- No class union anywhere
- No cardinality restrictions
- No `owl:hasValue`
- No `owl:hasSelf`
- No `owl:DisjointClasses` between class expressions (only between named classes)
- Property characteristics: forbids functional, inverse-functional, transitive
- ... (full QL list per spec)

For v1, detect violations using union of the EL forbidden patterns plus QL-specific extras.

~12 QL patterns total.

- [ ] **Step 1-4: Same pattern as Tasks 2-3.** Failing tests, impl, fixtures, commit.

`feat(owl-profile): OWL 2 QL forbidden-pattern detection`

---

## Task 5: OWL 2 DL structural checks

**Files:**
- Create: `ontoexplorer/modules/owl_profile/structural.py`
- Create: `tests/unit/owl_profile/test_structural_dl.py`
- Add fixtures: `punning.ttl`, `role-hierarchy-cycle.ttl`, `bad-datatype.ttl`

OWL 2 DL violations are structural — must detect:

### 1. Punning restrictions (W3C OWL 2 §3.5)

OWL 2 *allows* class-individual punning but FORBIDS:
- Same IRI used as both **annotation property** AND **(object|data) property**
- Same IRI used as both **datatype** AND **class**
- Same IRI used as **datatype property** AND **object property**

Check via SPARQL: for each IRI declared as `owl:AnnotationProperty`, check it's not also declared as `owl:ObjectProperty` or `owl:DatatypeProperty`. Similarly for the other forbidden punnings.

```python
PUNNING_CHECK_SPARQL = f"""{_PREFIXES}
SELECT DISTINCT ?iri ?type1 ?type2 WHERE {{ {graph_clause}
  ?iri a ?type1 .
  ?iri a ?type2 .
  FILTER(?type1 != ?type2)
  FILTER(
    (?type1 = owl:AnnotationProperty && ?type2 IN (owl:ObjectProperty, owl:DatatypeProperty))
    || (?type1 = owl:DatatypeProperty && ?type2 = owl:ObjectProperty)
  )
}} LIMIT 100"""
```

### 2. Role hierarchy cycles for transitive properties (W3C OWL 2 §11.2)

If a property is transitive (`?p a owl:TransitiveProperty`), then the role hierarchy involving it must not contain certain cycles. Simplified check: detect transitive properties that are also sub-properties of themselves (direct or transitively).

```python
TRANSITIVE_CYCLE_CHECK_SPARQL = f"""{_PREFIXES}
SELECT ?p WHERE {{ {graph_clause}
  ?p a owl:TransitiveProperty .
  ?p rdfs:subPropertyOf+ ?p .   # SPARQL property path
}}"""
```

(Full role hierarchy check per spec is more complex; v1 catches the obvious case.)

### 3. Datatype restrictions (W3C OWL 2 §10)

Only specific datatypes are allowed in OWL 2 DL. Check that all `rdfs:Datatype` declarations and all `^^xsd:...` literal datatypes used are in the OWL 2 datatype map:

```python
ALLOWED_OWL2_DATATYPES = {
    "http://www.w3.org/2001/XMLSchema#string",
    "http://www.w3.org/2001/XMLSchema#integer",
    "http://www.w3.org/2001/XMLSchema#decimal",
    "http://www.w3.org/2001/XMLSchema#double",
    "http://www.w3.org/2001/XMLSchema#float",
    "http://www.w3.org/2001/XMLSchema#boolean",
    "http://www.w3.org/2001/XMLSchema#dateTime",
    "http://www.w3.org/2001/XMLSchema#dateTimeStamp",
    "http://www.w3.org/2001/XMLSchema#anyURI",
    "http://www.w3.org/2000/01/rdf-schema#Literal",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#PlainLiteral",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#XMLLiteral",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
    # ... full list per spec §10.2
}
```

Check via SPARQL: any literal whose datatype IRI is not in the allowed set.

### 4. Reserved vocabulary check

OWL 2 reserves certain IRIs (everything in `owl:`, `rdf:`, `rdfs:`, `xsd:` core namespaces). They cannot be redefined as user classes/properties. Detect any triple where a reserved IRI appears as the *subject* of a user declaration (e.g., `owl:Class a owl:Class` is fine; `owl:Class a owl:NamedIndividual` is a violation).

Bounded check via SPARQL on subject IRIs starting with the reserved namespace prefixes.

### Structural detector entry

```python
# structural.py
def detect_dl_violations(store, graph_iri: str | None) -> list[ProfileViolation]:
    violations = []
    violations.extend(_detect_punning(store, graph_iri))
    violations.extend(_detect_transitive_cycles(store, graph_iri))
    violations.extend(_detect_bad_datatypes(store, graph_iri))
    violations.extend(_detect_reserved_vocab(store, graph_iri))
    return violations
```

- [ ] **Step 1: Failing tests** — one synthetic fixture per check (punning, transitive cycle, bad datatype, reserved vocab).

- [ ] **Step 2: Implement `structural.py`** with one function per check + the aggregator.

- [ ] **Step 3: Add fixtures** `punning.ttl`, `role-hierarchy-cycle.ttl`, `bad-datatype.ttl` with `.expected.json`.

- [ ] **Step 4: Run tests, commit.** `feat(owl-profile): OWL 2 DL structural checks (punning, role cycles, datatypes, reserved vocab)`

---

## Task 6: Detector aggregator + indexer hook

**Files:**
- Create: `ontoexplorer/modules/owl_profile/detector.py`
- Modify: `ontoexplorer/modules/search/indexer.py`
- Create: `tests/unit/owl_profile/test_detector.py`
- Create: `tests/unit/owl_profile/test_robot_regression.py`

- [ ] **Step 1: Failing test for `detect_profiles`** (`tests/unit/owl_profile/test_detector.py`):

```python
import pytest, pyoxigraph
from ontoexplorer.modules.owl_profile.detector import detect_profiles


def test_pure_el_ontology_in_all_profiles():
    ttl = open("tests/fixtures/owl_profile/el-only.ttl").read()
    store = pyoxigraph.Store()
    store.load(ttl.encode("utf-8"), "text/turtle")
    result = detect_profiles(store, graph_iri=None, ontology_id="test", version_id="v1")
    assert result["el"]["in_profile"] is True
    assert result["rl"]["in_profile"] is True
    assert result["ql"]["in_profile"] is True
    assert result["dl"]["in_profile"] is True


def test_disjoint_classes_not_in_el():
    ttl = open("tests/fixtures/owl_profile/disjoint-classes.ttl").read()
    store = pyoxigraph.Store()
    store.load(ttl.encode("utf-8"), "text/turtle")
    result = detect_profiles(store, graph_iri=None, ontology_id="test", version_id="v1")
    assert result["el"]["in_profile"] is False
    assert "owl:AllDisjointClasses" in result["el"]["violations_by_axiom_type"]
    assert result["dl"]["in_profile"] is True  # DisjointClasses is allowed in DL


def test_punning_detected_as_dl_violation():
    ttl = open("tests/fixtures/owl_profile/punning.ttl").read()
    store = pyoxigraph.Store()
    store.load(ttl.encode("utf-8"), "text/turtle")
    result = detect_profiles(store, graph_iri=None, ontology_id="test", version_id="v1")
    assert result["dl"]["in_profile"] is False
    assert "punning" in result["dl"]["violations_by_axiom_type"]
```

- [ ] **Step 2: Implement `detector.py`**:

```python
"""Aggregate detector that runs all profile checks against a Pyoxigraph store."""
from __future__ import annotations
from datetime import datetime, timezone
import pyoxigraph

from ontoexplorer.modules.owl_profile.patterns import (
    make_el_patterns, make_rl_patterns, make_ql_patterns, run_pattern_count,
)
from ontoexplorer.modules.owl_profile.structural import detect_dl_violations


def detect_profiles(store: pyoxigraph.Store, graph_iri: str | None,
                     ontology_id: str, version_id: str) -> dict:
    result = {}
    for profile, patterns in (
        ("el", make_el_patterns(graph_iri)),
        ("rl", make_rl_patterns(graph_iri)),
        ("ql", make_ql_patterns(graph_iri)),
    ):
        violations_by_type: dict[str, int] = {}
        samples: list[dict] = []
        for pat in patterns:
            count, sample_rows = run_pattern_count(store, graph_iri, pat)
            if count > 0:
                violations_by_type[pat.axiom_type] = count
                for s in sample_rows:
                    samples.append({"axiom_type": pat.axiom_type, **s})
        total = sum(violations_by_type.values())
        result[profile] = {
            "in_profile": total == 0,
            "total_violations": total,
            "violations_by_axiom_type": violations_by_type,
            "sample_violations": samples[:50],
        }
    # DL: structural checks
    dl_violations = detect_dl_violations(store, graph_iri)
    by_type: dict[str, int] = {}
    for v in dl_violations:
        by_type[v.axiom_type] = by_type.get(v.axiom_type, 0) + 1
    result["dl"] = {
        "in_profile": len(dl_violations) == 0,
        "total_violations": len(dl_violations),
        "violations_by_axiom_type": by_type,
        "sample_violations": [
            {"axiom_type": v.axiom_type, "subject_iri": v.subject_iri, "details": v.details}
            for v in dl_violations[:50]
        ],
    }
    result["indexed_at"] = datetime.now(timezone.utc).isoformat()
    return result
```

- [ ] **Step 3: Implement `test_robot_regression.py`** that iterates `tests/fixtures/owl_profile/*.ttl` + `.expected.json` pairs, loads the TTL, runs `detect_profiles`, compares the `in_profile` boolean per profile against the expected.

- [ ] **Step 4: Wire detector into indexer.** In `ontoexplorer/modules/search/indexer.py`, around line 484 (after `_populate_coverage_cache`):

```python
_populate_owl_profile_cache(version_id, ontology_id, store, r)
```

And define the helper near the other cache populators (around line 754):

```python
def _populate_owl_profile_cache(version_id, ontology_id, store, r):
    from ontoexplorer.modules.owl_profile.detector import detect_profiles
    from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
    from ontoexplorer.clients.oxigraph import graph_iri as _graph_iri
    g = _graph_iri(ontology_id, version_id)
    payload = detect_profiles(store, graph_iri=g, ontology_id=ontology_id, version_id=version_id)
    r.setex(owl_profile_cache_key(version_id), _SEARCH_TTL, json.dumps(payload))
```

Add invalidation in `invalidate_index`:

```python
from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
to_delete.append(owl_profile_cache_key(version_id))
```

- [ ] **Step 5: Run all unit tests + a manual indexer smoke test** (re-index one small ontology and confirm `redis-cli get owl_profile:{vid}` returns JSON).

- [ ] **Step 6: Commit.** `feat(owl-profile): detector aggregator + indexer integration`

---

## Task 7: API endpoints

**Files:**
- Create: `ontoexplorer/api/owl_profile.py`
- Modify: `ontoexplorer/main.py` (include router)
- Modify: `ontoexplorer/api/ontologies.py` (add `?profile=` filter to list endpoint)
- Modify: `ontoexplorer/api/ols/ontologies.py` (same filter on OLS list)
- Create: `tests/integration/test_owl_profile_api.py`

**Endpoints:**
- `GET /api/v1/ontologies/{ontology_id}/{version_id}/owl-profile` — per-version detail
- `GET /api/v1/owl-profile/public` — fleet rollup
- `?profile=el|rl|ql|dl` on existing `/api/v1/ontologies` and `/ols/api/ontologies` and `/ols/api/v2/ontologies` list endpoints

- [ ] **Step 1: Failing integration tests.** Mirror `tests/integration/test_coverage_api.py` patterns. Cover:
  1. Per-version returns cached payload
  2. 404 when cache missing
  3. Fleet rollup aggregates correctly
  4. `?profile=el` filter excludes non-EL ontologies
  5. `?profile=invalid` returns 422

- [ ] **Step 2: Implement `owl_profile.py`**:

```python
"""OWL 2 profile endpoints — read-only views over the Redis owl_profile cache."""
import asyncio, json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
from ontoexplorer.modules.owl_profile.registry import PROFILE_NAMES
from ontoexplorer.modules.search.indexer import _get_redis

router = APIRouter(prefix="/api/v1", tags=["owl-profile"])


@router.get("/ontologies/{ontology_id}/{version_id}/owl-profile",
            summary="Per-version OWL 2 profile classification")
async def get_version_profile(ontology_id: str, version_id: str):
    r = _get_redis()
    raw = await asyncio.to_thread(r.get, owl_profile_cache_key(version_id))
    if raw is None:
        raise HTTPException(404, detail="OWL profile not computed — reindex pending")
    return json.loads(raw)


@router.get("/owl-profile/public", summary="Fleet OWL profile rollup (no auth)")
async def get_fleet_profile(db: AsyncSession = Depends(get_db)):
    # Same subquery pattern as coverage fleet
    subq = (
        select(OntologyVersion.ontology_id,
               func.max(OntologyVersion.created_at).label("max_created"))
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id).subquery()
    )
    rows = (await db.execute(
        select(OntologyVersion.id, OntologyVersion.ontology_id,
               Ontology.shortname, Ontology.title)
        .join(subq, (OntologyVersion.ontology_id == subq.c.ontology_id)
                    & (OntologyVersion.created_at == subq.c.max_created))
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
    )).all()

    r = _get_redis()
    keys = [owl_profile_cache_key(str(row.id)) for row in rows]
    payloads = await asyncio.to_thread(lambda: r.mget(keys) if keys else [])

    ontologies = []
    totals = {f"{p}_count": 0 for p in PROFILE_NAMES}
    totals["fleet_size"] = 0
    for row, raw in zip(rows, payloads):
        if not raw:
            continue
        data = json.loads(raw)
        entry = {
            "id": row.ontology_id, "shortname": row.shortname, "title": row.title,
            "version_id": str(row.id),
        }
        totals["fleet_size"] += 1
        for p in PROFILE_NAMES:
            in_p = data.get(p, {}).get("in_profile", False)
            entry[f"in_{p}"] = in_p
            entry[f"{p}_violations"] = data.get(p, {}).get("total_violations", 0)
            if in_p:
                totals[f"{p}_count"] += 1
        ontologies.append(entry)
    return {"ontologies": ontologies, "totals": totals}
```

- [ ] **Step 3: Mount in `main.py`.** Add the import and `include_router`. Place after `coverage_router`:

```python
from ontoexplorer.api.owl_profile import router as owl_profile_router
# ...
app.include_router(owl_profile_router)
```

- [ ] **Step 4: Add `?profile=` filter to existing list endpoints.** In `ontoexplorer/api/ontologies.py`, find the list endpoint (`@router.get("", summary="List ontologies")`). Add a `profile: str | None = Query(None)` parameter. After fetching ontology rows, if `profile` is set:
  - Validate it's in `PROFILE_NAMES`; 422 if not
  - For each row's latest ready version, lookup `owl_profile_cache_key(vid)` from Redis
  - Filter to rows where `data[profile]["in_profile"] is True`

Same filter on `ontoexplorer/api/ols/ontologies.py` list endpoints (HAL v1 and v2 flat).

- [ ] **Step 5: Run all tests + manual curl smoke test.**

- [ ] **Step 6: Commit.** `feat(owl-profile): API endpoints + ?profile= search filter`

---

## Task 8: Frontend

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/pages/OwlProfile.tsx`
- Create: `frontend/src/components/OwlProfileSection.tsx`
- Modify: `frontend/src/pages/OntologyPage.tsx`
- Modify: `frontend/src/components/NavBar.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/components/OwlProfileSection.test.tsx`
- Create: `frontend/src/pages/OwlProfile.test.tsx`

### `lib/api.ts` additions

```typescript
export type ProfileName = 'el' | 'rl' | 'ql' | 'dl'
export interface ProfileResult {
  in_profile: boolean
  total_violations: number
  violations_by_axiom_type: Record<string, number>
  sample_violations: Array<{ axiom_type: string; subject_iri?: string; details?: string }>
}
export interface OwlProfileRecord {
  el: ProfileResult
  rl: ProfileResult
  ql: ProfileResult
  dl: ProfileResult
  indexed_at: string
}
export interface OwlProfileFleetEntry {
  id: string; shortname?: string; title?: string; version_id: string
  in_el: boolean; in_rl: boolean; in_ql: boolean; in_dl: boolean
  el_violations: number; rl_violations: number; ql_violations: number; dl_violations: number
}
export interface OwlProfileFleet {
  ontologies: OwlProfileFleetEntry[]
  totals: { fleet_size: number; el_count: number; rl_count: number; ql_count: number; dl_count: number }
}

owl_profile: {
  fleet: () => request<OwlProfileFleet>('/owl-profile/public'),
  version: (ontologyId, versionId) =>
    request<OwlProfileRecord>(`/ontologies/${ontologyId}/${versionId}/owl-profile`),
}
```

### `OwlProfileSection.tsx` (per-version tab content)

- 4-up card layout: EL ✅ / RL ❌ / QL ❌ / DL ✅ with violation counts under each badge
- For each non-conformant profile: expandable section showing `violations_by_axiom_type` as a sorted list with counts; below it, `sample_violations` table showing the first 10 axioms per type
- Last-computed timestamp footer
- "Not yet computed" placeholder when API returns 404

### `OwlProfile.tsx` (fleet page)

- Summary cards top: "12 of 20 ontologies in OWL 2 EL" etc., 4 cards
- Sortable table: Ontology | EL | RL | QL | DL | Violations summary
- Each row links to `/ontologies/{slug}#owl-profile`
- Filter pill: All | EL | RL | QL | DL

### Routing + nav

- Add `/owl-profile` to `App.tsx`
- Add nav link in `NavBar.tsx`: `{ to: '/owl-profile', label: 'OWL Profile' }`

### `OntologyPage.tsx` modifications

- Extend `detailTab` state union with `'owl-profile'`
- Add the tab button
- Add the conditional `<OwlProfileSection .../>` render
- Extend the hash-link `useEffect` to recognize `#owl-profile`

### Tests

3-4 component tests for `OwlProfileSection.test.tsx` (renders, expands a profile, shows placeholder). 3-4 for `OwlProfile.test.tsx` (table renders, sorts, filter pill works).

- [ ] **Step 1-N:** Same TDD pattern as the Coverage frontend work (see git log around `950e6c9`/`5b09d10` for reference patterns).

- [ ] **Final step: Commit.** `feat(owl-profile): per-onto tab + fleet page + search filter UI`

---

## Task 9: Documentation + memory

- [ ] Strike through `OWL profile detection — OWL 2 DL / EL / RL / QL classification` line in `docs/ideas.md` with the ship date and a brief note linking to the spec
- [ ] Add `### OWL 2 profiles (/owl-profile)` subsection in `README.md` under "Using the Browser" and a small API Reference entry
- [ ] Update memory: add `[OWL profile detection](feature_owl_profile_detection.md)` pointer to MEMORY.md, create the memory file
- [ ] Commit: `docs(owl-profile): README + ideas.md update for shipped OWL profile detection`

---

## Final verification

- [ ] All unit tests pass: `uv run pytest tests/unit/owl_profile/ tests/integration/test_owl_profile_api.py -v`
- [ ] Frontend tests pass: `cd frontend && npm test`
- [ ] No regression: `uv run pytest tests/integration/ tests/unit/ -v` (modulo the SPARQL pre-existing fails)
- [ ] Manual smoke: reindex one ontology with known profile membership (e.g. a small EL-conformant ontology), then `curl http://localhost:8000/api/v1/ontologies/<id>/<vid>/owl-profile | jq` and confirm `el.in_profile = true`
- [ ] App boots: `uv run python -c "from ontoexplorer.main import app; print(len(app.routes))"`
- [ ] Use **superpowers:finishing-a-development-branch** to complete.
