"""Bundle CSVs + summary into a v2/ subdirectory of the companion docs repo."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--companion-repo", type=Path, default=None)
    args = p.parse_args()

    if args.companion_repo is None:
        print(f"Outputs left in {args.output_dir}")
        return

    target = args.companion_repo / "docs" / "consistency_v2"
    target.mkdir(parents=True, exist_ok=True)
    for f in args.output_dir.iterdir():
        if f.is_file():
            shutil.copy(f, target / f.name)
    print(f"Copied {len(list(args.output_dir.iterdir()))} files to {target}")


if __name__ == "__main__":
    main()
