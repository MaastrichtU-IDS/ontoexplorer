import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from ontoexplorer.models.db import OntologyProfile


def test_ontology_profile_model_fields():
    p = OntologyProfile(
        version_id="vid-1",
        label_props=["http://www.w3.org/2000/01/rdf-schema#label"],
        definition_props=[],
        synonym_props=[],
        deprecated_props=["http://www.w3.org/2002/07/owl#deprecated"],
        candidates_data={},
        status="auto_detected",
    )
    assert p.version_id == "vid-1"
    assert p.status == "auto_detected"
    assert p.label_props == ["http://www.w3.org/2000/01/rdf-schema#label"]


from ontoexplorer.modules.profile.registry import (
    LABEL_PROPS, DEFINITION_PROPS, SYNONYM_PROPS, DEPRECATED_PROPS,
    IRI_TO_ROLE, MOD_PREF_LABEL, MOD_DEFINITION, default_profile,
)


def test_registry_label_props_first_is_rdfs_label():
    assert LABEL_PROPS[0] == "http://www.w3.org/2000/01/rdf-schema#label"


def test_registry_iri_to_role_covers_all_props():
    assert IRI_TO_ROLE["http://purl.obolibrary.org/obo/IAO_0000115"] == "definition"
    assert IRI_TO_ROLE["http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"] == "synonym"
    assert IRI_TO_ROLE["http://www.w3.org/2002/07/owl#deprecated"] == "deprecated"


def test_default_profile_returns_all_roles():
    p = default_profile()
    assert "label_props" in p
    assert "definition_props" in p
    assert "synonym_props" in p
    assert "deprecated_props" in p
    assert len(p["label_props"]) > 0


from ontoexplorer.modules.profile.detector import (
    _count_property_usage,
    _count_classes,
    _build_role_list,
    load_profile,
)


def test_count_property_usage_returns_int():
    mock_rows = [{"n": MagicMock(value="42")}]
    with patch("ontoexplorer.modules.profile.detector.sparql_query", return_value=mock_rows):
        result = _count_property_usage("urn:graph", "http://example.org/prop")
    assert result == 42


def test_count_property_usage_returns_zero_on_empty():
    with patch("ontoexplorer.modules.profile.detector.sparql_query", return_value=[]):
        result = _count_property_usage("urn:graph", "http://example.org/prop")
    assert result == 0


def test_build_role_list_orders_by_count():
    counts = {
        "http://www.w3.org/2004/02/skos/core#prefLabel": 100,
        "http://www.w3.org/2000/01/rdf-schema#label": 50,
    }
    result = _build_role_list(
        ["http://www.w3.org/2000/01/rdf-schema#label",
         "http://www.w3.org/2004/02/skos/core#prefLabel"],
        counts,
        mod_override=None,
    )
    assert result[0] == "http://www.w3.org/2004/02/skos/core#prefLabel"


def test_build_role_list_mod_override_goes_first():
    counts = {
        "http://www.w3.org/2004/02/skos/core#prefLabel": 100,
        "http://www.w3.org/2000/01/rdf-schema#label": 50,
    }
    result = _build_role_list(
        ["http://www.w3.org/2000/01/rdf-schema#label",
         "http://www.w3.org/2004/02/skos/core#prefLabel"],
        counts,
        mod_override="http://www.w3.org/2000/01/rdf-schema#label",
    )
    assert result[0] == "http://www.w3.org/2000/01/rdf-schema#label"


@pytest.mark.anyio
async def test_load_profile_returns_defaults_when_no_row():
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    from ontoexplorer.modules.profile.registry import default_profile
    result = await load_profile(mock_db, "vid-1")
    assert result == default_profile()


@pytest.mark.anyio
async def test_load_profile_returns_stored_profile():
    mock_profile = MagicMock()
    mock_profile.label_props = ["http://www.w3.org/2004/02/skos/core#prefLabel"]
    mock_profile.definition_props = ["http://purl.obolibrary.org/obo/IAO_0000115"]
    mock_profile.synonym_props = []
    mock_profile.deprecated_props = ["http://www.w3.org/2002/07/owl#deprecated"]
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_profile
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    result = await load_profile(mock_db, "vid-1")
    assert result["label_props"] == ["http://www.w3.org/2004/02/skos/core#prefLabel"]


def test_detect_profile_task_enqueues_index_on_success():
    with patch("ontoexplorer.modules.jobs.tasks.asyncio") as mock_asyncio, \
         patch("ontoexplorer.modules.jobs.tasks.index_ontology") as mock_index:
        mock_asyncio.run.return_value = None
        from ontoexplorer.modules.jobs.tasks import detect_profile
        detect_profile("vid-1", ontology_id="oid-1")
        mock_index.delay.assert_called_once_with("vid-1", ontology_id="oid-1")


def test_detect_profile_task_enqueues_index_on_failure():
    with patch("ontoexplorer.modules.jobs.tasks.asyncio") as mock_asyncio, \
         patch("ontoexplorer.modules.jobs.tasks.index_ontology") as mock_index:
        mock_asyncio.run.side_effect = RuntimeError("oxigraph unavailable")
        from ontoexplorer.modules.jobs.tasks import detect_profile
        detect_profile("vid-1", ontology_id="oid-1")
        mock_index.delay.assert_called_once_with("vid-1", ontology_id="oid-1")
