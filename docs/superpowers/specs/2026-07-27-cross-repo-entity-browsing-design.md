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

- **List mode** — a cross-repository, paged listing of entities of one type,
  backed by the existing Postgres `entity_index` table. Type tabs across the
  top: Classes · Object Properties · Data Properties · Annotation Properties ·
  Individuals. State lives in the URL (`/browse?type=class&page=2`). Each row
  links to that term's page.
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

One new endpoint, one SQL query over `entity_index` (no SPARQL fan-out):

```
GET /entities?type=<t>&limit=50&offset=0&lang=en&q=
```

Listing query (empty `q`):

```sql
SELECT ei.iri, ei.primary_label, ei.short, ei.type,
       ei.ontology_id, ei.version_id, ei.source
FROM entity_index ei
JOIN versions v ON v.id = ei.version_id
WHERE v.status NOT IN ('pending','failed','deprecated')
  AND ei.type = :type
ORDER BY ei.primary_label_norm, ei.iri
LIMIT :limit OFFSET :offset
```

A `COUNT(*)` with the same `WHERE` returns the total so the pager can compute
page count. Response shape:

```json
{ "entities": [ { "iri": "...", "label": "...", "short": "...", "type": "class",
                  "ontology_id": "...", "version_id": "...", "source": "..." } ],
  "total": 1234567, "limit": 50, "offset": 0 }
```

Rules:

- **`type`** validated against the existing allow-list already used by global
  search: `class`, `object_property`, `data_property`, `annotation_property`,
  `individual`. Anything else → 422.
- **No deduplication.** The same IRI appears across ontologies (e.g. `owl:Thing`);
  List mode shows every occurrence, each tagged with its ontology, so the total
  matches the stat-card count (which counts occurrences, not unique IRIs). The
  Home cards already display "N unique" as a subtitle, so this stays consistent.
- **`q` (optional).** Non-empty `q` delegates to the existing
  `pg_entity_search` (already type-aware) rather than the listing query. Empty
  `q` = the paged listing above.
- **Deep-offset guard.** Large `OFFSET` on a big table degrades. Cap reachable
  offset (e.g. `offset ≤ 10_000`); beyond it the endpoint returns a flag /
  the pager stops and the UI shows "Refine with search to go deeper."
- **Index.** Add a btree on `entity_index (type, primary_label_norm)` to serve
  the `ORDER BY` and `type` filter. Small Alembic migration.

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

- Reads `mode` (`list` default, or `query`), `type` (default `class`), and
  `page` from the URL via `useSearchParams`; writes them back on interaction so
  the view is shareable and back-button friendly.
- **Mode toggle** identical to Home's (Keyword-equivalent "List" vs "Structured
  Query").
- **List mode:** type tabs → a results list (reuse the row rendering pattern
  from Home's `ResultList` — TypeBadge, label linking to
  `/ontologies/<slug>/<version_id>?term=<iri>`, source badge, ontology badge) →
  `TablePager` (existing component) driven by `total`. Switching tabs resets to
  page 1 and updates the URL.
- **Query mode:** render the existing `MOSQuery` component. Add a one-line
  header note: "Probe the logical content with a Manchester expression, or
  [browse axioms in SPARQL →]" linking to `/sparql/gallery`.

### Frontend — Home wiring

Change only the `to` targets of the seven `StatCard`s per the routing table
above. No structural change to `Home.tsx`.

### Frontend — API client

Add `api.entities.list({ type, limit, offset, lang, q })` in `lib/api.ts`
returning the response shape above, plus a `useEntities` hook (react-query)
mirroring the existing `useOntologies` / search hooks.

## Data flow

1. User clicks "Classes" on Home → navigates to `/browse?type=class`.
2. `Browse.tsx` reads `type=class`, `mode=list` (default), `page=1`.
3. `useEntities({ type: 'class', limit, offset: 0 })` → `GET /entities?...`.
4. Backend runs the listing query + count over `entity_index`, returns rows +
   total.
5. Rows render as links; `TablePager` uses `total` for page controls.
6. Clicking a row navigates to that term's page in its ontology.
7. Clicking "Axioms" on Home → `/browse?mode=query` → `MOSQuery` mounts.

## States and error handling

**List mode:**
- Loading → skeleton rows.
- Empty (`total === 0`) → "No <type> in the repository yet."
- Error → inline message with a retry control.
- Deep offset past the cap → pager disables "next", shows "Refine with search to
  go deeper."

**Query mode:** inherits `MOSQuery`'s existing states — searching, no results,
`not_classified` guidance, per-ontology errors.

## Testing

**Backend (`/entities`):**
- Returns correct rows and `total` per type.
- Type validation rejects unknown values (422).
- Excludes `pending` / `failed` / `deprecated` versions.
- Offset cap enforced.
- Ordering is `(primary_label_norm, iri)`.

**Frontend (`Browse.test.tsx`):**
- Tab switch updates URL `type` and resets to page 1.
- Pager paging issues the right offset and renders returned rows.
- Empty and error states render.
- Row click navigates to the term page URL.
- `mode=query` renders the MOS query UI; Axioms stat card lands here.

**Migration:** the new `(type, primary_label_norm)` index is created and
reversible.

## Out of scope

- A cross-repository raw-axiom (triple) listing — deliberately delegated to
  SPARQL.
- A per-ontology "all axioms in Manchester" listing endpoint (considered,
  rejected in favour of SPARQL starter queries).
- De-duplicating entities across ontologies in List mode.
- Faceting List mode by ontology (possible future addition; the URL/endpoint
  leave room for a future `ontology_id` filter).
