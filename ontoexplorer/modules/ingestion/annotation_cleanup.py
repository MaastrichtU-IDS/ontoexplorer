"""Remove copied-in ("bled") ontology-header title/description annotations.

A host ontology authored by copying a template (SIO/SKOS/BFO/SWEET/…) frequently
keeps the template's dcterms:title / dcterms:description on its OWN ontology
subject. This deletes a host title/description value that is ALSO asserted on a
different NAMED subject in the same graph — i.e. the template's own declaration
rides along in the file, giving a twin to compare against.

Self-limiting: a value present only on the host subject (no foreign twin) is
never touched, so a legitimate title/description is never removed. Scoped to the
DC/DCTERMS title + description predicates — deliberately NOT rdfs:label /
rdfs:comment, which are generic and collide benignly across many subjects.
"""
from __future__ import annotations

from ontoexplorer.clients.oxigraph import graph_iri, sparql_update
from ontoexplorer.logging_config import get_logger

log = get_logger(__name__)

_BLED_PREDS = (
    "http://purl.org/dc/terms/title",
    "http://purl.org/dc/elements/1.1/title",
    "http://purl.org/dc/terms/description",
    "http://purl.org/dc/elements/1.1/description",
)


def build_strip_update(named_graph: str, host_iri: str) -> str:
    """The SPARQL UPDATE that removes the host's bled title/description triples."""
    vals = " ".join(f"<{p}>" for p in _BLED_PREDS)
    return (
        f"DELETE {{ GRAPH <{named_graph}> {{ <{host_iri}> ?p ?t }} }} "
        f"WHERE {{ GRAPH <{named_graph}> {{ "
        f"VALUES ?p {{ {vals} }} "
        f"<{host_iri}> ?p ?t . "
        f'?s ?p ?t . FILTER(isIRI(?s) && STR(?s) != "{host_iri}") }} }}'
    )


def strip_bled_annotations(ontology_id: str, version_id: str, host_iri: str | None) -> None:
    """Delete bled title/description triples from the host subject. Best-effort:
    a failure never blocks ingestion. Needs the import closure already loaded so a
    foreign twin is present to compare against. No-op for a missing/blank host."""
    if not host_iri or not host_iri.startswith(("http://", "https://", "urn:")):
        return
    try:
        sparql_update(build_strip_update(graph_iri(ontology_id, version_id), host_iri))
    except Exception as exc:
        log.warning("strip_bled_annotations_failed", ontology_id=ontology_id, error=str(exc)[:200])
