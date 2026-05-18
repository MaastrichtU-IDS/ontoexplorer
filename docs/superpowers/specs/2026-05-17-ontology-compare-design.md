# Cross-ontology comparison route and page — `/compare`

**Status:** approved design
**Date:** 2026-05-17
**Scope:** A new `/compare` route lets users compare any two ontologies (and any specific versions of them) in the OntoExplorer system. Reuses the existing diff infrastructure — Manchester renderer, diff data shape, Celery task pattern — but stores results in a new `ontology_comparisons` table so the existing `ontology_diffs` semantics (intra-ontology, version-pair) stay clean.

## Background

The existing diff feature compares two *versions* of the *same* ontology. The entity-identity model is "same IRI = same entity," which holds within an ontology's version history. The `ontology_diffs` table, the `compute_diff` Celery task, the `/api/v1/ontologies/{id}/diff` endpoint, and the `HistoryTab` page all assume a single ontology_id.

Users need a way to compare two **different** ontologies — typical questions: how much do these overlap, which classes are unique to each, when both reuse a shared upper-ontology class do they extend it differently? This phase adds that workflow.

Entity-identity model for this phase: still IRI matching only (mapping-based alignment is explicitly deferred). Two entities are "the same" iff they share an IRI, which in practice catches imported terms (`owl:Thing`, common upper-ontology classes) and any deliberate reuse. Distinct namespaces (`pizza:Tomato` vs `food:Tomato`) appear as "only in A" / "only in B" — not as "modified."

## Architecture

A new pair of modules and a new table mirror the existing diff pipeline:

| Existing (intra-ontology) | New (cross-ontology) |
|---|---|
| `ontology_diffs` table | `ontology_comparisons` table |
| `ontoexplorer/modules/diff/compute.py:run_diff` | `ontoexplorer/modules/compare/compute.py:run_comparison` |
| `compute_diff` Celery task | `compute_ontology_comparison` Celery task |
| `/api/v1/ontologies/{oid}/diff` | `/api/v1/compare` |
| `HistoryTab` page | `Compare.tsx` page |

The Manchester renderer (`ontoexplorer/modules/diff/manchester.py`) is reused as-is. The diff-computation body (the per-entity loop that produces added/removed/modified buckets) is extracted from `run_diff` into a private `_run_diff_core(store, from_graph_iri, to_graph_iri)` helper. Both `run_diff` (same ontology, two versions) and `run_comparison` (two ontologies, two versions) become thin wrappers that build their respective graph IRIs and delegate to `_run_diff_core`.

On the frontend, the existing `HistoryTab` is refactored to extract a `DiffResultView` component that renders the added/removed entity lists and the modified-entity Manchester frames. `HistoryTab` and the new `Compare` page both render their results through `DiffResultView`.

## Data model

New SQLAlchemy model in `ontoexplorer/models/db.py`:

```python
class OntologyComparison(Base):
    __tablename__ = "ontology_comparisons"
    __table_args__ = (UniqueConstraint("version_from_id", "version_to_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    from_ontology_id: Mapped[str] = mapped_column(
        ForeignKey("ontologies.id", ondelete="CASCADE")
    )
    to_ontology_id: Mapped[str] = mapped_column(
        ForeignKey("ontologies.id", ondelete="CASCADE")
    )
    version_from_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE")
    )
    version_to_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String, default="pending")
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    diff_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

`summary` and `diff_data` share the same JSON shape as `OntologyDiff` so the existing TypeScript types (`DiffSummary`, `DiffEntity`, etc.) and the `DiffResultView` component work unchanged.

Alembic migration creates the table; no other schema change.

## Compute pipeline

`ontoexplorer/modules/compare/compute.py`:

```python
def run_comparison(
    store: ox.Store,
    from_ontology_id: str, from_vid: str,
    to_ontology_id: str,   to_vid: str,
) -> tuple[dict, dict]:
    """Diff two versions, possibly from different ontologies.
    Same JSON shape as run_diff. IRI-based identity.
    """
    from_graph = graph_iri(from_ontology_id, from_vid)
    to_graph   = graph_iri(to_ontology_id,   to_vid)
    return _run_diff_core(store, from_graph, to_graph)
```

`_run_diff_core` is the extracted helper in `ontoexplorer/modules/diff/compute.py`. It contains everything currently inside `run_diff`'s entity-comparison loop: iterating `_ENTITY_TYPES`, calling `_collect_iris`, `_literal_triples`, `_structural_triples`, `_first_label`, building `change_records`, calling the Manchester renderer, and assembling the result dict. The legacy `run_diff(store, ontology_id, from_vid, to_vid)` becomes a one-liner that wraps `_run_diff_core(store, graph_iri(ontology_id, from_vid), graph_iri(ontology_id, to_vid))`.

`ontoexplorer/modules/jobs/tasks.py` gains:

```python
@celery_app.task(name="ontoexplorer.compute_ontology_comparison", time_limit=600)
def compute_ontology_comparison(from_version_id: str, to_version_id: str) -> dict:
    """Look up each version's ontology_id, run cross-ontology comparison,
    persist to ontology_comparisons.
    """
```

Body mirrors `compute_diff` but with two ontology_ids resolved by SELECT on the `versions` table. Hard time limit raised to 600s (vs 300s for intra-ontology diffs) to allow for larger ontologies in cross comparisons.

## REST API

New router `ontoexplorer/api/compare.py`, prefix `/api/v1/compare`. Two endpoints, matching the existing diff API's "lookup-or-enqueue" pattern.

```
GET  /api/v1/compare?from_version_id={X}&to_version_id={Y}
```

- If a row exists with status=ready → 200 with `{status, summary, diff_data}`.
- If a row exists with status=pending/failed → 202 with `{status}`.
- If no row exists → 404 (caller should POST first).
- 400 if `from_version_id == to_version_id`.

```
POST /api/v1/compare/compute?from_version_id={X}&to_version_id={Y}
```

- Validates both versions exist (404 if either missing).
- Idempotent: if a row exists, returns its current status; if not, inserts pending row and queues Celery task.
- 202 with `{status: "pending"}` on first call. Subsequent calls return whatever the row's current status is.

Both endpoints are public-readable (no auth required) — matching the existing `/api/v1/ontologies/{id}/diff` semantics. Any user can compare any two ingested ontologies.

The router is mounted in `ontoexplorer/main.py` next to the existing routers.

## Frontend

### Routing

`App.tsx` gains:

```tsx
<Route path="/compare" element={<Shell><Compare /></Shell>} />
```

`Layout.tsx`'s top nav gets a new "Compare" item between Search and SPARQL.

### `Compare.tsx`

State driven by URL params:
- `?from=<vid>&to=<vid>` — full comparison request
- No params — show empty form

Form structure (top to bottom):

1. **Two searchable ontology dropdowns** side-by-side, fed by `api.ontologies.list()`. Each dropdown item shows `shortname` (with IRI fallback) and the optional `label`. Selecting an ontology reveals its version dropdown immediately below.
2. **Two version dropdowns**, populated when each ontology is selected, fed by `api.ontologies.versions(id)`. Default selection: most recent non-deprecated version. Items show `version_iri` (with creation date fallback).
3. **"Compare" button** — disabled until both versions are picked AND the two version IDs differ. (Picking the same ontology twice with two different versions IS allowed — the resulting comparison is mathematically equivalent to a version diff but stored in `ontology_comparisons`; we don't redirect to the version-diff page since the page is identical in output.) Clicking writes `?from=&to=` to the URL via `useNavigate(replace=true)` and triggers compute.

Once a comparison is in flight:

- `POST /api/v1/compare/compute` is called.
- The page polls `GET /api/v1/compare` every 2 seconds via React Query's `refetchInterval`.
- A status banner shows "Computing comparison… ({elapsed}s)" while pending.
- When status flips to `ready`, results render via `<DiffResultView>` (see below).
- If status flips to `failed`, an error banner appears with a "Retry" button that re-POSTs compute.

### `DiffResultView.tsx` (refactor)

Extracted from `HistoryTab.tsx`'s rendering loop. Takes:

```tsx
interface Props {
  data: OntologyDiff['diff_data']        // {added, removed, modified}
  summary: OntologyDiff['summary']
  fromLabel: string                       // for header
  toLabel: string                         // for header
  variant: 'version-diff' | 'cross-compare'  // controls labeling
}
```

When `variant === 'cross-compare'`:
- The added-bucket header reads **"Only in {toLabel}"** (e.g., "Only in food").
- The removed-bucket header reads **"Only in {fromLabel}"**.
- The modified-bucket header reads **"Shared IRI, axioms differ"**.

When `variant === 'version-diff'`, headers stay "Added" / "Removed" / "Modified" — current behavior.

Everything else (filtering, search, Manchester frames, expand/collapse) is identical across both variants.

`HistoryTab.tsx` is refactored to pass `variant="version-diff"` and use existing label conventions; otherwise unchanged in functionality.

### Frontend API client

`frontend/src/lib/api.ts` gains:

```typescript
compare: {
  get: (fromVid: string, toVid: string) =>
    request<OntologyDiff | { status: 'pending' | 'failed' }>(
      `/compare?from_version_id=${fromVid}&to_version_id=${toVid}`
    ),
  compute: (fromVid: string, toVid: string) =>
    request<{ status: string }>(
      `/compare/compute?from_version_id=${fromVid}&to_version_id=${toVid}`,
      { method: 'POST' }
    ),
}
```

A `useArbitraryComparison` hook in `frontend/src/hooks/useCompare.ts` wraps both with the polling pattern.

## Testing

- `tests/unit/test_compare_compute.py` — `run_comparison` over two synthetic in-memory ontologies. Cases:
  - All-disjoint IRIs → both added/removed lists populated, modified empty.
  - One shared IRI with differing axioms → modified bucket populated, frame rendered.
  - Bnode-fingerprinting still suppresses spurious diffs across ontologies (regression of the existing behavior).
- `tests/unit/test_diff_core_split.py` — Sanity check: the refactor of `run_diff` into `_run_diff_core` preserves output. (Existing `tests/unit/test_diff_compute.py` already covers behavior; this just verifies the extraction.)
- `tests/integration/test_compare_api.py` — POST `/compare/compute`, poll `/compare`, verify result shape. Skip-if-no-redis decorator.
- `frontend/src/pages/Compare.test.tsx` — Form happy path: mock `api.ontologies.list`, `api.ontologies.versions`, `api.compare.compute`, `api.compare.get`. Assert form renders, picking both sides enables button, clicking writes URL params, and `DiffResultView` mounts when result lands.

## Out of scope

- **Label / SSSOM-based entity alignment** — would let `pizza:Tomato` ↔ `food:Tomato` show up as "shared, axioms differ." Deferred per user preference; the design leaves room (a future `match_strategy` parameter on `run_comparison` and a new column on `ontology_comparisons`).
- **LLM narrative for cross-ontology comparisons** — the existing narrative endpoint is intra-ontology only. Adding it for cross-ontology comparisons is a small follow-up that doesn't change this design.
- **Comparing more than two ontologies in one view** — out of scope.
- **Read/write permissions** — `/compare` is public-readable, same as `/ontologies/{id}/diff`.

## Risk and mitigation

- **Storage growth.** Cross-ontology comparisons of large ontology pairs (UBERON × MONDO, hundreds of MB raw RDF each) can produce multi-MB `diff_data` blobs. Mitigation: same as the version-diff (just store it; revisit if it becomes a problem). The `ontology_comparisons` table is independent of `ontology_diffs`, so an emergency truncate doesn't affect existing version diffs.
- **Compute time on large pairs.** A cross-comparison of two large ontologies takes longer than a version diff (more entities total). The async polling pattern protects the HTTP layer. Celery task time_limit raised to 600s (vs 300s on `compute_diff`). If real-world usage hits the limit, raise further or add per-entity-type chunking in a follow-up.
- **Asymmetric semantics in shared internals.** The `diff_data` JSON keeps `added` / `removed` / `modified` keys for code reuse with `DiffResultView`. The Compare page relabels them on render; the keys remain internal naming. This is invisible to users and keeps the React component shared.
- **Refactor of `run_diff`.** Extracting `_run_diff_core` touches a function that already has multiple tests. The split is mechanical (move the body of the entity loop into a new function that takes two graph IRIs instead of an ontology_id + two version_ids; existing `run_diff` becomes a one-line wrapper). All existing `test_diff_compute.py` tests must continue passing without modification.
