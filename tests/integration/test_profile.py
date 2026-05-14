import pytest
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
