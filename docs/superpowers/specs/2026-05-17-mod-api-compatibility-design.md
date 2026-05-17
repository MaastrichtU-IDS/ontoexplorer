# MOD-API Compatibility Implementation Design

## Goal

Expose OntoExplorer as a MOD-API-compliant semantic artefact catalogue at `/mod/`, enabling discovery and harvesting by EOSC catalogue systems and other MOD-compatible clients.

## Architecture

**New files:**

| File | Responsibility |
|---|---|
| `ontoexplorer/api/mod.py` | FastAPI router — all `/mod/*` handlers; each returns an `rdflib.Graph` wrapped in `RDFResponse` |
| `ontoexplorer/modules/mod/builder.py` | Pure functions that take DB rows and return `rdflib.Graph` objects, one per endpoint group |
| `ontoexplorer/modules/mod/response.py` | `RDFResponse(rdflib.Graph)` — content-negotiates and serializes to JSON-LD / Turtle / RDF-XML / HTML |
| `ontoexplorer/modules/mod/ratelimit.py` | FastAPI dependency — Redis counter per IP (anonymous) or API key (authenticated) |
| `ontoexplorer/modules/mod/context.py` | MOD JSON-LD `@context` document mapping all prefixes to canonical URIs |
| `docs/mod-metadata-elements.md` | Reference list of all MOD metadata fields with OntoExplorer source and editor status |

**No new DB tables.** Reads from: `ontologies`, `versions`, `ontology_meta_profiles`, VoID stats (Redis).

**Visibility rule:** All MOD endpoints expose only ontologies that have at least one version with `status=ready`. Ontologies with no ready version (all versions are `pending`, `reasoning`, `deprecated`, or `failed`) are invisible to the MOD API and return `404` on direct lookup.

**Data flow:**
```
request → router handler → DB query → builder.py → rdflib.Graph → RDFResponse → serialized response
```

The router is registered in `main.py` at prefix `/mod` (not `/api/v1/mod`), keeping it visually distinct from the internal REST API.

---

## Endpoints

All 30 endpoints are read-only (GET only). `{artefactID}` accepts either a URL-encoded ontology IRI or a shortname.

### Catalogue
| Method | Path | Description |
|---|---|---|
| GET | `/mod/` | Catalogue metadata (`modSemanticArtefactCatalog`): name, description, total count, SPARQL endpoint URI, publisher |

### Records
| Method | Path | Description |
|---|---|---|
| GET | `/mod/records` | Paginated list of `dcat:CatalogRecord` (one per ontology) |
| GET | `/mod/records/{artefactID}` | Single record by IRI or shortname |

### Artefacts
| Method | Path | Description |
|---|---|---|
| GET | `/mod/artefacts` | Paginated list of `modSemanticArtefact` with core metadata; supports `?q=` filter |
| GET | `/mod/artefacts/{artefactID}` | Full single artefact |
| GET | `/mod/artefacts/{artefactID}/record` | Catalogue record for this artefact |
| GET | `/mod/artefacts/{artefactID}/distributions` | All version distributions |
| GET | `/mod/artefacts/{artefactID}/distributions/{distributionID}` | Single distribution by version ID |
| GET | `/mod/artefacts/{artefactID}/distributions/latest` | Latest ready version distribution |

### Resources
| Method | Path | Description |
|---|---|---|
| GET | `/mod/artefacts/{artefactID}/resources` | Summary resource counts by type |
| GET | `/mod/artefacts/{artefactID}/resources/classes` | Paginated `owl:Class` nodes |
| GET | `/mod/artefacts/{artefactID}/resources/properties` | Paginated `rdf:Property` nodes |
| GET | `/mod/artefacts/{artefactID}/resources/individuals` | Paginated `owl:NamedIndividual` nodes |
| GET | `/mod/artefacts/{artefactID}/resources/concepts` | Paginated `skos:Concept` nodes |
| GET | `/mod/artefacts/{artefactID}/resources/schemes` | Paginated `skos:ConceptScheme` nodes |
| GET | `/mod/artefacts/{artefactID}/resources/collections` | Paginated `skos:Collection` nodes |
| GET | `/mod/artefacts/{artefactID}/resources/labels` | All `rdfs:label` values (multi-language) |

### Search
| Method | Path | Description |
|---|---|---|
| GET | `/mod/search?q=` | Metadata + content search |
| GET | `/mod/search/content?q=` | Term-level search only |
| GET | `/mod/search/metadata?q=` | Artefact metadata search only |

---

## Data Mapping

### `modSemanticArtefact` ← OntoExplorer sources

| MOD property | URI | OntoExplorer source |
|---|---|---|
| `@id` | — | `ontology.iri` |
| `mod:acronym` | `https://w3id.org/mod#acronym` | `ontology.shortname` |
| `dcterms:title` | `http://purl.org/dc/terms/title` | `meta_profile.resolved["title"]` |
| `dcterms:description` | `http://purl.org/dc/terms/description` | `meta_profile.resolved["description"]` |
| `dcterms:creator` | `http://purl.org/dc/terms/creator` | `meta_profile.resolved["creator"]` |
| `dcterms:contributor` | `http://purl.org/dc/terms/contributor` | `meta_profile.resolved["contributor"]` |
| `dcterms:publisher` | `http://purl.org/dc/terms/publisher` | `meta_profile.resolved["publisher"]` |
| `dcterms:license` | `http://purl.org/dc/terms/license` | `meta_profile.resolved["license"]` |
| `foaf:homepage` | `http://xmlns.com/foaf/0.1/homepage` | `meta_profile.resolved["homepage"]` |
| `owl:versionInfo` | `http://www.w3.org/2002/07/owl#versionInfo` | `meta_profile.resolved["version_info"]` |
| `owl:versionIRI` | `http://www.w3.org/2002/07/owl#versionIRI` | `version.version_iri` |
| `dcterms:language` | `http://purl.org/dc/terms/language` | `meta_profile.resolved["language"]` |
| `schema:citation` | `https://schema.org/citation` | `meta_profile.resolved["citation"]` |
| `schema:funding` | `https://schema.org/funding` | `meta_profile.resolved["funding"]` |
| `vann:preferredNamespacePrefix` | `http://purl.org/vocab/vann/preferredNamespacePrefix` | `meta_profile.resolved["prefix"]` |
| `vann:preferredNamespaceUri` | `http://purl.org/vocab/vann/preferredNamespaceUri` | `meta_profile.resolved["namespace_uri"]` |
| `dcterms:created` | `http://purl.org/dc/terms/created` | `ontology.created_at` |
| `dcterms:modified` | `http://purl.org/dc/terms/modified` | `version.created_at` (latest) |
| `mod:numberOfClasses` | `https://w3id.org/mod#numberOfClasses` | VoID stats `class_count` |
| `mod:numberOfProperties` | `https://w3id.org/mod#numberOfProperties` | VoID stats `property_count` |
| `mod:numberOfIndividuals` | `https://w3id.org/mod#numberOfIndividuals` | VoID stats `individual_count` |
| `void:triples` | `http://rdfs.org/ns/void#triples` | VoID stats `triple_count` |
| `mod:status` | `https://w3id.org/mod#status` | `version.status` → mapped to MOD status URI |
| `dcat:distribution` | `http://www.w3.org/ns/dcat#distribution` | links to distributions |

**Fields not yet captured** (target for Profile/metadata editor):
`mod:competencyQuestion`, `mod:endorsedBy`, `mod:reliesOn`, `mod:similar`, `mod:generalizes`, `mod:specializes`, `mod:knownUsage`, `mod:usedInProject`

### `modSemanticArtefactDistribution`

| MOD property | Source |
|---|---|
| `@id` | `/mod/artefacts/{id}/distributions/{vid}` |
| `dcat:accessURL` | `/api/v1/ontologies/{id}/{vid}/download` |
| `dcat:downloadURL` | same |
| `dcterms:format` | `version.format` |
| `dcat:mediaType` | mapped: `owl`→`application/owl+xml`, `ttl`→`text/turtle`, `rdf`→`application/rdf+xml`, `nt`→`application/n-triples`, `obo`→`text/obo` |
| `dcterms:created` | `version.created_at` |

### `dcat:CatalogRecord`

| MOD property | Source |
|---|---|
| `@id` | `/mod/records/{shortname_or_id}` |
| `foaf:primaryTopic` | `ontology.iri` |
| `dcterms:created` | `ontology.created_at` |
| `dcterms:modified` | `version.created_at` (latest) |

### `modSemanticArtefactCatalog` (catalogue root)

| MOD property | Source |
|---|---|
| `dcterms:title` | `"OntoExplorer Catalogue"` (config) |
| `dcterms:description` | configurable via `.env` |
| `mod:numberOfArtefacts` | count of ready ontologies |
| `sd:endpoint` | `{BASE_URL}/api/v1/sparql/content` |
| `dcat:dataset` | links to `/mod/artefacts` |

---

## Content Negotiation

`RDFResponse` inspects (in priority order):
1. `?format=` query param: `jsonld`, `ttl`, `rdfxml`, `html`
2. `Accept` header: `application/ld+json`, `text/turtle`, `application/rdf+xml`, `text/html`
3. Default: JSON-LD

| Format | Content-Type | Serialization |
|---|---|---|
| JSON-LD | `application/ld+json` | `rdflib` JSON-LD serializer + `@context` from `context.py` |
| Turtle | `text/turtle` | `rdflib` Turtle serializer |
| RDF/XML | `application/rdf+xml` | `rdflib` XML serializer |
| HTML | `text/html` | Jinja2 template (human-readable table of properties) |

Pagination collections use Hydra: `hydra:Collection`, `hydra:totalItems`, `hydra:itemsPerPage`, `hydra:view` with `hydra:first`/`hydra:next`/`hydra:last` links.

---

## Rate Limiting

Configuration in `.env` (read via `pydantic-settings`):
```
MOD_RATE_LIMIT_ANON=1000      # requests/day per IP (unauthenticated)
MOD_RATE_LIMIT_AUTH=10000     # requests/day per API key (authenticated)
```

Implementation (`modules/mod/ratelimit.py`) — FastAPI dependency injected on all `/mod/*` routes:

| Client | Limit | Redis key |
|---|---|---|
| Unauthenticated | `MOD_RATE_LIMIT_ANON` / day | `ratelimit:mod:ip:{ip}` |
| API key (existing system) | `MOD_RATE_LIMIT_AUTH` / day | `ratelimit:mod:key:{key_id}` |

- Uses Redis `INCR` + `EXPIRE` (TTL = seconds until midnight UTC)
- Missing API key → falls back to IP-based limiting (not a 401)
- Exceeded → `429 Too Many Requests` with `Retry-After` header
- Reuses existing API key lookup from `ontoexplorer/api/api_keys.py`

---

## `{artefactID}` Resolution

All artefact endpoints accept either:
- **Shortname**: `go`, `mondo` — exact match on `ontology.shortname`
- **URL-encoded IRI**: `http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2Fgo.owl` — decoded and matched on `ontology.iri`

Returns `404` if not found or not `status=ready`.

---

## File Map Summary

| File | Action |
|---|---|
| `ontoexplorer/api/mod.py` | Create — 30-endpoint router |
| `ontoexplorer/modules/mod/__init__.py` | Create |
| `ontoexplorer/modules/mod/builder.py` | Create — graph builder functions |
| `ontoexplorer/modules/mod/response.py` | Create — `RDFResponse` class |
| `ontoexplorer/modules/mod/ratelimit.py` | Create — rate limit dependency |
| `ontoexplorer/modules/mod/context.py` | Create — JSON-LD `@context` |
| `ontoexplorer/main.py` | Modify — register `mod_router` at prefix `/mod` |
| `ontoexplorer/config.py` (or equivalent) | Modify — add `MOD_RATE_LIMIT_ANON`, `MOD_RATE_LIMIT_AUTH`, `MOD_CATALOGUE_TITLE`, `MOD_CATALOGUE_DESCRIPTION` |
| `.env.example` | Modify — document new MOD vars |
| `docs/mod-metadata-elements.md` | Create — reference field list for Profile/metadata editor |
| `tests/test_mod_api.py` | Create — integration tests |
