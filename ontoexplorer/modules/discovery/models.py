"""Models for ontology candidates discovered in external catalogues."""

from __future__ import annotations

from pydantic import BaseModel


class Candidate(BaseModel):
    """One ontology discovered in a catalogue, not yet ingested."""

    canonical_iri: str
    title: str
    license: str | None = None  # catalogue-declared, raw
    download_url: str | None = None
    landing_url: str | None = None
    source_catalogue_id: str
    source_catalogue_label: str

    def ingest_target(self) -> tuple[str, str]:
        """Return ``(kind, value)`` to ingest: the download URL if known, else the IRI."""
        if self.download_url:
            return ("url", self.download_url)
        return ("iri", self.canonical_iri)
