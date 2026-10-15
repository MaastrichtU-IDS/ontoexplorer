"""_serialize_violation must surface the SPECIFIC offending entity/axiom, not a
generic message. Fakes duck-type the horned-profile Violation attribute shapes
(entity violations carry `iri`; expression/property ones carry `axiom`/`ce`/`ope`),
so this needs no native pyhornedowl.
"""
from ontoexplorer.modules.owl_profile.detector import _serialize_violation


class UseOfUndeclaredClass:  # entity violation: only `iri`
    def __init__(self, iri):
        self.iri = iri
        self.message = "Use of an undeclared class"


class UseOfNonSuperClassExpression:  # expression violation: `axiom` + `ce`
    def __init__(self, axiom, ce):
        self.axiom = axiom
        self.ce = ce
        self.message = "Use of a class expression not allowed in superclass position"


class UseOfNonSimplePropertyInCardinalityRestriction:  # property violation: `ope`
    def __init__(self, ope):
        self.ope = ope
        self.message = "Use of a non-simple property in a cardinality restriction"


class Mystery:  # no component attribute -> fall back to message
    def __init__(self):
        self.message = "something odd"


def test_undeclared_class_names_the_specific_class():
    out = _serialize_violation(
        UseOfUndeclaredClass("http://purl.obolibrary.org/obo/GO_0008150")
    )
    assert out["axiom_type"] == "UseOfUndeclaredClass"
    assert out["subject_iri"] == "http://purl.obolibrary.org/obo/GO_0008150"
    assert out["details"] == "GO_0008150"
    assert out["details"] != "Use of an undeclared class"


def test_expression_violation_shows_full_axiom_shortened():
    out = _serialize_violation(UseOfNonSuperClassExpression(
        axiom="SubClassOf(<http://ex.org/A> ObjectUnionOf(<http://ex.org/B> <http://ex.org/C>))",
        ce="ObjectUnionOf(<http://ex.org/B> <http://ex.org/C>)",
    ))
    assert out["details"] == "SubClassOf(A ObjectUnionOf(B C))"
    assert out["subject_iri"] == "http://ex.org/A"


def test_property_violation_uses_the_property_iri():
    out = _serialize_violation(
        UseOfNonSimplePropertyInCardinalityRestriction("http://ex.org/p")
    )
    assert out["subject_iri"] == "http://ex.org/p"
    assert out["details"] == "p"


def test_falls_back_to_message_when_no_component():
    out = _serialize_violation(Mystery())
    assert out["subject_iri"] == ""
    assert out["details"] == "something odd"
