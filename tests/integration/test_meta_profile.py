from ontoexplorer.models.db import OntologyMetaProfile


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
