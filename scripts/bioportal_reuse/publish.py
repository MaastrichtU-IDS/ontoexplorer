"""Package output CSVs + summary into the bioportal-ontology-analysis docs/v2/ dir."""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def publish(output_dir: Path, summary: dict, companion_repo: Path | None) -> Path:
    """Write summary.json alongside CSVs; optionally copy into companion repo."""
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    if companion_repo is not None:
        target = companion_repo / "docs" / "v2"
        target.mkdir(parents=True, exist_ok=True)
        for f in output_dir.iterdir():
            if f.is_file():
                shutil.copy(f, target / f.name)
        print(f"Copied {len(list(output_dir.iterdir()))} files to {target}")

    return summary_path
