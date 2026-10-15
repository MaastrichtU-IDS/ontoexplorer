"""CLI: full OWL 2 profile violation report for a single ontology file.

    python -m ontoexplorer.modules.owl_profile.detect <ontology-file> [PROFILE] [--json]

PROFILE is one of EL/RL/QL/DL (case-insensitive) or `all` (default). Unlike the
cached in-app summary (which keeps only per-type counts — see detector.detect_profiles),
this prints EVERY violation with the specific offending entity/axiom. It runs the
exact classifier OntoExplorer uses (`detector.full_violations` → the pinned
`py-horned-owl` `check_profile`), so the counts match the ontology page.

Intended as the maintainer's self-serve "full report": run the published api image
against your own ontology file, e.g.

    docker run --rm -v "$PWD:/data" ghcr.io/maastrichtu-ids/ontoexplorer-api:<ver> \\
        python -m ontoexplorer.modules.owl_profile.detect /data/myont.owl DL
"""
from __future__ import annotations

import argparse
import json
import sys

from ontoexplorer.modules.owl_profile.detector import PROFILE_NAMES, full_violations

# File extension -> the format hint detector._load_ontology understands. Absent /
# unknown extensions fall through to horned-owl's auto-detection (None).
_EXT_FORMAT = {
    "owl": "owl", "rdf": "rdf", "xml": "rdf", "rdfxml": "rdf",
    "ofn": "ofn", "ofl": "ofn", "func": "ofn",
    "owx": "owx", "owl-xml": "owx",
    "omn": "omn",
    "obo": "obo",
    "ttl": None, "nt": None, "n3": None,  # auto-detect (no direct horned-owl literal)
}


def _format_for(path: str) -> str | None:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _EXT_FORMAT.get(ext)


def _render_text(report: dict) -> str:
    lines: list[str] = []
    for key in (k for k in PROFILE_NAMES if k in report):
        entry = report[key]
        status = "in profile" if entry["in_profile"] else "NOT in profile"
        lines.append(f"\nOWL 2 {key.upper()}: {status} — {entry['total_violations']} violation(s)")
        for t, n in sorted(entry["violations_by_axiom_type"].items(), key=lambda kv: -kv[1]):
            lines.append(f"    {n:>6}  {t}")
        if entry["violations"]:
            lines.append("    ──")
            for v in entry["violations"]:
                detail = v["details"] or v["subject_iri"] or ""
                lines.append(f"    {v['axiom_type']:<48} {detail}")
    return "\n".join(lines).lstrip("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m ontoexplorer.modules.owl_profile.detect",
        description="Full OWL 2 profile violation report for an ontology file.",
    )
    ap.add_argument("file", help="Path to the ontology file")
    ap.add_argument(
        "profile", nargs="?", default="all",
        help="EL, RL, QL, DL, or all (default)",
    )
    ap.add_argument("--format", dest="fmt", default=None,
                    help="Override the serialization (owl/rdf/ofn/owx/omn/obo)")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = ap.parse_args(argv)

    profile = args.profile.lower()
    if profile == "all":
        profiles = PROFILE_NAMES
    elif profile in PROFILE_NAMES:
        profiles = (profile,)
    else:
        ap.error(f"profile must be one of {', '.join(p.upper() for p in PROFILE_NAMES)} or all")

    try:
        with open(args.file, "rb") as fh:
            content = fh.read()
    except OSError as exc:
        print(f"error: cannot read {args.file}: {exc}", file=sys.stderr)
        return 2

    fmt = args.fmt or _format_for(args.file)
    try:
        report = full_violations(content, fmt, profiles)
    except Exception as exc:  # parse/load failure
        print(f"error: could not classify {args.file}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
