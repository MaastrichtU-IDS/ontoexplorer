# OWL 2 Profile Detection — Design

**Status:** Draft for review
**Date:** 2026-05-19
**Author:** Michel Dumontier (with Claude)

## Goal

Per OWL 2 spec (https://www.w3.org/TR/owl2-profiles/), classify every indexed ontology version against the four W3C OWL 2 profiles — **EL**, **RL**, **QL**, and **DL** — by detecting forbidden axiom patterns via SPARQL ASK/COUNT queries against the already-loaded Oxigraph store. Result is cached at indexing time and surfaced via a new `/owl-profile` API plus per-ontology page tab, fleet page, and `?profile=` search filter.

## Non-goals

- Bug-for-bug parity with ROBOT (we'll use it once for regression validation, not at runtime)
- Profile *repair* — only detection. "How do I fix the EL violations" is a future feature.
- Full **OWL 2 Full** detection — Full has no syntactic restrictions beyond well-formedness; treat any ontology that parses as Full.

## Why SPARQL over ROBOT

Validated in pre-design discussion. Summary:
- ROBOT loads the ontology a second time into OWL-API → ~16 GB heap for NCBITaxon, ~5 min wall time
- SPARQL ASK against Oxigraph reuses already-loaded data → estimated <60s for NCBITaxon, no extra memory
- No JVM dep in the worker container
- W3C profiles are syntactic restrictions on axiom shape → SPARQL pattern-matching is the natural implementation

Risk (we own spec implementation) is mitigated by a **ROBOT regression test set**: a small curated collection of ontologies with known ROBOT profile classifications. We validate our detector against those once; CI runs it on every change.

## Scope

### Profiles detected

All 4 W3C profiles:
- **OWL 2 EL** — fragment tailored for very large ontologies with simple axioms (biomedical: GO, ChEBI, HP, SNOMED). Allows existential restrictions, intersection, subclass; forbids inverse properties, functional properties, disjointness, full negation, universal restrictions.
- **OWL 2 RL** — fragment compatible with rule-based reasoning (SWRL/RIF/Datalog). Restricts what can appear on left- vs right-hand sides of subclass axioms.
- **OWL 2 QL** — fragment for query rewriting (DL-Lite). Very restrictive on class expressions.
- **OWL 2 DL** — decidable fragment. Almost everything OWL 2 allows, with structural restrictions (no punning of classes/properties, no cycles in role hierarchies for transitive roles, no datatype-property/object-property mixing, etc.).

For each profile, the detector reports:

```json
{
  "el": {
    "in_profile": false,
    "total_violations": 47,
    "violations_by_axiom_type": {
      "owl:DisjointClasses": 12,
      "owl:inverseOf": 3,
      "owl:FunctionalProperty": 8,
      "owl:complementOf": 1,
      "rdfs:subClassOf-with-allValuesFrom": 23
    },
    "sample_violations": [
      {"axiom_type": "owl:DisjointClasses", "iris": ["http://...", "http://..."]},
      ...
    ]
  },
  "rl": { ... },
  "ql": { ... },
  "dl": { "in_profile": true, "total_violations": 0, ... }
}
```

`sample_violations` is capped at 10 per axiom type — enough to give users concrete examples without bloating the response.

## Architecture

### File layout

```
ontoexplorer/modules/owl_profile/
    __init__.py
    detector.py             # Public entry: detect_profiles(version_id, db, r) → dict
    patterns.py             # SPARQL templates per (profile, forbidden-pattern)
    registry.py             # ProfileViolation dataclass, profile-name constants
    cache.py                # owl_profile_cache_key, _SEARCH_TTL, JSON shape

ontoexplorer/api/
    owl_profile.py          # Routes (see API section below)

ontoexplorer/modules/search/
    indexer.py              # MODIFY: call _populate_owl_profile_cache(...) after coverage

frontend/src/
    pages/OwlProfile.tsx    # Fleet page
    components/OwlProfileSection.tsx   # Per-version tab content
    lib/api.ts              # MODIFY: add owl_profile namespace
    pages/OntologyPage.tsx  # MODIFY: add 'owl-profile' tab
    components/NavBar.tsx   # MODIFY: add /owl-profile link
    App.tsx                 # MODIFY: route

tests/unit/owl_profile/
    test_detector.py        # Each forbidden pattern, against synthetic graphs
    test_robot_regression.py # Smoke-validate against ROBOT outputs

tests/integration/
    test_owl_profile_api.py # Per-version + fleet + 404 + filter
```

The `owl_profile` module mirrors `coverage` — both are Redis-cached results computed at index time from the same loaded data.

### Forbidden-pattern catalog (`patterns.py`)

Each entry is a triple of `(profile, axiom_type, sparql_template)`. The SPARQL detects the *existence* (ASK) or *count* (COUNT with LIMIT 1000) of axioms matching the forbidden pattern.

**OWL 2 EL** forbidden patterns (W3C OWL 2 Profiles §4.2):
- `owl:DisjointClasses` (binary form too)
- `owl:disjointUnionOf`
- `owl:complementOf`
- `owl:oneOf` with more than one individual
- `owl:unionOf` (any use)
- `owl:hasValue`-of-individual (only allowed for data properties; restricted forms)
- `owl:allValuesFrom`
- `owl:inverseOf`
- `owl:FunctionalProperty` on object properties
- `owl:InverseFunctionalProperty`
- `owl:IrreflexiveProperty`
- `owl:AsymmetricProperty`
- `owl:SymmetricProperty` (on object properties)
- `owl:propertyChainAxiom` with restricted forms (most chains are allowed but with rules)
- `owl:hasSelf`
- Property cardinality (`owl:maxCardinality`, `owl:cardinality`, `owl:minCardinality`)
- Equivalent-classes via class-expression-with-disjunction

**OWL 2 QL** forbidden patterns (§6.2):
- Existential restrictions on the LEFT side of `rdfs:subClassOf`
- Class intersection on the LEFT side
- Class union (anywhere)
- Cardinality restrictions
- `owl:hasValue`
- Most things — QL is the most restrictive

**OWL 2 RL** forbidden patterns (§5.2):
- Different rules for subclass-superclass position
- LHS: allows existential, intersection, class IRIs; forbids `oneOf`, `unionOf`, cardinality
- RHS: allows intersection, complement, universal, cardinality ≤0/≤1; forbids `unionOf`, `oneOf`

**OWL 2 DL** forbidden patterns:
- Punning (a single IRI used as both class and individual — wait, OWL 2 explicitly *allows* punning for class-property and class-individual, but with annotation-property-vs-others restriction)
- Cycles in datatype hierarchies
- Use of reserved vocabulary in non-meta positions
- Property chain cycles for transitive properties

A full enumeration lives in `patterns.py`; full count ~30-45 SPARQL templates total across all profiles.

### Storage shape

Redis key: `owl_profile:{version_id}` → JSON-encoded dict matching the response shape above, plus an `indexed_at` ISO timestamp.

TTL: same `_SEARCH_TTL` as coverage (30 days).

Postgres: no new schema; Redis is sufficient because the result is deterministically reproducible from the indexed ontology.

### Detection pipeline

```python
# ontoexplorer/modules/owl_profile/detector.py

def detect_profiles(version_id: str, ontology_id: str, store, r) -> dict:
    """Run all OWL 2 profile checks against the in-memory Oxigraph store.

    Returns the cache payload. Called from the indexer at the end of indexing,
    on the same thread that already holds the store reference."""
    g = graph_iri(ontology_id, version_id)
    result = {}
    for profile_name in ("el", "rl", "ql", "dl"):
        violations_by_type = {}
        sample_violations = []
        for pattern in PATTERNS[profile_name]:
            count, samples = _run_pattern(store, g, pattern)
            if count > 0:
                violations_by_type[pattern.axiom_type] = count
                sample_violations.extend(samples)
        total = sum(violations_by_type.values())
        result[profile_name] = {
            "in_profile": total == 0,
            "total_violations": total,
            "violations_by_axiom_type": violations_by_type,
            "sample_violations": sample_violations[:50],
        }
    result["indexed_at"] = datetime.now(timezone.utc).isoformat()
    return result
```

`_run_pattern` issues one COUNT query (LIMIT 1000) + one SELECT for samples (LIMIT 10) per pattern.

### Indexer hook

In `ontoexplorer/modules/search/indexer.py`, after `_populate_coverage_cache(...)` (around line 484), add:

```python
_populate_owl_profile_cache(version_id, ontology_id, store, r)
```

with the helper defined alongside `_populate_coverage_cache`:

```python
def _populate_owl_profile_cache(version_id, ontology_id, store, r):
    from ontoexplorer.modules.owl_profile.detector import detect_profiles
    from ontoexplorer.modules.owl_profile.cache import owl_profile_cache_key
    payload = detect_profiles(version_id, ontology_id, store, r)
    r.setex(owl_profile_cache_key(version_id), _SEARCH_TTL, json.dumps(payload))
```

Invalidation: same pattern as coverage — add `owl_profile_cache_key(version_id)` to the delete list in `invalidate_index`.

## API surface

```
GET /api/v1/ontologies/{ontology_id}/{version_id}/owl-profile
GET /api/v1/owl-profile/public                      # fleet rollup
GET /api/v1/ontologies?profile=el                   # filter list endpoint by profile membership
```

Mounted via a new `owl_profile_router` with `prefix="/api/v1"`. Public — no auth (matches coverage).

### Per-version response

The full cache payload, including `sample_violations`.

### Fleet rollup `/owl-profile/public`

```json
{
  "ontologies": [
    {
      "id": "go", "shortname": "go", "title": "Gene Ontology",
      "version_id": "...",
      "in_el": true, "in_rl": false, "in_ql": false, "in_dl": true,
      "el_violations": 0, "rl_violations": 142, "ql_violations": 891, "dl_violations": 0
    },
    ...
  ],
  "totals": {
    "el_count": 12,
    "rl_count": 4,
    "ql_count": 2,
    "dl_count": 18,
    "fleet_size": 20
  }
}
```

### Search filter

Extend the existing `/api/v1/ontologies` list endpoint with `?profile=el|rl|ql|dl` (case-insensitive). When set, return only ontologies whose latest ready version is in that profile. Implementation: query the OntologyVersion table for ready versions, look up each version's cached `owl_profile:{vid}` in Redis, filter by `in_profile=true` for the requested profile, return matching ontologies.

Same filter applied to:
- `/api/v1/ontologies?profile=el`
- `/ols/api/ontologies?profile=el` (extend the OLS shim too — OLS clients may want this filter)

## UI

### Per-ontology page tab

New "OWL Profile" tab on `OntologyPage` (alongside existing Info / Profile / History / Coverage tabs). Layout:

- **Profile badges** (4-up): EL ✅ / RL ❌ / QL ❌ / DL ✅ with violation counts as small text
- For each profile that's not in:
  - Expandable section showing the **violations_by_axiom_type** breakdown as a bar chart or sorted list
  - "Sample violations" sub-table showing up to 10 example axiom IRIs per type
- "Last computed: <indexed_at>" footer
- If the cache is missing: "OWL profile not yet computed — will be available after the next reindex"

Hash link support: `#owl-profile` → switches to this tab, mirroring the `#coverage` pattern.

### Fleet page `/owl-profile`

Coverage-style table:
- One row per ontology
- Columns: Ontology | EL | RL | QL | DL | Violations summary
- Sortable; click a column header to sort
- Top-of-page summary cards: "12 of 20 ontologies in OWL 2 EL"
- Each ontology row links to `/ontologies/{slug}#owl-profile`

### Search filter

Add a "Profile" pill filter on the ontologies list page (and global search page) — radio selector for EL/RL/QL/DL/All. Translates to `?profile=el` in the API call.

## Testing strategy

### Unit (`tests/unit/owl_profile/`)

For each forbidden pattern in `patterns.py`:
- Synthesize a minimal RDF graph that triggers the pattern (e.g., for EL `owl:DisjointClasses` violation: 3 named classes with `owl:DisjointClasses` triple)
- Load into an in-memory Pyoxigraph store
- Run the corresponding SPARQL query
- Assert violation count is correct

~30-45 micro-tests, one per pattern. Fast (<1s total).

### ROBOT regression (`tests/unit/owl_profile/test_robot_regression.py`)

Curated test set of ~5 small ontologies with known ROBOT-computed profile classifications:
- Pizza ontology — known DL, not EL/RL/QL
- A pure EL subset of GO (custom small graph) — known EL
- A minimal QL ontology — known QL
- An ontology with `owl:DisjointClasses` only — known DL, not EL
- An ontology with no axioms beyond `rdfs:subClassOf` between named classes — known EL/RL/QL/DL

For each: load → detect → compare with the recorded ROBOT output. Mismatches fail the test.

These ontologies live in `tests/fixtures/owl_profile/` as `.ttl` files. The expected results live alongside as `.expected.json`. CI runs them on every change to `patterns.py` or `detector.py`.

### Integration (`tests/integration/test_owl_profile_api.py`)

Mirrors `tests/integration/test_coverage_api.py`:
- Per-version endpoint returns cached payload
- 404 when cache missing
- Fleet rollup aggregates correctly across multiple versions
- `?profile=el` filter excludes non-EL ontologies

### Frontend (`frontend/src/components/OwlProfileSection.test.tsx`, `OwlProfile.test.tsx`)

- Renders profile badges correctly
- Expanding a profile's violation section shows the type breakdown
- Fleet table sorts and filters
- "Not yet computed" placeholder for missing data

## Documentation

- `README.md`: add `### OWL 2 profiles (/owl-profile)` subsection under "Using the Browser" + entry in "API Reference"
- `docs/ideas.md`: strike through "OWL profile detection" with ship date
- Memory file in `~/.claude/.../memory/` named `feature_owl_profile_detection.md`

## Risks & open questions

1. **Spec implementation drift.** Our SPARQL templates approximate the W3C spec; subtle deviations from ROBOT are possible. Mitigation: the regression test set. Failure mode: a user trusts our "in EL" badge for an ontology that ROBOT would flag as not EL. Acceptable for v1 if the regression test set passes; users can always re-validate with ROBOT for authoritative output.

2. **Performance on NCBITaxon.** Estimated <60s but unverified until tested. If a single SPARQL query takes >30s, we degrade gracefully: cap each query at a hard timeout, mark that pattern as "could not evaluate" rather than failing the whole detection.

3. **DL profile detection is the hardest.** DL has *structural* restrictions (no punning, role hierarchy cycles for transitive roles) that need graph-traversal logic, not just per-axiom pattern matching. For v1 we may default DL to "in_profile = true if all other profile checks completed cleanly" — i.e. treat DL as the residual, NOT a strict check. This is documented under "Open question" — flag for user.

4. **`?profile=el` filter is O(N) per request.** It iterates all ready versions and Redis-looks-up each. With ~20 ontologies it's fine; at >1000 ontologies we'd want to maintain a reverse index (one Redis set per profile listing in-profile versions). Defer until needed.

5. **Sample IRI extraction.** For each violation pattern we record up to 10 sample axiom IRIs. The SPARQL must return *triples involving* the violation, but axioms in OWL/RDF often span multiple triples (a blank-node restriction). Sample format will be "the subject + the violating predicate" — enough to look the axiom up manually, not a full axiom serialization.

## Phased rollout

1. **Foundation:** `owl_profile/` module skeleton + cache key + ROBOT regression test fixtures
2. **EL pattern set:** implement detection for all EL forbidden patterns; pass regression tests against EL test cases
3. **RL + QL pattern sets:** add their forbidden patterns; pass their regression tests
4. **DL detection:** structural checks (or document the "residual" approximation if we defer)
5. **API endpoints:** `/owl-profile/version`, `/owl-profile/public`, `?profile=` filter
6. **Indexer hook:** wire into the existing indexing pipeline; reindex existing ontologies to populate caches
7. **Frontend:** per-onto tab, fleet page, search filter pill
8. **Docs + ideas.md strike-through**

Each phase is independently shippable.
