"""CLI entry: load preliminary CSVs, normalize, write outputs.

Usage:
  python -m scripts.bioportal_reuse.run \\
      --input-dir ~/bpoa/results/tables \\
      --output-dir ~/bpoa/results/tables/v2-normalized \\
      [--companion-repo ~/bpoa]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.bioportal_reuse.mireot_heuristic import estimate_mireot_candidates
from scripts.bioportal_reuse.normalize import (
    normalize_hub_ontologies,
    normalize_upper_level_adoption,
)
from scripts.bioportal_reuse.publish import publish


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--companion-repo", type=Path, default=None)
    args = p.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    upper_summary = normalize_upper_level_adoption(
        args.input_dir / "upper_level_adoption.csv",
        args.output_dir / "upper_level_adoption_normalized.csv",
    )
    hub_summary = normalize_hub_ontologies(
        args.input_dir / "hub_ontologies.csv",
        args.output_dir / "hub_ontologies_normalized.csv",
    )
    mireot_summary = estimate_mireot_candidates(
        args.input_dir / "hub_ontologies.csv",  # serves as mapping source
        args.input_dir / "upper_level_adoption.csv",  # imports source
        args.output_dir / "mireot_candidates.csv",
    )

    summary = {
        "upper_level": upper_summary,
        "hubs": hub_summary,
        "mireot": mireot_summary,
    }
    print(json.dumps(summary, indent=2))
    summary_path = publish(args.output_dir, summary, args.companion_repo)
    print(f"Wrote summary to {summary_path}")


if __name__ == "__main__":
    main()
