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
