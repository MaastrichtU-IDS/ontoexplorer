"""rustdl backend (owl-dl-py PyO3 binding). Classify + native justify."""
from __future__ import annotations

import importlib.util
from registry import ReasonerInfo
from classifier import ClassificationResult


class RustdlBackend:
    info = ReasonerInfo(
        name="rustdl", profile="DL (SROIQ)",
        capabilities=frozenset({"classify", "consistency", "justify"}),
        available=importlib.util.find_spec("rustdl") is not None,
    )

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
        raise NotImplementedError  # Task 4

    def justify(self, ntriples, sub, sup, max_justifications):
        raise NotImplementedError  # Task 5
