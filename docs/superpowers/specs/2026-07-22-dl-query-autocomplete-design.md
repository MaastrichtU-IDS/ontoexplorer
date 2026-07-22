# DL-Query (MOS) Autocomplete — Design

**Status:** Delivered (retrospective). Shipped incrementally in PRs #18–#29, released through 0.3.6.

**Scope:** The context-sensitive autocomplete behind the Structured Query / DL-query boxes, both the per-ontology **Query** tab and the front-page **Structured Query** box. Covers the Manchester OWL Syntax (MOS) parse-and-suggest pipeline, the Postgres-backed entity ranking, keyword/cardinality suggestions, observed-filler suggestions, and the frontend dropdown interaction. It does **not** cover query *evaluation* except where the autocomplete's promises must match what the evaluator can actually answer (cardinality semantics).

**Why this doc exists:** The feature was built as a sequence of ad-hoc requests with no governing spec. This captures the delivered design so the next change starts from a written baseline instead of re-derived intent.

---

## Goal

As a user types a Manchester class expression (e.g. `'has part' some 'unit'`), suggest the *right kind* of token at the cursor: an entity when an entity is expected, the legal keywords when a keyword is expected, cardinality integers after `min`/`max`/`exactly`, and — after a restriction keyword — the classes actually observed as fillers of that property.

## Architecture

Three cooperating layers, one shared implementation behind two HTTP endpoints:

1. **Cursor-aware partial parser** (`mos_parser.partial_parse`) — classifies what the cursor position expects.
2. **Suggestion engine** (`modules/search/autocomplete.mos_autocomplete`) — turns the parse context into ranked completion dicts, pulling entities from Postgres and fillers from oxigraph.
3. **Frontend dropdown** (`frontend/src/components/SearchBar.tsx`) — renders suggestions, handles keyboard navigation, and splices the accepted completion back into the query at the parser-provided offsets.

### Parser context model

`partial_parse(q, cursor)` returns a `PartialParseResult`:

- `token_type`: `OPEN_QUOTE` | `EXPECT_ENTITY` | `EXPECT_KEYWORD` | `EXPECT_INT`
- `partial`: the text of the token being typed at the cursor
- `token_start`: index where the current token starts (the splice point for replacement)
- `prev_entity`: on `EXPECT_KEYWORD`, the identifier (label/CURIE/IRI) of the entity immediately before the cursor. Lets the engine offer *restriction* keywords after a property vs *boolean* keywords after a class. `None` after a closing paren (a group is always a class expression).
- `restriction_property`: on `EXPECT_ENTITY` in a *filler* position (right after `some`/`only`/`value` or `min N`/`max N`/`exactly N`), the property the restriction is on. Enables observed-filler suggestions.

### Suggestion engine — `mos_autocomplete`

Single async function behind every MOS autocomplete endpoint (unified in #22). Signature:

```python
async def mos_autocomplete(
    db, q, cursor, limit, *,
    version_id: str | None = None,
    ontology_ids: list[str] | None = None,
    filler_scope: list[tuple[str, str]] | None = None,   # (version_id, graph_iri) pairs
    excluded_types: frozenset[str] = frozenset({"annotation_property"}),
) -> tuple[list[dict], PartialParseResult]
```

Branches, in order:

1. **Entity context** (`OPEN_QUOTE`, or `EXPECT_ENTITY` with a non-empty partial): call `pg_autocomplete_entities` and wrap rows via `_entity_dicts` (close-quote insert when inside an open quote).
2. **Filler position** (`EXPECT_ENTITY`, empty partial, `restriction_property` set, `filler_scope` provided): resolve the property IRI (`pg_property_iri`), find IRIs observed as fillers of it across the scoped graphs (`_observed_filler_iris`), hydrate to entity rows (`pg_entities_by_iri`), and append `not` / `'`. Falls back to keywords if nothing resolves.
3. **Keyword context** (everything else): `keyword_set_for(token_type, prev_is_property)` where `prev_is_property` is computed via `pg_is_property(prev_entity)`.

`keyword_set_for` is pure:
- `EXPECT_KEYWORD` + property → `some, only, value, min, max, exactly, Self`
- `EXPECT_KEYWORD` + class → `and, or, not, (, )`
- `EXPECT_INT` → `1, 2, 3`
- `EXPECT_ENTITY` (empty) → `not, '`

### Postgres entity ranking — `pg_autocomplete_entities`

Three tiers over the `entity_index` table (each runs only if the previous didn't fill the limit):

1. **Prefix** — btree `text_pattern_ops` prefix scan on `primary_label_norm`. Exact head-of-label matches, cheapest and highest-precedence.
2. **tsvector** — GIN full-text fallback for word-suffix / multi-token matches in label or synonyms.
3. **Trigram fuzzy** (#26) — typo tolerance via `pg_trgm`. `SET LOCAL pg_trgm.word_similarity_threshold = 0.4`; `:norm <% ei.primary_label_norm`, index-accelerated by a GIN `gin_trgm_ops` index (`entity_index_norm_trgm`), ordered by `word_similarity(...) DESC`. Runs only when the exact tiers leave room, so clean prefixes never see fuzzy noise.

Scoping: `version_id` (single) for the per-ontology path, `ontology_ids` (list) for the front-page path. `annotation_property` is excluded by default.

### Observed-filler suggestions

`_observed_filler_iris(prop_iri, graph_iris, limit)` runs one SPARQL query over oxigraph across all scoped graphs:

```sparql
SELECT ?f (COUNT(DISTINCT ?r) AS ?n) WHERE {
  VALUES ?g { <g1> <g2> ... }
  GRAPH ?g {
    ?r owl:onProperty ?p .
    ?p rdfs:subPropertyOf* <prop_iri> .
    { ?r owl:someValuesFrom ?f } UNION
    { ?r owl:allValuesFrom ?f } UNION
    { ?r owl:onClass ?f }
    FILTER(isIRI(?f))
  }
} GROUP BY ?f ORDER BY DESC(?n) ?f LIMIT n
```

Fillers are ranked by **frequency of use** — the number of distinct restrictions
that use each class as a filler of the property (across the scoped graphs), most-used
first, with the IRI as a deterministic tiebreaker (#30). The engine over-fetches
(`limit * 4` IRIs) and `pg_entities_by_iri` **preserves that rank** when hydrating
display rows, so the likeliest completions stay at the top of the dropdown.

For a `value` restriction the fillers are **individuals** drawn from `owl:hasValue`
rather than classes; the parser reports the triggering keyword (`restriction_keyword`)
so `_observed_filler_iris` swaps the class-restriction clause for `owl:hasValue`, and
the completer offers only an opening quote after the individuals (`not` is a class-
expression operator, invalid before a `value` individual) (#33).

`pg_property_iri` and `pg_entities_by_iri` take a `version_ids` list (`= ANY(:vids)`,
`DISTINCT ON (iri)`) so both paths share one code path (generalized in #29).

## Cardinality semantics (evaluator, kept consistent with the suggestions)

The autocomplete offers `min`/`max`/`exactly`, so the evaluator must answer them — and match filler-aware expectations (#23, #24):

- `min N R C` → qualified min on `owl:onClass`; for `N <= 1` also matches `owl:someValuesFrom` (i.e. `min 1 R C ≡ some R C`), on both `subClassOf` and `equivalentClass`-intersection forms. Unqualified min only for `owl:Thing`.
- `max N R C` / `exactly N R C` → one branch, qualified predicate with comparator `<=` / `=`, filler-aware, no `some`-fallback.

## Frontend interaction (`SearchBar.tsx`)

- Arrow-key navigation with an active-highlight index; `scrollIntoView?.()` (guarded — jsdom lacks it).
- `Tab` / `Enter` accept the highlighted suggestion; `Enter` submits the query only when nothing is highlighted.
- Accepted completion is spliced using the parser's `token_start` → `cursor` range, and the completion dict's `insert` (trailing space for keywords, bare `(`/`'` for openers, close-quote-aware for entities).

## Endpoints & caching

- **Per-ontology:** `GET /api/v1/ontologies/{oid}/{vid}/autocomplete` → `mos_autocomplete(version_id=vid, filler_scope=[(vid, graph_iri(oid, vid))])`.
- **Front-page (global):** `GET /api/v1/autocomplete` → `mos_autocomplete(ontology_ids=..., filler_scope=...)`. When specific ontologies are selected, their latest-version graphs are resolved into `filler_scope` (capped at 25); "all" scope skips fillers (querying every graph is too broad) and keeps `not`/`'`. Response cached in Redis under `search:autocomplete:v4:{hash}`; the version prefix is bumped whenever suggestion content changes.

Both endpoints return `{completions, context, replace_from, replace_to}`.

## Out of scope / future

- Cross-ontology fillers when scope is "all" (deliberately skipped for cost).
- Property-chain / inverse-property completion.
- Datatype-restriction (`xsd:int[>= 5]`) autocomplete.

## Delivery history

| PR | Change |
|----|--------|
| #18 | Postgres-backed entity autocomplete (prefix + tsvector, ranking, multi-token) |
| #19 | Keyboard navigation for the dropdown |
| #20 | Restriction keywords after a property (per-ontology) |
| #21 | Restriction keywords in the front-page (global) path |
| #22 | Unify the MOS autocomplete implementations into one |
| #23 | `min` cardinality respects filler; `min 1 ≡ some` |
| #24 | `max`/`exactly` cardinality respect the filler |
| #26 | Trigram fuzzy (typo-tolerant) tier |
| #28 | Observed-filler suggestions after a restriction keyword (per-ontology) |
| #29 | Observed-filler suggestions on the front-page (multi-ontology) path |
| #30 | Rank fillers by frequency of use (most-used first) |
| #33 | `value`-restriction fillers suggest individuals (owl:hasValue) |
