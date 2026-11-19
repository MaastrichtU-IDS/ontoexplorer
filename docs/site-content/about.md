# About OntoExplorer

**OntoExplorer is a continuously-maintained catalogue and quality observatory for
ontologies and controlled vocabularies.** It ingests ontologies from the major
registries and from maintainers directly, then automatically computes a uniform
set of artifacts over every version — a search index, semantic embeddings, a
class hierarchy, OWL 2 profile reports, FAIR scores, and more — and keeps them
fresh as upstream ontologies change.

Where a point-in-time validator assesses an ontology once, on request,
OntoExplorer tracks the same evidence across the **whole catalogue, over time**,
and acts on it: a quality gate holds non-compliant submissions, a feedback loop
alerts maintainers, and an update poller detects new upstream releases.

## Who it's for

- **Ontology users** — find the right vocabulary, search across terms from every
  ontology at once, compare versions, and judge fitness with transparent FAIR and
  OWL-profile signals.
- **Ontology authors & maintainers** — publish an ontology, keep it current, and
  see concrete, actionable quality feedback (missing licences, absent labels,
  profile violations) instead of a single opaque score.
- **Researchers & tool builders** — a public REST API and SPARQL endpoint over a
  large, normalised, richly-indexed corpus.

## What it does, at a glance

- **Catalogue & browse** — {{nOnt}} ontologies in {{nVer}} versions, aggregated
  from LOV, the OBO Foundry, and BioPortal, plus a curated upper-level set. Filter
  by source, expressivity tier, licence, and language.
- **Search** — lexical *and* semantic search across millions of indexed entities
  (classes, properties, individuals) from across the catalogue, with labels,
  synonyms, and definitions.
- **FAIR assessment** — a FAIR *report* per version aligned with the FOOPS! check
  set (19 checks across Findable, Accessible, Interoperable, Reusable), rolled up
  across the catalogue and tracked over time.
- **Reasoning & profiles** — OWL 2 EL/QL/RL/DL profile membership with violation
  details, plus a language-expressivity tier for every version.
- **Versioning & diffs** — full version history with semantic diffs that explain
  what changed between two releases.
- **Automated maintenance** — upstream-update detection, optional auto-sync,
  IRI-resolvability checks, and a submission quality gate.
- **Programmatic access** — a documented REST API, a SPARQL endpoint with a saved
  query gallery, and per-account API keys and webhooks.

See the [full documentation](documentation.md) for details on each feature.

## How it works (in one paragraph)

Every ontology enters through the same automated pipeline: it is fetched,
parsed, stored in a triple store, and passed through a quality gate (licence,
title, and minimum-content checks). Jobs then build the entity index, generate
vector embeddings, extract the class hierarchy, classify OWL 2 profiles, and
compute the FAIR report — each step idempotent and self-healing, so a change to
one input (a new licence, a re-resolved IRI) invalidates and recomputes only
what depends on it. A scheduled poller re-checks each ontology's canonical IRI
for new upstream releases.

## Project & governance

OntoExplorer is developed by **«Maastricht University — Institute of Data Science
(IDS)»**. The source code is open and public under the Apache 2.0 licence:
<https://github.com/MaastrichtU-IDS/ontoexplorer>.

Catalogue content is aggregated from third-party registries and from direct
submissions; each ontology retains its own upstream licence, shown on its page.

> Figures such as {{nOnt}}/{{nVer}} are rendered live from the deployment at wire-in
> time; here they are template placeholders.
