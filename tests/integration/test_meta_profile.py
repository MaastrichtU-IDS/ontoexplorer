from ontoexplorer.models.db import OntologyMetaProfile
from ontoexplorer.modules.meta_profile.registry import (
    ALL_META_ROLES,
    MULTI_VALUE_ROLES,
    ROLE_RESOLVED_KEY,
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
