# Subsystem 3: Manchester OWL Syntax Search Engine — Design Spec

## Goal

Add a Manchester OWL Syntax (MOS) search engine to OntoExplorer with context-sensitive autocomplete. Users can look up ontology entities by label/IRI or query the ontology using MOS class expressions. A natural-language interface will be layered on top in a later iteration.

---

## Scope

**In scope:**
- Entity lookup: prefix/fuzzy search for classes, properties, individuals by label, synonym, or CURIE/IRI
- Expression query: evaluate MOS class expressions against the ontology, returning matching classes
- Context-sensitive MOS autocomplete: entity completions + keyword completions based on parser state
- Label disambiguation: explicit `label (CURIE)` syntax; 422 response with candidates when bare label is ambiguous
- Redis entity index built by the existing `index_ontology` Celery stub (wired up by this subsystem)

**Out of scope:**
- Cross-version or cross-ontology search (single version only)
- Natural-language query translation (Subsystem 3b, later)
- Ranking/scoring beyond exact/prefix match
- Individual (ABox) instance retrieval

---

## Architecture

Five new modules, no new Docker services. Redis and Oxigraph are already running.

```
ontoexplorer/
├── modules/search/
│   ├── indexer.py       # builds Redis entity index from Oxigraph (wires up index_ontology stub)
│   ├── mos_parser.py    # lark grammar → typed AST + partial_parse for autocomplete
│   ├── autocomplete.py  # cursor-aware completion engine
│   └── evaluator.py     # AST → results (hybrid ELK cache / Oxigraph SPARQL)
└── api/search.py        # FastAPI router: GET /search, GET /autocomplete
```

---

## Redis Entity Index

All keys are namespaced per version and expire after 30 days (same TTL as ELK classification cache). Keys are invalidated when a version is deprecated.

### `search:entities:{version_id}:prefix` — Sorted Set

Score=0 for all members. ZRANGEBYLEX gives O(log N) prefix scan.

Members are `"{normalised_label}|{type}|{iri}"` where:
- `normalised_label` = lowercase, punctuation stripped, whitespace collapsed, leading articles removed
- `type` = `class` | `property` | `individual`
- `iri` = full IRI

One entry per (label, entity) pair. Synonyms create additional entries pointing to the same IRI.

### `search:entities:{version_id}:iri:{url_encoded_iri}` — Hash

Fields: `label`, `type`, `iri`, `short` (CURIE if known, else local name), `synonyms` (pipe-separated).

### `search:entities:{version_id}:type:class` / `:type:property` — Sets

IRI members by entity type. Used by autocomplete to filter completions by expected token type (e.g., only properties after a class name, only classes after `some`).

### `search:meta:{version_id}` — String (JSON)

`{"indexed_at": "…", "class_count": N, "property_count": N, "individual_count": N}`

### Label normalisation

Applied identically at index time and query time:
1. Lowercase
2. Strip punctuation except `:` (for CURIEs) and `<>` (for full IRIs)
3. Collapse whitespace
4. Strip leading `the`/`a`/`an`

### Indexing sources (SPARQL over Oxigraph)

Extracted per version from the asserted named graph `urn:ontology:{oid}:{vid}`:
- `rdfs:label`
- `oboInOwl:hasExactSynonym`, `oboInOwl:hasRelatedSynonym`
- `skos:prefLabel`, `skos:altLabel`
- `schema:name`
- Short IRI (CURIE or local name) as an additional entry

---

## MOS Grammar (lark)

Covers the OWL-EL-useful fragment. All entity references (classes, properties, individuals) are written as single-quoted labels. The `'` character triggers autocomplete in the UI. Because labels are always quoted, keywords (`some`, `only`, `and`, `or`, `not`, `min`, `max`, `exactly`, `value`, `Self`) can never collide with label text — no escaping needed.

```lark
expression   : or_expr
or_expr      : and_expr ("or" and_expr)*
and_expr     : not_expr ("and" not_expr)*
not_expr     : "not" primary | primary
primary      : "(" expression ")"
             | restriction
             | named_class
restriction  : property_ref "some"     expression
             | property_ref "only"     expression
             | property_ref "value"    individual_ref
             | property_ref "Self"
             | property_ref "min"      INT expression
             | property_ref "max"      INT expression
             | property_ref "exactly"  INT expression

named_class   : QUOTED_LABEL   // 'cell death' or 'cell death (GO:0008219)'
              | CURIE           // GO:0008219
              | FULL_IRI        // <http://…/GO_0008219>

property_ref  : QUOTED_LABEL
              | CURIE
              | FULL_IRI

individual_ref: QUOTED_LABEL | CURIE | FULL_IRI

QUOTED_LABEL : "'" /[^']+/ "'"
CURIE        : /[A-Za-z_][A-Za-z0-9_\-]*:[A-Za-z0-9_\-\.]+/
FULL_IRI     : "<" /[^>]+/ ">"
INT          : /[0-9]+/

%ignore /\s+/
```

**Disambiguated label form inside quotes:** when a label is ambiguous, the autocomplete inserts the full form `'cell death (GO:0008219)'` — the CURIE is embedded inside the quotes. The evaluator strips the outer quotes and checks for the `{label} ({CURIE})` pattern to resolve the IRI directly.

**Example expressions:**
```
'Cell' and 'hasPart' some 'Nucleus'
'cell death (GO:0008219)' and not 'apoptosis (GO:0006915)'
'Disease' and 'causedBy' some 'Bacterium' and not 'CancerDisease'
'DevelopmentalProcess' and ('occursIn' some 'Brain' or 'occursIn' some 'SpinalCord')
'hasPart' min 2 'Protein'
```

`partial_parse(text, cursor)` runs the grammar in lark's error-recovery mode on the prefix `text[:cursor]` and returns the expected token type at the cursor: one of `CLASS`, `PROPERTY`, `KEYWORD_RESTRICTION`, `KEYWORD_BOOLEAN`, `INT`, `CLOSE_PAREN`, `OPEN_QUOTE`.

The `OPEN_QUOTE` context fires as soon as the user types `'` — the autocomplete engine begins prefix-scanning Redis immediately with whatever follows.

---

## Autocomplete Engine

`get_completions(q: str, cursor: int, version_id: str, limit: int) -> list[Completion]`

Steps:
1. Call `partial_parse(q, cursor)` → expected token type + partial token being typed
2. If expected type is `OPEN_QUOTE` or cursor is inside an open `'…`: extract the partial label text after the `'`, prefix-scan Redis, filter by expected entity type (CLASS or PROPERTY based on position)
3. If multiple Redis hits share the same normalised label (different IRIs): return the disambiguated `label (CURIE)` form for each; if only one hit, return plain `label`
4. `insert` field always includes the closing `'`: e.g. `'cell death (GO:0008219)'` or `'cell death'`
5. If expected type is `KEYWORD_RESTRICTION`: inject `some`, `only`, `value`, `Self`, `min`, `max`, `exactly`
6. If expected type is `KEYWORD_BOOLEAN`: inject `and`, `or`, `)`, plus `'` to start a new entity reference
7. Rank: exact prefix matches first, then fuzzy (edit distance ≤ 2), then keyword suggestions
8. Return `[{text, type, iri, short, insert}]` where `insert` is the string to splice at cursor

---

## Expression Evaluator

`evaluate(ast_node, version_id: str) -> set[str]`  (returns set of matching class IRIs)

| AST node | Backend | Strategy |
|---|---|---|
| `NamedClass` | Redis + ELK | Resolve label→IRI via Redis; look up `subclasses[iri]` from ELK cached classification |
| `And(A, B)` | ELK | `evaluate(A) ∩ evaluate(B)` |
| `Or(A, B)` | ELK | `evaluate(A) ∪ evaluate(B)` |
| `Not(A)` | ELK | `all_classes(version_id) − evaluate(A)` |
| `SomeValuesFrom(p, C)` | Oxigraph SPARQL | Find X with `rdfs:subClassOf [owl:onProperty p; owl:someValuesFrom C]` |
| `AllValuesFrom(p, C)` | Oxigraph SPARQL | Find X with `rdfs:subClassOf [owl:onProperty p; owl:allValuesFrom C]` |
| `MinCardinality(n, p, C)` | Oxigraph SPARQL | `owl:minCardinality n` filter |
| `MaxCardinality(n, p, C)` | Oxigraph SPARQL | `owl:maxCardinality n` filter |
| `ExactCardinality(n, p, C)` | Oxigraph SPARQL | `owl:cardinality n` filter |

Mixed expressions (e.g. `NamedClass and SomeValuesFrom`): each subtree evaluated independently, results intersected.

**Label resolution in evaluator:**
- `QUOTED_LABEL` node: strip outer `'` characters, check for embedded `{label} ({CURIE})` pattern
  - If CURIE present → resolve CURIE directly via Redis hash lookup (unambiguous)
  - If no CURIE → normalise label, prefix-scan Redis for exact match
    - One match → proceed
    - Multiple matches → raise `AmbiguousLabelError(label, candidates)` → API returns `422` with `{"error": "ambiguous_label", "label": "…", "candidates": [{label, curie, iri}]}`
- CURIE and FULL_IRI nodes → direct Redis hash lookup, no ambiguity possible

**ELK cache loading:** evaluator loads the full `ClassificationResult` from Redis (Subsystem 2 cache) once per request and holds it in memory for the request lifetime. If the cache is cold (version not yet classified), returns `503` with `{"error": "not_classified"}`.

---

## API Endpoints

Both endpoints require authentication (Bearer token, same as existing endpoints).

### `GET /api/v1/ontologies/{oid}/{vid}/search`

| Param | Type | Default | Description |
|---|---|---|---|
| `q` | string | required | Query: entity label, CURIE, IRI, or MOS expression |
| `mode` | `auto`\|`entity`\|`expression` | `auto` | `auto` tries expression parse, falls back to entity lookup |
| `limit` | int | 20 | Max results (max 200) |

**`auto` mode logic:** attempt `parse(q)` with lark; if successful and AST contains at least one restriction or boolean operator → expression mode; if AST is a single `NamedClass` or parse fails → entity lookup mode.

**Response 200:**
```json
{
  "mode": "expression",
  "query": "hasPart some Nucleus",
  "results": [
    {"iri": "…", "label": "Cell", "short": "GO:0005623", "match_type": "elk"},
    {"iri": "…", "label": "Nucleated cell", "short": "GO:0099512", "match_type": "sparql"}
  ],
  "count": 2,
  "truncated": false
}
```

`match_type`: `"elk"` (from ELK subclass index) or `"sparql"` (from Oxigraph restriction query) or `"entity"` (label/prefix match).

**Error responses:**
- `422` — ambiguous bare label in expression: `{"error": "ambiguous_label", "label": "…", "candidates": [...]}`
- `503` — ontology not yet classified: `{"error": "not_classified"}`
- `400` — unparseable expression with `mode=expression`: `{"error": "parse_error", "message": "…"}`

### `GET /api/v1/ontologies/{oid}/{vid}/autocomplete`

| Param | Type | Default | Description |
|---|---|---|---|
| `q` | string | required | Partial expression text |
| `cursor` | int | `len(q)` | Byte offset of cursor in `q` |
| `limit` | int | 10 | Max completions (max 50) |

**Response 200:**
```json
{
  "completions": [
    {"text": "cell death (GO:0008219)", "type": "class",   "iri": "…", "short": "GO:0008219", "insert": "cell death (GO:0008219)'"},
    {"text": "cell death (MONDO:0021700)", "type": "class","iri": "…", "short": "MONDO:0021700", "insert": "cell death (MONDO:0021700)'"},
    {"text": "cell division",             "type": "class", "iri": "…", "short": "GO:0051301",   "insert": "cell division'"}
  ],
  "context": "open_quote"
}
```

The `insert` value completes the token from the current cursor position (after the `'`) through the closing `'`. The client splices `insert` at the cursor to produce e.g. `'cell death (GO:0008219)'`.

`context` values: `expecting_class`, `expecting_property`, `expecting_class_or_keyword`, `expecting_restriction_keyword`, `expecting_cardinality`, `expecting_close_paren`.

---

## Module Responsibilities

### `indexer.py`

- `build_index(version_id: str, ontology_id: str) -> IndexStats` — SPARQL over Oxigraph, writes Redis structures, returns counts
- `invalidate_index(version_id: str)` — deletes all `search:*:{version_id}:*` keys
- Called by `index_ontology` Celery task (replacing the stub) and by `deprecate_version` endpoint

### `mos_parser.py`

- `parse(text: str) -> ASTNode` — full parse, raises `ParseError` on failure
- `partial_parse(text: str, cursor: int) -> PartialParseResult` — error-recovery parse, returns `(expected_token_type, partial_token)`
- AST node types: `NamedClass`, `And`, `Or`, `Not`, `SomeValuesFrom`, `AllValuesFrom`, `HasValue`, `HasSelf`, `MinCardinality`, `MaxCardinality`, `ExactCardinality`

### `autocomplete.py`

- `get_completions(q, cursor, version_id, limit) -> list[Completion]`
- `Completion`: `text, type, iri, short, insert`

### `evaluator.py`

- `evaluate(node: ASTNode, version_id: str) -> list[SearchResult]`
- `SearchResult`: `iri, label, short, match_type`
- `AmbiguousLabelError(label, candidates)`

### `api/search.py`

- FastAPI router, prefix `/api/v1/ontologies/{ontology_id}/{version_id}`
- Mounts on existing app in `main.py`
- Uses existing `_get_version_or_404` helper from `api/ontologies.py`

---

## Testing

### Unit tests (`tests/unit/search/`)

- `test_mos_parser.py`: parse valid expressions, parse errors, partial parse returns correct expected token type for each cursor context
- `test_autocomplete.py`: mock Redis, verify correct completions for each context (class expected, property expected, keyword expected, disambiguated label shown)
- `test_evaluator.py`: mock ELK cache + Oxigraph SPARQL, verify set operations (And, Or, Not), verify SPARQL path for restrictions, verify `AmbiguousLabelError` on multi-IRI label

### Integration tests (`tests/integration/test_search.py`)

- Load a small test ontology (Turtle) into Oxigraph + run `build_index` → verify Redis keys populated
- `GET /search?q=cell+death&mode=entity` → verify entity results
- `GET /search?q=Cell+and+hasPart+some+Nucleus` → verify expression results
- Ambiguous label → 422 with candidates
- Not-yet-classified version → 503
- `GET /autocomplete?q=cell+d` → verify completions include disambiguated form

---

## Dependencies

Add to `pyproject.toml`:
- `lark>=1.2` — PEG parser for MOS grammar

No new Docker services. No schema migrations required.
