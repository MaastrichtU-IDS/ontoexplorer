"""Detect the lossy OWL/XML-structural-flatten ingest form (#311).

Some sources — notably several LOV ``.n3`` dumps (gci, dfc, dfc-p, dfc-t,
IIoT) — serve an ontology as its OWL/XML *structural* syntax mechanically
flattened into RDF triples: every grammar production becomes a blank node typed
``owl:Declaration`` / ``owl:AbbreviatedIRI`` / ``owl:IRI`` (and
``owl:AnnotationAssertion`` etc.), and the entity IRIs and labels are NOT present
as RDF terms — they live only inside the ``owl:IRI`` / ``owl:AbbreviatedIRI``
wrapper nodes, which carry no usable value. The graph therefore has **zero
IRI-typed subjects**, so ``build_index`` (even the #322 ABox-only domain-class
fallback) extracts nothing and the version would reach ``ready`` with 0
searchable terms — silently invisible in the catalogue.

This form is unrecoverable by any converter or SPARQL rewrite: the names simply
aren't in the data. The right response is therefore to **refuse the ingest** with
a clear reason that points at re-fetching from a source serving real RDF or
native OWL/XML, rather than persist a 0-entity "ready" version. See #311 / #229.

The detector is deliberately conservative — it fires only when BOTH hold:

1. the structural-artifact signature is present (>=1 subject typed by one of the
   OWL/XML grammar classes, which have no legitimate RDF meaning), AND
2. the graph has **no** IRI-typed subject of any kind — i.e. nothing that
   ``build_index`` or its fallback could ever extract.

Condition 2 is the safety gate: a vocabulary that carries real entities (or even
a bare ``owl:Ontology`` IRI, as a legitimately metadata-only wrapper does) is
never blocked. Only the genuinely-empty-and-structurally-lossy case is refused.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


class LossyOwlXmlIngest(Exception):
    """Terminal: the ingested graph is an OWL/XML structural serialization
    flattened into RDF with no recoverable entity IRIs. Not transient — a retry
    re-rejects — so callers treat it like OntologyAccessDenied (fail, don't retry)."""


# OWL/XML grammar productions that have NO mapping to RDF semantics. Their
# appearance as an rdf:type object means an OWL/XML document tree was serialized
# as triples verbatim (the lossy flatten), never a hand- or tool-authored RDF
# ontology.
_STRUCTURAL_TYPES = (
    "http://www.w3.org/2002/07/owl#Declaration",
    "http://www.w3.org/2002/07/owl#AbbreviatedIRI",
    "http://www.w3.org/2002/07/owl#IRI",
)


def _as_int(term) -> int:
    """Read a COUNT(...) binding as an int, whether it is a pyoxigraph Literal
    (``.value``) or a plain string/number."""
    value = getattr(term, "value", None)
    if value is None:
        value = term
    return int(str(value))


def _count(query, sparql: str) -> int:
    rows = list(query(sparql))
    if not rows:
        return 0
    return _as_int(rows[0]["n"])


def lossy_owlxml_report(graph: str, *, query=None) -> dict | None:
    """Return a diagnostics dict when ``graph`` holds the lossy OWL/XML-flatten
    form, else ``None``.

    ``query`` is injected for testing; by default the live Oxigraph client is
    used. Best-effort: any query error returns ``None`` (never block an ingest on
    a detector failure).
    """
    if query is None:
        from ontoexplorer.clients.oxigraph import sparql_query as query

    values = " ".join(f"<{t}>" for t in _STRUCTURAL_TYPES)
    try:
        structural = _count(query, f"""
            SELECT (COUNT(DISTINCT ?s) AS ?n) FROM <{graph}> WHERE {{
                VALUES ?t {{ {values} }}
                ?s a ?t .
            }}
        """)
        if structural <= 0:
            return None  # fast path: no OWL/XML-structural artifacts → fine
        entities = _count(query, f"""
            SELECT (COUNT(DISTINCT ?s) AS ?n) FROM <{graph}> WHERE {{
                ?s a ?t .
                FILTER(isIRI(?s) && isIRI(?t))
            }}
        """)
    except Exception as exc:
        # Fail open: never block an ingest on a detector/store error.
        log.warning("lossy_owlxml_detect_failed", graph=graph, error=str(exc))
        return None

    if entities > 0:
        return None  # has real IRI-typed entities → usable, don't block

    return {
        "structural_count": structural,
        "entity_count": entities,
        "message": (
            "Ingest refused: this source is an OWL/XML structural serialization "
            "flattened into RDF "
            f"({structural} owl:Declaration/owl:IRI/owl:AbbreviatedIRI wrapper "
            "nodes, 0 IRI-typed entities). The entity IRIs and labels are not "
            "present as RDF terms, so it would index to zero searchable terms and "
            "no converter can recover them. Re-fetch a valid RDF/XML or Turtle "
            "serialization of the ontology (e.g. convert the original with ROBOT "
            "or Protégé) instead of this flattened dump."
        ),
    }
