"""Benchmark OWL 2 profile detection across the entire ontology repository.

Compares our in-process SPARQL detector to ROBOT 1.x for verdict agreement
and wall-clock performance. Intended for periodic re-runs as the fleet grows.

Usage:
    uv run python scripts/benchmark_owl_profile.py
    uv run python scripts/benchmark_owl_profile.py --skip-robot         # ours only
    uv run python scripts/benchmark_owl_profile.py --max-triples 5_000_000
    uv run python scripts/benchmark_owl_profile.py --ontologies go,hp,cl  # subset by shortname
    uv run python scripts/benchmark_owl_profile.py --workdir ./bench-out

Outputs: a results.csv in the workdir plus a printed summary table.
Requirements: ROBOT on PATH (https://robot.obolibrary.org/), running OntoExplorer
API on http://localhost:8000 (or set --api-base).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import pyoxigraph


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api-base", default="http://localhost:8000",
                   help="OntoExplorer API base URL")
    p.add_argument("--workdir", default="bench-out",
                   help="Directory for downloaded ontologies + results.csv")
    p.add_argument("--skip-robot", action="store_true",
                   help="Time our detector only, skip ROBOT")
    p.add_argument("--robot-cmd", default="robot",
                   help="ROBOT executable name (default: robot on PATH)")
    p.add_argument("--max-triples", type=int, default=None,
                   help="Skip ontologies whose triple_count exceeds this (None = no cap)")
    p.add_argument("--ontologies", default=None,
                   help="Comma-separated shortnames to benchmark (default: all)")
    p.add_argument("--keep-downloads", action="store_true",
                   help="Keep downloaded ontology files after benchmark")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class OntologyMeta:
    shortname: str
    ontology_id: str
    version_id: str
    triple_count: int
    download_url: str


@dataclass
class ResultRow:
    shortname: str
    triples: int
    # Our detector
    ours_load_s: float = 0.0
    ours_detect_s: float = 0.0
    ours_verdicts: dict[str, bool] = field(default_factory=dict)
    ours_counts: dict[str, int] = field(default_factory=dict)
    ours_error: str | None = None
    # ROBOT
    robot_times: dict[str, float] = field(default_factory=dict)  # per profile
    robot_verdicts: dict[str, bool] = field(default_factory=dict)
    robot_counts: dict[str, int] = field(default_factory=dict)
    robot_error: str | None = None

    @property
    def robot_total_s(self) -> float:
        return sum(self.robot_times.values())

    @property
    def ours_total_s(self) -> float:
        return self.ours_load_s + self.ours_detect_s


# ---------------------------------------------------------------------------
# API enumeration
# ---------------------------------------------------------------------------

def list_ontologies(api_base: str) -> list[OntologyMeta]:
    """Fetch every ontology + its latest ready version from the API."""
    metas: list[OntologyMeta] = []
    # The list endpoint is paginated; iterate.
    offset = 0
    while True:
        url = f"{api_base}/api/v1/ontologies?limit=100&offset={offset}"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read())
        rows = data.get("ontologies", [])
        if not rows:
            break
        for o in rows:
            lv = o.get("latest_version")
            if not lv or lv.get("status") != "ready":
                continue
            metas.append(OntologyMeta(
                shortname=o.get("shortname") or o["id"][:8],
                ontology_id=o["id"],
                version_id=lv["id"],
                triple_count=int(o.get("triple_count") or 0),
                download_url=f"{api_base}{lv['download_url']}",
            ))
        if len(rows) < 100:
            break
        offset += 100
    return metas


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    urllib.request.urlretrieve(url, dest)


# ---------------------------------------------------------------------------
# Our detector
# ---------------------------------------------------------------------------

def time_ours(ttl_path: Path, shortname: str) -> tuple[float, float, dict, dict, str | None]:
    """Returns (load_s, detect_s, verdicts, counts, error)."""
    # Import lazily so the script is importable even without the project root.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ontoexplorer.modules.owl_profile.detector import detect_profiles

    content = ttl_path.read_bytes()
    store = pyoxigraph.Store()
    t0 = time.time()
    try:
        store.load(content, pyoxigraph.RdfFormat.TURTLE)
    except Exception:
        store = pyoxigraph.Store()
        try:
            store.load(content, pyoxigraph.RdfFormat.RDF_XML)
        except Exception as e:
            return 0.0, 0.0, {}, {}, f"load failed: {e}"
    load_s = time.time() - t0

    t0 = time.time()
    try:
        result = detect_profiles(store, graph_iri=None,
                                 ontology_id=shortname, version_id="bench")
    except Exception as e:
        return load_s, 0.0, {}, {}, f"detect failed: {e}"
    detect_s = time.time() - t0

    verdicts = {p: result[p]["in_profile"] for p in ("el", "rl", "ql", "dl")}
    counts = {p: result[p]["total_violations"] for p in ("el", "rl", "ql", "dl")}
    return load_s, detect_s, verdicts, counts, None


# ---------------------------------------------------------------------------
# ROBOT
# ---------------------------------------------------------------------------

# ROBOT prints "PROFILE VIOLATION ERROR ... violates profile X" on the LAST line(s)
# of stderr on failure. On success it prints "OWL 2 X Profile Report: [Ontology and
# imports closure in profile]" on stdout. We parse both.
_VIOLATION_LINE_RE = re.compile(
    r"^(Axiom type not allowed|Use of |Class expressions not allowed|Use of non-superclass)"
)


def time_robot_one_profile(robot_cmd: str, ont_path: Path, profile: str) -> tuple[float, bool, int, str | None]:
    """Run `robot validate-profile`. Returns (wall_s, in_profile, violation_count, error)."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            [robot_cmd, "validate-profile", "--profile", profile, "--input", str(ont_path)],
            capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return 600.0, False, -1, "timeout"
    except FileNotFoundError:
        return 0.0, False, -1, f"robot binary not found: {robot_cmd}"
    wall = time.time() - t0
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # Count violation lines (matches both stdout and stderr forms)
    count = sum(1 for line in out.splitlines() if _VIOLATION_LINE_RE.match(line.strip()))
    in_profile = "violates profile" not in out and count == 0
    err = None if proc.returncode in (0, 1) else f"robot exit {proc.returncode}"
    return wall, in_profile, count, err


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    skip_robot = args.skip_robot
    if not skip_robot and not shutil.which(args.robot_cmd):
        print(f"WARNING: '{args.robot_cmd}' not on PATH — switching to --skip-robot", file=sys.stderr)
        skip_robot = True

    print(f"Enumerating ontologies from {args.api_base}...")
    metas = list_ontologies(args.api_base)
    if args.ontologies:
        keep = set(args.ontologies.split(","))
        metas = [m for m in metas if m.shortname in keep]
    if args.max_triples is not None:
        before = len(metas)
        metas = [m for m in metas if m.triple_count <= args.max_triples]
        print(f"  skipped {before - len(metas)} ontologies above {args.max_triples:,} triples")

    metas.sort(key=lambda m: m.triple_count)
    print(f"Benchmarking {len(metas)} ontologies (smallest first)\n")

    results: list[ResultRow] = []
    for i, m in enumerate(metas, 1):
        print(f"[{i:>2}/{len(metas)}] {m.shortname} ({m.triple_count:,} triples)")
        ont_path = workdir / f"{m.shortname}.owl"
        try:
            download(m.download_url, ont_path)
        except Exception as e:
            print(f"  download failed: {e}")
            continue

        row = ResultRow(shortname=m.shortname, triples=m.triple_count)

        # Ours
        load_s, detect_s, verdicts, counts, err = time_ours(ont_path, m.shortname)
        row.ours_load_s = load_s
        row.ours_detect_s = detect_s
        row.ours_verdicts = verdicts
        row.ours_counts = counts
        row.ours_error = err
        if err:
            print(f"  ours: {err}")
        else:
            print(f"  ours: load {load_s:6.2f}s + detect {detect_s:6.2f}s "
                  f"= {load_s+detect_s:6.2f}s — verdicts: " +
                  " ".join(f"{p}={'IN' if verdicts[p] else 'OUT'}" for p in ("el","rl","ql","dl")))

        # ROBOT (per profile)
        if not skip_robot:
            for p in ("EL", "RL", "QL", "DL"):
                wall, in_p, n, err = time_robot_one_profile(args.robot_cmd, ont_path, p)
                row.robot_times[p.lower()] = wall
                row.robot_verdicts[p.lower()] = in_p
                row.robot_counts[p.lower()] = n
                if err and "exit" not in err:
                    row.robot_error = err
                    print(f"  robot {p}: {err}")
                    break
            if not row.robot_error:
                print(f"  robot total: {row.robot_total_s:6.2f}s — verdicts: " +
                      " ".join(f"{p}={'IN' if row.robot_verdicts[p] else 'OUT'}"
                              for p in ("el","rl","ql","dl")))

        results.append(row)

        if not args.keep_downloads:
            ont_path.unlink(missing_ok=True)

    # Write CSV
    csv_path = workdir / "results.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "shortname", "triples",
            "ours_load_s", "ours_detect_s", "ours_total_s",
            "ours_el", "ours_rl", "ours_ql", "ours_dl",
            "ours_el_count", "ours_rl_count", "ours_ql_count", "ours_dl_count",
            "robot_total_s", "robot_el_s", "robot_rl_s", "robot_ql_s", "robot_dl_s",
            "robot_el", "robot_rl", "robot_ql", "robot_dl",
            "robot_el_count", "robot_rl_count", "robot_ql_count", "robot_dl_count",
            "speedup_cold", "verdict_agreement",
        ])
        for r in results:
            agreement = "?"
            if r.robot_verdicts and r.ours_verdicts:
                agreement = "MATCH" if all(
                    r.ours_verdicts.get(p) == r.robot_verdicts.get(p)
                    for p in ("el","rl","ql","dl")
                ) else "MISMATCH"
            speedup = (r.robot_total_s / r.ours_total_s) if r.ours_total_s > 0 and r.robot_total_s > 0 else 0.0
            w.writerow([
                r.shortname, r.triples,
                f"{r.ours_load_s:.3f}", f"{r.ours_detect_s:.3f}", f"{r.ours_total_s:.3f}",
                r.ours_verdicts.get("el", ""), r.ours_verdicts.get("rl", ""),
                r.ours_verdicts.get("ql", ""), r.ours_verdicts.get("dl", ""),
                r.ours_counts.get("el", ""), r.ours_counts.get("rl", ""),
                r.ours_counts.get("ql", ""), r.ours_counts.get("dl", ""),
                f"{r.robot_total_s:.3f}",
                f"{r.robot_times.get('el', 0):.3f}", f"{r.robot_times.get('rl', 0):.3f}",
                f"{r.robot_times.get('ql', 0):.3f}", f"{r.robot_times.get('dl', 0):.3f}",
                r.robot_verdicts.get("el", ""), r.robot_verdicts.get("rl", ""),
                r.robot_verdicts.get("ql", ""), r.robot_verdicts.get("dl", ""),
                r.robot_counts.get("el", ""), r.robot_counts.get("rl", ""),
                r.robot_counts.get("ql", ""), r.robot_counts.get("dl", ""),
                f"{speedup:.1f}", agreement,
            ])

    # Summary table
    print(f"\n\n{'=' * 72}")
    print(f"Results written to {csv_path}")
    print(f"{'=' * 72}\n")
    print(f"{'Ontology':12s} {'Triples':>10s}  {'Ours':>8s}  {'ROBOT':>8s}  {'Speedup':>8s}  Verdicts")
    print(f"{'-' * 72}")
    for r in results:
        speedup = (r.robot_total_s / r.ours_total_s) if r.ours_total_s > 0 and r.robot_total_s > 0 else 0.0
        agree = ""
        if r.robot_verdicts and r.ours_verdicts:
            agree = " ✓" if all(r.ours_verdicts.get(p) == r.robot_verdicts.get(p)
                              for p in ("el","rl","ql","dl")) else " ✗"
        rob = f"{r.robot_total_s:7.2f}s" if r.robot_total_s > 0 else "      —"
        spd = f"{speedup:>6.1f}×" if speedup > 0 else "      —"
        verdicts = " ".join(
            f"{p}={'I' if r.ours_verdicts.get(p) else 'O'}"
            + (("/" + ('I' if r.robot_verdicts.get(p) else 'O'))
               if r.robot_verdicts else "")
            for p in ("el","rl","ql","dl")
        )
        print(f"{r.shortname:12s} {r.triples:>10,d}  {r.ours_total_s:>7.2f}s  {rob}  {spd}  {verdicts}{agree}")

    # Aggregate
    if results:
        agreed = sum(
            1 for r in results
            if r.robot_verdicts and all(
                r.ours_verdicts.get(p) == r.robot_verdicts.get(p)
                for p in ("el","rl","ql","dl")
            )
        )
        with_robot = sum(1 for r in results if r.robot_verdicts)
        if with_robot:
            print(f"\nVerdict agreement: {agreed}/{with_robot} ontologies "
                  f"({100 * agreed / with_robot:.0f}%)")
        total_ours = sum(r.ours_total_s for r in results)
        total_rob = sum(r.robot_total_s for r in results)
        if total_rob > 0:
            print(f"Total time: ours {total_ours:.1f}s, ROBOT {total_rob:.1f}s "
                  f"({total_rob/total_ours:.1f}× overall speedup)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
