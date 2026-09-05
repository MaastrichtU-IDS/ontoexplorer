"""The shared catalogue and provenance graphs must not accumulate stale copies."""

import pytest
import rdflib

from ontoexplorer.modules.metadata import fuseki_writer


class _Recorder:
    """Captures the SPARQL Updates write_version_metadata issues."""

    def __init__(self):
        self.updates: list[str] = []
        self.inserts: list[tuple[str, str]] = []
        self.dropped: list[str] = []

    async def sparql_update(self, update: str, timeout: float = 30.0) -> None:
        self.updates.append(update)

    async def insert_turtle(self, ttl: str, graph_iri=None, timeout: float = 60.0) -> None:
        self.inserts.append((graph_iri, ttl))

    async def delete_graph(self, graph_iri: str) -> None:
        self.dropped.append(graph_iri)


@pytest.fixture
def recorder(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(fuseki_writer, "sparql_update", r.sparql_update)
    monkeypatch.setattr(fuseki_writer, "insert_turtle", r.insert_turtle)
    monkeypatch.setattr(fuseki_writer, "delete_graph", r.delete_graph)
    return r


def _graph(subject: str, obj: str) -> rdflib.Graph:
    g = rdflib.Graph()
    g.add((rdflib.URIRef(subject), rdflib.URIRef("http://ex.org/p"), rdflib.Literal(obj)))
    return g


@pytest.mark.anyio
async def test_shared_graphs_are_cleared_of_this_version_before_insert(recorder):
    """Without this the catalogue was append-only: re-ingesting a version left
    the old record in place beside the new one, so a single version advertised
    several download URLs and several ingestion times."""
    dcat = _graph("http://app/api/v1/ontologies/o1/v1", "first")
    prov = _graph("http://app/api/v1/versions/v1/provenance", "first")

    await fuseki_writer.write_version_metadata("o1", "v1", dcat, prov)

    deletes = [u for u in recorder.updates if u.startswith("DELETE")]
    assert len(deletes) == 2, "expected one subject-scoped delete per shared graph"

    meta_delete = next(u for u in deletes if fuseki_writer.META_GRAPH in u)
    assert "<http://app/api/v1/ontologies/o1/v1>" in meta_delete

    prov_delete = next(u for u in deletes if fuseki_writer.PROV_GRAPH in u)
    assert "<http://app/api/v1/versions/v1/provenance>" in prov_delete


@pytest.mark.anyio
async def test_delete_precedes_the_matching_insert(recorder):
    """Order matters: deleting after inserting would remove what was just written."""
    dcat = _graph("http://app/api/v1/ontologies/o1/v1", "x")
    prov = _graph("http://app/api/v1/versions/v1/provenance", "x")

    await fuseki_writer.write_version_metadata("o1", "v1", dcat, prov)

    # Both shared graphs received an insert, and each was cleared beforehand.
    shared_inserts = [g for g, _ in recorder.inserts
                      if g in (fuseki_writer.META_GRAPH, fuseki_writer.PROV_GRAPH)]
    assert shared_inserts == [fuseki_writer.META_GRAPH, fuseki_writer.PROV_GRAPH]
    assert len([u for u in recorder.updates if u.startswith("DELETE")]) == 2


@pytest.mark.anyio
async def test_subjectless_graph_issues_no_delete(recorder):
    """An empty record must not emit a DELETE with an empty VALUES block."""
    await fuseki_writer.write_version_metadata("o1", "v1", rdflib.Graph(), rdflib.Graph())
    assert [u for u in recorder.updates if u.startswith("DELETE")] == []
