# OWL 2 Profile Detection

OntoExplorer classifies every indexed ontology version against the four
W3C OWL 2 profiles — **EL**, **RL**, **QL**, and **DL** — using SPARQL ASK/COUNT
queries against the in-process pyoxigraph store. The result is cached in Redis
at indexing time, surfaced via API, per-ontology page tab, fleet page, and
search filter. **The standalone detector** ships separately as the
`pyowl2-profiles` PyPI library (https://github.com/MaastrichtU-IDS/pyowl2-profiles).

## Why this matters

OWL 2 profile membership drives reasoner choice and tooling compatibility:

| Profile | Reasoner family | Typical domain |
|---------|----------------|----------------|
| **EL**  | ELK, jcel | Biomedical (GO, ChEBI, HP, SNOMED) |
| **RL**  | Rule engines (SWRL, RIF, Datalog) | Schema validation, RDF-based reasoning |
| **QL**  | Query rewriters (DL-Lite) | Database integration |
| **DL**  | HermiT, Pellet, FaCT++ | General OWL DL |

Classifying every loaded ontology gives FAIR users a quick "what can I run on
this?" answer without re-validating each time.

## Architecture

```
ontoexplorer/modules/owl_profile/
    __init__.py           # exports
    registry.py           # ProfileName, PROFILE_NAMES, ProfileViolation
    cache.py              # Redis cache key helpers
    patterns.py           # SPARQL pattern catalogs (EL/RL/QL ~45 patterns + RL positional)
    structural.py         # DL structural checks (punning, role cycles, undeclared-property, reserved vocab)
    detector.py           # detect_profiles() — runs all checks, returns cache payload
```

**Detection runs at indexing time** via `_populate_owl_profile_cache` in
`ontoexplorer/modules/search/indexer.py` — same path as the coverage cache.
Reading is a single Redis fetch (microseconds); detection only re-runs on
reindex.

**Refresh-only path:** the `ontoexplorer.refresh_owl_profile` celery task
rebuilds JUST the OWL profile cache without re-running the search indexer or
embeddings — useful after detector bug fixes. Script at
`scripts/owl_profile_bench/refresh_cache.py`.

## API surface

```
GET /api/v1/ontologies/{ontology_id}/{version_id}/owl-profile
GET /api/v1/owl-profile/public                                 # fleet rollup
GET /api/v1/ontologies?profile=el|rl|ql|dl                     # filter
GET /ols/api/ontologies?profile=el|rl|ql|dl                    # filter (OLS shim)
```

Per-version response shape:

```json
{
  "el": {
    "in_profile": false,
    "total_violations": 34,
    "violations_by_axiom_type": {"owl:inverseOf": 10, "owl:allValuesFrom": 9, ...},
    "sample_violations": [
      {"axiom_type": "owl:inverseOf", "subject_iri": "https://...", "manchester": [...]},
      ...
    ]
  },
  "rl": {...},
  "ql": {...},
  "dl": {...},
  "indexed_at": "2026-05-20T12:34:56+00:00"
}
```

Each sample optionally carries a `manchester` field — an array of
text/IRI tokens rendered via the existing `ontoexplorer.modules.diff.manchester`
verbalizer. The frontend `ManchesterInline` component renders these.

## Frontend

- **Per-ontology tab:** `OwlProfileSection` (`frontend/src/components/`) — four
  cards (EL/RL/QL/DL) with badges, expandable details showing violations
  grouped by axiom type plus up to 10 sample axioms in Manchester syntax.
- **Fleet view:** `OwlProfile` page rendered as a tab inside `Ontologies.tsx`
  at `/ontologies?tab=profiles` — sortable table + summary cards + filter pill.
- **Hash routing:** `/ontologies/{slug}#owl-profile` opens the tab directly.

## Validation against ROBOT

The detector was validated against ROBOT 1.9.10 (the OBO Foundry standard,
using OWL-API + HermiT) on a 19-ontology fleet covering ~100 to ~900K triples.
**Verdict agreement: 19/19 (100%) across all four profiles.**

Detection performance vs ROBOT cold-start:

| Ontology | Triples | Ours (load + detect) | ROBOT (4 profiles) | Speedup |
|----------|--------:|---------------------:|-------------------:|--------:|
| sulo     | 374     | 0.01s                | 7s                 | ~700× |
| ro       | 12K     | 0.13s                | 11s                | ~85× |
| obi      | 116K    | 0.81s                | 21s                | ~26× |
| hp       | 908K    | 8s                   | 108s               | ~13× |

Production reads from cache are constant-time HTTP fetches (microseconds).
Indexing-time detection adds ~5s to HP-class indexing — negligible against
the existing indexer cost.

**Memory headroom:** our SPARQL-over-Oxigraph approach reuses the
already-loaded store; ROBOT loads each ontology a second time into OWL-API's
in-memory model (~2 GB for HP, projected ~16 GB for NCBITaxon). For
NCBITaxon-class data the difference is "fits in the worker container" vs
"OOM-kill."

## Spec-correctness notes

The detector matches what real OWL DL reasoners (HermiT, Pellet, ROBOT) accept,
which sometimes diverges from a literal reading of the W3C spec:

- **`xsd:date`, `xsd:duration`, `xsd:time`, `xsd:g*`**: strictly omitted from
  W3C OWL 2 datatype map (§4.1), but HermiT accepts them. We disabled the
  datatype-map check entirely — empirically HermiT accepts ANY datatype IRI
  including fabricated custom ones, making the strict check pointless.
- **EL/RL/QL ⊂ DL propagation**: spec-correct; if DL=OUT then EL/RL/QL must
  also be OUT. ROBOT enforces this transitively, so do we.
- **Pairwise disjointness in EL/QL** (`owl:disjointWith` between named
  classes): allowed in EL (§4.2) and QL (§6.2). Previously flagged as
  spec-incorrect; now correctly accepted.
- **`owl:hasValue` in EL**: allowed (`ObjectHasValue` reduces to
  `ObjectSomeValuesFrom` over a singleton `ObjectOneOf`). Previously
  over-flagged.

## Detection pipeline summary

For each profile (EL/RL/QL):
1. Iterate the catalog of forbidden SPARQL patterns (~45 total)
2. For each pattern, count matches via `SELECT (COUNT(*) AS ?n)`
3. If count > 0, fetch up to 10 sample violations via `SELECT ... LIMIT 10`
4. Render each sample to Manchester syntax tokens via `render_axiom`

For DL:
1. Run 4 structural checks: punning, role hierarchy cycles, reserved
   vocabulary, undeclared properties
2. Each check returns a list of `ProfileViolation` instances

Aggregator merges results and propagates DL=OUT to EL/RL/QL=OUT per spec.

## Standalone library

The core detector ships as a separate PyPI package, `pyowl2-profiles`, so the
detection logic is usable outside OntoExplorer. The library includes everything
in `ontoexplorer/modules/owl_profile/` plus an extracted Manchester renderer
and a CLI for ROBOT comparison.

See https://github.com/MaastrichtU-IDS/pyowl2-profiles for installation,
usage, and API documentation.
