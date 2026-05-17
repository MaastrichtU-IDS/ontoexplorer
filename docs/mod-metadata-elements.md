# MOD Metadata Elements Reference

All fields from `modSemanticArtefact` (MOD-API OpenAPI spec). Used as a shopping list
for the OntoExplorer ontology metadata editor.

## Tiers

- **Captured** — already stored and exposed by OntoExplorer
- **Derivable** — computable from existing data, not yet exposed
- **Missing** — needs new UI in the Profile/metadata editor

---

## Core Identity

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `@id` | (ontology IRI) | Captured | `ontology.iri` |
| `mod:acronym` | `https://w3id.org/mod#acronym` | Captured | `ontology.shortname` |
| `dcterms:title` | `http://purl.org/dc/terms/title` | Captured | `meta_profile.resolved["title"]` |
| `dcterms:description` | `http://purl.org/dc/terms/description` | Captured | `meta_profile.resolved["description"]` |

## Provenance & Attribution

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `dcterms:creator` | `http://purl.org/dc/terms/creator` | Captured | `meta_profile.resolved["creator"]` |
| `dcterms:contributor` | `http://purl.org/dc/terms/contributor` | Captured | `meta_profile.resolved["contributor"]` |
| `dcterms:publisher` | `http://purl.org/dc/terms/publisher` | Captured | `meta_profile.resolved["publisher"]` |
| `schema:funding` | `https://schema.org/funding` | Captured | `meta_profile.resolved["funding"]` |
| `prov:wasGeneratedBy` | `http://www.w3.org/ns/prov#wasGeneratedBy` | Missing | — |

## Rights & Access

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `dcterms:license` | `http://purl.org/dc/terms/license` | Captured | `meta_profile.resolved["license"]` |
| `dcterms:rights` | `http://purl.org/dc/terms/rights` | Missing | — |
| `dcterms:accessRights` | `http://purl.org/dc/terms/accessRights` | Missing | — |

## Discovery & Navigation

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `foaf:homepage` | `http://xmlns.com/foaf/0.1/homepage` | Captured | `meta_profile.resolved["homepage"]` |
| `dcterms:language` | `http://purl.org/dc/terms/language` | Captured | `meta_profile.resolved["language"]` |
| `dcat:keyword` | `http://www.w3.org/ns/dcat#keyword` | Missing | — |
| `dcat:theme` | `http://www.w3.org/ns/dcat#theme` | Missing | — |
| `dcat:landingPage` | `http://www.w3.org/ns/dcat#landingPage` | Missing | — |

## Versioning

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `owl:versionInfo` | `http://www.w3.org/2002/07/owl#versionInfo` | Captured | `meta_profile.resolved["version_info"]` |
| `owl:versionIRI` | `http://www.w3.org/2002/07/owl#versionIRI` | Captured | `version.version_iri` |
| `dcterms:created` | `http://purl.org/dc/terms/created` | Captured | `ontology.created_at` |
| `dcterms:modified` | `http://purl.org/dc/terms/modified` | Captured | `version.created_at` |
| `owl:priorVersion` | `http://www.w3.org/2002/07/owl#priorVersion` | Derivable | previous `version.version_iri` |
| `owl:backwardCompatibleWith` | `http://www.w3.org/2002/07/owl#backwardCompatibleWith` | Missing | — |
| `owl:incompatibleWith` | `http://www.w3.org/2002/07/owl#incompatibleWith` | Missing | — |

## Technical Metadata

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `vann:preferredNamespacePrefix` | `http://purl.org/vocab/vann/preferredNamespacePrefix` | Captured | `meta_profile.resolved["prefix"]` |
| `vann:preferredNamespaceUri` | `http://purl.org/vocab/vann/preferredNamespaceUri` | Captured | `meta_profile.resolved["namespace_uri"]` |
| `mod:numberOfClasses` | `https://w3id.org/mod#numberOfClasses` | Derivable | Redis stats `class_count` |
| `mod:numberOfProperties` | `https://w3id.org/mod#numberOfProperties` | Derivable | Redis stats `property_count` |
| `mod:numberOfIndividuals` | `https://w3id.org/mod#numberOfIndividuals` | Derivable | Redis stats `individual_count` |
| `void:triples` | `http://rdfs.org/ns/void#triples` | Derivable | Redis stats `triple_count` |
| `mod:status` | `https://w3id.org/mod#status` | Derivable | `version.status` → MOD URI |

## Citation & Scholarly Use

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `schema:citation` | `https://schema.org/citation` | Captured | `meta_profile.resolved["citation"]` |
| `dcterms:bibliographicCitation` | `http://purl.org/dc/terms/bibliographicCitation` | Missing | — |
| `mod:knownUsage` | `https://w3id.org/mod#knownUsage` | Missing | — |
| `mod:usedInProject` | `https://w3id.org/mod#usedInProject` | Missing | — |

## Semantic Relations (Missing — needs metadata editor)

| MOD Property | URI | Tier | Notes |
|---|---|---|---|
| `mod:competencyQuestion` | `https://w3id.org/mod#competencyQuestion` | Missing | Scope/purpose statement |
| `mod:endorsedBy` | `https://w3id.org/mod#endorsedBy` | Missing | Endorsing organization |
| `mod:reliesOn` | `https://w3id.org/mod#reliesOn` | Missing | External ontologies used |
| `mod:similar` | `https://w3id.org/mod#similar` | Missing | Related ontologies |
| `mod:generalizes` | `https://w3id.org/mod#generalizes` | Missing | More general ontology |
| `mod:specializes` | `https://w3id.org/mod#specializes` | Missing | More specific ontology |
| `mod:hasDisjunctionsWith` | `https://w3id.org/mod#hasDisjunctionsWith` | Missing | Disjoint ontology |
| `mod:hasEquivalences` | `https://w3id.org/mod#hasEquivalences` | Missing | Equivalent ontology |
