from ontoexplorer.modules.owl_profile.registry import (
    ProfileName, PROFILE_NAMES, ProfileViolation,
)


def test_profile_names_are_lowercase():
    assert PROFILE_NAMES == ("el", "rl", "ql", "dl")


def test_profile_violation_dataclass():
    v = ProfileViolation(profile="el", axiom_type="owl:DisjointClasses",
                          subject_iri="http://example.org/A", details="A disjoint with B")
    assert v.profile == "el"
    assert v.axiom_type == "owl:DisjointClasses"
    assert v.subject_iri == "http://example.org/A"


def test_profile_violation_subject_iri_optional():
    v = ProfileViolation(profile="dl", axiom_type="punning",
                         subject_iri=None, details="IRI used as both class and obj prop")
    assert v.subject_iri is None
