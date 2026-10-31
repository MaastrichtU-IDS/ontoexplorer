# Cross-repository entity browsing (`/browse`)

**Date:** 2026-10-31
**Status:** Design — approved, pending implementation plan
**Supersedes:** the 2026-07-27 design (shipped as closed PR #73, now 300+ commits stale; its page name `Browse.tsx` was since taken by an unrelated per-ontology class-tree browser).

## Problem

The Home page shows seven clickable repository-wide statistics: Ontologies,
Classes, Object Properties, Data Properties, Annotation Properties, Individuals,
and Axioms. Six of the seven link to `/ontologies` (the plain catalogue list),
so clicking "Classes" (showing e.g. 1.2M) never surfaces a single class. The
number is a promise the destination does not keep.

There is no cross-repository way to browse the entities behind these counts.
Per-ontology browsing exists (the ontology page's class/property trees), and
cross-ontology keyword search exists, but nothing lets a user land on "the
classes across the whole repository" from a stat card and then actually find
one among millions.

## Goals

- Make each repository-wide statistic lead to a page that surfaces the entities
  (or logical content) it counts.
- Make that page **findable at scale**: a flat alphabetical list of 1.2M rows is
  browsable but useless for locating a specific term, so the landing page must
  let the user narrow by text, by meaning, and by ontology.
- Reuse what exists: the Postgres `entity_index` for listing, the new
  pgvector/`term_embeddings` path for semantic ranking, and the existing MOS
  reasoner search for the logical (axiom) case.

## Non-goals

- A cross-repository raw-axiom (triple) listing — delegated to SPARQL.
- De-duplicating entities across ontologies (the same IRI, e.g. `owl:Thing`,
  appears in many; each occurrence is shown, so counts stay consistent with the
  stat cards).
- Faceting by anything other than ontology (no source-namespace facet — decided
  out of scope; ontology-level is enough).
- Migrating the triplestore. Keyset pagination makes `/browse` scale on the
  current substrate, decoupling engine choice from this feature.

## Approach

A new route `/browse`, implemented as `EntityBrowser.tsx` (**not** `Browse.tsx`,
which is an unrelated existing page), mirroring the Home page's two-mode shape:

- **List mode** (default) — a cross-repository listing of entities of one type,
  with a unified search box (text + semantic), a searchable ontology facet, and
  expandable definition snippets.
- **Structured query mode** — the existing reasoner-backed MOS expression search,
  reused unchanged. The **Axioms** stat card lands here (that number is the summed
  triple count, not a browsable axiom store; a flat triple dump is neither
  feasible nor useful, and a Manchester expression is the meaningful probe of
  logical content).

### Stat-card routing (Home)

`StatCard` already takes a `to` prop; only the target strings change.

| Card | Destination |
|------|-------------|
| Ontologies | `/ontologies` (unchanged) |
| Classes | `/browse?type=class` |
| Object Properties | `/browse?type=object_property` |
| Data Properties | `/browse?type=data_property` |
| Annotation Properties | `/browse?type=annotation_property` |
| Individuals | `/browse?type=individual` |
| Axioms | `/browse?mode=query` |

### List mode — unified search

One search box, no mode toggle. Behavior depends on whether a query is present:

- **Empty query → browse.** Keyset-paginated alphabetical listing of the type
  (Next/Previous), ordered by `(primary_label_norm, iri, version_id)`.
- **Non-empty query → search.** Two sections:
  1. **Exact matches** — full-text matches on label/synonyms (via the existing
     `search_tsv`), ranked, keyset-paged (the common case is few enough for one
     page; a cursor provides "more").
  2. **Related by meaning** — a small fixed-size set (K≈8) of semantic neighbors
     from the pgvector cosine search over `term_embeddings` (query embedded with
     the `search_query:` prefix via the gateway), **excluding** anything already
     in the exact-match set. Rendered under a "Related by meaning" divider.

  If the embedding backend is unavailable, the related section is omitted and the
  box degrades to text-only (no hard failure).

### List mode — definition snippets

Each row can show a one-line definition (first entry of `entity_index.definitions`,
trimmed). **Collapsed by default.** Two controls:
- A per-row caret toggles that row's definition.
- A global **Show/Hide definitions** button expands/collapses all at once.

### List mode — ontology facet

A searchable checkbox list of the ontologies that have entities of the current
type, each with a count. Selecting one or more narrows the listing/search to
those ontologies. The facet search filters the list client-side (the full set is
small enough to send once per type). Counts and the ontology set come from a
cached facet endpoint (see Backend).

### List mode — rows

Each row: definition caret · label (links to the term page
`/ontologies/<slug>/<version_id>?term=<iri>`) · CURIE (`short`) · ontology name ·
optional definition line when expanded · a relevance score + bar in the
Related-by-meaning section only.

## Backend

### `GET /api/v1/entities` — listing + text search

One endpoint over `entity_index`, keyset-paginated.

```
GET /api/v1/entities?type=<t>[&q=<text>][&ontology=<id>,<id>][&limit=50][&cursor=<opaque>][&lang=en]
```

- **`type`** validated against the existing allow-list (`class`,
  `object_property`, `data_property`, `annotation_property`, `individual`);
  anything else → 422. **Individuals listing uses `type = 'individual'`** to match
  the Individuals stat-card count exactly (that card counts only `type='individual'`).
  A punned Class+NamedIndividual keeps `type='class'` (first-wins) and so appears
  under Classes, not Individuals. *(Alternative: `is_individual = true` includes
  punned individuals but then the listing exceeds the card — rejected for parity;
  flagged as the one overridable call.)*
- **Version scope:** list only the **latest-ready version per ontology** — the
  same set the stat cards use (`modules/stats/public_stats.py` /
  `modules/search/versions.latest_ready_versions()`). `entity_index` keeps rows
  for *every* indexed version and superseded versions stay `status='ready'`, so a
  status join would list multiple ready versions plus non-counted indexed states
  and inflate the number; this must be a `version_id IN (<latest-ready ids>)`
  filter so rows, counts, and term links all match the clicked number. The id set
  is small (~#ontologies) and already cached for stats.
- **Empty `q` (browse):** keyset listing. Order
  `(primary_label_norm, iri, version_id)` — unique because `(version_id, iri)` is
  the PK. The `cursor` is an opaque `base64(json)` of the last row's key; the
  client only echoes `next`. No OFFSET anywhere.
- **Non-empty `q` (text search):** reuse the existing `pg_entity_search` strategy
  — a bounded pool fetched in index order and ranked in Python, returning a
  **top-N** (e.g. 50), **not** rank-keyset pagination. `ts_rank` is neither stored
  nor indexed, so sorting *all* matches by rank is the multi-second scan
  `pg_search` was written to avoid for common terms ("cell", "protein"). The
  exact-match section is therefore a bounded top-N with no deep "page 2"; true
  keyset/cursor pagination applies to the empty-`q` **browse** case only.
- **`ontology`** optional repeated/CSV filter on `ontology_id`.
- Each row returns: `iri, primary_label, short, type, ontology_id, ontology_title,
  version_id, source, definition` (`definitions[0]["value"]` — the list holds
  `{value, lang}` dicts — trimmed to one line).
- **`approx_total`**: for the unfiltered case (no `q`, no `ontology`) **reuse the
  stat cards' own cached per-type total** (`public_stats`) so "~N" equals the
  clicked number exactly — do not recompute it. For the filtered case (facet /
  ontology selected) return a Redis-cached scoped `COUNT(*)` over the latest-ready
  set (TTL ~300s, direct-count fallback when Redis is down; keeps tests
  SQLite-friendly). Shown as "~N".

Response:
```json
{ "entities": [ { "iri":"...", "primary_label":"...", "short":"GO:0006915",
                  "type":"class", "ontology_id":"...", "ontology_title":"Gene Ontology",
                  "version_id":"...", "source":"...", "definition":"A programmed..." } ],
  "next": "<opaque-cursor-or-null>", "approx_total": 1243918, "limit": 50 }
```

### `GET /api/v1/entities/related` — semantic neighbors

```
GET /api/v1/entities/related?type=<t>&q=<text>[&ontology=...][&k=8][&lang=en]
```

- Embeds `q` via `embedder.embed_query` (applies the `search_query:` prefix from
  config) wrapped in `asyncio.to_thread`, as `semantic.py` does — then a pgvector
  cosine search over `term_embeddings` **filtered by `entity_type`** (and the
  ontology / latest-ready version scope via a join to `entity_index`), ordered by
  distance, `LIMIT k`. A new function is needed so an embed-backend raise can be
  distinguished from an empty result (the existing `semantic_search` collapses
  both to `[]`).
- Joins back to `entity_index` on `(version_id, iri = entity_iri)` for the display
  fields + definition.
- Returns the same row shape as `/entities`, each with a `score` (1 − cosine
  distance). Caller excludes IRIs already shown as exact matches.
- **Degradation:** if `embed_client` raises (backend down) or no embeddings exist
  yet, return `{ "entities": [], "unavailable": true }` (HTTP 200) so the UI just
  drops the Related section.

*(Two endpoints rather than one combined response: keyset text paging and
fixed-K semantic ranking have different pagination models; the frontend fires
both in parallel on a query and composes the two sections.)*

### `GET /api/v1/entities/facets` — ontology facet

```
GET /api/v1/entities/facets?type=<t>
```

- Returns the ontologies that have entities of `type`, with counts:
  `[{ ontology_id, short, title, count }]`, within the same version scope.
- Backed by a `GROUP BY ontology_id` over `entity_index` for the type, **scoped to
  the latest-ready version set** (else an ontology with several ready versions is
  double-counted), **Redis-cached** (TTL ~300s). `entity_index` is a few million
  rows, so the scoped grouped scan is cheap and cached; a maintained
  per-(type,ontology) counter is a future optimization if it ever isn't.

### Indexes (Alembic migration)

- `entity_index (type, primary_label_norm, iri, version_id)` — equality on type
  (covers the Individuals tab too, since it filters `type='individual'`), then the
  keyset range scan for browse mode. The latest-ready `version_id IN (...)` filter
  applies on top; confirm during build that the planner uses this index for the
  range scan (a large `IN` list can tempt it off; verify with `EXPLAIN` on a big
  type like Classes).
- Text search relies on the existing `search_tsv` GIN index; the semantic path on
  the existing `term_embeddings` HNSW index (`vector_cosine_ops`). No new index
  for those.

### Query mode / axioms

No new backend. Query mode reuses the existing global MOS expression search
(same component Home's Structured Query tab uses, including `not_classified`
handling). The axiom fallback is a link from query mode to the existing
`/sparql` starter-query gallery; optionally a few axiom-oriented starter queries
can be added there (data, not code).

## Frontend

- **`EntityBrowser.tsx`** at `/browse`, registered in `App.tsx` inside the public
  shell. Reads `mode` (`list` default | `query`) and `type` (`class` default)
  from the URL (`useSearchParams`); writes them back on interaction. Cursor
  position is component state, not URL (keyset cursors aren't meaningful to
  deep-link; `type`/`mode` are shareable, a specific page is not).
- **Unified search:** debounced input → on empty, `useEntities` keyset listing;
  on non-empty, fire `/entities?q=` and `/entities/related` in parallel and render
  the two sections. Keep previous rows visible while fetching (skeleton on first
  load).
- **Definitions:** global `showDefs` state + a per-row expanded set; a row shows
  its definition when either is set.
- **Facet:** `useFacets(type)` → searchable checkbox list; selection drives the
  `ontology` param on both calls.
- **Pager:** Next/Previous cursor stack (push on Next, pop on Previous; reset on
  type/query/facet change). Not the offset-based `TablePager`.
- **Home wiring:** change the seven `StatCard` `to` targets per the routing table,
  **and** extract the structured-query UI (`MOSQuery` plus its deps — `RelationChips`
  and the relation state it owns) out of `Home.tsx` into a shared module that both
  Home and `EntityBrowser` import. `MOSQuery` is currently an internal, un-exported
  Home component, so query-mode reuse requires this extraction (a small refactor
  with Home test churn), not a copy.
- **API client + hooks:** `api.entities.list / related / facets` in `lib/api.ts`,
  plus `useEntities` / `useRelated` / `useFacets` react-query hooks mirroring the
  existing `useOntologies` pattern.

## States and error handling

- **Browse:** loading → skeleton rows; empty → "No <type> in the repository yet.";
  error → inline retry; last page → Next disabled.
- **Search:** no exact match but related present → "No exact match — related by
  meaning:"; neither → empty state; related backend down → related section simply
  absent.
- **Query mode:** inherits the MOS component's existing states.

## Testing

**Backend:**
- `/entities`: correct rows per type and order; keyset page 2 (via page 1's
  `next`) has no overlap/gap and `next` is null on the last page; `type` validation
  (422); excludes pending/failed/deprecated; individuals come from `is_individual`
  (a punned Class+NamedIndividual appears under Individuals and under Classes);
  `definition` is the trimmed first definition; `approx_total` via the direct-count
  fallback (Redis absent under test).
- `/entities/related`: returns type-filtered neighbors with scores, excludes
  nothing server-side (caller dedupes); `unavailable:true` when the embed client
  raises (mock it) — never a 5xx.
- `/entities/facets`: counts per ontology for the type, within version scope;
  fallback path without Redis.
- Migration: the two new indexes are created and reversible.

**Frontend (`EntityBrowser.test.tsx`):**
- Tab switch updates URL `type`, resets cursor/facet/expanded.
- Empty query → keyset list; Next advances via the returned cursor, Previous
  returns; last page disables Next.
- Non-empty query → exact + related sections render; related omitted when the API
  reports `unavailable`.
- Definition caret toggles one row; global toggle flips all.
- Facet search filters the list; selecting an ontology narrows results.
- Row click navigates to the term page URL; `mode=query` renders the MOS UI and
  the Axioms card lands there.

## Dependencies / sequencing

- The semantic path depends on the embedding migration being live (the
  `term_embeddings` GGUF re-embed + atomic swap, and `EMBEDDING_*` configured on
  the API). Until then, `/entities/related` returns `unavailable:true` and the
  page is text-only — so List/browse/text can ship independently of the swap, and
  the Related section lights up once embeddings are in place.

## Resolved by builder review (2026-10-31)

- **Version scope** corrected to latest-ready-per-ontology (not a status join), so
  the page honors the clicked number; `approx_total` reuses the stat cards' cached
  total. (Was the critical gap.)
- **Text search** is bounded top-N via `pg_entity_search`, not rank-keyset paging
  (which would hit the `ts_rank` full-scan trap). Keyset paging is browse-only.
- **Query-mode reuse** requires extracting `MOSQuery` from `Home.tsx` into a shared
  module.
- `definitions[0]["value"]` is the snippet; `embedder.embed_query` applies the
  query prefix; a new `/related` helper distinguishes an embed raise from empty.

## One call for the author to confirm

- **Individuals: parity vs completeness.** The plan uses `type='individual'` so the
  listing count matches the Individuals stat card, at the cost of omitting *punned*
  Class+NamedIndividual entities (which still appear under Classes). The alternative
  — `is_individual=true` — is more complete but makes the listing exceed the card.
  Say the word to flip it.
