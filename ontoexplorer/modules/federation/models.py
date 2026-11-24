"""Models for federated MOD-API catalogue results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SourceRef(BaseModel):
    """Attribution of a remote artefact to the peer that served it."""

    id: str
    label: str


class ArtefactRow(BaseModel):
    """One remote semantic artefact, normalised from a peer's MOD-API response."""

    iri: str
    acronym: str
    title: str
    description: str = ""
    publisher: str | None = None
    license: str | None = None
    homepage: str | None = None
    source_landing_url: str
    source: SourceRef
    remote: Literal[True] = True


class CatalogueStatus(BaseModel):
    """Per-peer outcome of a federated query (for the UI status strip)."""

    id: str
    label: str
    status: str  # e.g. "ok" | "timeout" | "error" | "unavailable"
    count: int = 0
    took_ms: int = 0
