# Justifications in OntoExplorer

> ⚠️ **Historical (2026-05-21). Superseded — kept for the algorithm write-up only.**
> The `elk-service` / ELK / ROBOT split described below no longer exists.
> Current state:
> - The reasoner lives in `docker/reasoner-service/` (not `elk-service`); reasoners are **rustdl** (default), **konclude**, and **km** (ELK, whelk, and the legacy rdflib classifier have all been removed).
> - Justification is **reasoner-agnostic**: `GET /justification` runs through a dedicated justifier (**rustdl**'s native `justify`/`justify_all`) regardless of which reasoner classified the version, so konclude/km versions get justifications too.
> - The app flow is **non-blocking**: peek the cache → dispatch a background Celery job (deduplicated) → poll; a provisional asserted-chain (BFS) is shown meanwhile. A per-version `.ofn` is cached to speed repeat justify/classify calls.
> - See [`../ingestion-storage-reasoning.md`](../ingestion-storage-reasoning.md) for the current reasoning + storage data flow.
>
> The greedy-shrink + hitting-set algorithm below still describes how black-box justification works in principle.

This is a status report on how OntoExplorer computes *justifications* (minimal axiom sets that prove an OWL entailment) and a recommendation for unifying the two systems that currently exist in parallel.

## Summary

OntoExplorer ships **two independent justification subsystems** as of 2026-05-21:

1. An **ELK-based system** (pre-Phase-2) that handles both subclass-entailment and unsatisfiability justifications via a hitting-set algorithm wrapping the ELK classifier. It's deployed today, used by the Term-detail UI, and works on OWL 2 EL inputs.
2. A **ROBOT-based system** (added by Phase 2) that handles unsatisfiability justifications via `robot explain --reasoner hermit`. It's wired into the consistency detector but not deployed — the runtime image does not bundle ROBOT/JVM, so the per-class justifications surface in the Consistency tab as empty lists.

Both systems can already explain `<C> SubClassOf owl:Nothing` axioms. The Phase 2 detector should be refactored to use the existing ELK system first and only fall back to ROBOT for non-EL ontologies. See [Recommendation](#recommendation-unify-via-elk-first-fallback-to-robot).

---

## System 1 — Existing ELK-based justifications

### Algorithm

`docker/elk-service/justification.py:24` implements a classical **greedy-shrink + hitting-set** justifier with the ELK classifier as the entailment oracle:

1. Reconstruct an `rdflib.Graph` from the proof traces stored by the prior classification (`docker/elk-service/main.py:152`).
2. For each axiom in the graph, try removing it. If the target entailment still holds when re-classified, drop the axiom permanently (`docker/elk-service/justification.py:86-92`).
3. Repeat until no further reduction is possible — the surviving axioms form a minimum justification.
4. For multiple justifications (`max_justifications > 1`), add a **blocking constraint** that excludes at least one axiom from each previously-found justification, then search again (`docker/elk-service/justification.py:55-62`).

The same code path handles two entailment types:

```python
# docker/elk-service/justification.py:113-116
if sup == str(rdflib.OWL.Nothing):
    return sub in r.unsatisfiable
return (sup in r.superclasses.get(sub, []) or
        sup in r.direct_superclasses.get(sub, []))
```

Unsatisfiability is treated as `<C> SubClassOf owl:Nothing`. The caller passes `sup=None` (or `type=unsatisfiable`) and the service substitutes `owl:Nothing` (`docker/elk-service/main.py:144`).

### Code layout

| Component | Path | Purpose |
|---|---|---|
| Algorithm | `docker/elk-service/justification.py` | Greedy shrink + hitting-set; ELK as oracle |
| HTTP wrapper | `docker/elk-service/main.py:135` | `POST /classify/{vid}/justification` |
| Result cache | `docker/elk-service/cache.py` | Redis-backed `load_justification` / `store_justification` |
| Client | `ontoexplorer/clients/reasoning.py:115` | `request_justification(vid, sub, sup, max)` |
| Celery task | `ontoexplorer/modules/jobs/tasks.py:616` | `compute_justification` — long-running (660s limit), fires `justification.completed` webhook |
| API: sync route | `ontoexplorer/api/ontologies.py:2201` | `GET /api/v1/ontologies/{id}/{vid}/justification` — 60s wait + BFS fallback |
| API: async route | `ontoexplorer/api/ontologies.py:2252` | `POST .../justification` — enqueues the Celery task |
| Render helper | `ontoexplorer/api/ontologies.py:164` | `_render_justification` — N-Triples → AST `{sub, rel, sup}` dicts |
| Frontend client | `frontend/src/lib/api.ts:1127` | `api.ontologies.justification(oid, vid, sub, sup)` |
| Frontend UI | `frontend/src/components/TermPanel.tsx:151, 355` | "Why is X a subclass of Y?" expansion in Term detail |

### Caching and concurrency

- Result cache: every `(version_id, sub, sup, max_justifications)` tuple is cached in Redis by the ELK service (`docker/elk-service/main.py:147, 186`). Re-requests return immediately.
- Classification cache: the underlying classification result is cached for 600s in-process at `ontoexplorer/clients/reasoning.py:15`, with per-version asyncio locks at line 16 to prevent thundering herds when multiple requests arrive for the same uncached version.
- Time limits: the ELK service uses `_JUSTIFICATION_TIME_LIMIT` (300s default) per request; the Celery task uses a 660s hard limit; the sync route uses a 60s wait before falling back.

### Fallback behavior

The sync route falls back to a BFS over asserted `rdfs:subClassOf` edges in Oxigraph when ELK fails or times out (`ontoexplorer/api/ontologies.py:2244-2247`). This produces a path-style "justification" (chain of subclass edges) — useful for non-EL ontologies where ELK can't classify, but limited to transitive subclass chains rather than minimal axiom sets.

### Critical correctness notes

The algorithm has one subtle correctness requirement, captured in memory at `feedback_elk_justification.md`: **blank-node IDs must be preserved across the whole graph**. rdflib regenerates blank-node IDs per `parse()` call, so:

- `_entails` in `justification.py:96` parses all axioms in ONE `g.parse(data="\n".join(axioms))` call, never one-by-one.
- `_extract_all_axioms` in `justification.py:119` serializes the whole graph once, then splits by lines — never serializes triples individually.
- `_reconstruct_graph_from_traces` in `main.py` collects all axiom strings into one parse call.

Violations cause silent graph disconnection (triples sharing the same `_:Nxxx` no longer connect) and produce wrong classification results without any error being raised. This is documented as a known sharp edge.

### Output format

Each justification is returned as a list of N-Triple strings (e.g., `<http://ex.org/A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <http://ex.org/B> .`). The API's `_render_justification` helper (`ontoexplorer/api/ontologies.py:164`) parses these into a structured AST per axiom — `{sub: ClassExprNode, rel: "subClassOf" | "equivalentClass", sup: ClassExprNode}` — which the frontend renders inline.

---

## System 2 — Phase 2 ROBOT-based justifications

### Algorithm

`ontoexplorer/modules/consistency/robot_explain.py` shells out to ROBOT:

```
robot explain --input <merge.owl> --reasoner hermit -M unsatisfiability -u all -m <N>
              --explanation <out.md>
```

ROBOT 1.9.10 with the HermiT reasoner computes justifications for every unsatisfiable class up to the cap `N`, producing a Markdown file with `[label](IRI)` Markdown-link references for every entity. The parser at `ontoexplorer/modules/consistency/robot_md_parser.py:50` converts that to `dict[class_iri, list[list[ManchesterToken]]]` — outer dict keyed by unsat class IRI, inner list per justification axiom, innermost list per text/IRI token.

This deliberately avoids parsing Manchester syntax (which has nested class expressions, restrictions, property chains, etc.). ROBOT has already done the verbalization work; the parser only needs to convert Markdown links to typed `IriToken`/`TextToken` for inline rendering.

### Code layout

| Component | Path | Purpose |
|---|---|---|
| ROBOT wrapper | `ontoexplorer/modules/consistency/robot_explain.py` | `explain_unsatisfiability(path, max_explanations)` — one ROBOT call per merge file |
| MD parser | `ontoexplorer/modules/consistency/robot_md_parser.py` | Markdown-link tokenizer; produces `IriToken`/`TextToken` |
| Detector | `ontoexplorer/modules/consistency/detector.py:139` | Calls `explain_unsatisfiability` once per scope; gracefully handles `RobotExplainUnavailable` |
| Cache | Reuses `consistency:{version_id}` Redis cache — justifications are nested inside each scope's `unsatisfiable_classes` list |
| Frontend types | `frontend/src/lib/api.ts:226-239` | `JustificationAxiomConsistency`, `UnsatisfiableClass` |
| Frontend UI | `frontend/src/components/ConsistencySection.tsx` | "Show justifications" toggle per scope card |

### Status: not deployed

The Phase 2 detector falls back to empty justifications when ROBOT is missing (`detector.py:165-167`). The runtime Dockerfile bundles Konclude (Phase 2 commit `0ae6dc4`) but **deliberately omits ROBOT** because including ROBOT requires bundling a JVM (~200 MB image-size increase). The decision was documented in the runtime Dockerfile comment and the Phase 2 plan's risks section.

Consequence: in production, the Consistency tab's per-class justification lists are always empty. The status badges and unsat-class IRI lists work fine; only the inline Manchester axioms are missing.

---

## Comparison

| Property | ELK-based | ROBOT-based (Phase 2) |
|---|---|---|
| Deployed today | yes | no (no JVM in runtime image) |
| Algorithm | Greedy shrink + hitting-set, ELK as oracle | Black-box via ROBOT explain |
| Reasoner | ELK (purpose-built EL) | HermiT (full OWL 2 DL) via ROBOT |
| OWL fragment | OWL 2 EL | OWL 2 DL (full) |
| Handles `sup = owl:Nothing` | yes — `justification.py:113` | yes — `-M unsatisfiability` |
| Multiple justifications | yes — hitting-set | yes — `-m N` flag |
| Output format | N-Triples per axiom → AST `{sub, rel, sup}` | Markdown links → `ManchesterToken[]` |
| Caching | Redis per `(vid, sub, sup, max)` | Embedded in consistency cache |
| Time budget | 300s per request, 660s Celery task | 600s timeout, called once per scope |
| Performance on EL ontologies | Fast (ELK is purpose-built) | Slower (JVM startup ~5s) |
| Performance on non-EL | Out-of-scope — falls back to BFS | Native — HermiT handles full DL |
| MIREOT-source scope | Not designed for it | Phase 2's merger handles this |

Two important non-differences:

- **Both already handle `sup = owl:Nothing`** — neither was added specifically for Phase 2's needs.
- **Both produce the same kind of artifact** — a list of axioms that prove the entailment. The output formats differ but the semantic content is equivalent.

## The architectural mistake in Phase 2

Phase 2's `robot_explain.py` was added without first checking whether OntoExplorer already had a justification pipeline. It does. The detector should have:

1. Looked up Phase 1's `owl-profile` cache (`reuse:{version_id}`... actually `owl_profile:{version_id}`) to determine whether the ontology is in OWL 2 EL.
2. For EL ontologies: called `reasoning_client.request_justification(version_id, sub=class_iri, sup=None)` — the existing client returns justifications keyed by class IRI for unsatisfiability requests.
3. For non-EL ontologies: fallen back to ROBOT (once it's bundled).

This would have:
- Shipped working justifications today against the inconsistent fixture without any JVM in the runtime image.
- Avoided duplicate caching infrastructure (`consistency:{vid}` payloads now embed justifications that ELK already cached separately).
- Eliminated the need for the Phase-2-specific `robot_md_parser.py` token shape in favor of the existing `_render_justification` AST.

The duplication exists because Phase 2 was designed against the spec without auditing existing infrastructure first. This is documented here so future contributors don't make the same mistake.

---

## Recommendation: unify via ELK-first, fallback to ROBOT

### Target architecture

For each unsatisfiable class IRI found by Konclude:

1. **EL fast path** — if the ontology's owl-profile cache shows it's in OWL 2 EL: call `reasoning_client.request_justification(version_id, sub=class_iri, sup=None)`. This invokes the existing ELK pipeline (synchronous from the worker's perspective, cached in Redis). Re-shape the N-Triples-list result into the `JustificationAxiomConsistency` token form the Consistency UI expects.
2. **DL fallback** — if not in EL, AND ROBOT is available, call the existing ROBOT path. If ROBOT isn't bundled, leave the justification list empty (current behavior).
3. **Path fallback** — if both fail and a BFS path is available via the existing `_find_subclass_path` helper, surface that.

### Implementation sketch

Files to edit (~50 lines of code total):

1. **`ontoexplorer/modules/consistency/detector.py:139`** — modify the explanation call:
   ```python
   # Pseudocode
   def _explain_unsat_classes(version_id, ontology_id, merge_path, class_iris):
       profile = _load_owl_profile(version_id)
       if profile and profile.get("el", {}).get("in_profile"):
           # EL fast path — reuse existing ELK pipeline
           return _via_elk_justification_client(version_id, class_iris)
       try:
           return _via_robot(merge_path, class_iris)
       except RobotExplainUnavailable:
           return {iri: [] for iri in class_iris}
   ```

2. **`ontoexplorer/modules/consistency/robot_md_parser.py`** — keep as-is for the ROBOT path; the ELK path needs a separate render function that converts N-Triples justifications to the same `ManchesterToken[]` shape. The existing `_render_justification` at `ontoexplorer/api/ontologies.py:164` produces a richer `{sub, rel, sup}` AST — we should evaluate whether to reuse that AST shape end-to-end and update the frontend, or write a thin N-Triples → tokens adapter just for the consistency UI.

3. **Frontend: no breaking change required** if the adapter produces `JustificationAxiomConsistency` tokens identical to what `robot_md_parser` produces. If we move to the existing AST shape, the Consistency tab's render code would need to switch from token-list to AST-tree rendering — but that's an upgrade, not a regression.

### Risks and open questions

- **Justification call count.** The existing ELK justification endpoint takes one `(sub, sup)` per call. For N unsat classes per scope, that's N HTTP calls (each may be cached). Phase 2's ROBOT call does all N at once via `-u all`. For consistency over the OntoExplorer fleet (typically ≤10 unsat classes per scope per ontology) this is fine; for hypothetical inconsistent BioPortal ontologies with hundreds of unsat classes per merge, the per-call overhead could dominate.
- **`compute_justification` Celery task duplication.** The existing per-term flow goes through Celery; Phase 2 currently does justification inline in the detector. We'd need to decide: keep it inline (simpler, but blocks the detector on each ELK call) or refactor to enqueue separate `compute_justification` tasks (better parallelism, but the consistency cache write happens before justifications complete).
- **What about the MIREOT scope?** ELK can only reason over its loaded graph. Phase 2's `host_plus_imports_plus_mireot` scope fetches additional ontologies from bioregistry and appends them to the merge. To use ELK for justifications in this scope, we'd need to push the merged graph through the ELK service first (a separate classification per scope) and then request justifications. That's expensive — three full classifications per consistency check on large ontologies.
- **ROBOT bundling decision.** If we adopt ELK-first, the question of whether to ever bundle ROBOT becomes "what fraction of the fleet is non-EL AND inconsistent?" — likely small enough that the JVM image bloat isn't worth it. For the OntoExplorer 19-onto fleet, every inconsistency that surfaces in Phase 2 testing is in EL-handleable ontologies.

### Cache invalidation

Once unified, the existing ELK justification cache (`docker/elk-service/cache.py`) handles invalidation correctly (results are keyed by `(version_id, sub, sup, max)`, so reindexing produces a new version_id and a fresh cache). The Phase 2 `consistency:{version_id}` cache would no longer need to embed justifications — it can carry only the unsat class IRIs and let the detail UI fetch justifications on demand from the existing endpoint.

---

## File index for quick navigation

```
docker/elk-service/justification.py            ─ algorithm
docker/elk-service/main.py:135                 ─ HTTP endpoint
docker/elk-service/cache.py                    ─ Redis cache
ontoexplorer/clients/reasoning.py:115          ─ Python client
ontoexplorer/modules/jobs/tasks.py:616         ─ Celery task
ontoexplorer/api/ontologies.py:2201            ─ sync GET route
ontoexplorer/api/ontologies.py:2252            ─ async POST route
ontoexplorer/api/ontologies.py:164             ─ N-Triples → AST render
frontend/src/components/TermPanel.tsx:151,355  ─ per-term UI

ontoexplorer/modules/consistency/robot_explain.py     ─ ROBOT wrapper
ontoexplorer/modules/consistency/robot_md_parser.py   ─ MD-link tokenizer
ontoexplorer/modules/consistency/detector.py:139      ─ Phase 2 call site
frontend/src/components/ConsistencySection.tsx        ─ per-class UI
```
