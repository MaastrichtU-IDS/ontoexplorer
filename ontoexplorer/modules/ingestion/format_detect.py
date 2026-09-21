"""Detect the serialisation format of an ontology file from its bytes and optional filename."""

from enum import StrEnum


class OntologyFormat(StrEnum):
    OWL_XML = "owl"          # OWL/XML  → loaded as RDF/XML (bulk-load fast path)
    RDF_XML = "rdf"          # RDF/XML  → rdflib / bulk-load
    TURTLE = "ttl"           # Turtle   → rdflib
    N_TRIPLES = "nt"         # N-Triples → rdflib
    N_QUADS = "nq"           # N-Quads  → rdflib
    JSON_LD = "jsonld"       # JSON-LD  → rdflib
    OBO = "obo"              # OBO flat file → horned-convert → N-Triples (rdflib fallback)
    MANCHESTER = "omn"       # Manchester Syntax → horned-convert → N-Triples
    OWL_FUNCTIONAL = "ofn"   # OWL 2 Functional Syntax → horned-convert → N-Triples
    TRIG = "trig"            # TriG → rdflib


# Map file extensions → format
_EXT_MAP: dict[str, OntologyFormat] = {
    ".owl": OntologyFormat.OWL_XML,
    ".rdf": OntologyFormat.RDF_XML,
    ".xml": OntologyFormat.RDF_XML,
    ".ttl": OntologyFormat.TURTLE,
    ".turtle": OntologyFormat.TURTLE,
    # N3 is a superset of Turtle; the vocabularies served this way in practice
    # (e.g. every LOV distribution) are Turtle-compatible, so parse them as
    # Turtle rather than reject them for lack of a dedicated N3 parser.
    ".n3": OntologyFormat.TURTLE,
    ".nt": OntologyFormat.N_TRIPLES,
    ".nq": OntologyFormat.N_QUADS,
    ".jsonld": OntologyFormat.JSON_LD,
    ".json": OntologyFormat.JSON_LD,
    ".obo": OntologyFormat.OBO,
    ".omn": OntologyFormat.MANCHESTER,
    ".ofn": OntologyFormat.OWL_FUNCTIONAL,
    ".trig": OntologyFormat.TRIG,
}

# Map MIME types → format
_MIME_MAP: dict[str, OntologyFormat] = {
    "application/rdf+xml": OntologyFormat.RDF_XML,
    "application/owl+xml": OntologyFormat.OWL_XML,
    "text/turtle": OntologyFormat.TURTLE,
    "application/x-turtle": OntologyFormat.TURTLE,
    # N3 parsed as Turtle (see _EXT_MAP). LOV serves every distribution as
    # text/n3, which otherwise matched nothing and fell through to byte
    # sniffing — failing whenever the file opened with a blank node or a bare
    # subject IRI instead of `@prefix`.
    "text/n3": OntologyFormat.TURTLE,
    "text/rdf+n3": OntologyFormat.TURTLE,
    "application/n3": OntologyFormat.TURTLE,
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
    # OWL Functional Syntax: `Prefix(:=<...>)` / `Ontology(<iri> ...)`. The
    # parenthesis distinguishes it from Turtle's `PREFIX`/`@prefix` and
    # Manchester's `Prefix:`.
    (b"Prefix(", OntologyFormat.OWL_FUNCTIONAL),
    (b"Ontology(", OntologyFormat.OWL_FUNCTIONAL),
    # Manchester Syntax: colon-terminated frame keywords. The colon is what
    # separates it from Functional's `Prefix(` / `Ontology(` above, and the
    # mixed case separates it from Turtle's `@prefix` / SPARQL-style `PREFIX`.
    # Listed after the Functional entries so `Prefix(` is matched first.
    (b"Prefix: ", OntologyFormat.MANCHESTER),
    (b"Ontology: ", OntologyFormat.MANCHESTER),
    (b"Class: ", OntologyFormat.MANCHESTER),
    (b"{", OntologyFormat.JSON_LD),
]


# Friendly spellings a caller may send for an explicit format, on top of the
# OntologyFormat values themselves. Keeps the labels the paste form used to
# submit ("turtle", "n-triples", …) working for existing API callers.
_FORMAT_ALIASES: dict[str, OntologyFormat] = {
    "turtle": OntologyFormat.TURTLE,
    "rdfxml": OntologyFormat.RDF_XML,
    "rdf-xml": OntologyFormat.RDF_XML,
    "rdf/xml": OntologyFormat.RDF_XML,
    "xml": OntologyFormat.RDF_XML,
    "owlxml": OntologyFormat.OWL_XML,
    "owl-xml": OntologyFormat.OWL_XML,
    "ntriples": OntologyFormat.N_TRIPLES,
    "n-triples": OntologyFormat.N_TRIPLES,
    "nquads": OntologyFormat.N_QUADS,
    "n-quads": OntologyFormat.N_QUADS,
    "json-ld": OntologyFormat.JSON_LD,
    "jsonld": OntologyFormat.JSON_LD,
    "json": OntologyFormat.JSON_LD,
    "manchester": OntologyFormat.MANCHESTER,
    "functional": OntologyFormat.OWL_FUNCTIONAL,
    "owl-functional": OntologyFormat.OWL_FUNCTIONAL,
}


def parse_format(value: str | None) -> OntologyFormat | None:
    """Resolve a caller-supplied format to an OntologyFormat, or None for auto-detect.

    Accepts an OntologyFormat value ("ttl"), a friendly alias ("turtle"), or a
    real MIME type ("text/turtle"). Raises ValueError on anything else: an
    unrecognised format used to be discarded in silence, which is how the paste
    form's selector could go unnoticed as dead.
    """
    if value is None:
        return None
    key = value.strip().lower()
    if not key:
        return None
    try:
        return OntologyFormat(key)
    except ValueError:
        pass
    if key in _FORMAT_ALIASES:
        return _FORMAT_ALIASES[key]
    if key in _MIME_MAP:
        return _MIME_MAP[key]
    accepted = ", ".join(sorted(f.value for f in OntologyFormat))
    raise ValueError(f"Unknown ontology format {value!r}. Accepted: {accepted}")


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
