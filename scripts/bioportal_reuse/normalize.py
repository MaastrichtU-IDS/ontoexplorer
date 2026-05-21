"""Apply bioregistry normalization to the preliminary work's CSV tables."""
from __future__ import annotations

import csv
from pathlib import Path

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


def normalize_upper_level_adoption(input_csv: Path, output_csv: Path) -> dict:
    """Reduces variant IRIs to canonical bioregistry prefixes.

    Preliminary work CSV schema (`upper_level_adoption.csv`):
        acronym, name, imports_iri, upper_level_detected, ...

    We re-key the `imports_iri` column through bioregistry. Variants that
    previously did not match (because the upstream code checked literal IRI
    equality) now collapse to the same prefix and DO match.
    """
    summary = {"rows_in": 0, "rows_out": 0, "newly_resolved": 0}
    seen_resolved: set[tuple[str, str]] = set()

    with input_csv.open() as f_in, output_csv.open("w") as f_out:
        reader = csv.DictReader(f_in)
        fieldnames = list(reader.fieldnames or []) + ["normalized_prefix", "resolved"]
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            summary["rows_in"] += 1
            iri = row.get("imports_iri", "")
            prefix, resolved = iri_to_prefix(iri)
            if resolved:
                key = (row["acronym"], prefix or "")
                if key not in seen_resolved:
                    seen_resolved.add(key)
                    summary["newly_resolved"] += 1
            row["normalized_prefix"] = prefix or ""
            row["resolved"] = "true" if resolved else "false"
            writer.writerow(row)
            summary["rows_out"] += 1

    return summary


def normalize_hub_ontologies(input_csv: Path, output_csv: Path) -> dict:
    """Collapse mapping-hub counts by bioregistry prefix (instead of raw IRI base)."""
    summary = {"rows_in": 0, "rows_out": 0}
    counts: dict[str, int] = {}

    with input_csv.open() as f_in:
        reader = csv.DictReader(f_in)
        for row in reader:
            summary["rows_in"] += 1
            iri = row.get("target_iri") or row.get("ontology_iri") or ""
            prefix, _ = iri_to_prefix(iri)
            key = prefix or iri
            n = int(row.get("mapping_count", row.get("count", 0)))
            counts[key] = counts.get(key, 0) + n

    with output_csv.open("w") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=["target_prefix", "mapping_count"])
        writer.writeheader()
        for prefix, count in sorted(counts.items(), key=lambda x: -x[1]):
            writer.writerow({"target_prefix": prefix, "mapping_count": count})
            summary["rows_out"] += 1

    return summary
