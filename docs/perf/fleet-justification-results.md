# Fleet performance — /classify + /justification

Deployed stack: `main` after rdflib fallback + failed-marker fixes.
Bench script: `scripts/perf/fleet_perf_minio.py` for ontologies whose
host-graph dump via SPARQL CONSTRUCT is impractical (≥ ~700 K triples),
it reads the blob directly from MinIO and converts to N-Triples via
pyoxigraph in-process.

## Successful via SPARQL CONSTRUCT (≤ 600 K triples)

| ontology | triples | nt size | classes | inferred | /classify | /justify | found | axioms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pets | 86 | 0.0 MB | 10 | 6 | 1.0s | 0.0s | 1 | 2 |
| pro | 106 | 0.1 MB | 31 | 66 | 1.0s | 0.1s | 1 | 9 |
| skos | 252 | 0.0 MB | 4 | 0 | 1.0s | — | (no inferred) | |
| pav | 344 | 0.1 MB | 0 | 0 | 1.0s | — | (no inferred) | |
| sulo | 374 | 0.0 MB | 17 | 36 | 1.0s | 0.1s | 1 | 8 |
| dcterms | 700 | 0.1 MB | 13 | 15 | 0.5s | — | rdflib fallback | |
| bfo | 1,221 | 0.2 MB | 35 | 82 | 1.0s | 0.1s | 1 | 9 |
| dcat | 1,342 | 0.6 MB | 56 | 76 | 0.5s | — | rdflib fallback | |
| pizza | 1,483 | 0.3 MB | 115 | 274 | 1.1s | 1.5s | 1 | 8 |
| prov | 1,664 | 0.3 MB | 50 | 27 | 1.0s | 0.7s | 1 | 2 |
| dul | 1,917 | 0.4 MB | 78 | 190 | 1.0s | 11.3s | 1 | 8 |
| family | 5,017 | 0.8 MB | 58 | 296 | 1.1s | 1.1s | 0 | (inconsistent fixture) |
| ro | 11,640 | 1.7 MB | 58 | 110 | 2.4s | 45.3s | 1 | 7 |
| sdo | 17,949 | 2.4 MB | 958 | 3,077 | 1.1s | — | rdflib fallback | |
| obi | 116,121 | 15.8 MB | 5,177 | 21,776 | 3.0s | 12.6s | 1 | 6 |
| hdo | 303,727 | 46.3 MB | 19,482 | 127,496 | 9.9s | 38.8s | 1 | 9 |
| ordo | 606,476 | 80.9 MB | 16,036 | 28,502 | 14.2s | 48.6s | 1 | 4 |

## Giants via MinIO (≥ 700 K triples)

/justification skipped — the greedy walk OOMs elk-service even with BOT
extraction (the BOT module is itself ~30 MB / 450 K triples on cl,
which exceeds the available memory headroom after pyhornedowl + whelk
load both the full ontology and the candidate axiom list).

| ontology | triples | blob | NT | classes | inferred | /classify |
|---|---:|---:|---:|---:|---:|---:|
| cl | 777,527 | 63 MB | 103 MB | 19,151 | 205,406 | 27.1s |
| hp | 908,112 | 73 MB | 118 MB | 32,085 | 316,397 | 23.4s |
| uberon | 1,194,919 | 94 MB | 155 MB | 27,295 | 329,843 | 39.0s |
| mp | 1,259,780 | 98 MB | 163 MB | 35,151 | 407,674 | 51.6s |
| go | 1,444,037 | 124 MB | 193 MB | 51,937 | 305,886 | 32.7s |
| **mondo** | 3,054,374 | 232 MB | 382 MB | — | — | **OOM at /classify** |

## Known limits

- **mondo (3 M triples) OOMs elk-service** during whelk classification.
  py-horned-owl + whelk together hold multiple in-memory copies of the
  axiom graph; on this 15 GB host with API + worker + robot-service
  running, there's < 6 GB free which isn't enough. With more host memory
  or by streaming via pyoxigraph, mondo should classify.
- **/justification on ≥ 700 K triples** OOMs even with ROBOT BOT.
  Mitigations to try: hub-skip ON TOP of the BOT module; stream the
  greedy walk through pyoxigraph instead of materializing axiom lists.
- **dcterms / dcat / sdo** triggered horned-owl's property-type
  validation; resolved by the rdflib fallback (with the legacy
  classifier's known coverage gap on EL — acceptable since these vocabs
  are mostly subClassOf hierarchies).

`elk-service` now runs with `mem_limit: 6g` so OOMs are container-scoped
and restart cleanly instead of taking down the whole host.
