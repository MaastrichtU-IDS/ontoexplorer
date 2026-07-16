"""Konclude backend (prebuilt binary subprocess). Classify + consistency only."""
from __future__ import annotations

import shutil
from registry import ReasonerInfo
from classifier import ClassificationResult

_KONCLUDE_BIN = shutil.which("Konclude")


class KoncludeBackend:
    info = ReasonerInfo(
        name="konclude", profile="OWL 2 (all profiles)",
        capabilities=frozenset({"classify", "consistency"}),
        available=_KONCLUDE_BIN is not None,
    )

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
        raise NotImplementedError  # Task 6

    def justify(self, ntriples, sub, sup, max_justifications):
        raise NotImplementedError("Konclude has no justification facility")
