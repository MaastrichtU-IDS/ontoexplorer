# Bulk Discovery → Ingest — Phased Program Plan

> **For agentic workers:** This is a **phased program plan**, not a build-ready task plan. It is **contingent** on the go/no-go in `docs/superpowers/specs/2026-11-24-bulk-discovery-ingest-feasibility.md` and on prerequisites that are their own projects. Do **not** start Phase 2+ before Phase 0/1 land and the owner confirms the go. Phase 1 (the gate framework) is the first thing that could become a conventional TDD plan.

**Goal:** Grow the catalogue by discovering ontologies elsewhere (MOD-API catalogues; later, GitHub) and ingesting them through the existing pipeline — **safely**, behind an admission gate.

**Why phased, not one plan:** the feasibility review concluded *the gate is the project*. The discovery plugins are small (they just call `ingest_ontology.delay`); the risk and the work are the gate (dedup/license/quality/capacity) plus two unresolved prerequisites. A single TDD plan would be fiction until those land.

**Spec:** `docs/superpowers/specs/2026-11-24-bulk-discovery-ingest-feasibility.md`

## Recommendation this plan encodes

- **GO (gated)** for MOD-API harvest → Phases 0,1,2.
- **NO** to auto-bulk GitHub; **GO** for a GitHub **review queue** → Phase 4 (optional, later).
- Nothing auto-ingests at scale until the gate (Phase 1) and the capacity prerequisite (Phase 0) exist.

---

## Phase 0 — Prerequisites (each is its own effort; do first)

These block *any* bulk ingest. They are not "tasks" here; they are pre-work with their own planning.

- **P0.1 — Resolve/bound #402 (Postgres lock exhaustion)** under concurrent fleet-wide `entity_index` work, and size storage + worker fan-out for a 5–10× collection. **Hard gate on capacity.** (OPEN issue #402.)
- **P0.2 — Dedup-at-admission identity resolution** — a `canonical_iri(candidate) -> IRI|None` resolver (from MOD-API record; cheap partial parse as a fallback) **plus** a post-parse backstop dedup pass (admission-time resolution is unreliable — self-IRI drift). Builds on #250/#251.
- **P0.3 — License gate decision** — confirm the policy: ingest-and-serve only when the resolved license ∈ `compliant_licenses`; otherwise metadata-only-pointer or skip. (Builds on #364/#425.)

**Exit:** #402 bounded + capacity sized; a working `canonical_iri` resolver with a known false-negative rate; a written license-admission policy.

## Phase 1 — Admission gate + DiscoverySource framework (the real project; buildable as TDD)

**This is the phase to turn into a full `writing-plans` TDD plan when Phase 0 clears.** Sketch of its tasks:

1. **`DiscoverySource` interface + `Candidate` model** — `Candidate(source_url, provenance{catalogue_iri, source_record_iri, retrieved_at}, declared_license?)`; `DiscoverySource.discover() -> AsyncIterator[Candidate]`.
2. **The admission gate** `admit(candidate) -> AdmitDecision(admit|metadata_only|reject, reason)` composing four checks:
   - **dedup** (P0.2 resolver vs existing catalogue),
   - **license** (P0.3 policy),
   - **quality** (resolvable? parses? class/property count ≥ threshold? size ≤ `ingest_max_source_bytes`? not a known fork),
   - **capacity/throttle** (bounded enqueue rate so the pipeline backlog stays inside the Phase-0 envelope).
3. **Provenance persistence** — persist `{source catalogue IRI, original download URL, retrieved_at, resolved license}` onto the version record (new columns or a provenance table), written at ingest.
4. **Peer-politeness** — per-source outbound rate-limit + `Retry-After` backoff shared by every discovery source.
5. **Admitted → `ingest_ontology.delay(url=..., declared_license=..., groups=...)`** with provenance in the kwargs; reuse the existing pipeline unchanged.
6. **Freshness/re-harvest loop** — a beat task that re-checks harvested copies against their source and refreshes/retires stale mirrors (extends update-polling #336).
7. **Admin surface** — a review/metrics view: candidates seen, admitted, rejected (by reason), queue depth, per-source rate.

**Exit:** a source-agnostic gate that can admit candidates from a trivial test source and drive them through ingest with provenance, throttling, and a freshness loop — with no real discovery plugin yet.

## Phase 2 — MOD-API harvest plugin (first real source)

- A `ModApiHarvestSource(DiscoverySource)` that enumerates a configured peer's `/mod/artefacts` (paginated) and each artefact's distribution `downloadURL`, emitting `Candidate`s. **Reuses the Project-1 MOD-API client/adapters.**
- Runs **gated** (Phase 1): enumerate-all, admit-what-passes, throttle. No firehose.
- Start with **one** curated, well-licensed peer; measure admit/reject rates and real capacity cost against the Phase-0 model before widening.

**Exit:** one peer harvested end-to-end; catalogue grows only by admitted, deduped, licensed, provenance-tracked ontologies; capacity stays within the envelope.

## Phase 3 — Evaluate & widen (decision point)

- Review Phase-2 metrics (yield, dup rate, license-reject rate, infra cost). Decide whether to add more MOD-API peers. This is a **go/no-go checkpoint**, not automatic.

## Phase 4 — GitHub discovery as a review queue (optional, later; NOT auto-bulk)

- A `GithubScanSource` that emits `Candidate`s from GitHub code search / curated org scans into a **human-reviewed queue** (extends the inbound-webhook model, `api/inbound.py`), where a maintainer approves admission.
- **Explicitly not** wired to auto-admit — every GitHub gate (quality/dedup/license/capacity) is hostile un-reviewed. Build only if Phase 3 says the collection-growth strategy is worth extending to the long tail.

## Global constraints (all phases)

- Every admitted ontology flows through the **existing** `ingest_ontology.delay` / `run_ingestion` — no parallel ingest path.
- Nothing ingests without a resolved, compliant license (or is recorded metadata-only).
- Provenance is mandatory on every harvested version.
- Outbound harvest is polite (rate-limited, `Retry-After`).
- Capacity stays inside the Phase-0 envelope; the throttle is a hard limit, not advisory.

## Sequencing summary

```
Phase 0 (prereqs: #402 + dedup resolver + license policy)
   └─> Phase 1 (gate + DiscoverySource framework)  ← first TDD plan
          └─> Phase 2 (MOD-API harvest, one peer, gated)
                 └─> Phase 3 (evaluate → widen? go/no-go)
                        └─> Phase 4 (GitHub review queue, optional)
```
