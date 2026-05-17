# Inferred-axiom diffs in the Manchester diff view — Phase 4

**Status:** approved design
**Date:** 2026-05-17
**Depends on:** [Phase 1 — Manchester rendering for modified entities](2026-05-17-manchester-diff-rendering-design.md), [Phase 2 — added / removed entity frames](2026-05-17-manchester-diff-added-removed-design.md), [Phase 3 — clickable IRIs](2026-05-17-manchester-diff-clickable-iris-design.md)
**Scope:** Extend the ontology version diff to also surface differences in the inferred named graph (ELK classification output), interleaved with asserted changes in the same Manchester frames and badged per-axiom.

## Background

The version diff today operates only on the asserted named graph (`urn:ontology:X:V`). ELK classification populates a separate named graph (`urn:ontology:X:V:inferred`) but this graph is never read by `run_diff`, so the user can't see reasoning consequences in the diff view. For ontology authors this is a major blind spot: "did my new axiom cause unexpected inferences?" and "did refactoring class X break the hierarchy?" are answerable only by manually comparing ELK runs.

This phase makes inferred changes first-class in the diff, with a per-axiom `[inferred]` / `[asserted]` badge so the reader can distinguish what the author wrote from what ELK derived.

## Architecture

`run_diff` is extended to operate on both asserted and inferred named graphs for each version. For each entity, two passes are run (asserted, then inferred) and the resulting axiom changes are merged into a single list with a `source: 'asserted' | 'inferred'` field per entry. The Manchester frame interleaves both kinds under their normal keyword blocks.

Two pieces of new computation:

1. **Reasoning-readiness check** before reading the inferred graph for a version.
2. **Non-trivial filtering** of inferred triples to suppress the redundant 60-80% of ELK's hierarchy output.

Plus one new orchestration concern: re-queueing diffs when reasoning completes after the diff was first computed.

## Reasoning readiness check

Before reading the inferred graph for a version, `run_diff` queries:

```sql
SELECT 1 FROM jobs
WHERE version_id = :vid AND type = 'reason' AND status = 'done'
LIMIT 1
```

For each version it records one of `'ready' | 'pending' | 'failed' | 'missing'`:

- `ready` — a successful `reason` job exists for this version.
- `pending` — a `reason` job exists with status `'queued'` or `'running'`.
- `failed` — the most recent `reason` job for this version is `'failed'`.
- `missing` — no `reason` job has ever been queued for this version.

If both versions are `ready`, inferred diff is computed alongside asserted. Otherwise the inferred pass is skipped and the per-version statuses propagate into the summary.

## Non-trivial filtering

For the inferred-graph diff pass, per-entity (predicate, object) pairs are filtered to remove:

1. **Top-of-hierarchy trivia:** `(rdfs:subClassOf, owl:Thing)`, `(rdfs:subPropertyOf, owl:topObjectProperty)`, `(rdfs:subPropertyOf, owl:topDataProperty)`.
2. **Reflexive trivia:** `(rdfs:subClassOf, X)` where the object IRI equals the entity's own IRI; same for property hierarchies.
3. **Asserted duplicates:** triples that also appear in the *asserted* graph for the same entity. ELK output typically includes both asserted-and-inferred hierarchy edges; the inferred-only set is `inferred_triples - asserted_triples`.

Rule 3 carries the most signal. For a well-axiomatized ontology it drops the bulk of ELK's output, leaving only genuinely new inferences.

## Re-queue on reasoning completion

A diff that was computed when reasoning wasn't ready will be stale after reasoning finishes. Two mechanisms keep it fresh:

1. **Inline hook in `reason_ontology`.** When the task succeeds, it queries `ontology_diffs` for rows where this version is `version_from_id` or `version_to_id` AND `inferred_status` (in the stored summary JSON) for that version isn't `ready`. For each match it queues `compute_diff.delay(...)`. The task is idempotent — it re-reads from the store and updates the diff row in place via the existing `ON CONFLICT DO NOTHING` upsert + per-row `status` transition (`'ready' → 'pending' → 'ready'`).

2. **Periodic safety net.** A new Celery beat task `refresh_stale_inferred_diffs` runs every 15 minutes, identical logic to the hook. Catches cases where the inline hook didn't fire (worker crash between mark-done and re-queue).

The re-queue only fires for diff rows currently `'ready'` — if a recompute is already pending, no duplicate.

## API changes

`DiffAxiomChange` gains a `source` field:

```typescript
interface DiffAxiomChange {
  op: 'added' | 'removed'
  axiom: string                       // legacy Phase 1 string, unchanged
  source: 'asserted' | 'inferred'     // NEW
}
```

`DiffSummary` gains inferred counts and per-version status:

```typescript
interface DiffSummary {
  added: number
  removed: number
  modified: number
  literal_changes: number
  axiom_changes: number                    // total across both sources
  asserted_axiom_changes: number           // NEW
  inferred_axiom_changes: number           // NEW
  by_entity_type: Record<DiffEntityType, { added; removed; modified }>
  inferred_status: {                       // NEW
    from_version: 'ready' | 'pending' | 'failed' | 'missing'
    to_version:   'ready' | 'pending' | 'failed' | 'missing'
  }
}
```

The Phase 3 `ManchesterFrame` token structure gains a per-line `source` field:

```typescript
type Line = {
  op: 'added' | 'removed' | null
  source: 'asserted' | 'inferred' | null   // NEW; null on header/keyword lines
  tokens: Token[]
}
```

## Frame rendering with source badge

Each axiom line carries its source. The frontend renderer appends a small badge after the axiom tokens:

```
  Class: SaltyPizza  (https://w3id.org/.../SaltyPizza)
      SubClassOf:
  +     hasTopping some Anchovy                 [asserted]
  +     SaltyFood                                [inferred]
  +     SeasonedPizza                            [inferred]
```

Both badges render so the reader can see at-a-glance which axioms ELK derived vs. which are author edits. Badge styling: small (0.8em), italic, muted color (`var(--text-dim)`); not interactive.

If practice shows the `[asserted]` badge is too noisy (most axioms are asserted), a future cleanup can drop it and leave `[inferred]` as the only marker. Phase 4 keeps both per the brainstorming agreement.

## "Inferred unavailable" notice

At the top of the diff view, when `inferred_status.from_version !== 'ready'` OR `inferred_status.to_version !== 'ready'`:

```
ⓘ Inferred diff unavailable: reasoning is {status} for version {version_iri}.
   The diff will refresh automatically when reasoning completes.
```

Where `{status}` is `pending` / `failed` / `missing`. Notice is dismissable in-session via a small × button but reappears on diff reload. It links to the version's admin / detail page where the user can see the reasoning job status, retry it, or queue it manually.

The asserted diff renders normally below the notice; only the inferred axioms are missing.

## Auto-refresh after reasoning completes

While the notice is visible, the diff view polls the diff endpoint every 30 seconds. When the response shows both versions `ready`, the polling stops and the rendered diff updates in place (React Query's `refetchInterval` handles this naturally with the existing query key).

A websocket-based push from the worker would be lower-latency but adds infrastructure; polling is simpler and the latency is fine for the use case (reasoning takes minutes-to-hours, 30s polling is appropriate).

## Frontend changes

Three additions to `HistoryTab.tsx`:

1. Render the "inferred unavailable" notice at the top of the diff view when applicable.
2. Append the `[asserted]` / `[inferred]` badge to each axiom line based on `line.source`.
3. The summary header gains separate counts: "57 axiom changes (52 asserted, 5 inferred)".

The Phase 3 token renderer needs only the per-line `source` field addition; no new token kinds.

## Testing

- `tests/unit/test_diff_inferred.py` (new):
  - Inferred diff is computed when both versions have inferred triples in the store; entries get `source: 'inferred'`.
  - Trivial axioms filtered out: explicit fixtures for `SubClassOf owl:Thing`, reflexive, and asserted-duplicates.
  - When inferred graph is empty for one version, `inferred_status` reports `missing` and no inferred entries appear.
  - Non-trivial filtering does NOT drop genuinely new inferences (positive test).
- `tests/unit/test_diff_compute.py` extension: `inferred_status` propagates correctly when reasoning job status varies.
- `tests/integration/test_diff_api.py` extension:
  - The diff API response includes `inferred_status` in the summary.
  - End-to-end: compute diff without reasoning ready, verify `inferred_status` and zero inferred entries. Then complete reasoning for one version, verify status reflects the change. Complete reasoning for the other version, verify re-queue fires (via beat or hook) and inferred axioms appear.

## Risk and mitigation

- **Inline hook reliability.** The post-reasoning re-queue is a side effect of the `reason_ontology` Celery task. If the task crashes between `mark_done` and queuing the recompute, the diff stays stale. Mitigation: the `refresh_stale_inferred_diffs` beat task (15-minute interval) catches missed re-queues.
- **Volume from large ontologies.** Million-triple ontologies can have hundreds of thousands of inferred axioms before filtering. After non-trivial filtering, expect 1-10K. Per-entity caps and entity-level pagination can be added in a future phase if real-world testing reveals UI/storage problems.
- **Stale `inferred_status` in a long-running diff view.** A user looking at a diff for ~15 minutes might see the reasoning complete on the server but the client's diff payload (cached by React Query) is still old. Mitigation: the polling reduces this to a 30-second window; on `ready` flip the UI refreshes and the user sees inferred axioms appear.
- **`source` field for added / removed entities.** Phase 2's whole-entity frames collect axioms from the asserted graph and tag every line `source: 'asserted'`. Inferred-only entities (e.g. an entity that exists in the inferred graph but not the asserted graph) are not surfaced as separate added/removed entries in Phase 4. They appear only as inferred axioms inside other entities' frames. If this becomes a use case, future phase can extend `_collect_iris` to also scan the inferred graph for new entity types.

## Out of scope

- ELK justifications (the *why* of an inference) — that feature already exists separately in the `compute_justification` task and `/justify` endpoint. Diff view could link to it; explicitly deferred to keep Phase 4 focused.
- Diff over specific OWL reasoning profiles (EL, RL, QL) separately — single-profile assumption matches the current ELK integration.
- Manual "recompute now" button on the diff view — re-queue is automatic via hook + beat. If users hit cases where automatic refresh doesn't fire, that's a bug to fix in the re-queue path, not a button to add.
- `[asserted]` badge cleanup — if the dual badges feel noisy in practice, a small follow-up can drop the asserted one. Not done now per the brainstorming agreement to show both.
