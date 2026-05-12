"""Parse ontology bytes into an rdflib Graph, dispatching to py_horned_owl or rdflib."""

from io import BytesIO

import rdflib

from ontoexplorer.modules.ingestion.format_detect import OntologyFormat, format_to_rdflib_format, uses_horned_owl


def parse_ontology(data: bytes, fmt: OntologyFormat) -> rdflib.Graph:
    """
    Parse ontology bytes into an rdflib.Graph.

    Uses py_horned_owl for OWL/XML and Manchester Syntax (axiom-level access,
    better OWL 2 fidelity). Falls back to rdflib for all RDF surface syntaxes.

    Raises ValueError on parse failure.
    """
    if uses_horned_owl(fmt):
        return _parse_with_horned_owl(data, fmt)
    return _parse_with_rdflib(data, fmt)


def _parse_with_horned_owl(data: bytes, fmt: OntologyFormat) -> rdflib.Graph:
    """Parse OWL/XML or Manchester via py_horned_owl, then convert to rdflib Graph.
    Falls back to rdflib xml parser when py_horned_owl is not installed."""
    try:
        import py_horned_owl as pho
    except ImportError:
        # py_horned_owl not available — OWL/XML is valid RDF/XML, rdflib handles it
        return _parse_with_rdflib(data, OntologyFormat.RDF_XML)

    try:
        if fmt == OntologyFormat.OWL_XML:
            onto = pho.open_ontology_from_string(data.decode("utf-8"), pho.ParserOutput.OWLXMLParser)
        else:
            onto = pho.open_ontology_from_string(data.decode("utf-8"), pho.ParserOutput.ManchesterParser)
    except Exception as exc:
        raise ValueError(f"py_horned_owl failed to parse {fmt} ontology: {exc}") from exc

    # Serialise to RDF/XML and re-parse into rdflib for a uniform Graph interface
    try:
        rdf_bytes = pho.save_ontology_to_string(onto, pho.ParserOutput.RDFXMLParser).encode("utf-8")
    except Exception as exc:
        raise ValueError(f"py_horned_owl failed to serialise ontology to RDF/XML: {exc}") from exc

    g = rdflib.Graph()
    g.parse(BytesIO(rdf_bytes), format="xml")
    return g


def _parse_with_rdflib(data: bytes, fmt: OntologyFormat) -> rdflib.Graph:
    """Parse RDF surface syntaxes via rdflib."""
    rdflib_fmt = format_to_rdflib_format(fmt)
    g = rdflib.Graph()
    try:
        g.parse(BytesIO(data), format=rdflib_fmt)
    except Exception as exc:
        raise ValueError(f"rdflib failed to parse {fmt} ontology: {exc}") from exc
    return g
