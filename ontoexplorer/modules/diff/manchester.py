"""RDF → Manchester OWL syntax rendering for the version diff.

Pure functions over a pyoxigraph.Store + named graph. No DB access, no async.
See docs/superpowers/specs/2026-05-17-manchester-diff-rendering-design.md.
"""
from __future__ import annotations

import pyoxigraph as ox

# Common IRI constants
_RDF_TYPE  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"
_RDF_REST  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"
_RDF_NIL   = "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"

_RDFS_LABEL    = "http://www.w3.org/2000/01/rdf-schema#label"
_RDFS_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
_RDFS_SUBPROP  = "http://www.w3.org/2000/01/rdf-schema#subPropertyOf"
_RDFS_DOMAIN   = "http://www.w3.org/2000/01/rdf-schema#domain"
_RDFS_RANGE    = "http://www.w3.org/2000/01/rdf-schema#range"

_OWL = "http://www.w3.org/2002/07/owl#"
_OWL_RESTRICTION    = _OWL + "Restriction"
_OWL_ON_PROPERTY    = _OWL + "onProperty"
_OWL_SOME_VALUES    = _OWL + "someValuesFrom"
_OWL_ALL_VALUES     = _OWL + "allValuesFrom"
_OWL_HAS_VALUE      = _OWL + "hasValue"
_OWL_HAS_SELF       = _OWL + "hasSelf"
_OWL_CARDINALITY    = _OWL + "cardinality"
_OWL_MIN_CARD       = _OWL + "minCardinality"
_OWL_MAX_CARD       = _OWL + "maxCardinality"
_OWL_QCARDINALITY   = _OWL + "qualifiedCardinality"
_OWL_MIN_QCARD      = _OWL + "minQualifiedCardinality"
_OWL_MAX_QCARD      = _OWL + "maxQualifiedCardinality"
_OWL_ON_CLASS       = _OWL + "onClass"
_OWL_ON_DATARANGE   = _OWL + "onDataRange"
_OWL_INTERSECTION   = _OWL + "intersectionOf"
_OWL_UNION          = _OWL + "unionOf"
_OWL_COMPLEMENT     = _OWL + "complementOf"
_OWL_ONE_OF         = _OWL + "oneOf"
_OWL_EQUIV_CLASS    = _OWL + "equivalentClass"
_OWL_DISJOINT_WITH  = _OWL + "disjointWith"
_OWL_DISJOINT_UNION = _OWL + "disjointUnionOf"
_OWL_EQUIV_PROP     = _OWL + "equivalentProperty"
_OWL_INVERSE_OF     = _OWL + "inverseOf"
_OWL_SAME_AS        = _OWL + "sameAs"
_OWL_DIFFERENT      = _OWL + "differentFrom"
_OWL_ON_DATATYPE    = _OWL + "onDatatype"
_OWL_WITH_RESTRICTIONS = _OWL + "withRestrictions"

_XSD = "http://www.w3.org/2001/XMLSchema#"
_XSD_STRING = _XSD + "string"
_XSD_BOOLEAN = _XSD + "boolean"
_XSD_TRUE_LITERAL = "true"

# Property characteristics: rdf:type values that map to Characteristics: keywords
_CHARACTERISTICS: dict[str, str] = {
    _OWL + "FunctionalProperty":        "Functional",
    _OWL + "InverseFunctionalProperty": "InverseFunctional",
    _OWL + "ReflexiveProperty":         "Reflexive",
    _OWL + "IrreflexiveProperty":       "Irreflexive",
    _OWL + "SymmetricProperty":         "Symmetric",
    _OWL + "AsymmetricProperty":        "Asymmetric",
    _OWL + "TransitiveProperty":        "Transitive",
}

# Datatype-restriction facet IRIs → Manchester operator strings.
_FACETS: dict[str, str] = {
    _XSD + "minInclusive":  ">=",
    _XSD + "maxInclusive":  "<=",
    _XSD + "minExclusive":  ">",
    _XSD + "maxExclusive":  "<",
    _XSD + "length":        "length",
    _XSD + "minLength":     "minLength",
    _XSD + "maxLength":     "maxLength",
    _XSD + "pattern":       "pattern",
}

# Class expression recursion depth (matches compute._BNODE_FP_MAX_DEPTH).
_MAX_DEPTH = 10
