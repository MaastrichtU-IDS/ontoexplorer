"""Write FAIR metadata (DCAT + VoID + PROV-O) to QLever via SPARQL Update."""

import logging

import rdflib

from ontoexplorer.clients.qlever import delete_graph, insert_turtle

logger = logging.getLogger(__name__)

# Named graph IRIs in QLever
META_GRAPH = "urn:meta"
PROV_GRAPH = "urn:prov"


def _graph_iri(ontology_id: str, version_id: str) -> str:
    return f"urn:ontology:{ontology_id}:{version_id}:meta"


async def write_version_metadata(
    ontology_id: str,
    version_id: str,
    dcat_graph: rdflib.Graph,
    prov_graph: rdflib.Graph,
) -> None:
    """
    Insert DCAT + VoID metadata and PROV-O activity into QLever.

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
    logger.info("Wrote DCAT metadata for version %s to QLever graph <%s>", version_id, version_graph_iri)

    # Also insert into the catalog graph (for cross-ontology queries)
    await insert_turtle(dcat_ttl, graph_iri=META_GRAPH)

    # Insert provenance
    await insert_turtle(prov_ttl, graph_iri=PROV_GRAPH)
    logger.info("Wrote PROV-O activity for version %s to QLever", version_id)


async def delete_version_metadata(ontology_id: str, version_id: str) -> None:
    """Remove all QLever metadata for a specific version (called on deprecation)."""
    version_graph_iri = _graph_iri(ontology_id, version_id)
    await delete_graph(version_graph_iri)
    logger.info("Deleted QLever metadata for version %s", version_id)
