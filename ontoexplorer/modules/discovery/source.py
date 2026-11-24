"""Interface for catalogue discovery sources."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ontoexplorer.modules.discovery.models import Candidate


@runtime_checkable
class DiscoverySource(Protocol):
    """A catalogue that can be enumerated for ingestion candidates."""

    name: str  # for provenance / logging

    async def discover(self, *, limit: int) -> list[Candidate]:
        """Return up to ``limit`` candidates from this source."""
        ...
