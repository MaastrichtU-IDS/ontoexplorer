# OntoExplorer — Feature Ideas

## Search & Discovery
- ~~**Full-text semantic search** — vector/embedding search across term definitions, not just labels~~ (shipped: `semantic_search()` + `term_embeddings` pgvector store + `/api/v1/search?semantic=true` + `/ols/api/v2/classes/llm_search` & `llm_similar`)
- ~~**Cross-ontology term lookup** — find all classes matching an IRI or label across all loaded ontologies~~ (shipped: global `/api/v1/search`, `/ols/api/terms?iri=` + `/ols/api/terms/findByIdAndIsDefiningOntology`)
- ~~**SPARQL endpoint** — expose Oxigraph directly with a UI query editor~~ (shipped: `/api/v1/sparql` (QLever metadata) + `/api/v1/sparql/content` (in-process Oxigraph) + frontend [Sparql page](frontend/src/pages/Sparql.tsx) + SparqlGallery)

## Browsing & Visualization
- **Class hierarchy graph view** — force-directed or tree graph alongside the current list
- **Dependency graph** — which ontologies import which others
- **Term cross-references** — "this class is used/referenced by N other ontologies"

## Ontology-Specific ML
- **OWL2Vec*** — graph walk + OWL axiom embeddings per ontology; suited for ontology completion, class similarity, subsumption prediction, and ontology alignment/matching (not search — natural language queries can't be embedded into per-ontology walk spaces)

## Quality & Interoperability
- **SHACL validation reports** — per-ontology constraint validation
- ~~**OWL profile detection** — OWL 2 DL / EL / RL / QL classification~~ (shipped 2026-05-19: SPARQL ASK detection in-process at indexing time, cached in Redis; `/api/v1/owl-profile/*` API; per-onto tab + fleet page + `?profile=el|rl|ql|dl` search filter)
- **Ontology alignment / mapping** — suggest equivalent classes across ontologies

## Collaboration & Curation
- **Comments / issue tracking** on terms or ontologies
- **Suggested edits / community annotations**
- **Subscribe to ontology update notifications**

## Export & API
- **Multi-format term export** — JSON-LD, Turtle snippet, OWL/XML
- ~~**OLS-compatible API layer** — so tools already speaking OLS can point here~~ (shipped 2026-05-18: /ols/api/* — OLS4 v1 HAL + v2 flat + LLM endpoints via existing semantic_search + term_embeddings; jstree/graph widgets; 9 endpoints stubbed as 501 for features without backing data)
- **Citation / DOI integration** — link to published papers about an ontology

## Analytics
- **Search analytics** — most-queried terms, trending ontologies
- ~~**Coverage metrics** — how well-populated are labels, definitions, synonyms across the loaded set~~ (shipped 2026-05-18: `/coverage` fleet page + per-version tab on OntologyPage)

---

## Priority Notes
Top 4 high-ROI items shipped (SPARQL, cross-ontology search, OLS-compat, coverage). Next candidates worth considering:
1. **Dependency graph** — which ontologies import which (data already indexed via owl:imports)
2. **Multi-format term export** — JSON-LD / Turtle / OWL-XML snippets
3. **SHACL validation reports** — well-scoped FAIR checkbox
4. **OWL2Vec*** — per-ontology embeddings for alignment + completion (multi-week)
