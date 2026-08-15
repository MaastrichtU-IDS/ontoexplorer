# Ingestion, Storage & Reasoning — formats and data flow

How an uploaded ontology moves through the system, what serialization is used at
each hop, and where each artifact is stored.

## Accepted input formats

| Format | Extension(s) | How it's parsed |
|---|---|---|
| RDF/XML | `.rdf`, `.xml` | pyoxigraph (streamed into Oxigraph) |
| OWL/XML | `.owl` | pyoxigraph (RDF/XML family) |
| Turtle | `.ttl` | pyoxigraph |
| N-Triples | `.nt` | pyoxigraph |
| N-Quads | `.nq` | pyoxigraph |
| TriG | `.trig` | pyoxigraph |
| JSON-LD | `.jsonld`, `.json` | pyoxigraph |
| OBO flat file | `.obo` | `horned-convert` → Turtle (rdflib fallback) |
| Manchester | `.omn` | `horned-convert` → Turtle |
| OWL Functional | `.ofn` | `horned-convert` → Turtle |

Format is detected from Content-Type, then filename extension, then a byte-sniff
of the first 512 bytes (`ontoexplorer/modules/ingestion/format_detect.py`).

## What gets sent to Oxigraph

Oxigraph is an **embedded RDF triplestore** (RocksDB). It always stores triples;
one named graph per version: `urn:ontology:{ontology_id}:{version_id}`. What we
hand the bulk loader depends on the upload format:

- **RDF-family uploads** (RDF/XML, OWL/XML, Turtle, N-Triples, N-Quads, TriG,
  JSON-LD) stream in **as-is** — the raw uploaded bytes with their MIME type, via
  `bulk_load_bytes` (no rdflib parse). This is the fast path.
- **Manchester / OBO / OWL-Functional** — no RDF parser in the Python stack reads
  these, so `horned-convert` (horned-owl's CLI, built into the API image)
  converts them to **Turtle**, which is then bulk-loaded as `text/turtle`.
  - Turtle (not N-Triples) on purpose: horned-owl can emit a *relative* IRI for
    an OBO ontology node (e.g. `ontology: my-onto` → `<my-onto>` when the id
    isn't a PURL-expandable short id). N-Triples requires absolute IRIs and is
    rejected; Turtle resolves relatives against the loader's `base_iri` (the
    version's graph IRI). See `horned_convert.py`.
  - If `horned-convert` fails on an OBO file, ingestion falls back to rdflib's
    OBO plugin (lower fidelity). Manchester/OWL-Functional have no fallback.

### Which format parses fastest?

Measured on GO (~1.28M triples), Oxigraph `bulk_load`, best-of-3:

| Format | Size | Parse |
|---|---|---|
| Turtle | 163 MB | 5.8 s |
| N-Triples | 200 MB | 6.5 s |
| RDF/XML | 242 MB | 7.2 s |

Turtle edges out N-Triples — it's ~18% fewer bytes (prefix + subject/predicate
grouping), and scanning less data beats N-Triples' simpler-but-verbose lines.
The spread is small and shape-dependent; **parse format is not a bottleneck**
(reasoning dominates end-to-end cost). Converting the convertible formats to
Turtle is therefore also the fastest-parsing choice, not just the correct one.

## Storage split

| Store | Contents | Format |
|---|---|---|
| **MinIO** | Original upload (unconverted), cached `owl:imports` | as uploaded (provenance) |
| **Oxigraph** (embedded) | Asserted + inferred triples; SPARQL/browse | RDF triples (RocksDB) |
| **Fuseki** | DCAT / VoID / PROV-O FAIR metadata | RDF (SPARQL endpoint) |
| **Postgres** (pgvector) | Users, ontologies, versions, jobs, webhooks, API keys, profiles, term embeddings | relational |
| **Redis** | Celery broker, app search/label index, reasoner-service cache | see below |

## Reasoner service and its Redis cache

The reasoner service (port 8001) hosts a capability-aware registry:

| Reasoner | Profile | Notes |
|---|---|---|
| **rustdl** (default) | SROIQ DL | classify + native justify; EL-saturation mode for EL ontologies |
| **konclude** | OWL 2 DL | subprocess; classify + consistency (no justify) |
| **km** | EL++ | consequence-based; classify + **native incremental** sessions |

(The legacy pure-Python `rdflib` EL classifier and `whelk` have been retired.)

**What's sent to the reasoner:** N-Triples over HTTP JSON. The reason task reads
the version's asserted named graph back out of Oxigraph and serializes it to
N-Triples (including the import closure), then POSTs `{ntriples, version_id,
reasoner, params}` to `/classify`.

**Reasoner-service Redis cache** (`docker/reasoner-service/cache.py`, gzipped
where noted; TTLs in that file):

| Key | Value |
|---|---|
| `input_axioms:{vid}:{reasoner}` | **N-Triples** — the serialized asserted graph + imports (what the reasoner classified) |
| `classification:{vid}:{reasoner}` | gzipped **JSON** `ClassificationResult` (sub/super/direct/unsatisfiable/…) |
| `justification:{vid}:{reasoner}:{hash}` | **JSON** — Manchester justification strings + metadata |
| `ofn:{vid}` | gzipped **OWL Functional (`.ofn`)** — per-version reasoning cache, built once and reused (rustdl re-parses/re-classifies per justify call, so caching the `.ofn` avoids repeated NT→RDF/XML→OFN conversion) |
| `classification_error:{vid}:{reasoner}` | plain-text error surfaced via the GET endpoint |

**App-side Redis** additionally holds the search/label index per version and a
short-lived `justify_inflight:{vid}:{hash}` flag that deduplicates the
non-blocking justification flow (peek cache → dispatch background job → poll).

## One-line mental model

- **Original upload** → MinIO (unconverted).
- **Triples** → Oxigraph (raw bytes for RDF families; Turtle for Manchester/OBO/OFN).
- **Reasoning** → N-Triples over HTTP; results + a per-version `.ofn` cached in Redis.
