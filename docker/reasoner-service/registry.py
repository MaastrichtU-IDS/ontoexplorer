"""Capability-aware reasoner registry for reasoner-service.

Each reasoner is a Backend: it classifies N-Triples into a ClassificationResult
and (optionally) computes justifications. Capabilities let the HTTP layer and
the app decide what a given reasoner can do (e.g. Konclude cannot justify).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Protocol

from classifier import ClassificationResult

Capability = Literal["classify", "consistency", "justify", "diagnose", "repair"]


@dataclass(frozen=True)
class ReasonerInfo:
    name: str
    profile: str
    capabilities: frozenset[str]
    available: bool
    # Version of the underlying reasoner (e.g. rustdl "0.4.28", km "v0.2.21",
    # Konclude "v0.7.0-1138"). Empty when it can't be determined. Surfaced in the
    # UI (add-ontology advanced options, admin reasoners tab, ontology metadata).
    version: str = ""
    # Tunable parameters this backend accepts, as a tuple of specs the admin UI
    # renders into typed, validated form fields. Each spec is a dict:
    #   {key, type: 'bool'|'int'|'enum', default, label, help,
    #    min?/max? (int), choices? (enum)}. Empty tuple = no tunable params.
    param_schema: tuple[dict, ...] = ()


class Backend(Protocol):
    info: ReasonerInfo

    def classify_ntriples(
        self, ntriples: str, version_id: str, params: dict | None = None
    ) -> ClassificationResult: ...

    def justify(self, ntriples: str, sub: str, sup: str,
                max_justifications: int, version_id: str | None = None
                ) -> tuple[list[list[str]], str]: ...


def _import_ok(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


# whelk removed: py-whelk segfaults in reasoner.inferred_axioms() on this amd64
# build (never produced a classification here), so it is no longer registered.
# The EL role is covered by rustdl in saturation_only mode.
#
# rdflib (legacy) removed: the pure-Python CR1–CR6 EL classifier is retired —
# rustdl (EL saturation) + km cover EL, rustdl/konclude cover DL. It was slow,
# unmaintained, and never the default.


# Backends registered lazily so importing rustdl/konclude modules (which may be
# absent) does not break the registry import.
def _build_registry() -> dict[str, Backend]:
    reg: dict[str, Backend] = {}
    from rustdl_backend import RustdlBackend
    from konclude_backend import KoncludeBackend
    from km_backend import KmBackend
    reg["rustdl"] = RustdlBackend()
    reg["konclude"] = KoncludeBackend()
    reg["km"] = KmBackend()
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
    return os.getenv("DEFAULT_REASONER", "rustdl")
