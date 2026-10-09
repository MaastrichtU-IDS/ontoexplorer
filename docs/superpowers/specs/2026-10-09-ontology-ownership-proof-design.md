# Ontology ownership-proof layer — design

**Status:** draft for review · **Date:** 2026-10-09 · **Author:** Michel Dumontier + Claude

## Purpose & intent

PR #299 closed the concrete *hijack* vector: a user can no longer inject a version
into an **existing** ontology they don't own/maintain. But registration of a
**brand-new** IRI is still first-come-first-served — a user can register any IRI,
including a well-known one (`http://purl.obolibrary.org/obo/go.owl`,
`https://w3id.org/sulo/`) they don't actually publish, impersonating an
established ontology.

Most ontology IRIs live on **shared community redirect namespaces** (`w3id.org`,
`purl.obolibrary.org`, `purl.org`, `identifiers.org`) that no individual uploader
controls at the DNS level, so classic domain-verification (DNS TXT / `.well-known`)
does **not** fit the ecosystem. The chosen posture is therefore **detect &
curate, not hard-prevent**:

- **Always record provenance** (who registered what, from where, when).
- Run a **dereference check** as a *trust signal* (does the canonical IRI resolve,
  and does the authoritative location self-identify as this ontology).
- Registrations are **published immediately** but carry a **verification badge**;
  nothing blocks on upload.
- **Admins curate**: mark an ontology `verified`, or `dispute` a suspicious claim.

### In scope
Provenance surfacing; a dereference-based verification signal; a status model +
badge; an admin verify/dispute workflow.

### Out of scope (explicitly)
- Hard blocking / quarantine on upload (rejected in favour of badging).
- A curated reserved-namespace allowlist (rejected — high maintenance; the
  dereference signal covers the intent).
- DNS / `.well-known` domain-ownership proof (doesn't map to shared namespaces).
- Cryptographic signing of ontologies.

## Decisions (confirmed)

1. **`canonical_verified` definition:** the registered IRI **resolves to RDF whose
   declared `owl:Ontology` IRI (or `vann:preferredNamespaceUri`) canonicalizes to
   the registered IRI.** The authoritative location self-identifying as this
   ontology is the signal. Content overlap (shared class-IRI ratio vs the stored
   version) is **recorded as a sub-detail** but does **not** gate the badge —
   serializations/versions diverge too much to threshold reliably.
2. **Dispute/Revoke:** badge the ontology `⚠ Disputed` **and unlist it from
   catalogue + search**, but keep it **reachable by direct link** and **fully
   reversible**. Never an automatic delete (that stays a separate explicit action).
3. **Phased delivery** (below).

## Data model

Add to `ontologies` (one migration):

| column | type | notes |
|---|---|---|
| `verification_status` | `str` default `'unverified'` | one of: `unverified`, `canonical_verified`, `mismatch`, `unresolvable`, `admin_verified`, `disputed` |
| `verified_by` | FK `users.id` nullable, `ON DELETE SET NULL` | set only for admin actions (`admin_verified` / `disputed`) |
| `verified_at` | timestamptz nullable | last time status changed via admin or dereference |
| `verify_detail` | JSON nullable | `{ resolved_url, http_status, declared_iri, match_basis, class_overlap, checked_at }` |

Status precedence (highest wins): `admin_verified` and `disputed` are **sticky**
admin overrides — the dereference task never overwrites them. Otherwise the task
sets `canonical_verified` / `mismatch` / `unresolvable`.

Registrant provenance already exists and is reused: `ontologies.owner_id` →
display name + ORCID (`users` + `oauth_accounts`), `versions.source_url`,
`versions.sha256`, submit kind (iri/url/file/content). No new provenance columns.

## Components

### 1. Provenance surfacing (phase 1)
Expose on the ontology detail + catalogue list rows (owner name + ORCID already
present in the lean row): *"Registered by {display_name} ({ORCID}) · via
{IRI|URL|file} · {date}"*. Derive the submit kind from `versions.source_url`
presence / a small `source_kind` hint if not already recorded.

### 2. Verification badge (phase 1)
A small badge component, status-derived:

| status | badge | meaning |
|---|---|---|
| `admin_verified` | `✓ Verified` (solid) | an admin confirmed authenticity |
| `canonical_verified` | `✓ Canonical` | the IRI resolves & self-identifies as this ontology |
| `unverified` | `⚠ Unverified submission` | default; not yet checked |
| `mismatch` / `unresolvable` | `⚠ Unverified submission` (tooltip explains) | checked, no positive signal |
| `disputed` | `⚠ Disputed` | admin flagged; unlisted from catalogue/search |

Badge shows on the ontology page and catalogue card; tooltip carries the
provenance line + check detail.

### 3. Dereference verification task (phase 2)
A Celery task `verify_ontology_canonical(ontology_id)` on the light/IO queue,
dispatched after a version reaches `ready` (and manually re-triggerable):
1. Skip if status is a sticky admin override (`admin_verified` / `disputed`).
2. Fetch the canonical IRI with redirects, a short timeout, and a response-size
   cap (reuse the ingest `resolve_iri` fetch limits). Record `resolved_url`,
   `http_status`.
3. If non-RDF / unreachable → `unresolvable`.
4. Parse; extract the declared `owl:Ontology` IRI + `vann:preferredNamespaceUri`
   (reuse `_extract_ontology_iri_*` / `canonicalize_ontology_iri`). If it
   canonicalizes to the registered IRI → `canonical_verified`; else → `mismatch`.
5. Compute class-IRI overlap vs the stored latest version (from `entity_index`)
   into `verify_detail.class_overlap` (informational only).
6. Write status + `verify_detail` + `verified_at`.

Safety: best-effort and side-effect-free (reads only); a fetch failure yields
`unresolvable`, never an exception that affects ingest.

### 4. Admin workflow (phase 1 for actions; queue uses status)
- Admin endpoints: `POST /admin/ontologies/{id}/verify` and
  `.../dispute` (+ an `/unverify` reset), each `require_admin`, setting
  `verification_status` = `admin_verified` / `disputed` / cleared, with
  `verified_by`/`verified_at`.
- Dispute additionally excludes the ontology from the default catalogue list +
  `/search` (a `verification_status != 'disputed'` predicate on `list_ontologies`
  and the OLS/global search), reversible by clearing the status.
- Admin review queue: an admin page listing ontologies by status (default:
  `disputed`, `mismatch`, `unresolvable`), with Verify / Dispute / Re-check
  actions. Reuses the existing admin dashboard patterns.

## API changes
- `Ontology` response gains `verification_status`, `verified_at`, and a derived
  `registered_by` provenance block (name + ORCID + source). Lean list row gains
  `verification_status` (for the badge).
- `list_ontologies` + search exclude `disputed` by default (admins can include via
  a flag).
- New admin verify/dispute/recheck endpoints (above).

## Phasing
- **Phase 1 (immediate, low-risk, no network):** migration + status model +
  provenance surfacing + badge + admin verify/dispute endpoints + catalogue/search
  exclusion of `disputed`. Everything defaults to `unverified`; purely additive.
- **Phase 2:** the dereference task + auto-status + a "Re-check" admin action +
  dispatch-after-ingest hook.
- **Phase 3 (optional):** batch backfill the ~1,900 existing ontologies through
  the dereference task (rate-limited); periodic re-verification (IRIs drift).

## Testing
- Unit: status precedence (admin overrides sticky); badge mapping; the
  canonical-match decision (`canonical_verified` vs `mismatch` vs `unresolvable`)
  with mocked fetch/parse; `list_ontologies`/search excluding `disputed`; admin
  endpoints' `require_admin` gating.
- Integration: verify/dispute round-trip changes listing visibility.
- The dereference fetch is mocked in tests (no live network).

## Risks / open questions
- **False `mismatch`:** many legit ontologies don't resolve to RDF at their IRI
  (HTML landing page, auth-walled, moved). Hence `mismatch`/`unresolvable` are
  *neutral* ("unverified"), never punitive — only admins `dispute`.
- **Re-verification cadence** (phase 3) — left unspecified; start manual + on new
  version, add periodic later if useful.
- **Fetch abuse / SSRF:** the task fetches user-influenced URLs. Reuse the ingest
  resolver (`resolve_iri`) rather than adding a new fetch path, and — as a planning
  step — **audit that resolver for SSRF/size/timeout guards** (block internal/link-
  local targets, cap size, bound time); add them there if missing, since ingest
  shares the exposure.
