"""Classification result contract shared by every reasoner backend.

The legacy pure-Python rdflib CR1–CR6 EL classifier that used to live here was
retired — the EL role is covered by rustdl (EL saturation) and km, and DL by
rustdl/konclude. Only the result dataclass remains as the common return type.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClassificationResult:
    version_id: str
    classified_at: str
    class_count: int
    superclasses: dict[str, list[str]]          # all inferred (not asserted)
    subclasses: dict[str, list[str]]            # inverse of superclasses
    direct_superclasses: dict[str, list[str]]   # asserted only
    direct_subclasses: dict[str, list[str]]     # asserted only (inverted)
    unsatisfiable: list[str]
    proof_traces: dict[str, list[dict]]         # "sub|sup" -> steps
    duration_ms: float
