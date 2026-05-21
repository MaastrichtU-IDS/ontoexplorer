"""Run ROBOT/HermiT consistency across the OntoExplorer fleet.

For each (ontology, version), serialize host + imports closure to a single OWL/XML
file via OntoExplorer's existing merger, then invoke `robot reason --reasoner hermit`
and record consistent/inconsistent + any unsatisfiable class IRIs.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import subprocess
import tempfile
import time
from pathlib import Path

from sqlalchemy import select

from ontoexplorer.clients.oxigraph import graph_iri
from ontoexplorer.database import make_celery_db_session
from ontoexplorer.models.db import Ontology, OntologyImport, OntologyVersion
from ontoexplorer.modules.consistency.merger import build_merge


async def _enumerate_fleet() -> list[tuple[str, str, str, list[str]]]:
    """Return list of (ontology_id, version_id, host_iri, import_graph_iris) for latest-ready versions."""
    async with make_celery_db_session()() as db:
        # Latest ready version per ontology
        from sqlalchemy import func
        subq = (
            select(
                OntologyVersion.ontology_id,
                func.max(OntologyVersion.created_at).label("max_created"),
            )
            .where(OntologyVersion.status == "ready")
            .group_by(OntologyVersion.ontology_id)
            .subquery()
        )
        rows = (await db.execute(
            select(OntologyVersion.id, OntologyVersion.ontology_id, Ontology.iri)
            .join(subq, (OntologyVersion.ontology_id == subq.c.ontology_id)
                  & (OntologyVersion.created_at == subq.c.max_created))
            .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        )).all()
        out = []
        for vid, oid, host_iri in rows:
            imps = (await db.execute(
                select(OntologyImport.import_iri)
                .where(OntologyImport.version_id == vid)
            )).scalars().all()
            # In OntoExplorer's storage model imports are merged into the host graph,
            # so import_graph_iris is empty (the host graph already contains them).
            import_graphs: list[str] = []
            out.append((str(oid), str(vid), str(host_iri), import_graphs))
        return out


def run_hermit(merge_path: Path, robot_cmd: str = "robot") -> tuple[bool, list[str], float]:
    """Run `robot reason --reasoner hermit` and parse the verdict."""
    t0 = time.monotonic()
    proc = subprocess.run(
        [robot_cmd, "reason", "--input", str(merge_path),
         "--reasoner", "hermit",
         "--output", str(merge_path.with_suffix(".reasoned.owl"))],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    elapsed = time.monotonic() - t0
    out = (proc.stdout + proc.stderr).lower()
    consistent = "inconsistent" not in out and proc.returncode == 0
    unsat: list[str] = []
    # ROBOT prints unsatisfiable class IRIs to stderr in a known format; parse minimally
    for line in (proc.stdout + proc.stderr).splitlines():
        if "unsatisfiable" in line.lower() and "http://" in line:
            iri = line.split("http://", 1)[1].split()[0]
            unsat.append("http://" + iri.rstrip(",.;:"))
    return consistent, sorted(set(unsat)), elapsed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--robot-cmd", default="robot")
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = asyncio.run(_enumerate_fleet())
    out_csv = args.output_dir / "hermit_verdicts.csv"
    with out_csv.open("w") as f:
        w = csv.DictWriter(f, fieldnames=[
            "ontology_id", "version_id", "host_iri", "scope",
            "consistent", "unsatisfiable_count", "elapsed_seconds",
        ])
        w.writeheader()
        with tempfile.TemporaryDirectory(prefix="cbench_") as tmp:
            for oid, vid, host_iri, import_graphs in rows:
                for scope in ("host_only", "host_plus_imports"):
                    merge_path = build_merge(
                        out_dir=Path(tmp) / vid,
                        host_graph_iri=graph_iri(oid, vid),
                        import_graph_iris=import_graphs,
                        mireot_source_paths=[],
                        scope=scope,
                    )
                    try:
                        consistent, unsat, elapsed = run_hermit(merge_path, args.robot_cmd)
                    except Exception as exc:
                        print(f"FAIL {vid} {scope}: {exc}")
                        continue
                    w.writerow({
                        "ontology_id": oid, "version_id": vid,
                        "host_iri": host_iri, "scope": scope,
                        "consistent": "true" if consistent else "false",
                        "unsatisfiable_count": len(unsat),
                        "elapsed_seconds": round(elapsed, 2),
                    })
                    print(f"OK {vid} {scope}: consistent={consistent} unsat={len(unsat)} {elapsed:.1f}s")
    print(f"Wrote {out_csv}")


if __name__ == "__main__":
    main()
