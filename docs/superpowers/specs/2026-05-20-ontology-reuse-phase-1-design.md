# Phase 1: Ontology Reuse Analysis — Design

## Context

OntoExplorer needs a thorough ontology-reuse analysis surface. The user has prior work at [bioportal-ontology-analysis](https://github.com/micheldumontier/bioportal-ontology-analysis) ([site](https://micheldumontier.github.io/bioportal-ontology-analysis/)) that measured reuse *breadth* across 1,272 BioPortal ontologies via raw IRI matching, OBO Foundry membership, and acronym fallback (16% upper-level adoption; mapping hubs identified). That work has three explicit gaps the user wants closed:

1. **No IRI normalization** — variant URI forms were not reconciled, so reuse counts are undercounts.
2. **No MIREOT-pattern detection** — terms reused via the MIREOT pattern (foreign-namespace IRI with minimal axiomatization, no `owl:imports`) were not separated from owl:imports-based reuse. The user has a specific worry: *MIREOT bypasses source constraints and is more likely to produce inconsistency downstream*.
3. **Per-ontology consistency only** — Matentzoglu-style joint-reasoning across an import closure was deliberately listed as future work.

The user's overall vision bundles four substantial subsystems: reuse signal extraction, IRI normalization, joint-reasoning consistency, and interactive dependency visualization. We agreed to decompose into three phased specs:

- **Phase 1 (this spec):** Reuse signals + bioregistry-normalized IRIs. Ships per-ontology and fleet-level reuse metrics in OntoExplorer; reruns the BioPortal population analysis with normalization + MIREOT applied.
- **Phase 2 (later):** Joint-reasoning consistency analysis — the headline novel result, addressing the user's MIREOT concern directly.
- **Phase 3 (later):** Interactive dependency visualization (React Flow class/property-level).

OntoExplorer already provides most of the foundation: the `OntologyImport` model + recursive `owl:imports` resolver tracks the import graph as structured data; every indexed entity carries a `source` field naming the import it came from; the diff engine performs IRI-based identity matching across ontologies. The frontend uses an established tab pattern at `/ontologies?tab=`. Phase 1 plugs into all of these.

## Goal (one sentence)

Ship a per-ontology and fleet-level reuse-analysis surface inside OntoExplorer that captures four reuse signals (imports closure, term-IRI reuse, MIREOT-pattern, mappings) with bioregistry-normalized IRIs, plus a parallel BioPortal-scale population rerun.

## Scope

**In scope:**
- Four reuse signals (all selected):
  - `owl:imports` closure (transitive, depth-tracked, bioregistry-normalized)
  - Term-IRI reuse (per class/property: native vs reused-from-X, aggregated per source prefix)
  - MIREOT-pattern detection (foreign-namespace IRI + minimal axiomatization + no `owl:imports` of source)
  - Mapping-based reuse (`skos:closeMatch`, `skos:exactMatch`, `oboInOwl:hasDbXref`, `owl:sameAs`)
- Bioregistry-backed IRI/prefix normalization (offline, uses the `bioregistry` PyPI package)
- Per-ontology API + UI ("Reuse" section on `OntologyPage.tsx`)
- Fleet-level API + UI ("Reuse" tab under `/ontologies?tab=reuse`)
- BioPortal-scale rerun as a separate script under `scripts/bioportal_reuse/`
- Redis cache + Celery `refresh_reuse` task (same shape as `refresh_owl_profile`)

**Out of scope (deferred to later phases):**
- Joint reasoning across import closure → Phase 2
- Axiom-level reuse provenance (which axiom came from which import) → Phase 2
- Interactive dependency-graph visualization (React Flow / cytoscape) → Phase 3
- Library extraction to a separate PyPI package — defer until API stabilizes and Phase 2 lands

## Architecture

### Module layout (new code lives here)

```
ontoexplorer/modules/reuse/
    __init__.py
    bioregistry.py        # IRI → canonical prefix resolver (Redis-cached)
    detector.py           # Aggregator: returns ReuseReport for one version
    cache.py              # Redis key helper: reuse:{version_id}
    signals/
        __init__.py
        imports.py        # owl:imports closure, bioregistry-normalized
        term_iri.py       # Per-entity IRI namespace classification
        mireot.py         # MIREOT-pattern detection via SPARQL
        mappings.py       # Mapping-predicate extraction via SPARQL
```

### Reuse signal definitions

**`owl:imports` closure (`signals/imports.py`):**
- Walks `OntologyImport` rows transitively for the version
- Each edge: `(source_version_id, target_iri, target_prefix, target_resource, depth)`
- `target_prefix` is resolved via bioregistry; falls back to declared base IRI if unresolved (flag `_unresolved`)
- Output: list of edges + computed closure (set of all transitively-imported IRIs)

**Term-IRI reuse (`signals/term_iri.py`):**
- For each indexed entity in the version: bucket the IRI's namespace via bioregistry → `native` or `reused-from-<prefix>`
- Reuses the existing `source` field in the Redis index; bioregistry normalization is applied on top to collapse variants (e.g., `purl.obolibrary.org/obo/RO_` vs `purl.org/obo/RO_` both resolve to `ro`)
- Aggregates per (host_prefix, source_prefix): `{class_count, property_count, sample_iris[≤5]}`

**MIREOT-pattern detection (`signals/mireot.py`):**
A term in version V qualifies as `mireot` if ALL hold:
1. IRI namespace resolves to a `target_prefix` ≠ V's `host_prefix` (foreign).
2. V does NOT have an `owl:imports` edge that closes over `target_prefix` (i.e., the source is NOT imported).
3. V's axiom signature for the term is at most: `rdfs:label`, ≤1 `rdfs:subClassOf` or `rdfs:subPropertyOf`, plus optionally `IAO:0000412` ("imported from") and standard annotation properties (`rdfs:comment`, `rdfs:isDefinedBy`).
4. NO axioms involving the term as subject for: `owl:equivalentClass`, `owl:disjointWith`, `rdfs:domain`, `rdfs:range`, `owl:Restriction` blank nodes, property characteristics.

A term is `import-reused` if 1 holds but the source IS in the import closure (rule 2 inverted).
A term is `native` if it does not satisfy rule 1.
Detection is via a single SPARQL query per version against the Oxigraph store (counts + ≤10 samples per source_prefix).

**Mapping-based reuse (`signals/mappings.py`):**
- Single SPARQL query enumerating predicates: `skos:closeMatch`, `skos:exactMatch`, `skos:relatedMatch`, `skos:broadMatch`, `skos:narrowMatch`, `oboInOwl:hasDbXref`, `owl:sameAs`
- Per (host, target_prefix, predicate): count + ≤5 sample subject/object pairs
- Target prefix resolved via bioregistry

### Bioregistry integration (`bioregistry.py`)

- Add `bioregistry>=0.11` to `pyproject.toml` (offline-curated prefix maps shipped with the package; no network calls in the hot path)
- Wrapper functions:
  - `iri_to_prefix(iri: str) -> tuple[str | None, bool]` — returns `(prefix, is_resolved)`, supports `purl.obolibrary.org/obo/`, `identifiers.org/`, and ad-hoc OBO patterns
  - `prefix_to_canonical_iri(prefix: str) -> str | None` — for graph display
- Cache resolved-prefix lookups in Redis (`reuse:bioregistry:{sha1(iri_prefix)}`) with 30-day TTL — avoids repeat hashing inside detection runs
- Fallback for unresolved prefixes: use the raw namespace as the key with `_unresolved: true` on the report — surface in UI so users can flag missing bioregistry entries upstream

### Aggregator (`detector.py`)

`detect_reuse(store, version_id, host_iri) -> ReuseReport` runs all four signal modules and returns a dataclass:

```python
@dataclass
class ReuseReport:
    version_id: str
    host_prefix: str | None
    host_iri: str
    imports: list[ImportEdge]                                  # signals/imports.py
    term_iri_reuse: dict[str, TermIRIReuseEntry]               # by source_prefix
    mireot_terms: list[MireotTerm]
    mappings: dict[str, list[MappingEntry]]                    # by predicate
    indexed_at: str                                            # ISO timestamp
```

### Integration points

- **Indexing time:** add `_populate_reuse_cache(version_id, store)` hook in `ontoexplorer/modules/search/indexer.py`, called alongside the existing coverage + owl_profile cache populators. Writes `reuse:{version_id}` to Redis (30-day TTL).
- **Celery refresh:** add `ontoexplorer.refresh_reuse` task in `ontoexplorer/modules/jobs/tasks.py` — loads the version's Oxigraph store from MinIO, runs `detect_reuse`, repopulates cache. Mirrors `refresh_owl_profile`.
- **API:** new module `ontoexplorer/api/reuse.py` exposing:
  - `GET /api/v1/ontologies/{ontology_id}/{version_id}/reuse` — per-version `ReuseReport`
  - `GET /api/v1/reuse/fleet` — fleet-level rollup: top reused sources, top reusing hosts, NxN reuse matrix (counts), MIREOT-heavy ontologies
  - `GET /api/v1/ontologies?reuses=<prefix>` — filter list endpoint (analogous to `?profile=el`)
- **OLS shim:** no equivalent OLS4 endpoint to mirror — skip.

### Frontend

- **Per-ontology:** `frontend/src/components/ReuseSection.tsx` rendered as a section inside `OntologyPage.tsx`, structured as four cards (imports, term-IRI, MIREOT, mappings). Each card is collapsible; MIREOT card shows the sample term list with one-click jump to source ontology if present in fleet.
- **Fleet view:** `frontend/src/pages/Reuse.tsx` rendered as a new tab under `Ontologies.tsx` at `/ontologies?tab=reuse`. Contents:
  - Summary cards (total reuse edges in fleet, MIREOT-using ontologies count, top reused source prefix)
  - Sortable table: ontology × {imports_count, mireot_terms, term_iri_reused, mappings_count}
  - Filter pill `?reuses=<prefix>` integrated with the list endpoint
- **No graph visualization** in Phase 1. The dependency graph belongs in Phase 3 once we know what we're showing — Phase 1's job is to make sure the data is right first. We'll prepare the data structure for Phase 3 (the fleet rollup already returns an edge list), but we won't introduce React Flow or cytoscape yet.

### BioPortal-scale rerun (`scripts/bioportal_reuse/`)

Separate from the OntoExplorer runtime. Consumes the existing preliminary-work data assets where they exist (declared imports, mapping table from BioPortal API) and overlays bioregistry normalization + a MIREOT-from-metadata heuristic:

```
scripts/bioportal_reuse/
    README.md
    run.py              # main entry: load preliminary CSVs + bioregistry-normalize
    normalize.py        # apply bioregistry to existing imports/mapping tables
    mireot_heuristic.py # weaker MIREOT estimator (no axioms available at this scale)
    publish.py          # render CSVs/JSON for the bioportal-ontology-analysis site
```

**Caveat (documented in README):** Without ontology bodies, MIREOT detection at BioPortal scale is heuristic (e.g., entity is in the mapping table or external-ref table but ontology declares no `owl:imports` of source). Counts are upper-bound estimates and clearly labeled as such in the output. The precise pipeline (signals/mireot.py) only runs at OntoExplorer-fleet scale.

## Critical files referenced

Reusable infrastructure:
- [ontoexplorer/models/db.py](ontoexplorer/models/db.py) — `OntologyImport` (L131-139), `OntologyVersion` (L112-128)
- [ontoexplorer/modules/ingestion/import_resolver.py](ontoexplorer/modules/ingestion/import_resolver.py) — `resolve_imports_sparql()` (L29)
- [ontoexplorer/modules/search/indexer.py](ontoexplorer/modules/search/indexer.py) — `_get_source(iri)` (L214-218), per-entity `source` field (L396)
- [ontoexplorer/modules/jobs/tasks.py](ontoexplorer/modules/jobs/tasks.py) — `refresh_owl_profile` (the pattern to mirror)
- [ontoexplorer/api/owl_profile.py](ontoexplorer/api/owl_profile.py) — API-shape precedent
- [ontoexplorer/modules/owl_profile/cache.py](ontoexplorer/modules/owl_profile/cache.py) — Redis cache-key helper pattern
- [frontend/src/pages/Ontologies.tsx](frontend/src/pages/Ontologies.tsx) — tab dispatcher
- [frontend/src/pages/OwlProfile.tsx](frontend/src/pages/OwlProfile.tsx) — fleet-page precedent (sortable table + summary cards)
- [frontend/src/components/OwlProfileSection.tsx](frontend/src/components/OwlProfileSection.tsx) — per-onto section precedent

Files to be created:
- `ontoexplorer/modules/reuse/{__init__,bioregistry,detector,cache}.py`
- `ontoexplorer/modules/reuse/signals/{__init__,imports,term_iri,mireot,mappings}.py`
- `ontoexplorer/api/reuse.py`
- `frontend/src/pages/Reuse.tsx`
- `frontend/src/components/ReuseSection.tsx`
- `scripts/bioportal_reuse/{run,normalize,mireot_heuristic,publish}.py` + `README.md`
- Tests: `tests/unit/reuse/test_{bioregistry,imports,term_iri,mireot,mappings,detector}.py`, `tests/integration/test_reuse_api.py`

Files to be modified:
- `ontoexplorer/modules/search/indexer.py` — add `_populate_reuse_cache` hook
- `ontoexplorer/modules/jobs/tasks.py` — add `refresh_reuse` task
- `ontoexplorer/api/__init__.py` — mount reuse router
- `ontoexplorer/api/ontologies.py` — add `?reuses=<prefix>` filter
- `frontend/src/pages/Ontologies.tsx` — register Reuse tab
- `frontend/src/pages/OntologyPage.tsx` — embed `ReuseSection`
- `pyproject.toml` — add `bioregistry>=0.11`

## Verification

End-to-end:
1. Reindex one fleet ontology with a known imports profile (RO, which imports BFO + IAO).
2. Hit `GET /api/v1/ontologies/ro/<vid>/reuse` and check: imports lists BFO + IAO with bioregistry-resolved prefixes; term_iri_reuse shows non-zero counts for `bfo` and `iao`; mireot list is empty (RO uses imports, not MIREOT).
3. Reindex an ontology known to use MIREOT (e.g., a hand-crafted fixture or a known biomedical ontology that MIREOTs IAO terms). Check `mireot_terms` lists the foreign-namespace minimally-axiomatized terms; `imports` does NOT list the source.
4. Hit `/api/v1/reuse/fleet` and verify the fleet rollup includes both ontologies and the reuse matrix shape is correct.
5. Open `/ontologies?tab=reuse` in the browser — confirm the table renders sorted by reused-class count desc and the filter pill works.

Unit tests:
- `signals/imports.py`: synthetic OntologyImport rows → expected closure
- `signals/term_iri.py`: list of entity IRIs → expected per-prefix bucketing
- `signals/mireot.py`: SPARQL fixture stores with native / import-reused / MIREOT terms → correct classification
- `signals/mappings.py`: fixture store with each mapping predicate → enumeration matches
- `bioregistry.py`: known IRI variants resolve to same canonical prefix; unresolved IRIs flagged

ROBOT cross-check:
- For one fleet ontology, run `robot merge --input X.owl --output closure.owl` and compare our import closure to ROBOT's merged file's transitive imports. Should match exactly (this is mechanical, not semantic).

BioPortal-scale rerun verification:
- Run `scripts/bioportal_reuse/run.py` against the preliminary work's `results/tables/upper_level_adoption.csv`. Confirm: post-normalization adoption rate ≥ pre-normalization (because variant IRIs now collapse). Note the delta in the publish output.

## Risks / open questions

- **bioregistry coverage of obscure OBO prefixes:** real risk for the long tail. Mitigation: `_unresolved` flag surfaced in UI; users can submit prefix entries upstream.
- **MIREOT false positives:** ontologies that legitimately use external IRIs for metadata (e.g., `dcterms:creator`) without MIREOT intent. Mitigation: exclude the standard annotation-property namespaces (`dc`, `dcterms`, `foaf`, `prov`) from MIREOT detection; surface excluded namespaces in the report.
- **BioPortal API rate limits** during population rerun: out of scope for the OntoExplorer runtime; the script README will document caching + resume-from-checkpoint.
- **NCBITaxon-class ontologies:** term-IRI reuse over a 2M-class ontology may be heavy. Mitigation: cap sample lists at 5 per source_prefix; total counts are cheap (SPARQL COUNT).
- **What if bioregistry resolves two different ontology IRIs to the same prefix?** (Rare but possible — e.g., ChEBI ontology vs ChEBI compound IRIs.) Mitigation: bioregistry already distinguishes resource vs prefix; we use the resource-level resolution.

## Next steps

After approval of this spec, run `superpowers:writing-plans` to produce the step-by-step implementation plan. Phase 2 (joint-reasoning consistency analysis) and Phase 3 (visualization) get their own brainstorm → spec → plan cycles later.
