from unittest.mock import MagicMock
from ontoexplorer.api.ols._shapes import (
    entity_to_v1_term, entity_to_v2_class, ontology_to_v1, derive_obo_id,
)


def _mock_request():
    r = MagicMock()
    r.url = MagicMock()
    r.url.__str__.return_value = "http://api.example/ols/api/ontologies/go/terms"
    r.query_params = {}
    return r


def test_derive_obo_id_standard():
    assert derive_obo_id("GO_0008150") == "GO:0008150"
    assert derive_obo_id("HP_0000001") == "HP:0000001"


def test_derive_obo_id_non_obo_returns_none():
    assert derive_obo_id("Person") is None
    assert derive_obo_id("hasPart") is None


def test_entity_to_v1_term_basic_fields():
    entity = {
        "iri": "http://purl.obolibrary.org/obo/GO_0008150",
        "primary_label": "biological_process",
        "short": "GO_0008150",
        "type": "class",
        "source": "go",
        "labels": '[{"value":"biological_process","lang":""}]',
        "synonyms": '[]',
        "definitions": '[{"value":"A biological process is...","lang":""}]',
    }
    ontology = MagicMock(id="go", iri="http://purl.obolibrary.org/obo/go.owl",
                         shortname="go")
    out = entity_to_v1_term(entity, ontology, version_id="v1",
                            request=_mock_request(), is_obsolete=False,
                            is_root=False, has_children=True)
    assert out["iri"] == "http://purl.obolibrary.org/obo/GO_0008150"
    assert out["label"] == "biological_process"
    assert out["short_form"] == "GO_0008150"
    assert out["obo_id"] == "GO:0008150"
    assert out["ontology_name"] == "go"
    assert out["ontology_prefix"] == "GO"
    assert out["ontology_iri"] == "http://purl.obolibrary.org/obo/go.owl"
    assert out["is_obsolete"] is False
    assert out["is_root"] is False
    assert out["has_children"] is True
    assert out["description"] == ["A biological process is..."]
    assert out["synonyms"] == []
    assert "_links" in out
    # The self href double-encodes the IRI; the short form appears in the encoded path
    assert "GO_0008150" in out["_links"]["self"]["href"]


def test_entity_to_v1_term_lang_filter():
    entity = {
        "iri": "http://example.org/Cat",
        "primary_label": "Cat",
        "short": "Cat",
        "type": "class",
        "source": "test",
        "labels": '[{"value":"Cat","lang":"en"},{"value":"Chat","lang":"fr"}]',
        "synonyms": '[{"value":"félin","lang":"fr"},{"value":"feline","lang":"en"}]',
        "definitions": '[]',
    }
    ontology = MagicMock(id="test", iri="http://example.org/test", shortname="test")
    out_fr = entity_to_v1_term(entity, ontology, version_id="v1", request=_mock_request(),
                               is_obsolete=False, is_root=False, has_children=False, lang="fr")
    assert out_fr["label"] == "Chat"
    assert out_fr["synonyms"] == ["félin"]


def test_ontology_to_v1_shape():
    ontology = MagicMock(
        id="go", iri="http://purl.obolibrary.org/obo/go.owl",
        shortname="go", title="Gene Ontology", description="Gene Ontology terms",
        created_at=None,
    )
    version = MagicMock(version_iri="2025-01-01", created_at=MagicMock(isoformat=lambda: "2025-01-01T00:00:00"))
    meta_counts = {"class_count": 50000, "property_count": 12, "individual_count": 0}
    out = ontology_to_v1(ontology, version, meta_counts, request=_mock_request())
    assert out["ontologyId"] == "go"
    assert out["config"]["title"] == "Gene Ontology"
    assert out["config"]["preferredPrefix"] == "GO"
    assert out["numberOfTerms"] == 50000
    assert out["numberOfProperties"] == 12
    assert out["numberOfIndividuals"] == 0
    assert out["status"] == "LOADED"
    assert "_links" in out
