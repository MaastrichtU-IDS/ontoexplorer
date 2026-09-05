"""Write FAIR metadata (DCAT + VoID + PROV-O) to Fuseki via SPARQL Update."""

import logging

import rdflib

from ontoexplorer.clients.fuseki import delete_graph, insert_turtle, sparql_update

logger = logging.getLogger(__name__)

# Named graph IRIs in Fuseki
META_GRAPH = "urn:meta"
PROV_GRAPH = "urn:prov"


def _graph_iri(ontology_id: str, version_id: str) -> str:
    return f"urn:ontology:{ontology_id}:{version_id}:meta"


async def _drop_subjects(graph_iri: str, g: rdflib.Graph) -> None:
    """Remove everything the shared graph already holds about g's subjects.

    The catalogue and provenance graphs accumulate across versions, so they
    cannot simply be dropped. Without this they were append-only: re-ingesting
    or re-reasoning a version added a second copy of every triple whose object
    had changed, so one version could end up advertising several download URLs
    and several ingestion timestamps.

    Deleting by subject is safe because every subject these records introduce is
    version-scoped -- the DCAT dataset and its distribution, the PROV activity
    and its entity. The ontology IRI they reference appears only as an object,
    so no other version's triples are in range.
    """
    subjects = {s for s in set(g.subjects()) if isinstance(s, rdflib.URIRef)}
    if not subjects:
        return
    values = " ".join(f"<{s}>" for s in sorted(subjects))
    await sparql_update(
        f"DELETE {{ GRAPH <{graph_iri}> {{ ?s ?p ?o }} }} "
        f"WHERE {{ GRAPH <{graph_iri}> {{ VALUES ?s {{ {values} }} ?s ?p ?o }} }}"
    )


async def write_version_metadata(
    ontology_id: str,
    version_id: str,
    dcat_graph: rdflib.Graph,
    prov_graph: rdflib.Graph,
) -> None:
    """
    Insert DCAT + VoID metadata and PROV-O activity into Fuseki.

    DCAT metadata goes into the per-version named graph and the catalog graph.
    PROV activity goes into the provenance graph.
    """
    version_graph_iri = _graph_iri(ontology_id, version_id)

    # Serialise both graphs to Turtle
    dcat_ttl = dcat_graph.serialize(format="turtle")
    prov_ttl = prov_graph.serialize(format="turtle")

    # Clear any existing metadata for this version (idempotent on re-ingest)
    await delete_graph(version_graph_iri)

    # Write per-version metadata
    await insert_turtle(dcat_ttl, graph_iri=version_graph_iri)
    logger.info("Wrote DCAT metadata for version %s to Fuseki graph <%s>", version_id, version_graph_iri)

    # Also insert into the catalog graph (for cross-ontology queries), replacing
    # any earlier record for this version rather than stacking a second one.
    await _drop_subjects(META_GRAPH, dcat_graph)
    await insert_turtle(dcat_ttl, graph_iri=META_GRAPH)

    # Insert provenance, likewise replacing this version's previous activity.
    await _drop_subjects(PROV_GRAPH, prov_graph)
    await insert_turtle(prov_ttl, graph_iri=PROV_GRAPH)
    logger.info("Wrote PROV-O activity for version %s to Fuseki", version_id)
