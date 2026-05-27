"""Detect the serialisation format of an ontology file from its bytes and optional filename."""

from enum import StrEnum


class OntologyFormat(StrEnum):
    OWL_XML = "owl"          # OWL/XML  → loaded as RDF/XML (bulk-load fast path)
    RDF_XML = "rdf"          # RDF/XML  → rdflib / bulk-load
    TURTLE = "ttl"           # Turtle   → rdflib
    N_TRIPLES = "nt"         # N-Triples → rdflib
    N_QUADS = "nq"           # N-Quads  → rdflib
    JSON_LD = "jsonld"       # JSON-LD  → rdflib
    OBO = "obo"              # OBO flat file → rdflib (via plugin)
    MANCHESTER = "omn"       # Manchester Syntax → detected but unsupported (no parser)
    TRIG = "trig"            # TriG → rdflib


# Map file extensions → format
_EXT_MAP: dict[str, OntologyFormat] = {
    ".owl": OntologyFormat.OWL_XML,
    ".rdf": OntologyFormat.RDF_XML,
    ".xml": OntologyFormat.RDF_XML,
    ".ttl": OntologyFormat.TURTLE,
    ".turtle": OntologyFormat.TURTLE,
    ".nt": OntologyFormat.N_TRIPLES,
    ".nq": OntologyFormat.N_QUADS,
    ".jsonld": OntologyFormat.JSON_LD,
    ".json": OntologyFormat.JSON_LD,
    ".obo": OntologyFormat.OBO,
    ".omn": OntologyFormat.MANCHESTER,
    ".trig": OntologyFormat.TRIG,
}

# Map MIME types → format
_MIME_MAP: dict[str, OntologyFormat] = {
    "application/rdf+xml": OntologyFormat.RDF_XML,
    "application/owl+xml": OntologyFormat.OWL_XML,
    "text/turtle": OntologyFormat.TURTLE,
    "application/x-turtle": OntologyFormat.TURTLE,
    "application/n-triples": OntologyFormat.N_TRIPLES,
    "application/n-quads": OntologyFormat.N_QUADS,
    "application/ld+json": OntologyFormat.JSON_LD,
    # text/plain intentionally omitted — too ambiguous (GitHub serves OWL/XML as text/plain)
    # OBO detection falls through to byte sniffing (format-version: signature)
    "application/trig": OntologyFormat.TRIG,
    "application/x-manchester": OntologyFormat.MANCHESTER,
}

# Byte signatures for content sniffing
_SIGNATURES: list[tuple[bytes, OntologyFormat]] = [
    (b"<?xml", OntologyFormat.RDF_XML),   # disambiguate OWL/XML vs RDF/XML by content below
    (b"@prefix", OntologyFormat.TURTLE),
    (b"@base", OntologyFormat.TURTLE),
    (b"PREFIX", OntologyFormat.TURTLE),
    (b"format-version:", OntologyFormat.OBO),
    (b"{", OntologyFormat.JSON_LD),
]


def _is_owl_xml(data: bytes) -> bool:
    """Distinguish OWL/XML from generic RDF/XML by looking for the Ontology element."""
    snippet = data[:4096]
    return b"Ontology" in snippet and b"owl" in snippet


def detect_format(
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> OntologyFormat:
    """
    Detect ontology serialisation format.

    Priority: content_type > filename extension > byte sniffing.
    Raises ValueError if format cannot be determined.
    """
    # 1. Content-Type header (strip parameters like ;charset=utf-8)
    if content_type:
        mime = content_type.split(";")[0].strip().lower()
        if mime in _MIME_MAP:
            fmt = _MIME_MAP[mime]
            # Refine: if RDF/XML bytes look like OWL/XML, promote
            if fmt == OntologyFormat.RDF_XML and _is_owl_xml(data):
                return OntologyFormat.OWL_XML
            return fmt

    # 2. File extension
    if filename:
        import os
        ext = os.path.splitext(filename)[1].lower()
        if ext in _EXT_MAP:
            fmt = _EXT_MAP[ext]
            if fmt == OntologyFormat.RDF_XML and _is_owl_xml(data):
                return OntologyFormat.OWL_XML
            return fmt

    # 3. Byte sniffing on first 512 bytes
    head = data[:512].lstrip()
    for sig, fmt in _SIGNATURES:
        if head.startswith(sig):
            if fmt == OntologyFormat.RDF_XML and _is_owl_xml(data):
                return OntologyFormat.OWL_XML
            return fmt

    raise ValueError("Cannot determine ontology format from content, filename, or content-type")


def format_to_rdflib_format(fmt: OntologyFormat) -> str:
    """Map OntologyFormat to rdflib parse format string."""
    return {
        OntologyFormat.RDF_XML: "xml",
        OntologyFormat.OWL_XML: "xml",
        OntologyFormat.TURTLE: "turtle",
        OntologyFormat.N_TRIPLES: "nt",
        OntologyFormat.N_QUADS: "nquads",
        OntologyFormat.JSON_LD: "json-ld",
        OntologyFormat.OBO: "obo",
        OntologyFormat.TRIG: "trig",
    }[fmt]
