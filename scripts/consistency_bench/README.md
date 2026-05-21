# Consistency Bench (Konclude vs HermiT/ROBOT)

Standalone tool to validate Konclude's per-scope consistency verdicts against ROBOT/HermiT (the OBO Foundry community standard) across the OntoExplorer fleet. Produces verdict-agreement numbers comparable to Matentzoglu 2020.

## Inputs

- OntoExplorer's production consistency cache (Redis) for Konclude verdicts
- ROBOT 1.9.10 on PATH (already in the runtime container; uses `--reasoner hermit`)

## Usage

```
# Run HermiT on every fleet version, write per-version verdicts to a CSV
python -m scripts.consistency_bench.run --output-dir /tmp/cbench/

# Compare Konclude (production cache) vs HermiT (just produced)
python -m scripts.consistency_bench.compare \
    --hermit-csv /tmp/cbench/hermit_verdicts.csv \
    --output-dir /tmp/cbench/

# Publish summary CSV/JSON
python -m scripts.consistency_bench.publish --output-dir /tmp/cbench/
```

## Caveat

ROBOT/HermiT reasons over `host + owl:imports closure` natively. It does NOT support the host+imports+MIREOT-sources scope without pre-merging — so the bench compares only the first two scopes (`host_only`, `host_plus_imports`). The MIREOT scope's verdict is Konclude-only; trust requires manual review for now.
