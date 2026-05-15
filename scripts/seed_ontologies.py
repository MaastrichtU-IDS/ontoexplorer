"""Bulk-submit ontologies from seeds/catalog.yaml to a running OntoExplorer instance.

Usage:
    uv run scripts/seed_ontologies.py --api-key oe_... [options]

Options:
    --api-url URL       Base API URL (default: http://localhost:8000)
    --api-key KEY       API key with write scope (or set ONTOEXPLORER_API_KEY env var)
    --group GROUP       Only submit entries with this group tag (repeatable)
    --include-large     Also submit entries marked large:true (>40k classes; may OOM on
                        hosts with <16 GB RAM — submit one at a time on WSL)
    --dry-run           Print what would be submitted without sending requests
    --catalog PATH      Path to catalog YAML (default: seeds/catalog.yaml)
"""

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
import yaml


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    p.add_argument("--api-key", default=os.getenv("ONTOEXPLORER_API_KEY", ""), help="API key")
    p.add_argument("--group", action="append", dest="groups", metavar="GROUP",
                   help="Filter by group tag (repeatable; default: all groups)")
    p.add_argument("--include-large", action="store_true",
                   help="Include entries marked large:true (skipped by default to prevent OOM)")
    p.add_argument("--dry-run", action="store_true", help="Print plan without submitting")
    p.add_argument("--catalog", default=str(Path(__file__).parent.parent / "seeds" / "catalog.yaml"),
                   help="Path to catalog YAML")
    return p.parse_args()


def load_catalog(path: str) -> list[dict]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("ontologies", [])


def submit(client: httpx.Client, api_url: str, entry: dict) -> tuple[str, str]:
    """Submit one ontology. Returns (status, detail)."""
    body: dict = {}
    if "iri" in entry:
        body["iri"] = entry["iri"]
    elif "url" in entry:
        body["url"] = entry["url"]
    else:
        return "skip", "no iri or url"
    if entry.get("group"):
        body["groups"] = [entry["group"]]

    try:
        resp = client.post(f"{api_url}/api/v1/ontologies", json=body, timeout=30.0)
    except httpx.RequestError as exc:
        return "error", str(exc)

    if resp.status_code in (200, 201, 202):
        task_id = resp.json().get("task_id", "?")
        return "queued", f"task_id={task_id}"
    if resp.status_code == 409:
        return "exists", resp.json().get("detail", "already registered")
    return "error", f"HTTP {resp.status_code}: {resp.text[:120]}"


def main() -> None:
    args = parse_args()

    if not args.api_key and not args.dry_run:
        print("ERROR: --api-key or ONTOEXPLORER_API_KEY is required", file=sys.stderr)
        sys.exit(1)

    entries = load_catalog(args.catalog)

    if args.groups:
        entries = [e for e in entries if e.get("group") in args.groups]

    large_skipped = []
    if not args.include_large:
        large_skipped = [e for e in entries if e.get("large")]
        entries = [e for e in entries if not e.get("large")]

    if not entries and not large_skipped:
        print("No entries match the given filters.")
        return

    print(f"Catalog: {args.catalog}")
    print(f"Entries: {len(entries)}", end="")
    if large_skipped:
        print(f"  ({len(large_skipped)} large skipped — pass --include-large to include)", end="")
    print()
    if args.groups:
        print(f"Groups:  {', '.join(args.groups)}")
    if args.dry_run:
        print("Mode:    DRY RUN (nothing will be submitted)\n")
    else:
        print(f"API:     {args.api_url}\n")

    if large_skipped:
        print("Skipped (large — submit individually when ready):")
        for e in large_skipped:
            print(f"  - {e.get('label', e.get('iri', e.get('url', '?')))}  [{e.get('note', '')}]")
        print()

    if not entries:
        return

    counts = {"queued": 0, "exists": 0, "skip": 0, "error": 0}
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}

    with httpx.Client(headers=headers, follow_redirects=True) as client:
        for entry in entries:
            label = entry.get("label") or entry.get("iri") or entry.get("url", "?")
            ref = entry.get("iri") or entry.get("url", "")
            note = f"  [{entry['note']}]" if entry.get("note") else ""

            if args.dry_run:
                key = "iri" if "iri" in entry else "url"
                print(f"  WOULD SUBMIT  {label}{note}")
                print(f"    {key}: {ref}")
                counts["queued"] += 1
                continue

            status, detail = submit(client, args.api_url, entry)
            counts[status] += 1

            marker = {"queued": "✓", "exists": "~", "skip": "-", "error": "✗"}.get(status, "?")
            print(f"  [{marker}] {label}{note}")
            if status not in ("queued", "exists"):
                print(f"      → {detail}")

            if status == "queued":
                time.sleep(0.25)  # be gentle — each submission spawns a Celery task

    print()
    print(f"Results: {counts['queued']} queued, {counts['exists']} already registered, "
          f"{counts['skip']} skipped, {counts['error']} errors")

    if counts["error"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
