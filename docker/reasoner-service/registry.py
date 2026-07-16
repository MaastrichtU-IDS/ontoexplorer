"""Capability-aware reasoner registry for reasoner-service.

Each reasoner is a Backend: it classifies N-Triples into a ClassificationResult
and (optionally) computes justifications. Capabilities let the HTTP layer and
the app decide what a given reasoner can do (e.g. Konclude cannot justify).
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Literal, Protocol

import rdflib

from classifier import ClassificationResult

Capability = Literal["classify", "consistency", "justify", "diagnose", "repair"]


@dataclass(frozen=True)
class ReasonerInfo:
    name: str
    profile: str
    capabilities: frozenset[str]
    available: bool


class Backend(Protocol):
    info: ReasonerInfo

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult: ...

    def justify(self, ntriples: str, sub: str, sup: str,
                max_justifications: int) -> tuple[list[list[str]], str]: ...


def _import_ok(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


# ── whelk ──────────────────────────────────────────────────────────────────
class _WhelkBackend:
    info = ReasonerInfo(
        name="whelk", profile="EL",
        capabilities=frozenset({"classify", "consistency", "justify"}),
        available=_import_ok("pywhelk"),
    )

    def classify_ntriples(self, ntriples, version_id):
        from whelk_classifier import classify_ntriples
        return classify_ntriples(ntriples, version_id)

    def justify(self, ntriples, sub, sup, max_justifications):
        from justification import compute_justifications
        g = rdflib.Graph()
        g.parse(io.StringIO(ntriples), format="nt")
        # compute_justifications has an entry guard that checks the PASSED-IN
        # result's unsatisfiable/superclasses/direct_superclasses to confirm
        # the inference actually holds before doing any work — an empty
        # result always fails that guard and silently returns []. So we must
        # classify first and pass the REAL result, mirroring the main.py
        # /classify/{version_id}/justification call site (result = the
        # cached classification, g = the input graph).
        result = self.classify_ntriples(ntriples, "_justify")
        sets = compute_justifications(g, result, sub, sup, max_justifications)
        return sets, "ntriples"


# ── rdflib (legacy) ──────────────────────────────────────────────────────────
class _RdflibBackend:
    info = ReasonerInfo(
        name="rdflib", profile="EL (legacy)",
        capabilities=frozenset({"classify", "consistency"}),
        available=True,
    )

    def classify_ntriples(self, ntriples, version_id):
        from classifier import classify
        g = rdflib.Graph()
        g.parse(io.StringIO(ntriples), format="nt")
        return classify(g, version_id)

    def justify(self, ntriples, sub, sup, max_justifications):
        raise NotImplementedError("rdflib backend does not expose justifications in SP1")


# Backends registered lazily so importing rustdl/konclude modules (which may be
# absent) does not break the registry import.
def _build_registry() -> dict[str, Backend]:
    reg: dict[str, Backend] = {"whelk": _WhelkBackend(), "rdflib": _RdflibBackend()}
    from rustdl_backend import RustdlBackend
    from konclude_backend import KoncludeBackend
    reg["rustdl"] = RustdlBackend()
    reg["konclude"] = KoncludeBackend()
    return reg


_REGISTRY: dict[str, Backend] | None = None


def _registry() -> dict[str, Backend]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def get_backend(name: str) -> Backend:
    return _registry()[name]


def list_reasoners() -> list[ReasonerInfo]:
    return [b.info for b in _registry().values()]


def default_reasoner() -> str:
    return os.getenv("DEFAULT_REASONER", "whelk")
