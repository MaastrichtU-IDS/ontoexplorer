"""The embedded metadata store (pyoxigraph) that replaced Fuseki.

Round-trips the operations the metadata writer relies on: insert_turtle (append
into a named graph), sparql_update (the version-scoped DELETE/WHERE), delete_graph
(idempotent DROP), and query.
"""
import pytest

from ontoexplorer.clients import metadata_store
from ontoexplorer.config import get_settings


@pytest.fixture
def store(tmp_path, monkeypatch):
    # Isolate: fresh path, writable, and reset the module singletons.
    monkeypatch.setattr(get_settings(), "metadata_store_path", str(tmp_path / "meta"), raising=False)
    monkeypatch.setattr(get_settings(), "oxigraph_read_only", False, raising=False)
    monkeypatch.setattr(metadata_store, "_store", None)
    monkeypatch.setattr(metadata_store, "_ro_store", None)
    yield metadata_store


def _count(graph_iri: str) -> int:
    import pyoxigraph
    s = metadata_store.get_metadata_store()
    return sum(1 for _ in s.quads_for_pattern(None, None, None, pyoxigraph.NamedNode(graph_iri)))


@pytest.mark.anyio
async def test_insert_turtle_appends_into_named_graph(store):
    await store.insert_turtle("<urn:a> <urn:p> <urn:o> .", graph_iri="urn:meta")
    await store.insert_turtle("<urn:b> <urn:p> <urn:o> .", graph_iri="urn:meta")
    assert _count("urn:meta") == 2, "insert must append, not replace"


@pytest.mark.anyio
async def test_delete_graph_is_idempotent(store):
    await store.insert_turtle("<urn:a> <urn:p> <urn:o> .", graph_iri="urn:meta")
    await store.delete_graph("urn:meta")
    assert _count("urn:meta") == 0
    await store.delete_graph("urn:meta")          # again — must not raise
    await store.delete_graph("urn:never-existed")  # nonexistent — must not raise


@pytest.mark.anyio
async def test_sparql_update_subject_scoped_delete(store):
    await store.insert_turtle(
        "<urn:keep> <urn:p> <urn:o> . <urn:drop> <urn:p> <urn:o> .", graph_iri="urn:meta"
    )
    await store.sparql_update(
        "DELETE { GRAPH <urn:meta> { ?s ?p ?o } } "
        "WHERE { GRAPH <urn:meta> { VALUES ?s { <urn:drop> } ?s ?p ?o } }"
    )
    import pyoxigraph
    remaining = {str(q.subject) for q in metadata_store.get_metadata_store()
                 .quads_for_pattern(None, None, None, pyoxigraph.NamedNode("urn:meta"))}
    assert remaining == {"<urn:keep>"}


@pytest.mark.anyio
async def test_query_sees_only_this_store(store):
    await store.insert_turtle("<urn:a> <urn:p> <urn:o> .", graph_iri="urn:meta")
    res = store.get_metadata_store().query("ASK { GRAPH <urn:meta> { <urn:a> ?p ?o } }")
    assert bool(res) is True


def test_ro_open_of_uninitialised_store_serves_empty(tmp_path, monkeypatch):
    """A fresh deploy has no on-disk store until the first write. The API's
    read-only open must serve an empty store, not 500, until then."""
    monkeypatch.setattr(get_settings(), "metadata_store_path", str(tmp_path / "never-written"), raising=False)
    monkeypatch.setattr(get_settings(), "oxigraph_read_only", True, raising=False)
    monkeypatch.setattr(metadata_store, "_store", None)
    monkeypatch.setattr(metadata_store, "_ro_store", None)
    s = metadata_store.get_metadata_store()          # must NOT raise
    assert bool(s.query("ASK { ?s ?p ?o }")) is False  # empty -> false, no error
