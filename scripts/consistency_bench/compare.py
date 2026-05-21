"""Diff Konclude (production cache) vs HermiT (bench output) verdicts."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from ontoexplorer.modules.consistency.cache import consistency_cache_key
from ontoexplorer.modules.search.indexer import _get_redis


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--hermit-csv", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    r = _get_redis()
    hermit_rows = list(csv.DictReader(args.hermit_csv.open()))

    out_rows = []
    agreement = {"host_only": 0, "host_plus_imports": 0}
    total = {"host_only": 0, "host_plus_imports": 0}

    for h in hermit_rows:
        vid = h["version_id"]
        scope = h["scope"]
        raw = r.get(consistency_cache_key(vid))
        if not raw:
            continue
        konclude_data = json.loads(raw)
        konclude_status = konclude_data.get("scopes", {}).get(scope, {}).get("status")
        konclude_consistent = konclude_status == "consistent"
        hermit_consistent = h["consistent"] == "true"
        agree = (konclude_consistent == hermit_consistent)
        agreement[scope] += int(agree)
        total[scope] += 1
        out_rows.append({
            "version_id": vid,
            "scope": scope,
            "konclude_status": konclude_status,
            "hermit_consistent": h["consistent"],
            "agree": "true" if agree else "false",
        })

    comp_csv = args.output_dir / "konclude_vs_hermit.csv"
    with comp_csv.open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else
                           ["version_id", "scope", "konclude_status", "hermit_consistent", "agree"])
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        scope: {
            "agreed": agreement[scope],
            "total": total[scope],
            "agreement_pct": round(100 * agreement[scope] / total[scope], 1) if total[scope] else 0,
        }
        for scope in ("host_only", "host_plus_imports")
    }
    (args.output_dir / "agreement_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
