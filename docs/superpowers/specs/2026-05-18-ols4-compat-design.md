# OLS4-Compatible API Layer — Design

**Status:** Draft for review
**Date:** 2026-05-18
**Author:** Michel Dumontier (with Claude)

## Goal

Expose an OLS4-compatible read-only API at `/ols/api/...` so that any client speaking the EMBL-EBI Ontology Lookup Service v4 protocol (Zooma, `ols-client`, BioPortal mirrors, OxO, OLS web widgets, custom annotation pipelines) can repoint at an OntoExplorer instance without code changes. This is a thin translation layer over services we already have; it does not add new business logic.

## Non-goals

- A new feature surface — every endpoint backs onto existing OntoExplorer functions (term lookup, hierarchy traversal, search, semantic similarity, reasoning).
- Write-side parity. OLS is read-only; so is the shim.
- Bug-for-bug parity with Spring-HATEOAS quirks. We match shapes, not Java-isms.

## Scope

The shim mirrors OLS4's full read surface, organized in three tiers:

### Tier 1 — Backed by existing data (real implementation)

**V1 HAL surface (OLS3-compatible, ~25 endpoints):**

| Resource | Path |
|---|---|
| Ontologies | `GET /api/ontologies`, `/api/ontologies/{onto}` |
| Terms (global) | `GET /api/terms`, `/api/terms/{iri}`, `/api/terms/findByIdAndIsDefiningOntology[/{iri}]` |
| Terms (scoped) | `GET /api/ontologies/{onto}/terms`, `/{iri}`, `/roots` |
| Term hierarchy | `/parents`, `/children`, `/ancestors`, `/descendants`, `/hierarchicalParents`, `/hierarchicalAncestors`, `/hierarchicalDescendants` |
| Properties | Same shape as terms but scoped to `/properties` (global + per-ontology + hierarchy) |
| Individuals | `/individuals` (global + per-ontology + per-term `/types`) |

**Solr-style search (3 endpoints):** `/api/search`, `/api/select`, `/api/suggest`.

**V2 flat surface (~15 endpoints):** the `/api/v2/classes`, `/api/v2/properties`, `/api/v2/individuals`, `/api/v2/entities` family with their hierarchy variants. Same data, flatter envelope.

**V2 LLM endpoints (4 endpoints, backed by `term_embeddings`):**
- `GET /api/v2/classes/llm_search?q=…&model=…` → wraps `semantic_search()`
- `GET /api/v2/ontologies/{onto}/classes/llm_search` → semantic_search scoped to one version
- `GET /api/v2/classes/{class}/llm_similar` → nearest neighbours of a given embedding
- `GET /api/v2/llm_models` → returns one fixed entry (`{"id": "nomic-embed-text", "dimensions": 768}`) reflecting our current embedder

**Misc:** `/api/v2/stats`, `/api/v2/defined-fields`, `/api/ontologies/{onto}/download`, `/api/v2/ontologies` (paged v2 list).

### Tier 2 — UI-bespoke shapes (real implementation, derived from existing data)

- `GET /api/ontologies/{onto}/terms/{iri}/jstree` — recursive tree node array used by the OLS web UI.
- `GET /api/ontologies/{onto}/terms/{iri}/graph` — `{nodes[], edges[]}` for ontology graph widgets.

Both are derived from `list_terms` + hierarchy traversal. Implemented last; rarely used by programmatic clients.

### Tier 3 — Stubbed (no backing data → 501 Not Implemented with explanatory body)

| Endpoint | Reason |
|---|---|
| `POST/GET /api/v2/tag_text` | No NER engine wired up |
| `GET /api/v2/curation_sources` | No SSSOM mapping store |
| `GET /api/v2/ontologies/by-tag` | No ontology tag metadata |
| `GET /api/v2/ontologies/by-domain` | No ontology domain metadata |
| `GET /api/ontologies/{onto}/terms/preferredRoots` | No curation field for preferred roots |
| `POST /api/v2/classes/llm_embedding`, `/api/v2/ontologies/{onto}/classes/llm_embedding` | Public raw-embedding write surface intentionally not exposed |
| `GET /api/v2/classes/{c}/llm_embedding` | Returning 768-d vectors per request is not useful and bloats bandwidth |
| `GET /api/v2/classes/{c1}/llm_similarity/{c2}` | Could implement (dot-product of two stored vectors), but low-value; defer |

Each stub returns `501 Not Implemented` with `{"error": "not_implemented", "message": "…", "ols_path": "<path>"}`. Endpoint shape exists so a client probing the URL doesn't 404 unexpectedly.

### Out of scope (this iteration)

- `/api/mcp` (OLS4's MCP server endpoint — separate protocol)
- `/api/profile` (HAL ALPS endpoint — almost never used)
- per-relation traversal `/api/ontologies/{onto}/terms/{iri}/{relation_iri}` — needs OBO-relation parsing; defer until a real client asks.
- OLS3 surface as a separate prefix. We target OLS4 only. OLS3 clients hitting `/ols3/api/...` 404.

## Architecture

### File layout (new code)

```
ontoexplorer/api/ols/
    __init__.py                # re-exports `router`
    router.py                  # combines all sub-routers, mounted at /ols
    _envelope.py               # HAL+JSON helpers, v2 envelope, page builders
    _iri.py                    # double-URL-decode/encode, IRI validation
    _shapes.py                 # internal entity dict → OLS term/property/individual/ontology shape
    _common.py                 # shared deps: latest-version resolver, page params, lang resolver
    _solr.py                   # Solr-style envelope (numFound, docs, facets, highlighting)
    ontologies.py              # /api/ontologies, /api/v2/ontologies, by-tag/by-domain (stub)
    terms.py                   # /api/terms, /api/ontologies/{o}/terms[/...], /api/v2/classes
    properties.py              # /api/properties, /api/v2/properties + hierarchy
    individuals.py             # /api/individuals, /api/v2/individuals
    search.py                  # /api/search, /api/select, /api/suggest, /api/v2/tag_text (stub)
    llm.py                     # /api/v2/llm_models, /api/v2/classes/llm_search, /llm_similar
    hierarchy_widgets.py       # /jstree, /graph (Tier 2)
    misc.py                    # /api/v2/stats, /api/v2/defined-fields, /api/v2/curation_sources (stub)
```

Mount: `app.include_router(ols_router)` in `main.py`. Router declares `prefix="/ols"` (so its routes already include `/api/...`), `tags=["ols-compat"]`. No auth dependency on any route — OLS is fully public.

### Response envelope shapes

**HAL+JSON (v1):**
```json
{
  "_embedded": { "terms": [ {...}, {...} ] },
  "_links": {
    "first": {"href": "https://host/ols/api/ontologies/go/terms?page=0&size=20"},
    "self":  {"href": "https://host/ols/api/ontologies/go/terms?page=0&size=20"},
    "next":  {"href": "https://host/ols/api/ontologies/go/terms?page=1&size=20"},
    "last":  {"href": "https://host/ols/api/ontologies/go/terms?page=42&size=20"}
  },
  "page": { "size": 20, "totalElements": 853, "totalPages": 43, "number": 0 }
}
```

`_envelope.hal_page(items, request, total, page, size, embedded_key)` builds this. Link URLs use `request.url_for()`-style construction so a reverse proxy's `X-Forwarded-Host` / `X-Forwarded-Proto` flows through.

**V2 flat:**
```json
{
  "elements": [ {...}, {...} ],
  "page": { "size": 20, "totalElements": 853, "totalPages": 43, "number": 0 },
  "facetFieldsToCounts": { "ontologyId": [["go", 853], ["chebi", 0]] }
}
```

**Solr (`/api/search`, `/select`, `/suggest`):**
```json
{
  "responseHeader": {"status": 0, "QTime": 12, "params": {"q": "diabetes", "rows": "10"}},
  "response":       {"numFound": 47, "start": 0, "docs": [...]},
  "facet_counts":   {"facet_fields": {"ontology_name": ["go", 12, "chebi", 5]}},
  "highlighting":   {"<iri>": {"label": ["<em>diabetes</em>"]}}
}
```

`_solr.solr_envelope(docs, total, start, rows, q_params, qtime)`.

### Pagination translation

OLS uses `page` (0-based) + `size`. Internal endpoints use `limit` + `offset`. The shim translates:

```python
internal_offset = page * size
internal_limit = size
# call existing handler
items, total = await list_terms_internal(version_id, offset=internal_offset, limit=internal_limit, ...)
```

`/api/search` etc. use `rows` + `start` (Solr) — pass straight through to internal `offset` / `limit`.

### IRI handling

Per OLS4: IRIs in URL path segments are **double-URL-encoded** (e.g. `http://purl.obolibrary.org/obo/GO_0008150` → `http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FGO_0008150`). FastAPI single-decodes once; we manually `urllib.parse.unquote` again in handlers via a dependency `decoded_iri: str = Depends(double_decoded_iri_path)`.

IRIs in query params (`?iri=`) are single-encoded — handled by FastAPI normally.

### Version selection — "latest ready"

OLS exposes one current version per ontology. Our `/ols/api/...` endpoints resolve the ontology slug to the latest-ready version using the existing `_get_latest_version_or_404(db, ontology_id)` from `global_search.py:43` (or a re-exported equivalent in `_common.py`).

The version string returned in `ontology.config.version` is whatever our `OntologyVersion.version_iri` holds (or the row's `created_at` ISO date if no version IRI). One field, no version-switching API — this is by design; OLS clients don't know about our multi-version model.

### Field-shape mapping (internal → OLS term)

| OLS4 field | Source |
|---|---|
| `iri` | `entity["iri"]` |
| `label` | `entity["primary_label"]` (or lang-resolved from `labels[]` if `lang=` set) |
| `short_form` | `entity["short"]` |
| `obo_id` | derived: if `short` matches `^[A-Z]+_[0-9]+$`, replace `_` with `:`; else `None` |
| `ontology_name` | ontology shortname |
| `ontology_prefix` | ontology shortname (uppercased — OLS convention) |
| `ontology_iri` | `Ontology.iri` |
| `is_defining_ontology` | `entity["source"]` equals the ontology being queried |
| `description[]` | `[d["value"] for d in entity["definitions"]]` filtered by lang if requested |
| `synonyms[]` | `[s["value"] for s in entity["synonyms"]]` filtered by lang if requested |
| `annotation{}` | reserved for future — emit `{}` for now (OntoExplorer's annotations map isn't yet exposed in the indexer record) |
| `is_obsolete` | from `deprecated_iris` set in the version's index |
| `is_root` | true if entity has no asserted parents |
| `has_children` | true if entity has ≥1 asserted child (cheap check via children-count cache, or `len(children) > 0`) |
| `obo_xref[]` / `obo_definition_citation[]` / `obo_synonym[]` / `in_subset[]` | `[]` for now — these need axiom-aware extraction; out of scope for v1 |
| `_links` | computed: self, parents, children, ancestors, descendants, hierarchicalParents, hierarchicalAncestors, hierarchicalDescendants, jstree, graph |

`_shapes.entity_to_v1_term(entity_dict, ontology_row, version_id, request)` and `entity_to_v2_class(...)` produce these.

### Hierarchical vs non-hierarchical

OLS distinguishes `/parents` (may include reasoner shortcuts) vs `/hierarchicalParents` (strict asserted SubClassOf). Mapping:

- `/parents`, `/children`, `/ancestors`, `/descendants` → use **reasoner-inferred** when the version's reasoner status is ready (`get_superclasses`, `get_subclasses`, `inferred_children`, `term_ancestors`); fall back to **asserted** when reasoning isn't ready.
- `/hierarchicalParents`, `/hierarchicalAncestors`, `/hierarchicalDescendants` → always use **asserted** (from the index's parents / a parents-transitive-closure).

This honours the semantic distinction and gives clients the richer reasoner-derived view by default, which is OLS's behaviour for classified ontologies.

### LLM endpoints

`semantic_search()` already returns `[{iri, label, version_id, ontology_id, score, ...}]`. The shim:

- `/api/v2/classes/llm_search?q=…&rows=10` — calls `semantic_search(q, db, all_version_ids, limit=rows)`, returns v2-shaped class entries with a `score` field.
- `/api/v2/ontologies/{onto}/classes/llm_search` — scoped to one version.
- `/api/v2/classes/{class_iri}/llm_similar?rows=10` — looks up the entity's embedding via `term_embeddings`, computes cosine against the same table (`SELECT … ORDER BY embedding <=> $1 LIMIT $2`), returns v2-shaped classes excluding self.
- `/api/v2/llm_models` — returns a single hardcoded entry reflecting the current embedder.

### Auth, rate limits, caching

- **Auth:** none. No `get_current_user` dependency. Matches OLS exactly.
- **Rate limits:** none for this iteration. If abuse becomes an issue, a `slowapi`-based per-IP limit can be added globally to the OLS prefix later.
- **Caching:** rely on the existing Redis-backed indexer cache; no new caches introduced. Hot responses are list_terms and search, both of which hit Redis already.

## Testing strategy

### Unit (per envelope/shape helper)

- `_envelope.hal_page` — correct `_links` calculation for first/middle/last/empty pages, `totalPages = ceil(total/size)`, `number` zero-based, edge case `total=0`.
- `_envelope.v2_page` — same minus `_links`.
- `_iri.double_decode` — handles single-encoded, double-encoded, mixed, with `#` and `/` and query params.
- `_shapes.entity_to_v1_term` — every field mapped correctly; lang filter behaviour; obo_id derivation for `GO_0008150`/`HP_0000001`/non-OBO IRIs.
- `_solr.solr_envelope` — `numFound`/`start`/`docs` populated, `responseHeader.params` reflects input.

### Integration (per resource, hitting real Redis + DB via the test fixtures)

For each resource:
- One happy-path list (paged, with `_embedded` items)
- One detail-by-IRI (double-encoded path)
- One 404 (unknown ontology, unknown IRI)
- One pagination boundary (`page=0&size=10`, then `size=10&page=N`)
- One Tier-3 stub returns 501 with the expected shape

For search:
- `/api/search?q=…` returns Solr shape with `numFound > 0`
- `/api/search?ontology=go,chebi&type=class` filter
- `/api/search?groupField=iri` dedups across ontologies
- `/api/select?q=…` returns prefix matches
- `/api/suggest?q=…` returns suggestions

For LLM:
- `/api/v2/classes/llm_search?q=diabetes` returns v2 envelope with `score` on each
- `/api/v2/classes/{iri}/llm_similar` excludes the input itself, returns N neighbours

Aim for ~50 backend tests across all resources. No frontend tests — this is API-only.

## Documentation

- `README.md`: add a `### OLS4-compatible API (/ols/api)` subsection under "API Reference" with: (a) the parity claim, (b) the base URL pattern, (c) the four classes of differences clients should be aware of (versioning model, double-encoded IRIs in path, Tier-3 stubs, no auth), (d) a worked example of swapping `ols.ebi.ac.uk/api` for `<your-host>/ols/api`.
- `docs/ideas.md`: strike through "OLS-compatible API layer" with the ship date.

## Risks & open questions

1. **Spec drift.** OLS4 evolves. The shim is a snapshot of OLS4 as of 2026-05-18; field additions on their side won't auto-propagate. Acceptable — we'll track via downstream client breakage reports.

2. **HATEOAS `_links` URL construction under reverse proxies.** Need to honour `X-Forwarded-Proto` / `X-Forwarded-Host` so HAL links work behind a load balancer. Standard FastAPI `request.url_for()` does this if `ProxyHeadersMiddleware` is configured; if not currently configured, add it as part of this work.

3. **`is_defining_ontology` semantics.** OLS uses the term "defining ontology" loosely — usually it means "the ontology whose IRI prefix matches the term's IRI prefix". Our `entity["source"]` field carries the source of an imported term. Map as defined in the field table; clients that rely on this for downstream logic should be tested against real OLS responses.

4. **OBO ID derivation.** Only mechanical for terms with `^[A-Z]+_[0-9]+$` shorts. Non-OBO terms (e.g. SKOS, schema.org) get `obo_id: null`. Real OLS does the same — but if a downstream client crashes on null, we may need to omit the field entirely.

5. **jstree and graph shapes are non-trivial.** Tier 2 last. If usage analytics show no traffic, we may downgrade them to Tier 3 stubs.

## Phased rollout

The plan will execute in this order — each phase is independently shippable:

1. **Foundation:** package skeleton, envelope helpers, IRI decoder, shape mappers, version resolver (no routes yet).
2. **Ontologies + Terms v1 HAL:** the bedrock — list/detail/hierarchy. Covers ~60% of real-world traffic.
3. **Properties + Individuals v1 HAL:** same shape, scoped to other entity types.
4. **Search (Solr-style):** `/api/search`, `/api/select`, `/api/suggest`.
5. **V2 flat surface:** mirror of phases 2–3 with the v2 envelope.
6. **LLM endpoints:** wrap `semantic_search` and `term_embeddings`.
7. **Tier 2 (jstree + graph) and Tier 3 stubs.**
8. **Docs + ideas.md strike-through.**

After phase 4 the shim is already a viable drop-in for the majority of OLS clients.
