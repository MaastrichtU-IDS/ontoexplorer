"""Write FAIR metadata (DCAT + VoID + PROV-O) to Fuseki via SPARQL Update."""

import logging

import rdflib

from ontoexplorer.clients.fuseki import delete_graph, insert_turtle, sparql_update
from ontoexplorer.clients.sparql_iri import is_safe_iri
from ontoexplorer.config import get_settings
from ontoexplorer.modules.metadata.dcat import dcat_subject_iris
from ontoexplorer.modules.metadata.prov import prov_subject_iris

logger = logging.getLogger(__name__)

# Named graph IRIs in Fuseki
META_GRAPH = "urn:meta"
PROV_GRAPH = "urn:prov"


def _graph_iri(ontology_id: str, version_id: str) -> str:
    return f"urn:ontology:{ontology_id}:{version_id}:meta"


# Characters that cannot appear unescaped inside a SPARQL <IRIREF>. Anything
# carrying one cannot be interpolated into a query safely.
_IRIREF_FORBIDDEN = frozenset('<>"{}|^`\\') | frozenset(chr(c) for c in range(0x21))


def _version_scoped_subjects(g: rdflib.Graph, app_base_url: str) -> list[str]:
    """Subjects of `g` that this app minted for this version.

    Two things are deliberately excluded.

    Foreign subjects: `build_ingestion_activity` makes the *submitted source
    URL* a subject, and that value is user-supplied. Interpolating it into a
    SPARQL Update is an injection — a URL containing `>` closes the IRIREF and
    the rest of the string is executed. It is also shared state: two versions
    ingested from one URL would delete each other's triple.

    Anything holding an IRIREF-illegal character, as defence in depth: rdflib
    warns about such values but still builds the URIRef, so validity upstream
    cannot be assumed.
    """
    prefix = app_base_url.rstrip("/") + "/"
    keep: list[str] = []
    for subject in set(g.subjects()):
        if not isinstance(subject, rdflib.URIRef):
            continue
        iri = str(subject)
        if not iri.startswith(prefix):
            continue
        if any(ch in _IRIREF_FORBIDDEN for ch in iri):
            logger.warning("skipping subject with illegal IRI characters: %r", iri[:120])
            continue
        keep.append(iri)
    return sorted(keep)


async def _drop_subjects(graph_iri: str, g: rdflib.Graph, app_base_url: str) -> None:
    """Remove everything the shared graph already holds about g's own subjects.

    The catalogue and provenance graphs accumulate across versions, so they
    cannot simply be dropped. Without this they were append-only: re-ingesting
    or re-reasoning a version added a second copy of every triple whose object
    had changed, so one version could end up advertising several download URLs
    and several ingestion timestamps.
    """
    subjects = _version_scoped_subjects(g, app_base_url)
    if not subjects:
        return
    values = " ".join(f"<{s}>" for s in subjects)
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
    app_base_url = str(get_settings().app_url)
    await _drop_subjects(META_GRAPH, dcat_graph, app_base_url)
    await insert_turtle(dcat_ttl, graph_iri=META_GRAPH)

    # Insert provenance, likewise replacing this version's previous activity.
    await _drop_subjects(PROV_GRAPH, prov_graph, app_base_url)
    await insert_turtle(prov_ttl, graph_iri=PROV_GRAPH)
    logger.info("Wrote PROV-O activity for version %s to Fuseki", version_id)


async def _drop_subject_iris(graph_iri: str, subjects: list[str]) -> None:
    """Delete every triple in `graph_iri` whose subject is one of `subjects`."""
    safe = [s for s in subjects if is_safe_iri(s)]
    if not safe:
        return
    values = " ".join(f"<{s}>" for s in sorted(safe))
    await sparql_update(
        f"DELETE {{ GRAPH <{graph_iri}> {{ ?s ?p ?o }} }} "
        f"WHERE {{ GRAPH <{graph_iri}> {{ VALUES ?s {{ {values} }} ?s ?p ?o }} }}"
    )


async def delete_version_metadata(ontology_id: str, version_id: str) -> None:
    """Remove every trace of one version from Fuseki.

    Clears the per-version graph *and* the version's triples in the shared
    catalogue and provenance graphs. An earlier version of this function cleared
    only the per-version graph, which left a deleted ontology still listed in
    cross-ontology queries; it was unreferenced, so nothing surfaced that.

    The subject IRIs come from the builders that minted them, so deletion cannot
    drift from creation.
    """
    app_base_url = str(get_settings().app_url).rstrip("/")

    await delete_graph(_graph_iri(ontology_id, version_id))
    await _drop_subject_iris(META_GRAPH, dcat_subject_iris(ontology_id, version_id, app_base_url))
    await _drop_subject_iris(PROV_GRAPH, prov_subject_iris(version_id, app_base_url))

    logger.info("Deleted Fuseki metadata for version %s", version_id)
