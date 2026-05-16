# OntoExplorer — Feature Ideas

## Search & Discovery
- **Full-text semantic search** — vector/embedding search across term definitions, not just labels (currently Elasticsearch BM25)
- **Cross-ontology term lookup** — find all classes matching an IRI or label across all loaded ontologies
- **SPARQL endpoint** — expose Oxigraph directly with a UI query editor

## Browsing & Visualization
- **Class hierarchy graph view** — force-directed or tree graph alongside the current list
- **Dependency graph** — which ontologies import which others
- **Term cross-references** — "this class is used/referenced by N other ontologies"

## Ontology-Specific ML
- **OWL2Vec*** — graph walk + OWL axiom embeddings per ontology; suited for ontology completion, class similarity, subsumption prediction, and ontology alignment/matching (not search — natural language queries can't be embedded into per-ontology walk spaces)

## Quality & Interoperability
- **SHACL validation reports** — per-ontology constraint validation
- **OWL profile detection** — OWL 2 DL / EL / RL / QL classification
- **Ontology alignment / mapping** — suggest equivalent classes across ontologies

## Collaboration & Curation
- **Comments / issue tracking** on terms or ontologies
- **Suggested edits / community annotations**
- **Subscribe to ontology update notifications**

## Export & API
- **Multi-format term export** — JSON-LD, Turtle snippet, OWL/XML
- **OLS-compatible API layer** — so tools already speaking OLS can point here
- **Citation / DOI integration** — link to published papers about an ontology

## Analytics
- **Search analytics** — most-queried terms, trending ontologies
- **Coverage metrics** — how well-populated are labels, definitions, synonyms across the loaded set

---

## Priority Notes
High-ROI given FAIR focus:
1. SPARQL endpoint — researchers expect it
2. Cross-ontology term search
3. OLS-compatible API — drop-in for existing tooling
4. Annotation quality / coverage metrics — natural extension of annotation profile work
