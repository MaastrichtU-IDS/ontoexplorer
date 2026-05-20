"""Heuristic MIREOT candidate estimator for BioPortal scale.

Without ontology bodies, the best we can do is: a term in ontology H
points (via mapping table) to ontology X, but H does not declare
owl:imports X. That's a MIREOT *candidate* — upper bound only.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ontoexplorer.modules.reuse.bioregistry import iri_to_prefix


def estimate_mireot_candidates(
    mappings_csv: Path,
    imports_csv: Path,
    output_csv: Path,
) -> dict:
    """Cross-reference mapping targets vs declared imports per ontology."""
    declared: dict[str, set[str]] = {}
    with imports_csv.open() as f:
        for row in csv.DictReader(f):
            acronym = row.get("acronym", "")
            iri = row.get("imports_iri", "")
            prefix, _ = iri_to_prefix(iri)
            if prefix:
                declared.setdefault(acronym, set()).add(prefix)

    summary = {"rows_in": 0, "candidates": 0, "ontologies_with_candidates": 0}
    onts_with_candidates: set[str] = set()

    with mappings_csv.open() as f_in, output_csv.open("w") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=[
            "acronym", "target_prefix", "mapping_count", "is_candidate",
        ])
        writer.writeheader()
        # Group by (acronym, target_prefix)
        buckets: dict[tuple[str, str], int] = {}
        for row in csv.DictReader(f_in):
            summary["rows_in"] += 1
            acronym = row.get("acronym", "")
            target_iri = row.get("target_iri") or row.get("ontology_iri") or ""
            prefix, _ = iri_to_prefix(target_iri)
            if not prefix:
                continue
            buckets[(acronym, prefix)] = buckets.get((acronym, prefix), 0) + 1

        for (acronym, prefix), n in buckets.items():
            is_candidate = prefix not in declared.get(acronym, set())
            if is_candidate:
                summary["candidates"] += 1
                onts_with_candidates.add(acronym)
            writer.writerow({
                "acronym": acronym,
                "target_prefix": prefix,
                "mapping_count": n,
                "is_candidate": "true" if is_candidate else "false",
            })

    summary["ontologies_with_candidates"] = len(onts_with_candidates)
    return summary
