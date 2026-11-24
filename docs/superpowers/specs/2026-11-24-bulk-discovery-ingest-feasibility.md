# Bulk Discovery → Ingest (MOD-API harvest + GitHub scan) — Feasibility Design

**Status:** Feasibility design — a go/no-go for a *program*, not a build-ready spec. Issue: [#415](https://github.com/MaastrichtU-IDS/ontoexplorer/issues/415) (Project 2 of 2; Project 1 is `2026-11-24-mod-api-federation-design.md`).

**Question being answered:** Should OntoExplorer grow its collection by **bulk-harvesting content held elsewhere** — discovering ontologies via remote MOD-API catalogues and by scanning GitHub for OWL files, then fetching, indexing, embedding and reasoning each one locally so its terms are locally searchable?

**Short answer:** The *plumbing* is easy and already exists. The *program* is the **admission gate** — quality, duplication, licensing, capacity — and those four are what decide whether this is valuable or a liability. My recommendation (detailed at the end): **conditional go for gated MOD-API harvest; do NOT auto-bulk-ingest GitHub** — route GitHub discovery into a human-reviewed candidate queue instead. Both should run behind a review/approval gate before any auto-ingest, not as a firehose.

---

## 1. Reframing: this is not federation, it is ingest-seeding

Unlike Project 1 (which stores nothing), this fetches remote **content** and makes it local. That means it never touches the federation query path at all — it feeds the **existing** ingestion pipeline. Concretely, every candidate ends at one call:

```
DiscoverySource ──emits──> candidate { source_url, provenance, declared_license? }
                                │
                          [ ADMISSION GATE ]   ← the actual project
                                │
                   ingest_ontology.delay(url=..., groups=..., declared_license=...)
                                │
   (existing) run_ingestion → resolve → parse → store → reason → index → embed
```

- The pipeline entry point already exists: `ingest_ontology.delay(...)` (`ontoexplorer/modules/jobs/tasks.py:746`) → `run_ingestion` (`ontoexplorer/modules/ingestion/pipeline.py:113`). A discovery source just enqueues URLs.
- The "enumerate a remote source and submit each URL" pattern already exists too: `scripts/load_ontologies.py` does exactly this for **LOV** (SPARQL) and **BioPortal** (API), submitting via `POST /api/v1/ontologies`; `scripts/seed_ontologies.py` does it from `seeds/catalog.yaml`. A MOD-API harvester or GitHub scanner is **another enumerator of the same shape.**

So the two discovery plugins the user wants — **MOD-API bulk harvest** and **GitHub OWL scan** — are small. They generalise to a `DiscoverySource` interface that yields candidates. Everything hard is downstream of the gate.

## 2. The admission gate IS the project

Bulk + GitHub turns four normally-minor concerns into first-line, load-bearing gates:

### 2.1 Duplication (the dominant risk)
Remote SACs overlap massively — GO, ChEBI, ENVO, etc. live in OLS **and** OntoPortal **and** OBO **and** AgroPortal simultaneously. GitHub multiplies this again through **forks** and vendored copies: the same `.owl` appears in dozens of repos. Today's dedup (#250/#251) is a **post-hoc cleanup** keyed on canonical self-IRI, and identity is already unstable for some ontologies (SULO/rdf-ns self-IRI drift — see `ontoexplorer-catalogue-dupes`). Bulk ingest would pour thousands of near-identical copies in faster than cleanup can keep up.
**Required:** dedup must move to **admission control** — resolve a candidate's canonical ontology IRI (ideally *before* full ingest, from the MOD-API record or a cheap HEAD/partial parse), and reject/merge against the existing catalogue at enqueue time, not after. This is a non-trivial identity-resolution piece, and it is the single thing most likely to sink the effort if skipped.

### 2.2 Licensing (a hard legal gate)
Serving another party's ontology content locally requires the right to re-host. MOD-API records *can* carry `dcterms:license` (we emit it; AgroPortal's DCAT2 does too), but **GitHub repos are frequently unlicensed**, and "no license" means **no right to copy or re-serve** — not "permissive by default." OntoExplorer already has license canonicalisation + a compliance allowlist (`compliant_licenses` in `config.py:165`, PR #425, issue #364).
**Required:** the gate ingests-and-serves content **only** when a license resolves to the permissive allowlist; otherwise it either (a) records metadata-only with a link out (the Project-1-style pointer), or (b) skips. Unlicensed GitHub finds are (b).

### 2.3 Quality (especially GitHub)
MOD-API sources are curated catalogues, so their artefacts are mostly real ontologies. **GitHub is the opposite:** `.owl`/`.ttl`/`.rdf` matches are dominated by forks, test fixtures, course assignments, half-finished drafts, generated samples, and non-ontology RDF. Auto-ingesting that firehose would swamp the catalogue with junk and burn compute on files that fail to parse or carry three classes.
**Required:** a quality gate (building on the ingest quality work, #364): resolvable? parses as an ontology? has a meaningful class/property count? not a fork of an existing entry? sane size (`ingest_max_source_bytes` already caps at 2 GiB)? For GitHub this gate is so decisive that it argues for **human review, not auto-admit** (see §4).

### 2.4 Capacity (a real infra sizing exercise)
Each admitted ontology costs the **full** pipeline — download, parse, store triples (Oxigraph content store), reason (rustdl), index (`entity_index`), embed (nomic). Rough current-state anchors:
- Catalogue ≈ **1,898** ontologies today.
- `entity_index` ≈ **5.4 GB** (2.8 GB table + 2.6 GB indexes) for that population → order **~2–3 MB of index per ontology** on average (heavily skewed by large ontologies).
- Indexing cost ≈ **~24 s** `entity_index`-populate per version after the hash-partition fix (`ontoexplorer-index-perf`), plus parse + embed + reason on top.
- Known concurrency ceiling: concurrent fleet-wide work already hit **Postgres `max_locks_per_transaction`** exhaustion against the 64-partition `entity_index` (#402, OPEN) and the cold unique-count scan for home stats is ~110 s over ~2.8 M rows.

**Implications of bulk:** a 5–10× collection (e.g. +10k ontologies) means roughly **+25–55 GB** of `entity_index` alone (plus embeddings, Oxigraph content, Postgres rows), **thousands of worker-hours** of backlog across the `worker-index`/`worker-embed`/`worker-heavy` tiers, and it pushes directly on the open #402 lock-exhaustion and the stats-scan costs. This is not a config bump; it needs a sizing decision (storage, worker fan-out, and resolving #402 first) **before** turning any firehose on.

## 3. Discovery plugin A — MOD-API bulk harvest

- **Mechanism:** enumerate a peer's `/mod/artefacts` (paginated `hydra:Collection`), and for each artefact read its distribution `dcat:downloadURL` (`/mod/artefacts/{id}/distributions/latest`); emit `{source_url: downloadURL, provenance: {catalogue, artefact_iri}, declared_license: dcterms:license}`. Mirrors `load_ontologies.py`'s LOV/BioPortal enumerators; reuses Project 1's MOD-API client/adapters.
- **Feasibility: moderate-to-good, conditionally.** Sources are curated (quality mostly OK), records carry license + canonical IRI (dedup and licensing gates have the inputs they need), and pagination is well-defined. The limiter is **capacity + dedup**, not discovery.
- **Mode:** even here, prefer **gated** over pure firehose — dedup by IRI at admission, admit only allowlist-licensed artefacts, and rate-limit the enqueue so the pipeline backlog stays bounded. "Bulk" becomes "enumerate everything, admit what passes the gate, throttle the rest."

## 4. Discovery plugin B — GitHub OWL scan

- **Mechanism options:** GitHub **code search API** (`filename:*.owl`, `extension:owl`, content qualifiers) — but note it **requires auth, is heavily rate-limited, and does not cleanly enumerate all of GitHub** (code search is scoped and quota-bound); or a curated list of known ontology orgs/repos scanned via the contents API. The closest existing pattern is the **inbound webhook** (`ontoexplorer/api/inbound.py:104`), which already maps changed GitHub repo files → `ingest_ontology.delay(url=...)` for *registered* repos.
- **Feasibility: poor for auto-bulk, workable as a curated candidate queue.** Every one of the four gates is hostile here at once: quality (mostly non-ontologies/forks/fixtures), duplication (forks are exact copies), licensing (frequently absent → no re-host right), and capacity (unbounded, noisy input). Auto-ingesting GitHub code-search hits would degrade the catalogue and burn compute for little yield.
- **Recommended shape:** GitHub discovery emits candidates into a **human-reviewed queue** (an admin surface listing `{repo, file, detected_license, parses?, class_count, canonical_iri, dup_of?}`), where a maintainer approves admission. This keeps the valuable long-tail finds (a real ontology published only on GitHub, properly licensed) while refusing the firehose. It is essentially extending the existing registered-source webhook model to *discovered* sources with an approval step.

## 5. Capacity model (rough, for the go/no-go)

| Scenario | +ontologies | ~`entity_index` growth | pipeline backlog (very rough) | pressure points |
|---|---|---|---|---|
| Gated MOD-API harvest (dedup+license admit a fraction) | +1–3k | +3–9 GB | thousands of task-runs across index/embed/reason | #402 locks; storage; worker fan-out |
| Bulk MOD-API (little gating) | +5–10k | +15–30 GB | tens of thousands of task-runs | #402 almost certainly trips; stats-scan cost; Redis/PG |
| Bulk GitHub auto-ingest | unbounded/noisy | unbounded | dominated by parse-fail + dup churn | all four gates hostile; catalogue quality |

Numbers are order-of-magnitude from current-state anchors (§2.4), not measured projections. The takeaway is directional: **gating is what keeps this inside the infra envelope; ungated bulk breaks known-open limits (#402) and needs a deliberate scale-up first.**

## 6. Recommendation (go / no-go)

1. **Resolve the prerequisites before any auto-ingest at scale:** (a) move **dedup to admission control** (canonical-IRI resolution at enqueue), (b) make the **license gate** mandatory (allowlist-or-metadata-only), (c) fix or bound **#402** (lock exhaustion) and size storage/worker capacity. These are the real work; without them, bulk is a net negative.
2. **MOD-API harvest: conditional GO**, in **gated** mode (enumerate-all, admit-what-passes, throttle). Highest value, lowest noise, inputs for the gates are present in the records. Good candidate for the first real build after Project 1.
3. **GitHub scan: NO to auto-bulk**; **GO as a curated candidate queue** with maintainer approval, extending the existing inbound-webhook model. This preserves the genuine long-tail wins without the firehose's quality/licensing/capacity damage.
4. **Sequencing:** Project 1 (federation) first (demo + feasibility signal). Then, if we pursue Project 2, build the **gate + admission framework first**, wire **MOD-API harvest** into it, and only then consider **GitHub** as a review-queue plugin.

> This is a feasibility recommendation, not a decision. The user asked for bulk; the honest finding is that *bulk-from-curated-SACs is tractable behind a gate* while *bulk-from-GitHub is not advisable un-reviewed* — the deciding factors are dedup, licensing, quality, and the open #402 capacity limit, in that order.

## References

- Pipeline: `ontoexplorer/modules/jobs/tasks.py:746` (`ingest_ontology`), `ontoexplorer/modules/ingestion/pipeline.py:113` (`run_ingestion`).
- Existing enumerators: `scripts/load_ontologies.py` (LOV/BioPortal), `scripts/seed_ontologies.py` + `seeds/catalog.yaml`.
- GitHub→ingest precedent: `ontoexplorer/api/inbound.py:104` (registered-repo webhook).
- Guards/limits: `ontoexplorer/clients/fetch_guard.py` (SSRF), `config.py` (`ingest_max_source_bytes`, `compliant_licenses`, `ingest_fetch_allow_hosts`).
- Related work: dedup #250/#251, license compliance #364/#425, lock exhaustion **#402 (OPEN)**, index perf (`docs/perf`), update polling #336.
- MOD-API client + adapters: see Project 1 design.
