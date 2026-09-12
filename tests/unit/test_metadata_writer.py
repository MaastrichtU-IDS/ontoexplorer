"""The shared catalogue and provenance graphs must not accumulate stale copies."""

import pytest
import rdflib

from ontoexplorer.modules.metadata import metadata_writer


class _Recorder:
    """Captures the SPARQL Updates write_version_metadata issues."""

    def __init__(self):
        self.updates: list[str] = []
        self.inserts: list[tuple[str, str]] = []
        self.dropped: list[str] = []
        self.flushed = 0

    async def flush(self) -> None:
        self.flushed += 1

    async def sparql_update(self, update: str, timeout: float = 30.0) -> None:
        self.updates.append(update)

    async def insert_turtle(self, ttl: str, graph_iri=None, timeout: float = 60.0) -> None:
        self.inserts.append((graph_iri, ttl))

    async def delete_graph(self, graph_iri: str) -> None:
        self.dropped.append(graph_iri)


@pytest.fixture
def recorder(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(metadata_writer, "sparql_update", r.sparql_update)
    monkeypatch.setattr(metadata_writer, "insert_turtle", r.insert_turtle)
    monkeypatch.setattr(metadata_writer, "delete_graph", r.delete_graph)
    monkeypatch.setattr(metadata_writer, "flush", r.flush)
    return r


def _app_base() -> str:
    """Subjects must sit under the configured app_url to be in scope, so the
    fixtures derive it rather than hard-coding a host."""
    from ontoexplorer.config import get_settings
    return str(get_settings().app_url).rstrip("/")


def _graph(subject: str, obj: str) -> rdflib.Graph:
    g = rdflib.Graph()
    g.add((rdflib.URIRef(subject), rdflib.URIRef("http://ex.org/p"), rdflib.Literal(obj)))
    return g


@pytest.mark.anyio
async def test_shared_graphs_are_cleared_of_this_version_before_insert(recorder):
    """Without this the catalogue was append-only: re-ingesting a version left
    the old record in place beside the new one, so a single version advertised
    several download URLs and several ingestion times."""
    base = _app_base()
    dcat = _graph(f"{base}/api/v1/ontologies/o1/v1", "first")
    prov = _graph(f"{base}/api/v1/versions/v1/provenance", "first")

    await metadata_writer.write_version_metadata("o1", "v1", dcat, prov)

    assert recorder.flushed >= 1, "must flush so the API read-only secondary sees the write"
    deletes = [u for u in recorder.updates if u.startswith("DELETE")]
    assert len(deletes) == 2, "expected one subject-scoped delete per shared graph"

    meta_delete = next(u for u in deletes if metadata_writer.META_GRAPH in u)
    assert f"<{base}/api/v1/ontologies/o1/v1>" in meta_delete

    prov_delete = next(u for u in deletes if metadata_writer.PROV_GRAPH in u)
    assert f"<{base}/api/v1/versions/v1/provenance>" in prov_delete


@pytest.mark.anyio
async def test_delete_precedes_the_matching_insert(recorder):
    """Order matters: deleting after inserting would remove what was just written."""
    base = _app_base()
    dcat = _graph(f"{base}/api/v1/ontologies/o1/v1", "x")
    prov = _graph(f"{base}/api/v1/versions/v1/provenance", "x")

    await metadata_writer.write_version_metadata("o1", "v1", dcat, prov)

    # Both shared graphs received an insert, and each was cleared beforehand.
    shared_inserts = [g for g, _ in recorder.inserts
                      if g in (metadata_writer.META_GRAPH, metadata_writer.PROV_GRAPH)]
    assert shared_inserts == [metadata_writer.META_GRAPH, metadata_writer.PROV_GRAPH]
    assert len([u for u in recorder.updates if u.startswith("DELETE")]) == 2


@pytest.mark.anyio
async def test_subjectless_graph_issues_no_delete(recorder):
    """An empty record must not emit a DELETE with an empty VALUES block."""
    await metadata_writer.write_version_metadata("o1", "v1", rdflib.Graph(), rdflib.Graph())
    assert [u for u in recorder.updates if u.startswith("DELETE")] == []


# ── subject scoping (SPARQL injection) ────────────────────────────────────────

def _prov_with_source(source_url: str) -> rdflib.Graph:
    from ontoexplorer.modules.metadata.prov import build_ingestion_activity
    return build_ingestion_activity(
        version_id="v1", ontology_iri="http://ex.org/o", source_url=source_url,
        mode="url", sha256="abc", triple_count=1, app_base_url="http://app")


# _version_scoped_subjects takes the base explicitly, so these stay hermetic.


def test_submitted_source_url_is_not_interpolated():
    """The submitted URL becomes a PROV subject and is entirely user-supplied.
    Interpolated into a SPARQL Update, a `>` closes the IRIREF and everything
    after it executes — here a DROP of the catalogue graph."""
    from ontoexplorer.modules.metadata.metadata_writer import _version_scoped_subjects

    evil = ("http://evil.test/x> } }; DROP SILENT GRAPH <urn:meta> ; "
            "INSERT DATA { GRAPH <urn:meta> { <urn:pwned> <urn:p> <urn:o> } } #")
    kept = _version_scoped_subjects(_prov_with_source(evil), "http://app")

    assert all(s.startswith("http://app/") for s in kept)
    assert not any("DROP" in s or "INSERT" in s for s in kept)


def test_benign_source_url_is_also_excluded():
    """Not just an injection guard: the source URL is shared state. Two versions
    ingested from one URL would otherwise delete each other's triple."""
    from ontoexplorer.modules.metadata.metadata_writer import _version_scoped_subjects

    kept = _version_scoped_subjects(_prov_with_source("http://example.org/onto.ttl"), "http://app")
    assert "http://example.org/onto.ttl" not in kept
    assert "http://app/api/v1/versions/v1/provenance" in kept


def test_illegal_iri_characters_are_dropped_even_under_our_own_prefix():
    """rdflib warns about invalid IRIs but still builds the URIRef, so validity
    upstream cannot be assumed."""
    from ontoexplorer.modules.metadata.metadata_writer import _version_scoped_subjects

    g = rdflib.Graph()
    g.add((rdflib.URIRef("http://app/a> } } ; DROP ALL #"),
           rdflib.URIRef("http://ex/p"), rdflib.Literal("x")))
    assert _version_scoped_subjects(g, "http://app") == []
