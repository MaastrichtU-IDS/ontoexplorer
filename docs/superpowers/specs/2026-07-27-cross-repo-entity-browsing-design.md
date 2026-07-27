# Cross-repository entity browsing (`/browse`)

**Date:** 2026-07-27
**Status:** Design — approved, pending implementation plan

## Problem

The Home page shows seven clickable repository-wide statistics: Ontologies,
Classes, Object Properties, Data Properties, Annotation Properties, Individuals,
and Axioms. Six of the seven link to `/ontologies` (the plain ontology list),
so clicking "Classes" (showing e.g. 1.2M) does not let a user see or reach any
classes. The number is a promise the destination does not keep.

There is no cross-repository way to browse the entities behind these counts.
Per-ontology browsing already exists (the `OntologyPage` left pane has trees for
classes, object/data/annotation properties, and a flat individual list), and
cross-ontology keyword search exists (`useGlobalSearch` + the Home keyword tab),
but nothing lets a user land on "the classes across the whole repository" from a
stat card.

## Goal

Make each repository-wide statistic lead somewhere that actually surfaces the
entities (or logical content) it counts, without a flat dump of millions of rows.

## Approach

A new route `/browse` mirroring the Home page's existing two-mode structure
(Keyword / Structured Query):

- **List mode** — a cross-repository, cursor-paged listing of entities of one
  type, backed by the existing Postgres `entity_index` table. Type tabs across
  the top: Classes · Object Properties · Data Properties · Annotation Properties
  · Individuals. `type` and `mode` live in the URL; the page position is an
  opaque cursor advanced via Next/Previous (see "Scale" below). Each row links to
  that term's page.
- **Query mode** — the reasoner-backed MOS structured-query experience, reused
  from Home's `MOSQuery` component. State: `/browse?mode=query`.

### Stat-card routing (Home)

`StatCard` already accepts a `to` prop; only the target strings change.

| Card | Destination |
|------|-------------|
| Ontologies | `/ontologies` (unchanged) |
| Classes | `/browse?type=class` |
| Object Properties | `/browse?type=object_property` |
| Data Properties | `/browse?type=data_property` |
| Annotation Properties | `/browse?type=annotation_property` |
| Individuals | `/browse?type=individual` |
| Axioms | `/browse?mode=query` |

**Why Axioms → Query mode:** the "Axioms" stat is in fact the summed triple
count (`api/stats.py` sums each version's `triple_count`), not a count of OWL
axioms. There is no bulk axiom store — per-term Manchester axioms are computed
on demand by scanning a single graph for a single term (`_sparql_usage` +
`modules/diff/manchester`). A flat list of ~200M triples is neither feasible nor
useful. A MOS expression, by contrast, is a reasoner-backed probe of the logical
(axiomatic) content, which is the meaningful "browse the axioms" experience.

## Components

### Backend — List mode endpoint

One new endpoint, one SQL query over `entity_index`, **keyset (cursor)
paginated** so it stays O(page) regardless of depth. This is the critical
scaling decision: at tens-to-hundreds of millions of entities, `OFFSET` is
O(offset) in every engine (Postgres, Oxigraph, QLever alike), so we page by a
stable sort-key cursor instead of an offset.

```
GET /entities?type=<t>&limit=50&cursor=<opaque>&q=
```

Ordering / cursor key is the tuple `(primary_label_norm, iri, version_id)` —
unique because `(version_id, iri)` is the table's primary key. The `cursor` is
an opaque base64(JSON) blob carrying the last row's key; the client never
constructs it, it just echoes back the `next` value.

Listing query (empty `q`) — the keyset comparison is written in expanded form
so it runs identically on Postgres and the SQLite test DB:

```sql
SELECT ei.iri, ei.primary_label, ei.short, ei.type,
       ei.ontology_id, ei.version_id, ei.source, ei.primary_label_norm
FROM entity_index ei
JOIN versions v ON v.id = ei.version_id
WHERE v.status NOT IN ('pending','failed','deprecated')
  AND ei.type = :type
  -- only when a cursor is supplied:
  AND ( ei.primary_label_norm > :al
        OR (ei.primary_label_norm = :al AND ei.iri > :ai)
        OR (ei.primary_label_norm = :al AND ei.iri = :ai AND ei.version_id > :av) )
ORDER BY ei.primary_label_norm, ei.iri, ei.version_id
LIMIT :limit
```

Response shape (`next` is null when the last page is reached; `approx_total` is
a **cached, approximate** count — see below — never used for cursor logic):

```json
{ "entities": [ { "iri": "...", "label": "...", "short": "...", "type": "class",
                  "ontology_id": "...", "version_id": "...", "source": "..." } ],
  "next": "<opaque-cursor-or-null>", "approx_total": 1234567, "limit": 50 }
```

Rules:

- **`type`** validated against the existing allow-list already used by global
  search: `class`, `object_property`, `data_property`, `annotation_property`,
  `individual`. Anything else → 422.
- **No deduplication.** The same IRI appears across ontologies (e.g. `owl:Thing`);
  List mode shows every occurrence, each tagged with its ontology, so the count
  matches the stat-card count (which counts occurrences, not unique IRIs). The
  Home cards already display "N unique" as a subtitle, so this stays consistent.
- **`approx_total`.** A `COUNT(*)` over one type at 100M+ scale is itself a full
  scan, so it is **not** computed per request: the endpoint returns a count
  cached in Redis (TTL ~300s), falling back to a direct `COUNT(*)` when Redis is
  unavailable (matches the existing `terms` endpoint's best-effort Redis
  pattern; keeps the count path testable on SQLite). The UI shows it as "~N".
  A maintained per-type counter is a future optimisation if a single cached
  `COUNT` ever gets too slow.
- **`q` (optional).** Non-empty `q` delegates to the existing `pg_entity_search`
  (already type-aware) rather than the keyset listing. Empty `q` = the listing
  above. (List mode ships without a search box in v1; the plumbing is present
  for a later addition.)
- **Index.** Add a btree on `entity_index (type, primary_label_norm, iri,
  version_id)` — equality on `type`, then the keyset range scan over the sort
  tuple. Small Alembic migration.

There is no deep-offset problem to guard against: keyset paging has no offset.

### Backend — Query mode

No new backend. Query mode reuses the existing global MOS search fan-out
(`api/global_search.py` expression path) exactly as Home's Structured Query tab
does today, including the `not_classified` (503) handling.

### Backend — Axiom fallback

No new backend. The "browse axioms without writing an expression" fallback is a
link from Query mode to the existing SPARQL page / starter-query gallery
(`/sparql`, `/sparql/gallery`), which is the tool built for raw triples. If
useful, a small set of axiom-oriented starter queries (e.g. "all SubClassOf
axioms in an ontology") can be added to the existing starter-query set — that is
data, not new code.

### Frontend — `Browse.tsx`

New page at route `/browse`, registered in `App.tsx` inside the public `Shell`
(alongside `/ontologies`, `/search`). Structure:

- Reads `mode` (`list` default, or `query`) and `type` (default `class`) from
  the URL via `useSearchParams`; writes them back on interaction. The cursor
  position is component state (Next/Previous), not URL state — keyset cursors
  are not meaningful to deep-link, so `type`/`mode` are shareable but a specific
  page is not.
- **Mode toggle** identical to Home's ("List" vs "Structured Query").
- **List mode:** type tabs → a results list (row rendering modelled on Home's
  `ResultList` — type badge, label linking to
  `/ontologies/<slug>/<version_id>?term=<iri>`, source badge, ontology badge) →
  a **Next/Previous cursor pager** (not `TablePager`, which is offset/page
  based). The component keeps a stack of cursors: Next pushes the current cursor
  and loads `response.next`; Previous pops. Switching type resets the stack and
  cursor. A "~N total" label uses `approx_total`.
- **Query mode:** render the existing `MOSQuery` component. Add a one-line
  header note: "Probe the logical content with a Manchester expression, or
  [browse axioms in SPARQL →]" linking to `/sparql/gallery`.

### Frontend — Home wiring

Change only the `to` targets of the seven `StatCard`s per the routing table
above. No structural change to `Home.tsx`.

### Frontend — API client

Add `api.entities.list({ type, limit, cursor, lang, q })` in `lib/api.ts`
returning the response shape above, plus a `useEntities` hook (react-query)
mirroring the existing `useOntologies` / search hooks.

## Data flow

1. User clicks "Classes" on Home → navigates to `/browse?type=class`.
2. `Browse.tsx` reads `type=class`, `mode=list` (default); cursor starts null.
3. `useEntities({ type: 'class', limit, cursor: null })` → `GET /entities?...`.
4. Backend runs the keyset listing query (+ cached `approx_total`), returns rows
   and a `next` cursor.
5. Rows render as links; Next/Previous drive the cursor stack.
6. Clicking a row navigates to that term's page in its ontology.
7. Clicking "Axioms" on Home → `/browse?mode=query` → `MOSQuery` mounts.

## States and error handling

**List mode:**
- Loading → skeleton rows (keep previous rows while fetching the next page).
- Empty (`approx_total === 0` and no rows) → "No <type> in the repository yet."
- Error → inline message with a retry control.
- Last page reached (`next === null`) → Next button disabled.

**Query mode:** inherits `MOSQuery`'s existing states — searching, no results,
`not_classified` guidance, per-ontology errors.

## Testing

**Backend (`/entities`):**
- Returns correct rows per type, ordered by `(primary_label_norm, iri, version_id)`.
- Keyset paging: page 2 (using page 1's `next` cursor) returns the following
  rows with no overlap and no gap; `next` is null on the final page.
- `approx_total` reflects the count for the type (direct-count fallback path,
  Redis absent under test).
- Type validation rejects unknown values (422).
- Excludes `pending` / `failed` / `deprecated` versions.

**Frontend (`Browse.test.tsx`):**
- Tab switch updates URL `type` and resets the cursor/stack.
- Next advances using the returned cursor and renders the new rows; Previous
  returns to the prior page.
- Empty and error states render.
- Row click navigates to the term page URL.
- `mode=query` renders the MOS query UI; Axioms stat card lands here.

**Migration:** the new `(type, primary_label_norm, iri, version_id)` index is
created and reversible.

## Out of scope

- A cross-repository raw-axiom (triple) listing — deliberately delegated to
  SPARQL.
- A per-ontology "all axioms in Manchester" listing endpoint (considered,
  rejected in favour of SPARQL starter queries).
- De-duplicating entities across ontologies in List mode.
- Faceting List mode by ontology (possible future addition; the URL/endpoint
  leave room for a future `ontology_id` filter).
- Migrating the primary triplestore (e.g. to QLever). QLever scales to
  billions of triples and has strong text/autocomplete, but its named-graph
  handling is "not yet efficient when a permutation sorted by G is required",
  its SPARQL UPDATE is still WIP, and it does no OWL reasoning — all of which
  our per-version, mutable, reasoner-backed model depends on. Keyset pagination
  makes `/browse` scale to 100M+ on the current substrate, so the engine choice
  is decoupled from this feature and left to a separate evaluation.
