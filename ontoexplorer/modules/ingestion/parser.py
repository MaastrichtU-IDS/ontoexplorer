"""Parse ontology bytes into an rdflib Graph via rdflib.

OWL/XML is accepted as RDF/XML (it is loaded on the bulk-load fast path in the
pipeline, not here). Manchester Syntax is detected but not supported: no parser
in the stack reads it (rdflib has no Manchester plugin and the horned-owl
binding has no Manchester parser), so it is rejected with a clear error.
"""

from io import BytesIO

import rdflib

from ontoexplorer.modules.ingestion.format_detect import OntologyFormat, format_to_rdflib_format


def parse_ontology(data: bytes, fmt: OntologyFormat) -> rdflib.Graph:
    """
    Parse ontology bytes into an rdflib.Graph.

    All supported surface syntaxes are parsed by rdflib. Manchester Syntax is
    rejected: no parser in the dependency stack can read it.

    Raises ValueError on parse failure or for unsupported formats.
    """
    if fmt == OntologyFormat.MANCHESTER:
        raise ValueError(
            "Manchester Syntax (.omn) is not supported. Please convert the "
            "ontology to RDF/XML, Turtle, OWL/XML, or OWL Functional Syntax "
            "(e.g. with ROBOT: `robot convert`) and re-submit."
        )

    rdflib_fmt = format_to_rdflib_format(fmt)
    g = rdflib.Graph()
    try:
        g.parse(BytesIO(data), format=rdflib_fmt)
    except Exception as exc:
        raise ValueError(f"rdflib failed to parse {fmt} ontology: {exc}") from exc
    return g
