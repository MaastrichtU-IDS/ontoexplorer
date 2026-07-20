# Pluggable Reasoners — SP2: App Plumbing

**Date:** 2026-07-17
**Status:** Design (feature approved during SP1 brainstorming; SP2 decisions documented below)
**Depends on:** SP1 (reasoner-service engine layer — merged/PR #7). Branch off `feat/pluggable-reasoners`.
**Scope:** Make the reasoner a first-class, per-ontology property in the main app and route it end-to-end. No admin/UI work (that is SP3).

## Background

SP1 made the reasoner-service reasoner-aware: `POST /classify` and the justification
endpoint accept a `reasoner`, cache is reasoner-scoped, and `GET /reasoners`
reports `{name, profile, capabilities, available}` for whelk/rdflib/rustdl/konclude.
Today the main app never sends a `reasoner` — every classification defaults to
whelk. SP2 wires the choice through the app so each ontology is classified (and
explained) by the reasoner selected at ingest.

Feature-level decisions (fixed in SP1 brainstorming, apply here):
- Reasoner selection is first-class: a **global default in `.env`**, overridable
  **per-ontology at ingest time**, bound to the version.
- **Explanations follow the reasoner** (rustdl native / whelk proof-walk /
  Konclude disabled).

## SP2-specific decisions

1. **Storage:** a `reasoner` column on `versions` (`OntologyVersion`,
   `models/db.py:111`) — `String`, `NOT NULL`, default `"whelk"`. Bound per
   version. Alembic migration adds the column and backfills existing rows to
   `"whelk"` (their classifications were produced by whelk).
2. **App default:** a `default_reasoner: str = "whelk"` setting in `config.py`
   (env `DEFAULT_REASONER`), used when an ingest request omits `reasoner`. This
   is the *app-side* default; the service also has its own fallback, but the app
   always sends an explicit reasoner after SP2.
3. **Selection at ingest:** `POST /api/v1/ontologies` (`submit_ontology`,
   `api/ontologies.py:214`) accepts an optional `reasoner` — in the JSON body and
   as a multipart form field. It is **validated at submit time** against the
   reasoner-service `GET /reasoners`: unknown or `available: false` → HTTP 422
   with the list of available names. Threaded through `ingest_ontology.delay(...)`
   → stored on the version row the ingestion pipeline creates.
4. **Immutable after ingest (v1):** the reasoner is fixed for a version. To
   change it, re-ingest (a new version). No "re-classify with a different
   reasoner" endpoint in SP2 (YAGNI; the reasoner-scoped cache from SP1 leaves
   the door open for it later).
5. **Justification `manchester` format:** SP2 routes the version's reasoner to
   the justification endpoint and passes the `format` through. For
   `format == "ntriples"` (whelk/rdflib) the existing `_render_justification`
   N-Triples→AST path is unchanged. For `format == "manchester"` (rustdl), SP2
   returns the raw Manchester axiom strings in the response under a documented
   shape; a polished typed rendering of Manchester is **SP3** (UI). A reasoner
   with no `justify` capability (Konclude) surfaces as
   `{"reasoning_available": false, "reason": "reasoner '<name>' has no explanations"}`
   rather than an error.

## Architecture / data flow

```
submit_ontology (reasoner?, validate vs /reasoners)
  └─ ingest_ontology.delay(..., reasoner=<resolved>)
       └─ pipeline creates OntologyVersion(reasoner=<resolved>)
            └─ reason_ontology(version_id)
                 └─ _run_reasoning: read version.reasoner
                      └─ reasoning_client.classify_v2(graph, version_id, reasoner)
                           └─ POST /classify {ntriples, version_id, reasoner}
GET term inferences  → reasoning_client GET /classify/{v}/...?reasoner=<version.reasoner>
GET justification    → reasoning_client POST /classify/{v}/justification {…, reasoner}
                        → 422-if-no-justify handled; format threaded to renderer
```

## Components / changes

- **`models/db.py:111`** — add `reasoner: Mapped[str] = mapped_column(String, nullable=False, server_default="whelk")` to `OntologyVersion`.
- **Alembic migration** (new revision) — add `versions.reasoner` (not null, server default `'whelk'`), backfill existing rows to `'whelk'`. Follows the repo's existing migration style under `alembic/versions/`.
- **`config.py`** — add `default_reasoner: str = "whelk"` (env `DEFAULT_REASONER`), following the file's pydantic-settings pattern.
- **`api/ontologies.py:214` `submit_ontology`** — parse `reasoner` (body + form), resolve `reasoner or settings.default_reasoner`, validate against `GET /reasoners` (a small `reasoning_client.list_reasoners()` helper, cached briefly), pass to every `ingest_ontology.delay(...)` call.
- **`ingest_ontology` task** — accept `reasoner: str` kwarg; the pipeline persists it on the created `OntologyVersion`.
- **`modules/jobs/tasks.py` `_run_reasoning` (:397)** — load `version.reasoner`, pass to `classify_v2`.
- **`clients/reasoning.py`** —
  - `classify_v2(graph, version_id, reasoner)`: include `"reasoner"` in the POST body and in the poll GET (`/classify/{v}?reasoner=`).
  - the term-inference GET wrappers (superclasses/subclasses/consistency) gain a `reasoner` arg → `?reasoner=`.
  - `request_justification(version_id, sub, sup, max, reasoner)`: include `reasoner`; treat 422 (no-justify) as "not available" rather than raising.
  - add `list_reasoners()` → `GET /reasoners` (for submit-time validation).
  - callers of these read `version.reasoner` and pass it.
- **`api/ontologies.py` `get_justification` + `_render_justification`** — pass the version's reasoner; branch on `format`: `"ntriples"` → existing AST render; `"manchester"` → pass raw axiom strings through (SP3 renders); no-justify reasoner → `reasoning_available: false`.

## Non-goals (SP2)

- No admin dropdown, no reasoner shown in the UI, no typed Manchester rendering — **SP3**.
- No re-classify-with-different-reasoner endpoint.
- No change to the SP1 reasoner-service.

## Testing

- Migration: upgrade on a DB with existing versions → column present, existing rows `'whelk'`; downgrade drops it.
- `submit_ontology`: `reasoner` accepted (body + form); unknown/unavailable → 422; omitted → app default; threaded into `ingest_ontology.delay` (assert via mock).
- `_run_reasoning`: reads `version.reasoner` and calls `classify_v2` with it (mock the client, assert the reasoner argument).
- `clients/reasoning.py`: `classify_v2` puts `reasoner` in the POST body + poll URL; justification 422 → `reasoning_available: false`; `list_reasoners()` parses `/reasoners`.
- `get_justification`: routes the version's reasoner; `manchester` format passes axioms through; Konclude version → not-available response, not 500.
- End-to-end (integration, best-effort with the running stack): ingest a tiny ontology with `reasoner=rustdl`, confirm the version row stores it, classification runs via rustdl, and `superclasses` come back.

## Risks / open items

- **`available` at submit depends on the reasoner-service being reachable.** If `GET /reasoners` is down, fall back to accepting known names (whelk/rdflib/rustdl/konclude) rather than blocking ingest; log a warning. (Validation is a guardrail, not a hard dependency.)
- **Existing local caches** (`clients/reasoning.py` 10-min per-version cache) are keyed by `version_id`; since a version's reasoner is immutable, no key change is needed, but `invalidate_cache` on deprecation/re-ingest still applies.
- **Manchester passthrough** means rustdl-classified ontologies show justification axioms as raw Manchester text until SP3 adds typed rendering — acceptable interim.

## Forward pointer

- **SP3 — admin/UI:** reasoner dropdown at add-ontology (from `GET /reasoners`),
  reasoner shown on the ontology detail, explain button enabled/disabled by
  capability, typed rendering of `manchester` justifications.
