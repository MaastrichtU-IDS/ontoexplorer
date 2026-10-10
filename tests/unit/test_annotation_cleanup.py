"""The ingest-time bled-annotation strip: builds a scoped SPARQL DELETE and is a
no-op for blank/empty hosts."""
from unittest.mock import patch

from ontoexplorer.modules.ingestion import annotation_cleanup as ac


def test_build_strip_update_shape():
    upd = ac.build_strip_update("urn:g", "http://host.example/onto")
    # deletes only from the host subject, scoped to DC/DCTERMS title+description,
    # and only where a DIFFERENT named subject carries the same (pred, value).
    assert "DELETE { GRAPH <urn:g> { <http://host.example/onto> ?p ?t } }" in upd
    assert "http://purl.org/dc/terms/title" in upd
    assert "http://purl.org/dc/terms/description" in upd
    assert 'FILTER(isIRI(?s) && STR(?s) != "http://host.example/onto")' in upd
    # never touches rdfs:label / rdfs:comment
    assert "2000/01/rdf-schema#label" not in upd
    assert "2000/01/rdf-schema#comment" not in upd


def test_strip_runs_update_for_named_host():
    with patch.object(ac, "sparql_update") as upd, \
         patch.object(ac, "graph_iri", return_value="urn:g"):
        ac.strip_bled_annotations("o1", "v1", "http://host.example/onto")
    assert upd.call_count == 1
    assert "<http://host.example/onto>" in upd.call_args[0][0]


def test_strip_noop_for_blank_or_missing_host():
    with patch.object(ac, "sparql_update") as upd:
        ac.strip_bled_annotations("o1", "v1", None)
        ac.strip_bled_annotations("o1", "v1", "")
        ac.strip_bled_annotations("o1", "v1", "_:b0")   # blank node id
    upd.assert_not_called()


def test_strip_swallows_errors():
    with patch.object(ac, "sparql_update", side_effect=RuntimeError("boom")), \
         patch.object(ac, "graph_iri", return_value="urn:g"):
        # must not raise — ingestion continues
        ac.strip_bled_annotations("o1", "v1", "http://host.example/onto")
