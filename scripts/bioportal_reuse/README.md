# BioPortal Reuse Rerun

Re-runs the user's preliminary [bioportal-ontology-analysis](https://github.com/micheldumontier/bioportal-ontology-analysis)
work with two additions:

1. **Bioregistry-normalized IRIs** — variant URI forms (e.g. `purl.obolibrary.org/obo/RO_*` vs `purl.org/obo/RO_*`) collapse to the same target prefix, producing higher (more accurate) reuse counts.
2. **MIREOT heuristic** — without ontology bodies (BioPortal API gives metadata only at scale), we estimate MIREOT usage from the mapping table: a term that appears in `oboInOwl:hasDbXref` to ontology X but whose host does NOT declare `owl:imports` of X is a MIREOT *candidate*. Counts are upper-bound estimates and labelled as such.

## Inputs

Expects the preliminary work's CSV outputs to be available locally. Clone the
companion repo and pass its path:

```
git clone https://github.com/micheldumontier/bioportal-ontology-analysis.git ~/bpoa
python -m scripts.bioportal_reuse.run --input-dir ~/bpoa/results/tables --output-dir ~/bpoa/results/tables/v2-normalized
```

## Outputs

- `upper_level_adoption_normalized.csv` — adoption rate before/after normalization
- `hub_ontologies_normalized.csv` — mapping hubs with collapsed prefixes
- `mireot_candidates.csv` — terms that LOOK like MIREOT under the heuristic
- `summary.json` — single-file rollup for the GitHub Pages site

The publish step copies these into a `v2/` subdirectory of the
companion repo's `docs/` folder, ready for git commit + push.

## Caveat

This pipeline does NOT run the precise MIREOT detector — that requires
parsing ontology bodies and lives in OntoExplorer's `signals/mireot.py`.
The fleet-scale numbers from BioPortal are upper bounds. Use OntoExplorer's
per-ontology Reuse tab for ground-truth analysis.
