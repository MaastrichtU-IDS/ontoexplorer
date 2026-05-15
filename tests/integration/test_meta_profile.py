from ontoexplorer.models.db import OntologyMetaProfile
from ontoexplorer.modules.meta_profile.registry import (
    ALL_KNOWN_IRIS,
    ALL_META_ROLES,
    MULTI_VALUE_ROLES,
    ROLE_RESOLVED_KEY,
    TITLE_PROPS,
    default_meta_profile,
)


def test_ontology_meta_profile_model_fields():
    p = OntologyMetaProfile(
        version_id="vid-1",
        title_props=["http://purl.org/dc/terms/title"],
        shortname_props=[],
        description_props=[],
        creator_props=[],
        contributor_props=[],
        publisher_props=[],
        license_props=[],
        homepage_props=[],
        version_info_props=[],
        prefix_props=[],
        namespace_uri_props=[],
        created_props=[],
        modified_props=[],
        language_props=[],
        citation_props=[],
        funding_props=[],
        status_props=[],
        syntax_props=[],
        resolved={},
        candidates_data={},
        status="auto_detected",
    )
    assert p.version_id == "vid-1"
    assert p.title_props == ["http://purl.org/dc/terms/title"]
    assert p.status == "auto_detected"


def test_registry_all_meta_roles_has_18_roles():
    assert len(ALL_META_ROLES) == 18


def test_registry_title_props_dcterms_first():
    assert ALL_META_ROLES["title"][0] == "http://purl.org/dc/terms/title"


def test_registry_multi_value_roles():
    assert MULTI_VALUE_ROLES == {"creator", "contributor", "publisher"}


def test_registry_role_resolved_key_creator_is_plural():
    assert ROLE_RESOLVED_KEY["creator"] == "creators"
    assert ROLE_RESOLVED_KEY["contributor"] == "contributors"
    assert ROLE_RESOLVED_KEY["publisher"] == "publishers"


def test_default_meta_profile_has_all_roles():
    p = default_meta_profile()
    for role in ALL_META_ROLES:
        assert f"{role}_props" in p


def test_all_known_iris_is_union_of_all_props():
    expected = {iri for iris in ALL_META_ROLES.values() for iri in iris}
    assert ALL_KNOWN_IRIS == expected


def test_default_meta_profile_returns_copies():
    p = default_meta_profile()
    p["title_props"].clear()
    assert len(TITLE_PROPS) > 0


from unittest.mock import MagicMock, patch
from ontoexplorer.modules.meta_profile.detector import (
    _build_role_props,
    _fetch_onto_triples,
    _resolve_values,
)


def test_fetch_onto_triples_returns_dict():
    mock_rows = [
        {
            "pred": MagicMock(value="http://purl.org/dc/terms/title"),
            "obj": MagicMock(value="My Ontology", language="en", spec=["value", "language"]),
        }
    ]
    with patch("ontoexplorer.modules.meta_profile.detector.sparql_query", return_value=mock_rows):
        result = _fetch_onto_triples("urn:graph:test", "http://example.org/onto")
    assert "http://purl.org/dc/terms/title" in result
    assert result["http://purl.org/dc/terms/title"][0]["value"] == "My Ontology"
    assert result["http://purl.org/dc/terms/title"][0]["language"] == "en"


def test_fetch_onto_triples_empty_graph():
    with patch("ontoexplorer.modules.meta_profile.detector.sparql_query", return_value=[]):
        result = _fetch_onto_triples("urn:graph:empty", "http://example.org/onto")
    assert result == {}


def test_resolve_values_single_role():
    triples = {
        "http://purl.org/dc/terms/title": [
            {"value": "My Ontology", "is_iri": False, "language": "en"}
        ]
    }
    role_props = {"title": ["http://purl.org/dc/terms/title"]}
    result = _resolve_values(triples, role_props)
    assert result["title"] == "My Ontology"


def test_resolve_values_multi_role_collects_all():
    triples = {
        "http://purl.org/dc/terms/creator": [
            {"value": "https://orcid.org/0000-0001", "is_iri": True, "language": None},
            {"value": "https://orcid.org/0000-0002", "is_iri": True, "language": None},
        ]
    }
    role_props = {"creator": ["http://purl.org/dc/terms/creator"]}
    result = _resolve_values(triples, role_props)
    assert result["creators"] == ["https://orcid.org/0000-0001", "https://orcid.org/0000-0002"]


def test_resolve_values_prefers_english():
    triples = {
        "http://purl.org/dc/terms/title": [
            {"value": "Mon Ontologie", "is_iri": False, "language": "fr"},
            {"value": "My Ontology", "is_iri": False, "language": "en"},
        ]
    }
    role_props = {"title": ["http://purl.org/dc/terms/title"]}
    result = _resolve_values(triples, role_props)
    assert result["title"] == "My Ontology"


def test_resolve_values_missing_role_returns_none():
    triples = {}
    role_props = {"title": ["http://purl.org/dc/terms/title"]}
    result = _resolve_values(triples, role_props)
    assert result["title"] is None


def test_build_role_props_only_detected():
    triples = {
        "http://purl.org/dc/terms/title": [{"value": "X", "is_iri": False, "language": None}],
    }
    result = _build_role_props(
        ["http://purl.org/dc/terms/title", "http://www.w3.org/2000/01/rdf-schema#label"],
        triples,
    )
    assert result == ["http://purl.org/dc/terms/title"]


def test_detect_meta_profile_task_runs_and_returns_done():
    from ontoexplorer.modules.jobs.tasks import detect_meta_profile
    with patch("ontoexplorer.modules.jobs.tasks.asyncio") as mock_asyncio:
        mock_asyncio.run.side_effect = lambda coro: coro.close()
        result = detect_meta_profile("vid-1", ontology_id="oid-1")
    assert result["status"] == "done"
    assert result["version_id"] == "vid-1"


def test_detect_meta_profile_task_handles_exception_gracefully():
    from ontoexplorer.modules.jobs.tasks import detect_meta_profile

    def _close_and_raise(coro):
        coro.close()
        raise RuntimeError("oxigraph down")

    with patch("ontoexplorer.modules.jobs.tasks.asyncio") as mock_asyncio:
        mock_asyncio.run.side_effect = _close_and_raise
        result = detect_meta_profile("vid-1", ontology_id="oid-1")
    assert result["status"] == "done"


import pytest


@pytest.mark.anyio
async def test_get_meta_profile_returns_404_when_missing(client, user_and_key):
    _, key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies/oid-1/vid-1/meta",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_meta_candidates_returns_404_when_missing(client, user_and_key):
    _, key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies/oid-1/vid-1/meta/candidates",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_patch_meta_validates_empty_title_props(client, user_and_key):
    _, key = user_and_key
    resp = await client.patch(
        "/api/v1/ontologies/oid-1/vid-1/meta",
        json={"title_props": []},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_post_detect_meta_returns_404_for_unknown_version(client, user_and_key):
    _, key = user_and_key
    resp = await client.post(
        "/api/v1/ontologies/oid-1/nonexistent-vid/meta/detect",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_ontologies_includes_label_field(client, user_and_key):
    _, key = user_and_key
    resp = await client.get(
        "/api/v1/ontologies",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    for ont in data.get("ontologies", []):
        assert "label" in ont
        assert "description" in ont
