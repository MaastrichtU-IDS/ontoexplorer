# OWL 2 profile benchmark vs ROBOT

Repository-wide comparison of OntoExplorer's in-process OWL 2 profile detector
against [ROBOT 1.x](https://robot.obolibrary.org/) (Java + OWL-API). Runs the
same `validate-profile EL|RL|QL|DL` check on every indexed ontology and reports
verdict agreement and wall-clock timing.

Use this as a recurring health check as the fleet grows.

## Prerequisites

- A running OntoExplorer API (default `http://localhost:8000`)
- `uv` for the Python deps already in this repo
- ROBOT on `PATH` (skip with `--skip-robot` if you don't have it)

## Usage

From the repo root:

```bash
# Full repository, ours vs ROBOT
uv run python scripts/owl_profile_bench/benchmark.py

# Skip ontologies above 1M triples (faster, avoids the giants)
uv run python scripts/owl_profile_bench/benchmark.py --max-triples 1_000_000

# Subset by shortname
uv run python scripts/owl_profile_bench/benchmark.py --ontologies mondo,hp,uberon

# Our detector only (no ROBOT — quick sanity check across the fleet)
uv run python scripts/owl_profile_bench/benchmark.py --skip-robot

# Compare ROBOT verdicts to our PRODUCTION cache (recommended for accuracy comparisons)
uv run python scripts/owl_profile_bench/benchmark.py --from-cache

# Keep downloaded ontology files in the workdir
uv run python scripts/owl_profile_bench/benchmark.py --keep-downloads --workdir ./bench-out
```

## --from-cache vs standalone-load

By default, the script loads each ontology's `.owl` file standalone and runs
`detect_profiles` against just those triples. This makes the speed comparison
fair (both sides parse from scratch) but **under-counts** declarations from
imported ontologies — ROBOT follows `owl:imports` and our production indexer
also loads imports closure, but the standalone benchmark doesn't.

For accurate verdict-agreement comparisons against ROBOT, use `--from-cache`.
This reads the production owl_profile cache (which was built from the
imports-loaded Oxigraph store) and compares directly to ROBOT. The "ours"
timing column becomes meaningless (HTTP fetch is microseconds), but the
verdict-agreement number reflects what users actually see.

Empirically on a 19-ontology sample: **standalone agreement ~42%, cache-based
agreement ~63%** — same detector, different data source.

## Output

- **`<workdir>/results.csv`** — one row per ontology, with:
  - `triples`, `ours_load_s`, `ours_detect_s`, `ours_total_s`
  - `ours_<profile>` (in-profile boolean) and `ours_<profile>_count`
  - `robot_total_s`, `robot_<profile>_s`, `robot_<profile>`, `robot_<profile>_count`
  - `speedup_cold` (ROBOT total / our load+detect)
  - `verdict_agreement` (`MATCH` / `MISMATCH` / `?`)
- **stdout** — a summary table + aggregate verdict-agreement percentage and overall speedup

## Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--api-base` | `http://localhost:8000` | OntoExplorer API base URL |
| `--workdir` | `bench-out` | Directory for downloads + `results.csv` |
| `--skip-robot` | off | Time our detector only |
| `--robot-cmd` | `robot` | ROBOT executable to invoke |
| `--max-triples` | none | Skip ontologies above this triple count |
| `--ontologies` | all | Comma-separated shortnames to benchmark |
| `--keep-downloads` | off | Don't delete downloaded files after the run |

## What the comparison measures

**Cold-start (load + detect):** the right comparison for users running ROBOT
manually one-off. Includes pyoxigraph parse on our side and JVM startup + OWL-API
parse on ROBOT's. Reported as `ours_total_s` vs `robot_total_s`.

**Production detect-only (`ours_detect_s`):** the cost we actually pay in
indexing — data is already loaded in Oxigraph; profile detection is just a few
extra SPARQL queries. ROBOT has no equivalent (it can't reuse our store).

**Verdict agreement:** does our in/out classification match ROBOT's for each of
the four profiles? Counts may diverge (we count at the RDF-triple level; ROBOT at
the OWL-axiom level) but the in/out verdict should match for well-formed ontologies.

## Known limitations

The detector under-counts OWL 2 RL violations because it doesn't check positional
rules (LHS vs RHS of `rdfs:subClassOf`). RL verdicts can be correct (out-of-profile
because we catch *some* violations) while RL counts are well below ROBOT's. See
`docs/superpowers/specs/2026-05-19-owl-profile-detection-design.md` "Measured
comparison vs ROBOT" for the case studies.

The default standalone-load benchmark does NOT follow `owl:imports`, so
declarations made in imported ontologies are missed and the undeclared-property
DL check over-fires. Use `--from-cache` for an apples-to-apples comparison with
ROBOT (which downloads imports).

## Reference results

Earlier benchmark on a 6-ontology sample (SULO ≤ HP, ~100 to ~900K triples):
all four verdicts agreed across all six ontologies; cold-start speedup ranged
from ~1400× on small ontologies (JVM startup dominates) to ~10× on the largest.
At indexing-time (data already in store) we add a few seconds for HP-class data.

For NCBITaxon-class data (~10M triples) the architectural difference matters more
than the raw speedup — ROBOT would need ~16-20 GB JVM heap; ours adds no memory
pressure on top of Oxigraph's working set.
